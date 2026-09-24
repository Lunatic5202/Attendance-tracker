"""SQLite persistence layer for the attendance tracker.

Uses only the standard library so the backend runs with zero extra deps
beyond FastAPI. In production this can be swapped for PostgreSQL.
"""

import os
import sqlite3
from datetime import datetime

from backend.security import encrypt_text

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.getenv("ATTENDANCE_DB", os.path.join(DATA_DIR, "attendance.db"))


def get_conn() -> sqlite3.Connection:
    """Return a connection (row factory enabled) to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables if they do not exist."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS employees (
                id            TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                department    TEXT NOT NULL DEFAULT 'General',
                role          TEXT NOT NULL DEFAULT '',
                email         TEXT NOT NULL DEFAULT '',
                phone         TEXT NOT NULL DEFAULT '',
                face_label    INTEGER UNIQUE,
                face_available INTEGER NOT NULL DEFAULT 0,
                is_active     INTEGER NOT NULL DEFAULT 1,
                created_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS attendance (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT NOT NULL,
                date        TEXT NOT NULL,
                check_in    TEXT,
                check_out   TEXT,
                hours       REAL NOT NULL DEFAULT 0,
                status      TEXT NOT NULL DEFAULT 'Present',
                source      TEXT NOT NULL DEFAULT 'face',
                created_at  TEXT NOT NULL,
                UNIQUE(employee_id, date),
                FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date);
            CREATE INDEX IF NOT EXISTS idx_attendance_employee ON attendance(employee_id);
            """
        )
        _migrate_legacy_plaintext(conn)


def _migrate_legacy_plaintext(conn: sqlite3.Connection) -> None:
    """Encrypt records written by pre-security versions.

    Old builds stored profile fields and timestamps as plaintext. New writes
    always encrypt them, so any value without the ``v1:`` ciphertext marker is
    an unencrypted legacy value and is encrypted in place with the current key.
    """
    for table, fields in (
        ("employees", ("name", "department", "role", "email", "phone", "created_at")),
        ("attendance", ("check_in", "check_out", "created_at")),
    ):
        columns = ", ".join(fields)
        rows = conn.execute(f"SELECT rowid, {columns} FROM {table}").fetchall()
        for row in rows:
            changes = [(f, encrypt_text(str(row[f]))) for f in fields if row[f] and not str(row[f]).startswith("v1:")]
            if not changes:
                continue
            sets = ", ".join(f"{field} = ?" for field, _ in changes)
            values = [value for _, value in changes] + [row["rowid"]]
            conn.execute(f"UPDATE {table} SET {sets} WHERE rowid = ?", values)


def next_employee_id(conn: sqlite3.Connection) -> str:
    """Generate the next sequential employee id (EMP###)."""
    row = conn.execute(
        "SELECT id FROM employees ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return "EMP001"
    try:
        num = int(row["id"].replace("EMP", "")) + 1
    except ValueError:
        num = len(conn.execute("SELECT COUNT(*) AS c FROM employees").fetchone()["c"]) + 1
    return f"EMP{num:03d}"


def now_str() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")