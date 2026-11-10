import os
import tempfile
import unittest

os.environ["ATTENDANCE_MASTER_KEY"] = "test-master-key"
os.environ["ADMIN_PASSWORD"] = "test-admin-password"
os.environ["ATTENDANCE_DB"] = os.path.join(tempfile.mkdtemp(prefix="attendance-api-"), "test.db")
os.environ["ATTENDANCE_DATA"] = os.path.dirname(os.environ["ATTENDANCE_DB"])

from fastapi.testclient import TestClient
from backend.main import app


class ApiAuthTests(unittest.TestCase):
    def test_admin_can_add_and_edit_employee_phone_number(self):
        with TestClient(app) as client:
            login = client.post("/api/admin/login", json={"password": "test-admin-password"})
            self.assertEqual(login.status_code, 200)
            created = client.post(
                "/api/employees",
                json={"name": "Phone Contact Test", "phone": "+91 98765 43210"},
            )
            self.assertEqual(created.status_code, 200, created.text)
            employee_id = created.json()["id"]
            self.assertEqual(created.json()["phone"], "+91 98765 43210")

            updated = client.patch(
                f"/api/employees/{employee_id}",
                json={"phone": "+91 91234 56789"},
            )
            self.assertEqual(updated.status_code, 200, updated.text)
            self.assertEqual(updated.json()["phone"], "+91 91234 56789")

            listed = client.get("/api/employees")
            self.assertEqual(listed.status_code, 200)
            employee = next(item for item in listed.json() if item["id"] == employee_id)
            self.assertEqual(employee["phone"], "+91 91234 56789")

            cleared = client.patch(f"/api/employees/{employee_id}", json={"phone": ""})
            self.assertEqual(cleared.status_code, 200, cleared.text)
            self.assertEqual(cleared.json()["phone"], "")

    def test_employee_logs_require_admin_session(self):
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/employees").status_code, 401)
            self.assertEqual(client.get("/api/attendance").status_code, 401)
            login = client.post("/api/admin/login", json={"password": "test-admin-password"})
            self.assertEqual(login.status_code, 200)
            self.assertEqual(client.get("/api/employees").status_code, 200)
            client.post("/api/admin/logout")
            self.assertEqual(client.get("/api/employees").status_code, 401)


if __name__ == "__main__":
    unittest.main()
