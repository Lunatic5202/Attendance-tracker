"""Encrypted data backups pushed to OneDrive for Business.

Features:
  * Snapshot of the SQLite database is taken via the sqlite backup API so the
    archive is always internally consistent (never half a transaction).
  * Face templates (``data/faces/*.enc``) are included byte-for-byte as stored
    server-side — already Fernet-encrypted.
  * The whole archive is then encrypted *again* with the application master key
    before upload, so even the filename-content mapping stays opaque.
  * Old backups are pruned so the folder does not grow without bound.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from backend import database as db, onedrive
from backend.security import fernet

log = logging.getLogger("backup_sync")

_FILENAME_PREFIX = "attendance-backup-"
_FILENAME_SUFFIX = ".bin.enc"


def _archive_bytes() -> bytes:
    db_path = Path(db.DB_PATH)
    faces_root = Path(os.getenv("ATTENDANCE_DATA", "data")) / "faces"

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        if db.using_postgres():
            payload = json.dumps(db.export_snapshot(), indent=2, default=str).encode()
            info = tarfile.TarInfo("attendance-data.json")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        elif db_path.exists():
            temp_path = None
            try:
                fd, temp_path = tempfile.mkstemp(prefix="attendance-db-", suffix=".db")
                os.close(fd)
                source = sqlite3.connect(str(db_path))
                try:
                    target = sqlite3.connect(temp_path)
                    try:
                        source.backup(target)
                    finally:
                        target.close()
                finally:
                    source.close()
                archive.add(temp_path, arcname="attendance.db")
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
        if faces_root.exists():
            for path in sorted(faces_root.iterdir()):
                if path.is_file():
                    archive.add(path, arcname=f"faces/{path.name}")
    return buffer.getvalue()


def _prune(folder: str, keep: int) -> int:
    """Remove the oldest encrypted backups beyond the newest ``keep``."""
    items = onedrive.list_folder(folder)
    backups = [item for item in items if item.get("name", "").endswith(_FILENAME_SUFFIX)]
    pruned = 0
    for item in backups[keep:]:
        onedrive.delete_item(item["id"])
        pruned += 1
    return pruned


def run_backup(keep: int | None = None) -> dict:
    """Encrypt a fresh archive and upload it; prune old ones. Returns status."""
    if not onedrive.configured():
        return {
            "ok": False,
            "disabled": True,
            "reason": "Microsoft Graph is not configured (set MS_CLIENT_ID / MS_CLIENT_SECRET / "
                      "MS_TENANT_ID / MS_DRIVE_UPN).",
        }
    keep = max(1, int(keep or os.getenv("MS_BACKUP_KEEP", "14")))
    folder = f"{os.getenv('MS_FOLDER', 'Attendance Tracker').strip('/')}/backups"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"{_FILENAME_PREFIX}{timestamp}{_FILENAME_SUFFIX}"

    content = fernet().encrypt(_archive_bytes())
    uploaded = onedrive.upload(folder, filename, content, content_type="application/octet-stream")
    pruned = _prune(folder, keep)
    return {
        "ok": True,
        "filename": uploaded["name"],
        "size_bytes": len(content),
        "folder": folder,
        "url": uploaded.get("url"),
        "kept": keep,
        "pruned": pruned,
    }