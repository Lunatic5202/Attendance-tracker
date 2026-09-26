import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["ATTENDANCE_MASTER_KEY"] = "test-master-key"
os.environ["ATTENDANCE_DATA"] = tempfile.mkdtemp(prefix="attendance-tests-")
os.environ["ATTENDANCE_DB"] = os.path.join(os.environ["ATTENDANCE_DATA"], "test.db")
os.environ["MIN_CHECKOUT_HOURS"] = "4"

from backend import attendance, database as db
from backend.security import create_session, decrypt_text, encrypt_text, verify_session


class SecurityAndAttendanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        with db.get_conn() as conn:
            conn.execute(
                """
                INSERT INTO employees (id, name, department, role, email, phone, category, face_label, face_available, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("EMP001", encrypt_text("Asha Rao"), encrypt_text("Operations"), encrypt_text("Engineer"), encrypt_text("asha@example.com"), encrypt_text("123"), "office", 1, 1, encrypt_text("08:00:00")),
            )

    def setUp(self):
        # The check-in buffer is process-wide state; start each test clean.
        attendance.reset_buffer()

    def test_encryption_round_trip(self):
        encrypted = encrypt_text("private-value")
        self.assertNotEqual(encrypted, "private-value")
        self.assertEqual(decrypt_text(encrypted), "private-value")

    def test_session_signature(self):
        token = create_session()
        self.assertTrue(verify_session(token))
        self.assertFalse(verify_session(token + "x"))

    def test_checkout_is_blocked_until_buffer(self):
        with patch.object(db, "today_str", return_value="2026-09-18"), patch.object(db, "now_str", side_effect=["09:00:00", "12:59:59", "13:00:00"]):
            first = attendance.record_scan("EMP001")
            self.assertEqual(first["action"], "CHECK-IN")
            with self.assertRaises(attendance.AttendanceError) as ctx:
                attendance.record_scan("EMP001")
            self.assertEqual(ctx.exception.code, "checkout_too_early")
            self.assertGreater(ctx.exception.info["minutes_remaining"], 0)
            final = attendance.record_scan("EMP001")
            self.assertEqual(final["action"], "CHECK-OUT")
            self.assertEqual(final["attendance"]["check_in"], "09:00:00")
            self.assertEqual(final["attendance"]["check_out"], "13:00:00")


if __name__ == "__main__":
    unittest.main()
