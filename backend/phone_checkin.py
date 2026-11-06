"""Phone-number fallback for people whose face cannot be scanned.

The kiosk captures a camera snapshot, the person types the number registered on
their profile, and attendance is recorded exactly as for a face scan (same
check-in / check-out rules and buffer), with ``source="phone"``.

A phone number is a weaker proof than a face, so the fallback leaves a trail
instead of trusting it blindly: the snapshot is stored encrypted for an admin to
review (and purged after ``PHONE_SNAPSHOT_DAYS``), the endpoint has its own
tight rate limit, and every failed lookup returns the same generic message.

Environment:
    PHONE_FALLBACK_ENABLED           "0" turns the feature off (default on)
    PHONE_FALLBACK_REQUIRE_SNAPSHOT  "0" allows a check-in with no camera (default on)
    PHONE_SNAPSHOT_DAYS              retention in days, 0 keeps forever (default 30)
    PHONE_RATE_LIMIT / PHONE_RATE_WINDOW   requests per window per client (6 / 60s)
"""

from __future__ import annotations

import base64
import logging
import os
from datetime import date, timedelta

import numpy as np

from backend import database as db
from backend.security import decrypt_text, encrypt_bytes, encrypt_text
from backend.store import store

log = logging.getLogger("phone")

#: Shorter inputs are too easy to guess to identify anyone.
MIN_DIGITS = 6
#: Snapshots are evidence, not portraits: keep them small.
SNAPSHOT_MAX_WIDTH = 480
SNAPSHOT_JPEG_QUALITY = 70
_MAX_PAYLOAD = 4_000_000


class PhoneError(Exception):
    """A user-facing failure with the HTTP status the endpoint should return."""

    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def enabled() -> bool:
    return os.getenv("PHONE_FALLBACK_ENABLED", "1").strip() != "0"


def snapshot_required() -> bool:
    return os.getenv("PHONE_FALLBACK_REQUIRE_SNAPSHOT", "1").strip() != "0"


def normalise(value: str | None) -> str:
    """Digits only, keeping the last ten so ``+91 98300 12345`` equals ``9830012345``."""
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[-10:] if len(digits) > 10 else digits


def find_employee(phone: str) -> dict:
    """Return the one active employee registered with ``phone``.

    Phone numbers are stored encrypted (non-deterministically), so they cannot
    be looked up in SQL; the roster is small enough to compare in memory.
    Unknown, inactive and invalid numbers all give the same wording so the
    kiosk cannot be used to find out who works here.
    """
    target = normalise(phone)
    if len(target) < MIN_DIGITS:
        raise PhoneError("invalid_number", f"Enter the full phone number (at least {MIN_DIGITS} digits).", 422)
    matches = []
    for row in store.employees():
        if not row.get("is_active"):
            continue
        try:
            stored = normalise(decrypt_text(row.get("phone")))
        except RuntimeError:
            log.warning("Skipping employee %s: phone could not be decrypted.", row.get("id"))
            continue
        if stored and stored == target:
            matches.append(row)
    if not matches:
        raise PhoneError("unknown_number", "That number isn't registered. Ask an administrator for help.", 404)
    if len(matches) > 1:
        log.warning("Phone number matches %d active employees; refusing to guess.", len(matches))
        raise PhoneError(
            "ambiguous_number",
            "That number is shared by more than one person. Ask an administrator to check you in.",
            409,
        )
    return matches[0]


def prepare_snapshot(payload: str) -> tuple[bytes, bool | None]:
    """Decode a base64 camera frame into a small JPEG.

    Returns ``(jpeg_bytes, face_detected)``. ``face_detected`` is ``None`` when
    no face engine is running to ask. Raises :class:`PhoneError` for anything
    that is not a usable image.
    """
    import cv2

    if len(payload) > _MAX_PAYLOAD:
        raise PhoneError("bad_snapshot", "Snapshot is too large.", 413)
    if payload.startswith("data:"):
        payload = payload.split(",", 1)[-1]
    try:
        raw = base64.b64decode(payload, validate=False)
    except Exception:
        raise PhoneError("bad_snapshot", "Snapshot could not be read.", 400)
    frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR) if raw else None
    if frame is None:
        raise PhoneError("bad_snapshot", "Snapshot could not be read.", 400)

    face_detected = None
    try:
        from backend.face_recognition import engine

        if getattr(engine, "name", "") == "opencv":
            face_detected = engine._largest(frame) is not None
    except Exception:  # the snapshot is still worth keeping
        log.exception("Face check on the phone snapshot failed.")

    height, width = frame.shape[:2]
    if width > SNAPSHOT_MAX_WIDTH:
        frame = cv2.resize(
            frame, (SNAPSHOT_MAX_WIDTH, max(1, round(height * SNAPSHOT_MAX_WIDTH / width))),
            interpolation=cv2.INTER_AREA,
        )
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, SNAPSHOT_JPEG_QUALITY])
    if not ok:
        raise PhoneError("bad_snapshot", "Snapshot could not be processed.", 400)
    return encoded.tobytes(), face_detected


def save_snapshot(employee_id: str, jpeg: bytes, face_detected: bool | None) -> None:
    """Store ``jpeg`` encrypted, then drop snapshots past the retention window."""
    now = db.now_str()
    store.insert_snapshot(
        {
            "employee_id": employee_id,
            "date": db.today_str(),
            "taken_at": encrypt_text(now),
            "source": "phone",
            "face_detected": None if face_detected is None else int(face_detected),
            "image": encrypt_bytes(jpeg),
            "created_at": encrypt_text(now),
        }
    )
    try:
        days = int(os.getenv("PHONE_SNAPSHOT_DAYS", "30"))
    except ValueError:
        days = 30
    if days > 0:
        store.purge_snapshots((date.today() - timedelta(days=days)).isoformat())
