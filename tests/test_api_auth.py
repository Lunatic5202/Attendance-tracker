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
