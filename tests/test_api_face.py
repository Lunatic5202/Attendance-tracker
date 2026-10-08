"""Endpoint tests for the face scan and additive-enrollment routes.

Detection/embedding at the pixel level is covered by the engine tests with a
stubbed detector. Here the ranking verdicts are swapped for stubs so the HTTP
behaviour (status codes, ``action`` values, messages, data preserved) is what
gets exercised.
"""

import base64
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["ATTENDANCE_MASTER_KEY"] = "test-master-key"
os.environ["ADMIN_PASSWORD"] = "test-admin-password"
os.environ["ATTENDANCE_DB"] = os.path.join(tempfile.mkdtemp(prefix="attendance-api-face-"), "test.db")
os.environ["ATTENDANCE_DATA"] = os.path.dirname(os.environ["ATTENDANCE_DB"])

from fastapi.testclient import TestClient  # noqa: E402
from backend.main import app, engine  # noqa: E402
from backend.attendance import reset_buffer  # noqa: E402
from backend.store import store  # noqa: E402


def _frame_b64():
    import cv2
    import numpy as np

    pixel = np.random.default_rng(0).integers(0, 256, (160, 160, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", pixel)
    assert ok
    return base64.b64encode(buf.tobytes()).decode()


VERDICT = lambda status, **kw: {  # noqa: E731
    "status": status,
    "label": None,
    "distance": None,
    "second": None,
    "reason": None,
    **kw,
}


class FaceRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app).__enter__()
        cls.client.post("/api/admin/login", json={"password": "test-admin-password"})

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def _create_employee(self):
        res = self.client.post(
            "/api/employees",
            json={"name": "Face Test User", "department": "Development"},
        )
        self.assertEqual(res.status_code, 200)
        return res.json()["id"]

    def _next_label(self):
        return (store.max_face_label() or 0) + 1

    def _enrolled_employee(self):
        """Employee wired to a face label, mimicking a completed enrollment."""
        emp_id = self._create_employee()
        label = self._next_label()
        store.set_face_label(emp_id, label)
        store.set_face_available(emp_id, 1)
        return emp_id, label

    def _add_files(self, count=1):
        raw = base64.b64decode(_frame_b64())
        return [("files", ("face.jpg", raw, "image/jpeg")) for _ in range(count)]

    # ---- enrollment -----------------------------------------------------
    def test_face_add_requires_admin(self):
        with TestClient(app) as anon:
            self.assertEqual(
                anon.post(f"/api/employees/EMP001/face/add", files=self._add_files()).status_code,
                401,
            )

    def test_face_add_allocates_label_and_adds_samples(self):
        emp_id = self._create_employee()
        with patch.object(
            engine,
            "enroll_more",
            return_value={"added": 2, "duplicates": 0, "no_face": 0, "over_capacity": 0, "total": 2},
        ):
            res = self.client.post(f"/api/employees/{emp_id}/face/add", files=self._add_files(2))
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["face_enrolled"])
        self.assertEqual(res.json()["added"], 2)
        self.assertIsNotNone(store.get_employee(emp_id)["face_label"])

    def test_face_add_never_undeploys_when_everything_is_duplicate(self):
        emp_id = self._create_employee()
        label = self._next_label()
        store.set_face_label(emp_id, label)
        store.set_face_available(emp_id, 1)

        with patch.object(
            engine,
            "enroll_more",
            return_value={"added": 0, "duplicates": 1, "no_face": 0, "over_capacity": 0, "total": 1},
        ):
            res = self.client.post(f"/api/employees/{emp_id}/face/add", files=self._add_files())
        self.assertEqual(res.status_code, 409)
        row = store.get_employee(emp_id)
        self.assertEqual(row["face_label"], label, "a rejected add must not touch the stored label")
        self.assertEqual(row["face_available"], 1)

    # ---- scanning -------------------------------------------------------
    def test_burst_scan_matches_when_the_majority_agrees(self):
        reset_buffer()
        emp_id, label = self._enrolled_employee()
        with patch.object(
            engine,
            "examine_multi",
            return_value=VERDICT("match", label=label, distance=0.1),
        ), patch.object(engine, "examine", return_value=VERDICT("no_face")) as single:
            res = self.client.post(
                "/api/attendance/scan",
                json={"images": [_frame_b64(), _frame_b64(), _frame_b64()]},
            )
        single.assert_not_called()
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn(res.json()["action"], ("CHECK-IN", "CHECK-OUT", "VISIT"))
        self.assertEqual(res.json()["employee"]["id"], emp_id)

    def test_scan_low_quality_returns_an_actionable_message(self):
        self._enrolled_employee()
        with patch.object(
            engine,
            "examine",
            return_value=VERDICT("low_quality", reason="Too dark — improve the lighting and try again."),
        ):
            res = self.client.post("/api/attendance/scan", json={"images": [_frame_b64()]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["action"], "LOW_QUALITY")
        self.assertIn("dark", res.json()["message"])

    def test_scan_ambiguous_is_reported_instead_of_guessed(self):
        self._enrolled_employee()
        with patch.object(
            engine,
            "examine",
            return_value=VERDICT("ambiguous", label=1, distance=0.3, second=0.31),
        ):
            res = self.client.post("/api/attendance/scan", json={"images": [_frame_b64()]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["action"], "UNKNOWN")
        self.assertIn("close to call", res.json()["message"])

    def test_scan_with_no_face_stays_unknown(self):
        self._enrolled_employee()
        with patch.object(
            engine,
            "examine",
            return_value=VERDICT("no_face", reason="No face detected."),
        ):
            res = self.client.post("/api/attendance/scan", json={"images": [_frame_b64()]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["action"], "UNKNOWN")

    def test_scan_match_records_attendance(self):
        reset_buffer()
        emp_id, label = self._enrolled_employee()
        with patch.object(
            engine,
            "examine",
            return_value=VERDICT("match", label=label, distance=0.1),
        ):
            res = self.client.post("/api/attendance/scan", json={"images": [_frame_b64()]})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn(res.json()["action"], ("CHECK-IN", "CHECK-OUT", "VISIT"))
        self.assertEqual(res.json()["employee"]["id"], emp_id)

    def test_health_reports_the_active_detector(self):
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        self.assertIn("face_detector", res.json())


if __name__ == "__main__":
    unittest.main()