"""Persistence boundary for the attendance tracker.

``SQLiteStore`` is the current implementation, backed by SQLite. A future
``MongoStore`` can implement the same contract and be dropped in without
touching callers. Rows are always plain ``dict`` objects, and sensitive fields
arrive already encrypted from the business layer; the store never interprets
their contents.

Contract (:class:`Store`)
-------------------------
* ``init()``                      - create schema / run migrations.
* ``session()``                   - single-connection unit of work (commit on clean exit,
                                    rollback on exception); exposes the query methods below.
* ``employees()``                 - all employees, newest first.
* ``get_employee(id)``, ``get_employee_by_face_label(label)``,
  ``get_active_employee(id)``     - single employee lookups (``None`` if absent).
* ``max_face_label()``            - highest face label in use (``None`` if none).
* ``next_employee_id()``          - next sequential ``EMP###``.
* ``insert_employee(record)``, ``update_employee(id, sets)`` (returns refreshed row),
  ``delete_employee(id)`` (returns ``{'face_label': ...}`` or ``None``).
* ``set_face_label(id, label)``, ``set_face_available(id, value)``.
* ``active_face_labels()``        - labels for active employees.
* ``departments(active_only)``    - raw department values (listen encrypted as stored).
* ``count_active_employees()``    - active employee count.
* ``attendance_for(emp_id, date)`` - single day record (``None`` if absent).
* ``insert_attendance(record)``, ``close_attendance(row_id, check_out, hours)``.
* ``attendance_entry(emp_id, date)`` - day record joined with employee fields.
* ``attendance_by_date(date)``, ``attendance_by_employee(emp_id, limit)`` - joined lists.
* ``attendance_date_rows(date)``  - raw day rows for summaries.
"""

from __future__ import annotations

from typing import Any, Iterator

from backend import database as db


class Store:
    """Documented persistence contract (behaviourful implementation: SQLiteStore)."""

    def init(self) -> None:
        raise NotImplementedError

    def session(self) -> "StoreSession":
        raise NotImplementedError


class StoreSession:
    """Unit of work exposing the same query methods against one connection."""


# --------------------------------------------------------------------------
# Row helpers (each takes a connection)
# --------------------------------------------------------------------------
def _employees(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM employees ORDER BY created_at DESC").fetchall()]


def _get_employee(conn, employee_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    return dict(row) if row else None


def _get_employee_by_label(conn, label: int) -> dict | None:
    row = conn.execute("SELECT * FROM employees WHERE face_label = ?", (label,)).fetchone()
    return dict(row) if row else None


def _get_active_employee(conn, employee_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM employees WHERE id = ? AND is_active = 1", (employee_id,)).fetchone()
    return dict(row) if row else None


def _max_face_label(conn) -> int | None:
    return conn.execute("SELECT MAX(face_label) AS m FROM employees").fetchone()["m"]


def _next_employee_id(conn) -> str:
    row = conn.execute("SELECT id FROM employees ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return "EMP001"
    try:
        num = int(row["id"].replace("EMP", "")) + 1
    except ValueError:
        num = conn.execute("SELECT COUNT(*) AS c FROM employees").fetchone()["c"] + 1
    return f"EMP{num:03d}"


def _insert_employee(conn, record: dict) -> None:
    conn.execute(
        """
        INSERT INTO employees (id, name, department, role, email, phone, face_label, face_available, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["id"], record["name"], record["department"], record["role"], record["email"],
            record["phone"], record.get("face_label"), record.get("face_available", 0),
            record.get("is_active", 1), record["created_at"],
        ),
    )


def _update_employee(conn, employee_id: str, sets: dict) -> dict | None:
    if sets:
        columns = ", ".join(f"{key} = ?" for key in sets)
        conn.execute(f"UPDATE employees SET {columns} WHERE id = ?", [*sets.values(), employee_id])
    return _get_employee(conn, employee_id)


def _delete_employee(conn, employee_id: str) -> dict | None:
    row = conn.execute("SELECT face_label FROM employees WHERE id = ?", (employee_id,)).fetchone()
    conn.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
    return dict(row) if row else None


def _set_face_label(conn, employee_id: str, label: int) -> None:
    conn.execute("UPDATE employees SET face_label = ? WHERE id = ?", (label, employee_id))


def _set_face_available(conn, employee_id: str, value: int) -> None:
    conn.execute("UPDATE employees SET face_available = ? WHERE id = ?", (value, employee_id))


def _active_face_labels(conn) -> list[int]:
    rows = conn.execute(
        "SELECT face_label FROM employees WHERE is_active = 1 AND face_label IS NOT NULL"
    ).fetchall()
    return [r["face_label"] for r in rows]


def _departments(conn, active_only: bool = False) -> list[Any]:
    where = " WHERE is_active = 1" if active_only else ""
    rows = conn.execute(f"SELECT department FROM employees{where}").fetchall()
    return [r["department"] for r in rows]


def _count_active(conn) -> int:
    return conn.execute("SELECT COUNT(*) AS c FROM employees WHERE is_active = 1").fetchone()["c"]


def _attendance_for(conn, employee_id: str, date: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM attendance WHERE employee_id = ? AND date = ?", (employee_id, date)
    ).fetchone()
    return dict(row) if row else None


def _insert_attendance(conn, record: dict) -> None:
    conn.execute(
        """
        INSERT INTO attendance (employee_id, date, check_in, check_out, hours, status, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["employee_id"], record["date"], record["check_in"], record["check_out"],
            record["hours"], record["status"], record["source"], record["created_at"],
        ),
    )


def _close_attendance(conn, row_id: int, check_out: str, hours: float) -> None:
    conn.execute(
        "UPDATE attendance SET check_out = ?, hours = ? WHERE id = ?", (check_out, hours, row_id)
    )


def _attendance_entry(conn, employee_id: str, date: str) -> dict | None:
    row = conn.execute(
        """
        SELECT a.*, e.name, e.department, e.role
        FROM attendance a JOIN employees e ON e.id = a.employee_id
        WHERE a.employee_id = ? AND a.date = ?
        """,
        (employee_id, date),
    ).fetchone()
    return dict(row) if row else None


def _attendance_by_date(conn, date: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT a.*, e.name, e.department, e.role
        FROM attendance a JOIN employees e ON e.id = a.employee_id
        WHERE a.date = ?
        ORDER BY a.check_in, a.check_out
        """,
        (date,),
    ).fetchall()
    return [dict(r) for r in rows]


def _attendance_by_employee(conn, employee_id: str, limit: int = 60) -> list[dict]:
    rows = conn.execute(
        """
        SELECT a.*, e.name, e.department, e.role
        FROM attendance a JOIN employees e ON e.id = a.employee_id
        WHERE a.employee_id = ?
        ORDER BY a.date DESC, a.check_in DESC
        LIMIT ?
        """,
        (employee_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def _attendance_date_rows(conn, date: str) -> list[dict]:
    rows = conn.execute(
        "SELECT check_in, check_out, hours, status FROM attendance WHERE date = ?", (date,)
    ).fetchall()
    return [dict(r) for r in rows]


class SQLiteSession:
    """A single-connection unit of work that commits on clean exit."""

    def __init__(self, conn):
        self._conn = conn

    def __enter__(self) -> "SQLiteSession":
        return self

    def __exit__(self, exc_type, *_exc) -> None:
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._conn.close()

    def next_employee_id(self) -> str:
        return _next_employee_id(self._conn)

    def get_active_employee(self, employee_id: str) -> dict | None:
        return _get_active_employee(self._conn, employee_id)

    def get_employee(self, employee_id: str) -> dict | None:
        return _get_employee(self._conn, employee_id)

    def attendance_for(self, employee_id: str, date: str) -> dict | None:
        return _attendance_for(self._conn, employee_id, date)

    def insert_attendance(self, record: dict) -> None:
        _insert_attendance(self._conn, record)

    def close_attendance(self, row_id: int, check_out: str, hours: float) -> None:
        _close_attendance(self._conn, row_id, check_out, hours)


class SQLiteStore(Store):
    """SQLite implementation of the persistence contract."""

    def init(self) -> None:
        db.init_db()

    def session(self) -> Iterator[SQLiteSession]:
        return SQLiteSession(db.get_conn())

    def employees(self) -> list[dict]:
        with db.get_conn() as conn:
            return _employees(conn)

    def get_employee(self, employee_id: str) -> dict | None:
        with db.get_conn() as conn:
            return _get_employee(conn, employee_id)

    def get_employee_by_face_label(self, label: int) -> dict | None:
        with db.get_conn() as conn:
            return _get_employee_by_label(conn, label)

    def get_active_employee(self, employee_id: str) -> dict | None:
        with db.get_conn() as conn:
            return _get_active_employee(conn, employee_id)

    def max_face_label(self) -> int | None:
        with db.get_conn() as conn:
            return _max_face_label(conn)

    def next_employee_id(self) -> str:
        with db.get_conn() as conn:
            return _next_employee_id(conn)

    def insert_employee(self, record: dict) -> None:
        with db.get_conn() as conn:
            _insert_employee(conn, record)

    def update_employee(self, employee_id: str, sets: dict) -> dict | None:
        with db.get_conn() as conn:
            return _update_employee(conn, employee_id, sets)

    def delete_employee(self, employee_id: str) -> dict | None:
        with db.get_conn() as conn:
            return _delete_employee(conn, employee_id)

    def set_face_label(self, employee_id: str, label: int) -> None:
        with db.get_conn() as conn:
            _set_face_label(conn, employee_id, label)

    def set_face_available(self, employee_id: str, value: int) -> None:
        with db.get_conn() as conn:
            _set_face_available(conn, employee_id, value)

    def active_face_labels(self) -> list[int]:
        with db.get_conn() as conn:
            return _active_face_labels(conn)

    def departments(self, active_only: bool = False) -> list[Any]:
        with db.get_conn() as conn:
            return _departments(conn, active_only)

    def count_active_employees(self) -> int:
        with db.get_conn() as conn:
            return _count_active(conn)

    def attendance_for(self, employee_id: str, date: str) -> dict | None:
        with db.get_conn() as conn:
            return _attendance_for(conn, employee_id, date)

    def insert_attendance(self, record: dict) -> None:
        with db.get_conn() as conn:
            _insert_attendance(conn, record)

    def close_attendance(self, row_id: int, check_out: str, hours: float) -> None:
        with db.get_conn() as conn:
            _close_attendance(conn, row_id, check_out, hours)

    def attendance_entry(self, employee_id: str, date: str) -> dict | None:
        with db.get_conn() as conn:
            return _attendance_entry(conn, employee_id, date)

    def attendance_by_date(self, date: str) -> list[dict]:
        with db.get_conn() as conn:
            return _attendance_by_date(conn, date)

    def attendance_by_employee(self, employee_id: str, limit: int = 60) -> list[dict]:
        with db.get_conn() as conn:
            return _attendance_by_employee(conn, employee_id, limit)

    def attendance_date_rows(self, date: str) -> list[dict]:
        with db.get_conn() as conn:
            return _attendance_date_rows(conn, date)


store: Store = SQLiteStore()