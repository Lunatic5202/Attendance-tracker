"""Attendance business logic: check-in / check-out automation.

Rules:
  * First successful scan of the day   -> CHECK-IN
  * Second successful scan of the day  -> CHECK-OUT + working-hours calculation
  * Any further scan the same day      -> rejected (duplicate protection)
  * Check-ins after the late threshold describe the employee as LATE
"""

import os
import logging
from datetime import datetime

from backend import database as db

log = logging.getLogger("attendance")

DEFAULT_LATE_AT = os.getenv("LATE_AT", "09:30")


class AttendanceError(Exception):
    def __init__(self, code: str, message: str, **info):
        super().__init__(message)
        self.code = code
        self.info = info
        self.message = message


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%H:%M:%S")


def _to_minutes(value: str) -> int:
    if len(value) == 5:  # HH:MM -> HH:MM:SS
        value = f"{value}:00"
    dt = _parse_time(value)
    return dt.hour * 60 + dt.minute


def _is_late(check_in: str, late_at: str = DEFAULT_LATE_AT) -> bool:
    return _to_minutes(check_in) > _to_minutes(late_at)


def _format_hours(hours: float) -> str:
    total = max(0, int(round(hours * 60)))
    h, m = divmod(total, 60)
    return f"{h}h {m:02d}m"


def record_scan(employee_id: str, source: str = "face", late_at: str = DEFAULT_LATE_AT) -> dict:
    """Apply the auto check-in / check-out rule for one recognised employee."""
    with db.get_conn() as conn:
        emp = conn.execute(
            "SELECT * FROM employees WHERE id = ? AND is_active = 1", (employee_id,)
        ).fetchone()
        if emp is None:
            raise AttendanceError("unknown_employee", "No active employee with that id.")

        date, now = db.today_str(), db.now_str()
        row = conn.execute(
            "SELECT * FROM attendance WHERE employee_id = ? AND date = ?",
            (employee_id, date),
        ).fetchone()

        if row is None:
            status = "Late" if _is_late(now, late_at) else "Present"
            conn.execute(
                """
                INSERT INTO attendance (employee_id, date, check_in, check_out, hours, status, source, created_at)
                VALUES (?, ?, ?, NULL, 0, ?, ?, ?)
                """,
                (employee_id, date, now, status, source, now),
            )
            action = "CHECK-IN"
        elif row["check_out"] is None:
            check_in = row["check_in"]
            seconds = (_parse_time(now) - _parse_time(check_in)).total_seconds()
            hours = round(max(0, seconds) / 3600, 3)
            conn.execute(
                "UPDATE attendance SET check_out = ?, hours = ? WHERE id = ?",
                (now, hours, row["id"]),
            )
            action = "CHECK-OUT"
        else:
            raise AttendanceError(
                "duplicate_scan",
                "Attendance already recorded for today (already checked out).",
                employee_id=employee_id,
                date=date,
            )
        conn.commit()

    fresh = fetch_entry(employee_id, date)
    return {
        "action": action,
        "message": f"{emp['name']} {action.lower()} recorded.",
        "employee": dict(emp),
        "attendance": fresh,
        "time": now,
    }


def fetch_entry(employee_id: str, date: str) -> dict | None:
    with db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT a.*, e.name, e.department, e.role
            FROM attendance a JOIN employees e ON e.id = a.employee_id
            WHERE a.employee_id = ? AND a.date = ?
            """,
            (employee_id, date),
        ).fetchone()
        if row is None:
            return None
        entry = dict(row)
        if entry["hours"]:
            entry["hours_fmt"] = _format_hours(entry["hours"])
        return entry


def get_today() -> list[dict]:
    return get_by_date(db.today_str())


def get_by_date(date: str) -> list[dict]:
    with db.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT a.*, e.name, e.department, e.role
            FROM attendance a JOIN employees e ON e.id = a.employee_id
            WHERE a.date = ?
            ORDER BY a.check_in, a.check_out
            """,
            (date,),
        ).fetchall()
        return [_decorate(dict(r)) for r in rows]


def get_by_employee(employee_id: str, limit: int = 60) -> list[dict]:
    with db.get_conn() as conn:
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
        return [_decorate(dict(r)) for r in rows]


def summary(date: str | None = None) -> dict:
    """Dashboard KPIs for a given date (defaults to today)."""
    date = date or db.today_str()
    with db.get_conn() as conn:
        employees = conn.execute(
            "SELECT COUNT(*) AS c FROM employees WHERE is_active = 1"
        ).fetchone()["c"]
        rows = conn.execute(
            """
            SELECT check_in, check_out, hours, status
            FROM attendance WHERE date = ?
            """,
            (date,),
        ).fetchall()
    present_today_count = len(rows)
    checked_out = sum(1 for r in rows if r["check_out"])
    late = sum(1 for r in rows if r["status"] == "Late")
    hours = [r["hours"] for r in rows if r["hours"]]
    avg_hours = round(sum(hours) / len(hours), 2) if hours else 0.0
    with db.get_conn() as conn:
        dep_rows = conn.execute(
            "SELECT department, COUNT(*) AS c FROM employees WHERE is_active = 1 GROUP BY department"
        ).fetchall()
        departments = {r["department"]: r["c"] for r in dep_rows}
    return {
        "date": date,
        "total_employees": employees,
        "present_today": present_today_count,
        "checked_out_today": checked_out,
        "late_today": late,
        "avg_hours": avg_hours,
        "avg_hours_fmt": _format_hours(avg_hours) if avg_hours else "—",
        "departments": departments,
    }


def _decorate(entry: dict) -> dict:
    if entry["hours"]:
        entry["hours_fmt"] = _format_hours(entry["hours"])
    return entry