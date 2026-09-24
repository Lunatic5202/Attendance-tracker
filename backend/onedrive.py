"""Microsoft Graph / OneDrive helpers (app-only access).

Uses the OAuth2 client-credentials grant with an Entra ID (Azure AD) app, so no
refresh token is stored on the (ephemeral) server disk. Uploads land in the
OneDrive for Business drive of ``MS_DRIVE_UPN``.

Required environment:
    MS_CLIENT_ID     - Entra app (client) ID
    MS_CLIENT_SECRET - Entra app client secret
    MS_TENANT_ID     - Entra directory (tenant) ID
    MS_DRIVE_UPN     - mailbox/UPN that owns the target OneDrive drive

The app must have the Microsoft Graph *application* permission
``Files.ReadWrite.All`` with admin consent.
"""

from __future__ import annotations

import logging
import os
import time
from urllib.parse import quote

import requests

log = logging.getLogger("onedrive")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPE = "https://graph.microsoft.com/.default"

_REQUIRED = ("MS_CLIENT_ID", "MS_CLIENT_SECRET", "MS_TENANT_ID", "MS_DRIVE_UPN")


class OneDriveError(RuntimeError):
    """Raised when a Graph/OneDrive call fails."""


def configured() -> bool:
    return all(os.getenv(key, "").strip() for key in _REQUIRED)


def _headers(with_type: str | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {_acquire_token()}",
        "Accept": "application/json",
    }
    if with_type:
        headers["Content-Type"] = with_type
    return headers


def _acquire_token() -> str:
    from msal import ConfidentialClientApplication

    app = ConfidentialClientApplication(
        client_id=os.environ["MS_CLIENT_ID"],
        client_credential=os.environ["MS_CLIENT_SECRET"],
        authority=f"https://login.microsoftonline.com/{os.environ['MS_TENANT_ID']}",
    )
    token = app.acquire_token_for_client(scopes=[_SCOPE])
    if "access_token" not in token:
        error = token.get("error_description") or token.get("error") or "unknown error"
        raise OneDriveError(f"Microsoft token acquisition failed: {error}")
    return token["access_token"]


def _upn() -> str:
    return os.environ["MS_DRIVE_UPN"]


def _drive_url(path: str = "") -> str:
    base = f"{GRAPH_BASE}/users/{quote(_upn())}/drive/root"
    if not path:
        return base
    segments = "/".join(quote(seg, safe="") for seg in path.split("/"))
    return f"{base}:/{segments}:"


def _request(method: str, url: str, *, url_kwargs: str = "", **kwargs) -> requests.Response:
    try:
        response = requests.request(method, url, headers=_headers(), timeout=60, **kwargs)
    except requests.RequestException as exc:
        raise OneDriveError(f"OneDrive request failed: {exc}") from exc
    if response.status_code >= 400:
        detail = response.text[:400]
        raise OneDriveError(
            f"OneDrive {method} {url_kwargs or url} failed: HTTP {response.status_code}: {detail}"
        )
    return response


def ensure_folder(path: str) -> None:
    """Create the folder ``path`` (slash separated) if it does not exist."""
    segments = [seg for seg in path.split("/") if seg]
    built: list[str] = []
    for seg in segments:
        built.append(seg)
        current = "/".join(built)
        if len(built) == 1:
            item = _request("GET", f"{_drive_url()}/children", url_kwargs=f"root/children:{seg}")
        else:
            item = _request("GET", _drive_url(current), url_kwargs=f"item:{current}")
        if item.status_code == 404:
            parent = "/".join(built[:-1]) if len(built) > 1 else None
            if parent is None:
                url = f"{_drive_url()}/children"
            else:
                url = f"{_drive_url(parent)}:/children"
            create = requests.post(url, headers=_headers("application/json"), timeout=60, json={
                "name": seg,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "fail",
            })
            if create.status_code not in (200, 201):
                raise OneDriveError(
                    f"Could not create OneDrive folder {current}: HTTP {create.status_code}: {create.text[:400]}"
                )


def upload(path: str, filename: str, content: bytes, content_type: str) -> dict:
    """Upsert ``filename`` inside the OneDrive folder ``path``."""
    ensure_folder(path)
    target = "/".join([*(seg for seg in path.split("/") if seg), filename])
    response = _request(
        "PUT",
        _drive_url(target),
        url_kwargs=f"upload:{target}",
        headers=_headers(content_type),
        data=content,
    )
    item = response.json()
    return {
        "name": item.get("name") or filename,
        "id": item.get("id"),
        "size": item.get("size"),
        "path": f"{path}/{filename}".strip("/"),
        "url": item.get("webUrl"),
    }


def list_folder(path: str) -> list[dict]:
    """List items in a OneDrive folder, newest-modified first."""
    if not path.strip("/"):
        response = _request("GET", f"{_drive_url()}/children", url_kwargs="root/children")
    else:
        response = _request("GET", f"{_drive_url(path)}:/children", url_kwargs=f"folder:{path}")
    items = response.json().get("value", [])
    for item in items:
        item["mtime"] = item.get("lastModifiedDateTime") or item.get("createdDateTime") or ""
    items.sort(key=lambda item: item["mtime"], reverse=True)
    return items


def delete_item(item_id: str) -> None:
    _request("DELETE", f"{GRAPH_BASE}/users/{quote(_upn())}/drive/items/{quote(item_id)}",
             url_kwargs=f"delete:{item_id}")