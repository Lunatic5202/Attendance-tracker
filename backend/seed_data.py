"""Reseed the employee roster and face templates on every application boot.

Render's free plan has an ephemeral container filesystem, so the SQLite
database and the enrolled face templates are lost on every deploy. Keeping
the roster here and the reference pictures under ``seed_faces/`` lets the app
rebuild itself from the repository after each deploy.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

from backend import database as db
from backend import security
from backend.store import store

SEED_DIR = Path(__file__).resolve().parent
FACE_DIR = Path(os.getenv("SEED_FACE_DIR", str(SEED_DIR / "seed_faces")))

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

SEED_EMPLOYEES: list[dict] = [
    {
        "id": "EMP001",
        "name": "",
        "department": "",
        "role": "",
        "email": "",
        "phone": "",
        "photos": ["EMP001_1.jpg", "EMP001_2.jpg"],
    },
]


def _enabled() -> bool:
    return os.getenv("SEED_EMPLOYEES_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _decode(path: Path):
    import cv2
    import numpy as np

    try:
        raw = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if raw.size == 0:
        return None
    return cv2.imdecode(raw, cv2.IMREAD_COLOR)


def _frames(photos: list[str]) -> list:
    frames = []
    for name in photos:
        path = FACE_DIR / name
        if not path.is_file():
            matches = sorted(glob.glob(str(FACE_DIR / f"{path.stem.rsplit('_', 1)[0]}*")))
            if not matches:
                continue
            path = Path(matches[0])
        frame = _decode(path)
        if frame is not None:
            frames.append(frame)
    return frames


def _has_photos(employee: dict) -> bool:
    pattern = str(FACE_DIR / f"{employee['id']}*")
    return any(
        Path(match).suffix.lower() in IMAGE_SUFFIXES for match in glob.glob(pattern)
    )


def _restore_missing_face(row, employee, engine) -> None:
    """Re-enroll a stored employee's face when its template is gone.

    The roster can outlive the face templates when the roster lives in an
    external database but the templates live on an ephemeral container disk.
    The existing label is reused so other employees' labels are unaffected.
    """
    label = row["face_label"]
    if label is None or not hasattr(engine, "has") or not hasattr(engine, "enroll_many"):
        return
    if engine.has(label):
        return
    frames = _frames(employee.get("photos", []))
    if not frames:
        return
    if engine.enroll_many(label, frames):
        store.set_face_available(row["id"], 1)
        print(f"[seed] restored face template for {row['id']}")


def seed_employees(engine) -> None:
    if not _enabled():
        return
    for employee in SEED_EMPLOYEES:
        employee_id = employee.get("id", "").strip()
        if not employee_id or not employee.get("name", "").strip():
            continue
        try:
            existing = store.get_employee(employee_id)
            if existing is not None:
                _restore_missing_face(existing, employee, engine)
                continue
            record = {
                "id": employee_id,
                **{
                    key: security.encrypt_text(employee.get(key, "") or "")
                    for key in ("name", "department", "role", "email", "phone")
                },
                "face_available": 0,
                "is_active": 1,
                "created_at": security.encrypt_text(db.now_str()),
            }
            frames = _frames(employee.get("photos", []))
            if frames and hasattr(engine, "enroll_many"):
                label = (store.max_face_label() or 0) + 1
                if engine.enroll_many(label, frames):
                    record["face_label"] = label
                    record["face_available"] = 1
            elif _has_photos(employee):
                record["face_available"] = 0
            store.insert_employee(record)
        except Exception as exc:
            print(f"[seed] skipped {employee_id}: {exc}")
