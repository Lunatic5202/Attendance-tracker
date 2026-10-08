"""Engine-level tests for quality gates, ambiguous-match rejection,
multi-frame voting and additive enrollment.

All of these run against stored embeddings only — the point of the design is
that every improvement keeps previously enrolled templates valid.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["ATTENDANCE_MASTER_KEY"] = "test-master-key"
os.environ["ATTENDANCE_DATA"] = tempfile.mkdtemp(prefix="attendance-engine-tests-")
os.environ["ATTENDANCE_DB"] = os.path.join(os.environ["ATTENDANCE_DATA"], "test.db")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("FACE_DETECTOR", None)

from backend.face_recognition import MAX_TEMPLATES, YUNET_MODEL  # noqa: E402
from backend.face_recognition import OpenCVFaceEngine  # noqa: E402
from backend.face_store import FileFaceStore  # noqa: E402
from backend.security import encrypt_bytes  # noqa: E402


class EngineTestBase(unittest.TestCase):
    def setUp(self):
        import numpy as np

        self.np = np
        self.faces_dir = tempfile.mkdtemp(prefix="engine-")
        self._patch = patch(
            "backend.face_recognition.build_store", return_value=FileFaceStore(self.faces_dir)
        )
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.engine = self._engine()

    def _engine(self):
        engine = OpenCVFaceEngine()
        engine._largest = lambda image: (0, 0, 160, 160)
        return engine

    def _pattern(self, seed):
        return self.np.random.default_rng(seed).integers(0, 256, (160, 160, 3), dtype=self.np.uint8)

    def _templates(self, label):
        return [blob for owner, blob in self.engine.store.iter_templates() if owner == label]


class AdditiveEnrollmentTests(EngineTestBase):
    def test_adding_a_sample_keeps_the_original_template(self):
        self.engine.enroll_many(1, [self._pattern(1)])
        original = list(self._templates(1))

        outcome = self.engine.enroll_more(1, [self._pattern(2)])

        self.assertEqual(outcome["added"], 1)
        self.assertEqual(outcome["total"], 2)
        for blob in original:
            self.assertIn(blob, self._templates(1))

    def test_added_sample_is_usable_for_recognition(self):
        self.engine.enroll_many(1, [self._pattern(1)])
        self.engine.enroll_more(1, [self._pattern(2)])

        fresh = self._engine()
        self.assertEqual(fresh.recognize(self._pattern(2), [1])[0], 1)
        self.assertEqual(fresh.recognize(self._pattern(1), [1])[0], 1)

    def test_other_employees_are_untouched(self):
        self.engine.enroll_many(1, [self._pattern(1)])
        self.engine.enroll_many(2, [self._pattern(2)])
        before = list(self._templates(2))

        self.engine.enroll_more(1, [self._pattern(3)])

        self.assertEqual(list(self._templates(2)), before)

    def test_near_duplicate_sample_is_not_stored(self):
        self.engine.enroll_many(1, [self._pattern(1)])

        outcome = self.engine.enroll_more(1, [self._pattern(1)])

        self.assertEqual(outcome["added"], 0)
        self.assertEqual(outcome["duplicates"], 1)
        self.assertEqual(len(self._templates(1)), 1)

    def test_duplicate_batch_still_stores_one_pose(self):
        outcome = self.engine.enroll_more(1, [self._pattern(4), self._pattern(4)])
        self.assertEqual(outcome["added"], 1)
        self.assertEqual(outcome["duplicates"], 1)

    def test_cap_refuses_additions_instead_of_evicting(self):
        self.engine.enroll_many(1, [self._pattern(1)])
        extra = [self._pattern(seed) for seed in range(10, 10 + MAX_TEMPLATES + 2)]

        outcome = self.engine.enroll_more(1, extra)

        self.assertEqual(outcome["total"], MAX_TEMPLATES)
        self.assertEqual(len(self._templates(1)), MAX_TEMPLATES)
        self.assertGreater(outcome["over_capacity"], 0)

    def test_legacy_lbph_template_survives_an_additive_enrollment(self):
        from backend.security import decrypt_bytes

        legacy = encrypt_bytes(b"\x00" * 25600)
        self.engine.store.save(3, [legacy])

        outcome = self.engine.enroll_more(3, [self._pattern(5)])

        self.assertEqual(outcome["added"], 1)
        self.assertIn(legacy, self._templates(3), "legacy bytes must never be deleted")
        fresh = self._engine()
        self.assertTrue(fresh.has(3), "the new sample must make the employee enrolled")

    def test_images_without_faces_report_no_face(self):
        flat = self.np.full((160, 160, 3), 128, dtype=self.np.uint8)
        self.engine._largest = lambda image: None
        outcome = self.engine.enroll_more(1, [flat, flat])
        self.assertEqual(outcome["added"], 0)
        self.assertEqual(outcome["no_face"], 2)


class ExamineStatusTests(EngineTestBase):
    def test_match_returns_match_status(self):
        self.engine.enroll_many(1, [self._pattern(1)])
        verdict = self.engine.examine(self._pattern(1), [1])
        self.assertEqual(verdict["status"], "match")
        self.assertEqual(verdict["label"], 1)

    def test_no_detection_reports_no_face(self):
        self.engine.enroll_many(1, [self._pattern(1)])
        self.engine._largest = lambda image: None
        verdict = self.engine.examine(self._pattern(1), [1])
        self.assertEqual(verdict["status"], "no_face")

    def test_dark_frame_is_rejected_as_low_quality(self):
        self.engine.enroll_many(1, [self._pattern(1)])
        dark = self.np.zeros((160, 160, 3), dtype=self.np.uint8)
        verdict = self.engine.examine(dark, [1])
        self.assertEqual(verdict["status"], "low_quality")
        self.assertIn("dark", verdict["reason"].lower())

    def test_bright_frame_is_rejected_as_low_quality(self):
        self.engine.enroll_many(1, [self._pattern(1)])
        blown = self.np.full((160, 160, 3), 255, dtype=self.np.uint8)
        verdict = self.engine.examine(blown, [1])
        self.assertEqual(verdict["status"], "low_quality")

    def test_unfamiliar_face_reports_unknown(self):
        self.engine.enroll_many(1, [self._pattern(1)])
        # Noise embeddings sit close together in SFace space, so tighten the
        # threshold to make "no match" reachable without real photos.
        with patch.object(self.engine, "threshold", 0.02):
            verdict = self.engine.examine(self._pattern(99), [1])
        self.assertEqual(verdict["status"], "unknown")

    def test_empty_gallery_reports_unknown(self):
        verdict = self.engine.examine(self._pattern(1), [1])
        self.assertEqual(verdict["status"], "unknown")
        self.assertIn("template", verdict["reason"].lower())


class AmbiguousMatchTests(EngineTestBase):
    """Two stored people indistinguishable from the query must not coin-flip."""

    def setUp(self):
        super().setUp()
        # Identical embeddings for two labels: the best and second-best
        # distances tie, so the gap collapses below any positive margin.
        self.engine.enroll_many(1, [self._pattern(7)])
        self.engine.enroll_many(2, [self._pattern(7)])

    def test_tied_labels_are_rejected_as_ambiguous(self):
        verdict = self.engine.examine(self._pattern(7), [1, 2])
        self.assertEqual(verdict["status"], "ambiguous")

    def test_ambiguous_scan_yields_no_match(self):
        self.assertIsNone(self.engine.recognize(self._pattern(7), [1, 2]))

    def test_single_candidate_still_matches(self):
        verdict = self.engine.examine(self._pattern(7), [1])
        self.assertEqual(verdict["status"], "match")
        self.assertEqual(verdict["label"], 1)

    def test_margin_zero_disables_the_ambiguity_gate(self):
        with patch.object(self.engine, "margin", 0.0):
            verdict = self.engine.examine(self._pattern(7), [1, 2])
        self.assertEqual(verdict["status"], "match")


class MultiFrameTests(EngineTestBase):
    def setUp(self):
        super().setUp()
        self.engine.enroll_many(1, [self._pattern(1)])
        self.engine.enroll_many(2, [self._pattern(2)])

    def test_majority_agreement_wins(self):
        verdict = self.engine.examine_multi(
            [self._pattern(1), self._pattern(1), self._pattern(2)], [1, 2]
        )
        self.assertEqual(verdict["status"], "match")
        self.assertEqual(verdict["label"], 1)

    def test_split_vote_is_rejected(self):
        verdict = self.engine.examine_multi([self._pattern(1), self._pattern(2)], [1, 2])
        self.assertEqual(verdict["status"], "unknown")

    def test_a_bad_frame_does_not_sink_the_scan(self):
        dark = self.np.zeros((160, 160, 3), dtype=self.np.uint8)
        verdict = self.engine.examine_multi(
            [self._pattern(1), dark, self._pattern(1)], [1, 2]
        )
        self.assertEqual(verdict["status"], "match")
        self.assertEqual(verdict["label"], 1)

    def test_all_frames_unusable_reports_quality_first(self):
        dark = self.np.zeros((160, 160, 3), dtype=self.np.uint8)
        verdict = self.engine.examine_multi([dark, dark], [1, 2])
        self.assertEqual(verdict["status"], "low_quality")

    def test_single_frame_burst_delegates_to_examine(self):
        verdict = self.engine.examine_multi([self._pattern(1)], [1, 2])
        self.assertEqual(verdict["status"], "match")
        self.assertEqual(verdict["label"], 1)

    def test_empty_burst_reports_no_face(self):
        verdict = self.engine.examine_multi([], [1, 2])
        self.assertEqual(verdict["status"], "no_face")


class DetectorSelectionTests(EngineTestBase):
    def test_default_detector_is_haar(self):
        self.assertEqual(self.engine.detector_name, "haar")
        self.assertIsNone(self.engine._yunet)

    def test_yunet_request_falls_back_to_haar_when_the_model_is_absent(self):
        with patch.dict(os.environ, {"FACE_DETECTOR": "yunet"}), patch(
            "backend.face_recognition.YUNET_MODEL", YUNET_MODEL.with_name("no-such-model.onnx")
        ):
            engine = OpenCVFaceEngine()
        self.assertEqual(engine.detector_name, "haar")
        self.assertIsNone(engine._yunet)

    @unittest.skipUnless(YUNET_MODEL.exists(), "YuNet model not downloaded")
    def test_yunet_activates_when_the_model_is_present(self):
        with patch.dict(os.environ, {"FACE_DETECTOR": "yunet"}):
            engine = OpenCVFaceEngine()
        self.assertEqual(engine.detector_name, "yunet")
        self.assertIsNotNone(engine._yunet)


if __name__ == "__main__":
    unittest.main()
