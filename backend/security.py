"""Security primitives for the attendance tracker.

Employees use the kiosk without accounts. Administrative actions use a short-lived,
HttpOnly signed session cookie. Sensitive values and face templates are encrypted at
rest with a Fernet key derived from ATTENDANCE_MASTER_KEY.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

SESSION_COOKIE = "bt_attendance_admin"
SESSION_TTL_SECONDS = int(os.getenv("ADMIN_SESSION_TTL", "28800"))


def _master_key() -> bytes:
    raw = os.getenv("ATTENDANCE_MASTER_KEY", "").strip()
    if not raw:
        if os.getenv("ENVIRONMENT", "development").lower() == "production":
            raise RuntimeError("ATTENDANCE_MASTER_KEY must be configured in production")
        raw = "development-only-change-this-key"
    return hashlib.sha256(raw.encode("utf-8")).digest()


def fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(_master_key()))


def encrypt_text(value: str | None) -> str | None:
    if value is None:
        return None
    if value.startswith("v1:"):
        return value
    return "v1:" + fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.startswith("v1:"):
        # Allows a safe, one-time read of records created by older versions.
        return value
    try:
        return fernet().decrypt(value[3:].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Encrypted data could not be decrypted; check ATTENDANCE_MASTER_KEY") from exc


def encrypt_bytes(value: bytes) -> bytes:
    return fernet().encrypt(value)


def decrypt_bytes(value: bytes) -> bytes:
    try:
        return fernet().decrypt(value)
    except InvalidToken as exc:
        raise RuntimeError("Encrypted biometric data could not be decrypted") from exc


def create_session() -> str:
    payload = f"{int(time.time())}.{secrets.token_urlsafe(32)}"
    signature = hmac.new(_master_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_session(token: str | None) -> bool:
    if not token:
        return False
    parts = token.split(".", 2)
    if len(parts) != 3:
        return False
    issued, nonce, signature = parts
    try:
        issued_at = int(issued)
    except ValueError:
        return False
    if time.time() - issued_at > SESSION_TTL_SECONDS or issued_at > time.time() + 60:
        return False
    payload = f"{issued}.{nonce}"
    expected = hmac.new(_master_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def public_employee(row: Any) -> dict:
    data = dict(row)
    for field in ("name", "department", "role", "email", "phone", "created_at"):
        data[field] = decrypt_text(data.get(field)) or ""
    data["is_active"] = bool(data.get("is_active"))
    data["face_enrolled"] = bool(data.get("face_available"))
    # Rows written before categories existed have no value; office is the default.
    data["category"] = (data.get("category") or "office")
    data.pop("face_label", None)
    data.pop("face_available", None)
    return data


def public_attendance(row: Any) -> dict:
    data = dict(row)
    for field in ("check_in", "check_out", "created_at"):
        data[field] = decrypt_text(data.get(field))
    for field in ("name", "department", "role"):
        if field in data:
            data[field] = decrypt_text(data.get(field)) or ""
    return data


def public_visit(row: Any) -> dict:
    """Public shape of one field / ground crew visit row."""
    data = dict(row)
    for field in ("visited_at", "created_at"):
        data[field] = decrypt_text(data.get(field))
    for field in ("name", "department", "role"):
        if field in data:
            data[field] = decrypt_text(data.get(field)) or ""
    data["category"] = data.get("category") or "field"
    return data


def admin_password_matches(password: str) -> bool:
    configured = os.getenv("ADMIN_PASSWORD", "").strip()
    if not configured:
        return False
    return hmac.compare_digest(password, configured)


def security_status() -> dict:
    return {
        "encryption": "configured" if os.getenv("ATTENDANCE_MASTER_KEY") else "development-key",
        "admin_auth": bool(os.getenv("ADMIN_PASSWORD")),
        "employee_mode": "face-kiosk",
    }
