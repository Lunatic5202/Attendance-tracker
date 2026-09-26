"""Employee categories, field-staff visits, and the check-in buffer."""

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["ATTENDANCE_MASTER_KEY"] = "test-master-key"
os.environ["ATTENDANCE_DATA"] = tempfile.mkdtemp(prefix="attendance-cat-tests-")
os.environ["ATTENDANCE_DB"] = os.path.join(os.environ["ATTENDANCE_DATA"], "test.db")
os.environ.pop("DATABASE_URL", None)

from backend import attendance, database as db
from backend.limits import client_identity
from backend.security import encrypt_text
from backend.store import store

TODAY = "2026-09-26"


def add_employee(employee_id: str, name: str, category: str) -> str:
    store.insert_employee(
        {
            "id": employee_id,
            "name": encrypt_text(name),
            "department": encrypt_text("Ops"),
            "role": encrypt_text("Staff"),
            "email": encrypt_text(f"{employee_id}@example.com"),
            "phone": encrypt_text("000"),
            "category": category,
            "is_active": 1,
            "created_at": encrypt_text("08:00:00"),
        }
    )
    return employee_id


class CategoryTestCase(unittest.TestCase):
    def setUp(self):
        db.init_db()
        with db.get_conn() as conn:
            conn.execute("DELETE FROM field_visits")
            conn.execute("DELETE FROM attendance")
            conn.execute("DELETE FROM employees")
        attendance.reset_buffer()


class NormaliseCategoryTests(CategoryTestCase):
    def test_known_values_pass_through(self):
        self.assertEqual(attendance.normalise_category("office"), "office")
        self.assertEqual(attendance.normalise_category("field"), "field")

    def test_loose_wording_maps_to_field(self):
        for value in ("Field", "GROUND CREW", "delivery", "Driver", "rider", " field staff "):
            self.assertEqual(attendance.normalise_category(value), "field", value)

    def test_blank_and_unknown_default_to_office(self):
        for value in (None, "", "   ", "nonsense", "manager"):
            self.assertEqual(attendance.normalise_category(value), "office", value)


class FieldVisitTests(CategoryTestCase):
    def test_field_scan_records_a_visit_not_a_check_in(self):
        emp = add_employee("FLD001", "Ravi Kumar", "field")
        with patch.object(db, "today_str", return_value=TODAY), patch.object(
            db, "now_str", return_value="11:20:00"
        ):
            result = attendance.record_scan(emp)
        self.assertEqual(result["action"], "VISIT")
        self.assertIsNone(result["attendance"])
        self.assertEqual(attendance.get_by_date(TODAY), [], "no office row for a field visit")
        visits = attendance.get_visits(TODAY)
        self.assertEqual(len(visits), 1)
        self.assertEqual(visits[0]["visited_at"], "11:20:00")
        self.assertEqual(visits[0]["name"], "Ravi Kumar")

    def test_several_visits_in_one_day_are_all_kept(self):
        emp = add_employee("FLD002", "Sana Ali", "field")
        for clock in ("08:05:00", "11:30:00", "16:45:00"):
            attendance.reset_buffer()
            with patch.object(db, "today_str", return_value=TODAY), patch.object(
                db, "now_str", return_value=clock
            ):
                self.assertEqual(attendance.record_scan(emp)["action"], "VISIT")
        self.assertEqual(len(attendance.get_visits(TODAY)), 3)

    def test_field_visit_row_has_no_hours_or_checkout(self):
        """A visit is a single timestamp, so the columns are not even present."""
        emp = add_employee("FLD003", "Omar Diaz", "field")
        with patch.object(db, "today_str", return_value=TODAY), patch.object(
            db, "now_str", return_value="23:58:00"
        ):
            attendance.record_scan(emp)
        with db.get_conn() as conn:
            row = conn.execute("SELECT * FROM field_visits").fetchone()
        self.assertNotIn("hours", row.keys())
        self.assertNotIn("check_out", row.keys())
        self.assertNotIn("status", row.keys())
        # Arriving at 23:58 is never "Late" for field staff.
        self.assertEqual(attendance.get_visits(TODAY)[0]["visited_at"], "23:58:00")

    def test_field_staff_never_get_a_checkout(self):
        emp = add_employee("FLD004", "Priya Nair", "field")
        attendance.reset_buffer()
        with patch.object(db, "today_str", return_value=TODAY), patch.object(
            db, "now_str", return_value="09:00:00"
        ):
            attendance.record_scan(emp)
        attendance.reset_buffer()
        with patch.object(db, "today_str", return_value=TODAY), patch.object(
            db, "now_str", return_value="17:00:00"
        ):
            result = attendance.record_scan(emp)
        self.assertEqual(result["action"], "VISIT")
        self.assertEqual(len(attendance.get_by_date(TODAY)), 0)

    def test_employee_without_a_category_defaults_to_office(self):
        """Rows written before categories existed must still check in normally."""
        with db.get_conn() as conn:
            conn.execute(
                """
                INSERT INTO employees (id, name, department, role, email, phone,
                                       face_label, face_available, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "OLD001", encrypt_text("Legacy Row"), encrypt_text("Ops"),
                    encrypt_text("Staff"), encrypt_text("o@x.io"), encrypt_text("1"),
                    None, 0, encrypt_text("08:00:00"),
                ),
            )
        with patch.object(db, "today_str", return_value=TODAY), patch.object(
            db, "now_str", return_value="09:00:00"
        ):
            result = attendance.record_scan("OLD001")
        self.assertEqual(result["action"], "CHECK-IN")
        self.assertEqual(result["employee"]["category"], "office")


class CheckinBufferTests(CategoryTestCase):
    def test_second_person_is_blocked_during_the_buffer(self):
        add_employee("OF101", "Asha Rao", "office")
        add_employee("OF102", "Ben Cole", "office")
        with patch.object(db, "today_str", return_value=TODAY), patch.object(
            db, "now_str", return_value="09:00:00"
        ):
            self.assertEqual(attendance.record_scan("OF101")["action"], "CHECK-IN")
            with self.assertRaises(attendance.AttendanceError) as ctx:
                attendance.record_scan("OF102")
        self.assertEqual(ctx.exception.code, "buffer_active")
        self.assertGreater(ctx.exception.info["retry_after"], 0)
        self.assertIn("one check-in at a time", ctx.exception.message)

    def test_buffer_expires_and_the_next_person_checks_in(self):
        add_employee("OF103", "Cara Diaz", "office")
        add_employee("OF104", "Dan Iqbal", "office")
        with patch.object(db, "today_str", return_value=TODAY), patch.object(
            db, "now_str", return_value="09:00:00"
        ):
            attendance.record_scan("OF103")
        attendance.reset_buffer()
        with patch.object(db, "today_str", return_value=TODAY), patch.object(
            db, "now_str", return_value="09:00:01"
        ):
            self.assertEqual(attendance.record_scan("OF104")["action"], "CHECK-IN")

    def test_buffer_also_gates_a_second_visit(self):
        emp = add_employee("FLD005", "Eve Ncube", "field")
        with patch.object(db, "today_str", return_value=TODAY), patch.object(
            db, "now_str", return_value="09:00:00"
        ):
            attendance.record_scan(emp)
            with self.assertRaises(attendance.AttendanceError) as ctx:
                attendance.record_scan(emp)
        self.assertEqual(ctx.exception.code, "buffer_active")

    def test_checkout_is_never_buffered(self):
        """The buffer is about starting a record, not about leaving."""
        emp = add_employee("OF105", "Femi Ojo", "office")
        with patch.object(db, "today_str", return_value=TODAY), patch.object(
            db, "now_str", side_effect=["09:00:00", "13:00:00"]
        ):
            attendance.record_scan(emp)
            self.assertEqual(attendance.record_scan(emp)["action"], "CHECK-OUT")

    def test_a_blocked_checkin_records_nothing(self):
        add_employee("OF106", "Gita Rao", "office")
        add_employee("OF107", "Hugo Silva", "office")
        with patch.object(db, "today_str", return_value=TODAY), patch.object(
            db, "now_str", return_value="09:00:00"
        ):
            attendance.record_scan("OF106")
            with self.assertRaises(attendance.AttendanceError):
                attendance.record_scan("OF107")
        self.assertEqual(attendance.get_by_date(TODAY)[0]["employee_id"], "OF106")
        self.assertEqual(len(attendance.get_by_date(TODAY)), 1)


class ReportingSplitTests(CategoryTestCase):
    def test_office_kpis_exclude_field_visits(self):
        add_employee("OF200", "Hana Ito", "office")
        add_employee("FLD200", "Ivan Petrov", "field")
        with patch.object(db, "today_str", return_value=TODAY), patch.object(
            db, "now_str", return_value="10:00:00"
        ):
            attendance.record_scan("OF200")
        for _ in range(3):
            attendance.reset_buffer()
            with patch.object(db, "today_str", return_value=TODAY), patch.object(
                db, "now_str", return_value="12:00:00"
            ):
                attendance.record_scan("FLD200")
        with patch.object(db, "today_str", return_value=TODAY):
            summary = attendance.summary()
        self.assertEqual(summary["present_today"], 1)
        self.assertEqual(summary["field_visits_today"], 3)
        self.assertEqual(summary["field_staff_seen_today"], 1)
        self.assertEqual(summary["avg_hours"], 0.0)

    def test_late_threshold_is_0930_by_default(self):
        self.assertEqual(attendance.DEFAULT_LATE_AT, "09:30")
        add_employee("OF201", "Iris Chen", "office")
        with patch.object(db, "today_str", return_value=TODAY), patch.object(
            db, "now_str", return_value="09:30:00"
        ):
            result = attendance.record_scan("OF201")
        self.assertEqual(result["attendance"]["status"], "Present")
        attendance.reset_buffer()
        add_employee("OF202", "Jamal Ford", "office")
        with patch.object(db, "today_str", return_value=TODAY), patch.object(
            db, "now_str", return_value="09:31:00"
        ):
            result = attendance.record_scan("OF202")
        self.assertEqual(result["attendance"]["status"], "Late")


class ClientIdentityTests(unittest.TestCase):
    """The rate-limit key must be the real client, not the proxy or a spoof."""

    class _Request:
        def __init__(self, headers, peer="10.0.0.1"):
            self.headers = headers
            self.client = type("C", (), {"host": peer})()

    def test_uses_rightmost_forwarded_entry(self):
        req = self._Request({"x-forwarded-for": "203.0.113.9"})
        self.assertEqual(client_identity(req), "203.0.113.9")

    def test_spoofed_left_entries_are_ignored(self):
        req = self._Request({"x-forwarded-for": "1.2.3.4, 5.6.7.8, 198.51.100.7"})
        self.assertEqual(client_identity(req), "198.51.100.7")

    def test_whitespace_is_tolerated(self):
        req = self._Request({"x-forwarded-for": "1.2.3.4,  198.51.100.7  "})
        self.assertEqual(client_identity(req), "198.51.100.7")

    def test_falls_back_to_socket_peer_without_the_header(self):
        req = self._Request({}, peer="192.0.2.5")
        self.assertEqual(client_identity(req), "192.0.2.5")

    def test_blank_header_falls_back_to_peer(self):
        req = self._Request({"x-forwarded-for": "  ,  "}, peer="192.0.2.5")
        self.assertEqual(client_identity(req), "192.0.2.5")

    def test_different_clients_do_not_share_a_bucket(self):
        a = self._Request({"x-forwarded-for": "198.51.100.7"})
        b = self._Request({"x-forwarded-for": "198.51.100.8"})
        self.assertNotEqual(client_identity(a), client_identity(b))


if __name__ == "__main__":
    unittest.main()