"""Extra engine tests for the post-ship changes."""

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["ATTENDANCE_MASTER_KEY"] = "test-master-key"
os.environ["ATTENDANCE_DATA"] = tempfile.mkdtemp(prefix="attendance-engine-extra-")
os.environ["ATTENDANCE_DB"] = os.path.join(os.environ["ATTENDANCE_DATA"], "test.db")
os.environ.pop("DATABASE_URL", None)

import numpy as np  # noqa: E402

from backend.face_recognition import OpenCVFaceEngine, MAX_TEMPLATES  # noqa: E402
from backend.face_store import FileFaceStore  # noqa: E402


class EnrollReportTests(unittest.TestCase):
    def setUp(self):
        faces_dir = tempfile.mkdtemp(prefix="engine-er-")
        self._patch = patch(
            "backend.face_recognition.build_store", return_value=FileFaceStore(faces_dir)
        )
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.engine = OpenCVFaceEngine()
        self.engine._largest = lambda image: (0, 0, 160, 160)

    def _p(self, s):
        return np.random.default_rng(s).integers(0, 256, (160, 160, 3), dtype=np.uint8)

    def test_enroll_many_report_includes_rejected_reasons(self):
        dark = np.zeros((160, 160, 3), dtype=np.uint8)
        report = self.engine.enroll_many_report(1, [self._p(1), dark, self._p(2)])
        self.assertEqual(report["stored"], 2)
        self.assertEqual(report["rejected"], 1)
        self.assertIn(report["reasons"][0], ["Too dark — improve the lighting and try again."])

    def test_enroll_more_quality_gates_and_rejected_are_reported(self):
        self.engine.enroll_many(1, [self._p(1)])
        dark = np.zeros((160, 160, 3), dtype=np.uint8)
        blown = np.full((160, 160, 3), 255, dtype=np.uint8)
        outcome = self.engine.enroll_more(1, [dark, blown, self._p(2)])
        self.assertEqual(outcome["added"], 1)
        self.assertEqual(outcome["rejected"], 2)

    def test_enroll_report_fails_only_when_nothing_stored(self):
        dark = np.zeros((160, 160, 3), dtype=np.uint8)
        blown = np.full((160, 160, 3), 255, dtype=np.uint8)
        report = self.engine.enroll_many_report(1, [dark, blown])
        self.assertEqual(report["stored"], 0)
        self.assertGreaterEqual(report["rejected"], 2)

    def test_template_count_reflects_stored_samples(self):
        self.engine.enroll_many(1, [self._p(1), self._p(2)])
        self.assertEqual(self.engine.template_count(1), 2)
        self.assertEqual(self.engine.template_count(99), 0)


if __name__ == "__main__":
    unittest.main()