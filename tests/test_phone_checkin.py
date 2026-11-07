"""Tests for the phone-number fallback (``POST /api/attendance/phone``).

The face engine is irrelevant here: the endpoint identifies people by their
registered number and keeps a camera snapshot as an audit trail.
"""

import base64
import itertools
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["ATTENDANCE_MASTER_KEY"] = "test-master-key"
os.environ["ADMIN_PASSWORD"] = "test-admin-password"
os.environ["ATTENDANCE_DB"] = os.path.join(tempfile.mkdtemp(prefix="attendance-phone-"), "test.db")
os.environ["ATTENDANCE_DATA"] = os.path.dirname(os.environ["ATTENDANCE_DB"])

from fastapi.testclient import TestClient  # noqa: E402
from backend import database as db  # noqa: E402
from backend import phone_checkin  # noqa: E402
from backend.attendance import reset_buffer  # noqa: E402
from backend.limits import phone_limiter  # noqa: E402
from backend.main import app  # noqa: E402
from backend.store import store  # noqa: E402

_numbers = itertools.count(9_000_000_000)


def _frame_b64():
    import cv2
    import numpy as np

    pixel = np.random.default_rng(1).integers(0, 256, (240, 320, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", pixel)
    assert ok
    return base64.b64encode(buf.tobytes()).decode()


def _fresh_number() -> str:
    return str(next(_numbers))


class NormaliseTests(unittest.TestCase):
    def test_formatting_and_country_code_are_ignored(self):
        self.assertEqual(phone_checkin.normalise("+91 98300-12345"), "9830012345")
        self.assertEqual(phone_checkin.normalise("(098) 300 12345"), "9830012345")
        self.assertEqual(phone_checkin.normalise("9830012345"), "9830012345")

    def test_short_numbers_stay_whole(self):
        self.assertEqual(phone_checkin.normalise("123456"), "123456")
        self.assertEqual(phone_checkin.normalise(None), "")


class PhoneCheckinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app).__enter__()
        cls.client.post("/api/admin/login", json={"password": "test-admin-password"})

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def setUp(self):
        reset_buffer()
        phone_limiter._hits.clear()

    def _employee(self, phone=None, category="office", name="Phone Test User"):
        phone = phone if phone is not None else _fresh_number()
        res = self.client.post(
            "/api/employees",
            json={"name": name, "department": "Development", "phone": phone, "category": category},
        )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["id"], phone

    def _checkin(self, phone, image="default", client=None):
        body = {"phone": phone}
        if image == "default":
            body["image"] = _frame_b64()
        elif image is not None:
            body["image"] = image
        return (client or self.client).post("/api/attendance/phone", json=body)

    def _snapshots(self, emp_id):
        res = self.client.get("/api/attendance/snapshots", params={"employee_id": emp_id})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    # ---- happy path -------------------------------------------------------
    def test_registered_number_checks_in_and_keeps_the_snapshot(self):
        emp_id, phone = self._employee()
        res = self._checkin(phone)
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["action"], "CHECK-IN")
        self.assertEqual(body["method"], "phone")
        self.assertEqual(body["employee"]["id"], emp_id)
        self.assertEqual(body["employee"]["name"], "Phone Test User")

        rows = self.client.get("/api/attendance", params={"employee_id": emp_id}).json()
        self.assertEqual(rows[0]["source"], "phone")

        snaps = self._snapshots(emp_id)
        self.assertEqual(len(snaps), 1)
        self.assertNotIn("image", snaps[0])
        image = self.client.get(f"/api/attendance/snapshots/{snaps[0]['id']}/image")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.headers["content-type"], "image/jpeg")
        self.assertTrue(image.content.startswith(b"\xff\xd8"), "admin should get a real JPEG back")

    def test_snapshot_is_encrypted_at_rest_and_downscaled(self):
        emp_id, phone = self._employee()
        self._checkin(phone)
        snap_id = self._snapshots(emp_id)[0]["id"]
        stored = bytes(store.get_snapshot(snap_id)["image"])
        self.assertFalse(stored.startswith(b"\xff\xd8"), "the JPEG must not be stored in the clear")

        import cv2
        import numpy as np

        jpeg = self.client.get(f"/api/attendance/snapshots/{snap_id}/image").content
        frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertLessEqual(frame.shape[1], phone_checkin.SNAPSHOT_MAX_WIDTH)

    def test_formatting_and_country_code_still_match(self):
        _, phone = self._employee(phone=f"+91 {_fresh_number()[:5]} {_fresh_number()[5:10]}")
        # Stored with a country code and spaces, typed bare on the kiosk.
        typed = phone_checkin.normalise(phone)
        res = self._checkin(typed)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["action"], "CHECK-IN")

    def test_field_staff_get_a_visit(self):
        emp_id, phone = self._employee(category="field")
        res = self._checkin(phone)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["action"], "VISIT")
        self.assertEqual(res.json()["method"], "phone")

    # ---- refusals ---------------------------------------------------------
    def test_unknown_number_is_refused_without_recording_anything(self):
        res = self._checkin(_fresh_number())
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["action"], "UNKNOWN")
        self.assertIn("isn't registered", res.json()["message"])

    def test_too_short_number_is_refused(self):
        res = self._checkin("123")
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.json()["action"], "UNKNOWN")

    def test_inactive_employee_looks_like_an_unknown_number(self):
        emp_id, phone = self._employee()
        self.client.patch(f"/api/employees/{emp_id}", json={"is_active": False})
        res = self._checkin(phone)
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["message"], self._checkin(_fresh_number()).json()["message"])

    def test_shared_number_is_never_guessed(self):
        phone = _fresh_number()
        self._employee(phone=phone, name="Twin One")
        self._employee(phone=phone, name="Twin Two")
        res = self._checkin(phone)
        self.assertEqual(res.status_code, 409)
        self.assertIn("shared", res.json()["message"])

    def test_snapshot_is_required_by_default_and_nothing_is_recorded_without_it(self):
        emp_id, phone = self._employee()
        res = self._checkin(phone, image=None)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["action"], "SNAPSHOT_REQUIRED")
        self.assertEqual(self.client.get("/api/attendance", params={"employee_id": emp_id}).json(), [])

    def test_snapshot_can_be_made_optional(self):
        emp_id, phone = self._employee()
        with patch.dict(os.environ, {"PHONE_FALLBACK_REQUIRE_SNAPSHOT": "0"}):
            res = self._checkin(phone, image=None)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self._snapshots(emp_id), [])

    def test_unreadable_snapshot_is_refused(self):
        emp_id, phone = self._employee()
        res = self._checkin(phone, image=base64.b64encode(b"not an image").decode())
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.client.get("/api/attendance", params={"employee_id": emp_id}).json(), [])

    def test_second_attempt_follows_the_normal_check_out_rule(self):
        emp_id, phone = self._employee()
        self.assertEqual(self._checkin(phone).status_code, 200)
        reset_buffer()
        with patch("backend.attendance.MIN_CHECKOUT_HOURS", 4.0):  # minimum is opt-in
            res = self._checkin(phone)
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.json()["action"], "CHECKOUT_TOO_EARLY")
        self.assertEqual(len(self._snapshots(emp_id)), 1, "a refused attempt must not store a snapshot")

    def test_check_in_buffer_applies_to_phone_check_ins(self):
        _, first = self._employee()
        _, second = self._employee()
        self.assertEqual(self._checkin(first).status_code, 200)
        res = self._checkin(second)
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.json()["action"], "WAIT")

    # ---- abuse controls ---------------------------------------------------
    def test_endpoint_is_rate_limited(self):
        with patch.object(phone_limiter, "limit", 2):
            codes = [self._checkin(_fresh_number()).status_code for _ in range(4)]
        self.assertEqual(codes[:2], [404, 404])
        self.assertEqual(codes[2:], [429, 429])

    def test_feature_can_be_switched_off(self):
        _, phone = self._employee()
        with patch.dict(os.environ, {"PHONE_FALLBACK_ENABLED": "0"}):
            res = self._checkin(phone)
            health = self.client.get("/api/health").json()
        self.assertEqual(res.status_code, 403)
        self.assertFalse(health["phone_fallback"])
        self.assertTrue(self.client.get("/api/health").json()["phone_fallback"])

    def test_snapshots_are_admin_only(self):
        emp_id, phone = self._employee()
        self._checkin(phone)
        snap_id = self._snapshots(emp_id)[0]["id"]
        with TestClient(app) as anon:
            self.assertEqual(anon.get("/api/attendance/snapshots").status_code, 401)
            self.assertEqual(anon.get(f"/api/attendance/snapshots/{snap_id}/image").status_code, 401)
        self.assertEqual(self.client.get("/api/attendance/snapshots/999999/image").status_code, 404)

    def test_old_snapshots_are_purged(self):
        emp_id, phone = self._employee()
        store.insert_snapshot(
            {
                "employee_id": emp_id,
                "date": "2000-01-01",
                "taken_at": "x",
                "face_detected": None,
                "image": b"old",
                "created_at": "x",
            }
        )
        self._checkin(phone)  # saving a new snapshot triggers the purge
        self.assertEqual(store.snapshots_by_date("2000-01-01", emp_id), [])
        self.assertEqual(len(self._snapshots(emp_id)), 1)

    def test_deleting_an_employee_removes_their_snapshots(self):
        emp_id, phone = self._employee()
        self._checkin(phone)
        self.client.delete(f"/api/employees/{emp_id}")
        self.assertEqual(store.snapshots_by_date(db.today_str(), emp_id), [])


if __name__ == "__main__":
    unittest.main()
