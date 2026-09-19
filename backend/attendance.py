"""Attendance business logic: check-in / check-out automation.

Rules:
  * First successful scan of the day   -> CHECK-IN
  * Second successful scan of the day  -> CHECK-OUT + working-hours calculation
  * Any further scan the same day      -> rejected (duplicate protection)
  * Check-ins after the late threshold describe the employee as LATE
"""

import os
import logging
from datetime import datetime, timedelta

from backend import database as db
from backend.security import decrypt_text, encrypt_text, public_attendance, public_employee
from backend.store import store

log = logging.getLogger("attendance")

DEFAULT_LATE_AT = os.getenv("LATE_AT", "09:30")
MIN_CHECKOUT_HOURS = float(os.getenv("MIN_CHECKOUT_HOURS", "4"))


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
    with store.session() as s:
        emp = s.get_active_employee(employee_id)
        if emp is None:
            raise AttendanceError("unknown_employee", "No active employee with that id.")

        date, now = db.today_str(), db.now_str()
        row = s.attendance_for(employee_id, date)
        public = public_employee(emp)

        if row is None:
            status = "Late" if _is_late(now, late_at) else "Present"
            s.insert_attendance(
                {
                    "employee_id": employee_id,
                    "date": date,
                    "check_in": encrypt_text(now),
                    "check_out": None,
                    "hours": 0,
                    "status": status,
                    "source": source,
                    "created_at": encrypt_text(now),
                }
            )
            action = "CHECK-IN"
        elif row["check_out"] is None:
            check_in = decrypt_text(row["check_in"])
            seconds = (_parse_time(now) - _parse_time(check_in)).total_seconds()
            if seconds < MIN_CHECKOUT_HOURS * 3600:
                remaining = max(1, int((MIN_CHECKOUT_HOURS * 3600 - seconds + 59) // 60))
                unlocks_at = (_parse_time(check_in) + timedelta(hours=MIN_CHECKOUT_HOURS)).strftime("%H:%M")
                raise AttendanceError(
                    "checkout_too_early",
                    (
                        f"Check-in is held until {unlocks_at} — "
                        f"{MIN_CHECKOUT_HOURS:g} hours after check-in at {check_in[:5]}."
                    ),
                    employee_id=employee_id,
                    employee=public,
                    check_in=check_in[:5],
                    unlocks_at=unlocks_at,
                    minutes_remaining=remaining,
                    min_checkout_hours=MIN_CHECKOUT_HOURS,
                )
            hours = round(max(0, seconds) / 3600, 3)
            s.close_attendance(row["id"], encrypt_text(now), hours)
            action = "CHECK-OUT"
        else:
            raise AttendanceError(
                "duplicate_scan",
                "Attendance already recorded for today (already checked out).",
                employee_id=employee_id,
                employee=public,
                date=date,
            )

    fresh = fetch_entry(employee_id, date)
    return {
        "action": action,
        "message": f"{public['name']} {action.lower()} recorded.",
        "employee": public,
        "attendance": fresh,
        "time": now,
    }


def fetch_entry(employee_id: str, date: str) -> dict | None:
    entry = store.attendance_entry(employee_id, date)
    if entry is None:
        return None
    entry = public_attendance(entry)
    if entry["hours"]:
        entry["hours_fmt"] = _format_hours(entry["hours"])
    return entry


def get_today() -> list[dict]:
    return get_by_date(db.today_str())


def get_by_date(date: str) -> list[dict]:
    return [_decorate(public_attendance(r)) for r in store.attendance_by_date(date)]


def get_by_employee(employee_id: str, limit: int = 60) -> list[dict]:
    return [_decorate(public_attendance(r)) for r in store.attendance_by_employee(employee_id, limit)]


def summary(date: str | None = None) -> dict:
    """Dashboard KPIs for a given date (defaults to today)."""
    date = date or db.today_str()
    rows = store.attendance_date_rows(date)
    present_today_count = len(rows)
    checked_out = sum(1 for r in rows if r["check_out"])
    late = sum(1 for r in rows if r["status"] == "Late")
    hours = [r["hours"] for r in rows if r["hours"]]
    avg_hours = round(sum(hours) / len(hours), 2) if hours else 0.0
    departments = {}
    for department in store.departments(active_only=True):
        name = decrypt_text(department) or "General"
        departments[name] = departments.get(name, 0) + 1
    return {
        "date": date,
        "total_employees": store.count_active_employees(),
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
