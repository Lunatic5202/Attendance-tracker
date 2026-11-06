"""Tests for the detection upgrades: multi-pass detection, face selection,
edge clamping and burst fusion.

The recognition model is stubbed, so these run without the SFace/YuNet files and
exercise the logic around the models, which is where the upgrades live. Real
accuracy on real faces still has to be checked with the models present.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["ATTENDANCE_MASTER_KEY"] = "test-master-key"
os.environ["ATTENDANCE_DATA"] = tempfile.mkdtemp(prefix="attendance-detect-")
os.environ["ATTENDANCE_DB"] = os.path.join(os.environ["ATTENDANCE_DATA"], "test.db")
os.environ.pop("DATABASE_URL", None)

import numpy as np  # noqa: E402

from backend.face_recognition import EMBED_DIMS, OpenCVFaceEngine  # noqa: E402
from backend.face_store import FileFaceStore  # noqa: E402
from backend.security import encrypt_bytes  # noqa: E402


class _StubRecognizer:
    def feature(self, buffer):
        return np.ones((1, EMBED_DIMS), dtype=np.float32)


class _ScriptedYuNet:
    """Returns the scripted detections call by call (``None`` = no face)."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = 0

    def setInputSize(self, size):
        self.size = size

    def detect(self, frame):
        row = self.script[self.calls] if self.calls < len(self.script) else None
        self.calls += 1
        return None, row


def _row(x, y, w, h, score):
    out = np.zeros((1, 15), dtype=np.float32)
    out[0, :4] = [x, y, w, h]
    out[0, 14] = score
    return out


def _engine():
    faces_dir = tempfile.mkdtemp(prefix="engine-detect-")
    with patch("backend.face_recognition._load_sface", return_value=_StubRecognizer()), patch(
        "backend.face_recognition.build_store", return_value=FileFaceStore(faces_dir)
    ), patch.dict(os.environ, {"FACE_DETECTOR": "haar"}):
        return OpenCVFaceEngine()


class ClampBoxTests(unittest.TestCase):
    def test_a_box_inside_the_frame_is_unchanged(self):
        self.assertEqual(OpenCVFaceEngine._clamp_box((10, 20, 80, 90), (200, 300, 3)), (10, 20, 80, 90))

    def test_negative_origin_is_clipped_instead_of_wrapping(self):
        # NumPy would read x=-8 as "8 from the right edge" and return nothing.
        self.assertEqual(OpenCVFaceEngine._clamp_box((-8, 5, 100, 100), (200, 300, 3)), (0, 5, 92, 100))

    def test_box_running_off_the_far_edge_is_clipped(self):
        # 65.6% of this face is inside the 300x200 frame, which is enough to keep.
        self.assertEqual(OpenCVFaceEngine._clamp_box((240, 130, 80, 80), (200, 300, 3)), (240, 130, 60, 70))

    def test_a_face_mostly_out_of_frame_is_rejected(self):
        self.assertIsNone(OpenCVFaceEngine._clamp_box((-70, 0, 100, 100), (200, 300, 3)))

    def test_degenerate_boxes_are_rejected(self):
        self.assertIsNone(OpenCVFaceEngine._clamp_box((10, 10, 0, 50), (200, 300, 3)))
        self.assertIsNone(OpenCVFaceEngine._clamp_box((500, 10, 50, 50), (200, 300, 3)))


class DetectionPassTests(unittest.TestCase):
    def setUp(self):
        self.engine = _engine()
        self.frame = np.random.default_rng(3).integers(0, 256, (240, 320, 3), dtype=np.uint8)

    def test_a_dim_frame_gets_a_third_enhanced_pass(self):
        fake = _ScriptedYuNet(None, None, _row(40, 50, 60, 70, 0.9))
        self.engine._yunet = fake
        boxes = self.engine._detect_yunet(self.frame)
        self.assertEqual(fake.calls, 3)
        self.assertEqual(boxes.tolist(), [[40, 50, 60, 70]])

    def test_the_enhanced_pass_can_be_switched_off(self):
        fake = _ScriptedYuNet(None, None, _row(40, 50, 60, 70, 0.9))
        self.engine._yunet = fake
        self.engine.enhance_retry = False
        self.assertEqual(self.engine._detect_yunet(self.frame).shape[0], 0)
        self.assertEqual(fake.calls, 2)

    def test_a_first_pass_hit_costs_a_single_detection(self):
        fake = _ScriptedYuNet(_row(40, 50, 60, 70, 0.9))
        self.engine._yunet = fake
        self.engine._detect_yunet(self.frame)
        self.assertEqual(fake.calls, 1)

    def test_enhancement_keeps_the_frame_size_and_lifts_a_dark_frame(self):
        dark = np.full((120, 160, 3), 30, dtype=np.uint8)
        dark[40:80, 60:100] = 55
        lifted = self.engine._enhance_for_detection(dark)
        self.assertEqual(lifted.shape, dark.shape)
        self.assertGreater(float(lifted.mean()), float(dark.mean()))

    def test_edge_face_no_longer_breaks_the_crop(self):
        # x=-6 used to produce an empty crop and a crash inside cv2.resize.
        self.engine._yunet = _ScriptedYuNet(_row(-6, 20, 110, 120, 0.95))
        crop = self.engine._largest(self.frame)
        self.assertEqual(crop, (0, 20, 104, 120))
        self.assertIsNotNone(self.engine._embed(self.frame, crop))


class FaceSelectionTests(unittest.TestCase):
    def setUp(self):
        self.engine = _engine()

    def _rows(self, *boxes):
        rows = np.zeros((len(boxes), 15), dtype=np.float32)
        for i, (x, y, w, h, score) in enumerate(boxes):
            rows[i, :4] = [x, y, w, h]
            rows[i, 14] = score
        return rows[np.argsort(-rows[:, 14])]

    def test_the_nearest_face_beats_a_slightly_more_confident_bystander(self):
        rows = self._rows((200, 40, 50, 50, 0.97), (60, 60, 140, 140, 0.90))
        self.assertEqual(self.engine._pick_face(rows)[:4].tolist(), [60, 60, 140, 140])

    def test_a_large_but_doubtful_detection_is_ignored(self):
        rows = self._rows((200, 40, 50, 50, 0.97), (20, 20, 220, 220, 0.30))
        self.assertEqual(self.engine._pick_face(rows)[:4].tolist(), [200, 40, 50, 50])


class BurstFusionTests(unittest.TestCase):
    """Embeddings are placed by hand so the cosine distances are known."""

    def setUp(self):
        self.engine = _engine()
        self.engine.margin = 0.04
        self.threshold = self.engine.threshold

        def unit(index):
            vector = np.zeros(EMBED_DIMS, dtype=np.float32)
            vector[index] = 1.0
            return vector

        self.unit = unit
        self.engine.store.save(1, [encrypt_bytes(unit(0).tobytes())])
        self.engine.store.save(2, [encrypt_bytes(unit(9).tobytes())])
        self.vectors = {}
        self.engine._query = lambda frame: (self.vectors[int(frame[0, 0, 0])], None)
        self.engine.min_motion = 0.0  # frames below are not real, skip the replay check

    def _frames(self, *ids):
        return [np.full((64, 64, 3), i, dtype=np.uint8) for i in ids]

    def _near_label_one(self, cosine, side):
        """A unit vector at ``cosine`` similarity to label 1, tilted towards ``side``."""
        vector = np.zeros(EMBED_DIMS, dtype=np.float32)
        vector[0] = cosine
        vector[side] = float(np.sqrt(1 - cosine**2))
        return vector

    def test_frames_that_each_narrowly_miss_are_rescued_by_averaging(self):
        cosine = 1 - (self.threshold + 0.02)  # each frame sits just outside the threshold
        self.vectors = {
            1: self._near_label_one(cosine, 3),
            2: self._near_label_one(cosine, 4),
            3: self._near_label_one(cosine, 5),
        }
        for frame in self._frames(1, 2, 3):
            self.assertEqual(self.engine._rank(self.vectors[int(frame[0, 0, 0])], [1, 2])["status"], "unknown")
        verdict = self.engine.examine_multi(self._frames(1, 2, 3), [1, 2])
        self.assertEqual(verdict["status"], "match")
        self.assertEqual(verdict["label"], 1)

    def test_fusion_can_be_switched_off(self):
        cosine = 1 - (self.threshold + 0.02)
        self.vectors = {i: self._near_label_one(cosine, 2 + i) for i in (1, 2, 3)}
        self.engine.fuse_frames = False
        verdict = self.engine.examine_multi(self._frames(1, 2, 3), [1, 2])
        self.assertEqual(verdict["status"], "unknown")

    def test_a_frame_that_matched_someone_else_blocks_fusion(self):
        cosine = 1 - (self.threshold + 0.02)
        self.vectors = {
            1: self._near_label_one(cosine, 3),
            2: self._near_label_one(cosine, 4),
            3: self.unit(9),  # unmistakably employee 2
        }
        verdict = self.engine.examine_multi(self._frames(1, 2, 3), [1, 2])
        self.assertEqual(verdict["status"], "unknown")

    def test_a_stranger_is_not_fused_into_a_match(self):
        self.vectors = {i: self.unit(40 + i) for i in (1, 2, 3)}
        verdict = self.engine.examine_multi(self._frames(1, 2, 3), [1, 2])
        self.assertEqual(verdict["status"], "unknown")

    def test_a_clear_majority_does_not_need_fusion(self):
        self.vectors = {1: self.unit(0), 2: self.unit(0), 3: self.unit(40)}
        with patch.object(self.engine, "_fuse") as fuse:
            verdict = self.engine.examine_multi(self._frames(1, 2, 3), [1, 2])
        fuse.assert_not_called()
        self.assertEqual((verdict["status"], verdict["label"]), ("match", 1))

    def test_one_usable_frame_is_never_fused(self):
        self.vectors = {1: self._near_label_one(1 - (self.threshold + 0.02), 3)}
        self.engine._query = lambda frame: (
            (self.vectors[1], None)
            if int(frame[0, 0, 0]) == 1
            else (None, {"status": "no_face", "label": None, "distance": None, "second": None, "reason": "No face detected."})
        )
        verdict = self.engine.examine_multi(self._frames(1, 2), [1, 2])
        self.assertEqual(verdict["status"], "unknown")


class PresetsStayTests(unittest.TestCase):
    def test_existing_tuning_knobs_still_drive_the_engine(self):
        env = {
            "FACE_THRESHOLD": "0.31",
            "FACE_MARGIN": "0.07",
            "FACE_NEAR_MISS": "0.44",
            "FACE_MIN_SHARPNESS": "22",
            "FACE_BRIGHTNESS_MIN": "35",
            "FACE_BRIGHTNESS_MAX": "230",
            "FACE_MIN_MOTION": "0.9",
            "FACE_DETECTOR": "haar",
        }
        faces_dir = tempfile.mkdtemp(prefix="engine-presets-")
        with patch("backend.face_recognition._load_sface", return_value=_StubRecognizer()), patch(
            "backend.face_recognition.build_store", return_value=FileFaceStore(faces_dir)
        ), patch.dict(os.environ, env):
            engine = OpenCVFaceEngine()
        self.assertEqual(
            (engine.threshold, engine.margin, engine.near_miss, engine.min_sharpness),
            (0.31, 0.07, 0.44, 22.0),
        )
        self.assertEqual((engine.brightness_min, engine.brightness_max, engine.min_motion), (35.0, 230.0, 0.9))

    def test_new_options_default_to_on(self):
        engine = _engine()
        self.assertTrue(engine.enhance_retry)
        self.assertTrue(engine.fuse_frames)


if __name__ == "__main__":
    unittest.main()
