"""Storage backends for enrolled face templates.

Templates are Fernet-encrypted SFace embeddings (512 bytes each, not pictures).
They are kept as files under
``data/faces`` when the app runs on SQLite, and in PostgreSQL tables when
``DATABASE_URL`` is set, because a container filesystem is wiped on every
deploy while a managed database survives.
"""

from __future__ import annotations

import time
from pathlib import Path

from backend import database as db


def _label_from_name(name: str) -> int | None:
    try:
        return int(name.split(".", 1)[0].split("-", 1)[0])
    except ValueError:
        return None


def _as_bytes(value) -> bytes:
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, bytearray):
        return bytes(value)
    return bytes(value)


class FileFaceStore:
    """Face templates stored as encrypted files on disk."""

    def __init__(self, faces_dir):
        self.faces_dir = Path(faces_dir)
        self.faces_dir.mkdir(parents=True, exist_ok=True)

    def _paths(self, label: int) -> list[Path]:
        paths = [self.faces_dir / f"{label}.enc", self.faces_dir / f"{label}.meta"]
        paths.extend(sorted(self.faces_dir.glob(f"{label}-*.enc")))
        return paths

    def iter_templates(self):
        for path in sorted(self.faces_dir.glob("*.enc")):
            label = _label_from_name(path.name)
            if label is None:
                continue
            yield label, path.read_bytes()

    def save(self, label: int, blobs: list[bytes]) -> None:
        self.clear(label)
        if len(blobs) == 1:
            (self.faces_dir / f"{label}.enc").write_bytes(blobs[0])
        else:
            for index, blob in enumerate(blobs):
                (self.faces_dir / f"{label}-{index}.enc").write_bytes(blob)
        self.mark(label)

    def mark(self, label: int) -> None:
        (self.faces_dir / f"{label}.meta").write_text("registered", encoding="utf-8")

    def clear(self, label: int) -> None:
        for path in self._paths(label):
            path.unlink(missing_ok=True)

    def has(self, label: int) -> bool:
        return any(path.exists() for path in self._paths(label))

    def signature(self):
        return tuple(
            (path.stat().st_mtime_ns, path.stat().st_size)
            for path in sorted(self.faces_dir.glob("*.enc"))
        )


class PostgresFaceStore:
    """Face templates stored as rows so they survive a container replacement.

    ``face_registry`` carries a per-label version so the in-memory recognizer
    can notice changes without re-reading every template blob on each frame.
    """

    def __init__(self, probe_seconds: float = 5.0):
        self._probe_seconds = probe_seconds
        self._signature = None
        self._probed_at = 0.0

    def iter_templates(self):
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT label, data FROM face_templates ORDER BY label, idx"
            ).fetchall()
        for row in rows:
            yield int(row["label"]), _as_bytes(row["data"])

    def save(self, label: int, blobs: list[bytes]) -> None:
        with db.get_conn() as conn:
            conn.execute("DELETE FROM face_templates WHERE label = ?", (label,))
            for index, blob in enumerate(blobs):
                conn.execute(
                    "INSERT INTO face_templates (label, idx, data) VALUES (?, ?, ?)",
                    (label, index, blob),
                )
            conn.execute(
                """
                INSERT INTO face_registry (label, version) VALUES (?, 1)
                ON CONFLICT (label) DO UPDATE SET version = face_registry.version + 1
                """,
                (label,),
            )
        self._signature = None

    def mark(self, label: int) -> None:
        return None

    def clear(self, label: int) -> None:
        with db.get_conn() as conn:
            conn.execute("DELETE FROM face_templates WHERE label = ?", (label,))
            conn.execute("DELETE FROM face_registry WHERE label = ?", (label,))
        self._signature = None

    def has(self, label: int) -> bool:
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM face_templates WHERE label = ?", (label,)
            ).fetchone()
        return bool(row["c"])

    def signature(self):
        now = time.monotonic()
        if self._signature is None or (now - self._probed_at) >= self._probe_seconds:
            self._probed_at = now
            with db.get_conn() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS c, COALESCE(SUM(version), 0) AS v FROM face_registry"
                ).fetchone()
            self._signature = (int(row["c"]), int(row["v"]))
        return self._signature


def build_store(faces_dir):
    """Return the template store matching the configured database."""
    if db.using_postgres():
        return PostgresFaceStore()
    return FileFaceStore(faces_dir)
