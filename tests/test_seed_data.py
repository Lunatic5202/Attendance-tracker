import os
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

os.environ["ATTENDANCE_MASTER_KEY"] = "test-master-key"
os.environ["ATTENDANCE_DATA"] = tempfile.mkdtemp(prefix="attendance-seed-tests-")
os.environ["ATTENDANCE_DB"] = os.path.join(os.environ["ATTENDANCE_DATA"], "test.db")
os.environ["SEED_FACE_DIR"] = tempfile.mkdtemp(prefix="attendance-seed-faces-")

from backend import database as db, security
from backend import seed_data
from backend.store import store

PHOTO = os.path.join(os.environ["SEED_FACE_DIR"], "EMP001_1.jpg")

ROSTER = [
    {
        "id": "EMP001",
        "name": "Asha Rao",
        "department": "Operations",
        "role": "Engineer",
        "email": "asha@example.com",
        "phone": "123",
        "photos": ["EMP001_1.jpg"],
    }
]


class StubEngine:
    def __init__(self, result=True, known=()):
        self.result = result
        self.known = set(known)
        self.calls = []

    def enroll_many(self, label, frames):
        self.calls.append((label, len(frames)))
        if self.result:
            self.known.add(label)
        return self.result

    def has(self, label):
        return label in self.known


class SeedEmployeeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        store.init()
        seed_data.FACE_DIR = Path(PHOTO).parent

    def setUp(self):
        with db.get_conn() as conn:
            conn.execute("DELETE FROM employees")
        seed_data.SEED_EMPLOYEES = [dict(row) for row in ROSTER]
        cv2.imwrite(PHOTO, np.full((80, 80, 3), 200, np.uint8))

    def test_roster_is_inserted_with_face_enrolled(self):
        engine = StubEngine(result=True)
        seed_data.seed_employees(engine)
        rows = store.employees()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "EMP001")
        self.assertEqual(rows[0]["face_available"], 1)
        self.assertEqual(rows[0]["face_label"], 1)
        self.assertEqual(engine.calls, [(1, 1)])

    def test_seeding_twice_does_not_duplicate(self):
        seed_data.seed_employees(StubEngine(result=True))
        seed_data.seed_employees(StubEngine(result=True))
        self.assertEqual(len(store.employees()), 1)

    def test_employee_is_added_when_face_detection_fails(self):
        seed_data.seed_employees(StubEngine(result=False))
        rows = store.employees()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["face_available"], 0)
        self.assertIsNone(rows[0]["face_label"])

    def test_persisted_employee_loses_no_face_after_container_reset(self):
        store.insert_employee(
            {
                "id": "EMP001",
                **{
                    key: security.encrypt_text(value)
                    for key, value in (
                        ("name", "Asha Rao"),
                        ("department", "Operations"),
                        ("role", "Engineer"),
                        ("email", "asha@example.com"),
                        ("phone", "123"),
                    )
                },
                "face_label": 1,
                "face_available": 1,
                "is_active": 1,
                "created_at": security.encrypt_text("08:00:00"),
            }
        )
        engine = StubEngine(result=True, known=set())
        seed_data.seed_employees(engine)
        row = store.get_employee("EMP001")
        self.assertEqual(engine.calls, [(1, 1)], "the face must be re-enrolled with the same label")
        self.assertEqual(row["face_label"], 1)
        self.assertEqual(row["face_available"], 1)
        self.assertEqual(len(store.employees()), 1)

    def test_intact_face_is_not_enrolled_again(self):
        store.insert_employee(
            {
                "id": "EMP001",
                **{
                    key: security.encrypt_text(value)
                    for key, value in (
                        ("name", "Asha Rao"),
                        ("department", "Operations"),
                        ("role", "Engineer"),
                        ("email", "asha@example.com"),
                        ("phone", "123"),
                    )
                },
                "face_label": 1,
                "face_available": 1,
                "is_active": 1,
                "created_at": security.encrypt_text("08:00:00"),
            }
        )
        engine = StubEngine(result=True, known={1})
        seed_data.seed_employees(engine)
        self.assertEqual(engine.calls, [], "an intact template must not be re-enrolled")

    def test_blank_entries_are_skipped(self):
        seed_data.SEED_EMPLOYEES = [{"id": "EMP002", "name": "  ", "photos": []}]
        seed_data.seed_employees(StubEngine())
        self.assertEqual(len(store.employees()), 0)

    def test_seeding_can_be_disabled(self):
        seed_data.SEED_EMPLOYEES = [dict(row) for row in ROSTER]
        os.environ["SEED_EMPLOYEES_ENABLED"] = "false"
        try:
            seed_data.seed_employees(StubEngine())
        finally:
            os.environ.pop("SEED_EMPLOYEES_ENABLED", None)
        self.assertEqual(len(store.employees()), 0)


if __name__ == "__main__":
    unittest.main()
