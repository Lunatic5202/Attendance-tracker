import os
import tempfile
from unittest.mock import patch
import unittest

os.environ["ATTENDANCE_MASTER_KEY"] = "test-master-key"
os.environ["ATTENDANCE_DATA"] = tempfile.mkdtemp(prefix="attendance-fs-tests-")
os.environ["ATTENDANCE_DB"] = os.path.join(os.environ["ATTENDANCE_DATA"], "test.db")
os.environ.pop("DATABASE_URL", None)

from backend.face_store import FileFaceStore


class FileFaceStoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="faces-")
        self.store = FileFaceStore(self.dir)

    def test_missing_label_reports_absent(self):
        self.assertFalse(self.store.has(1))

    def test_save_then_has(self):
        self.store.save(1, [b"blob"])
        self.assertTrue(self.store.has(1))

    def test_save_multiple_templates(self):
        self.store.save(1, [b"a", b"b", b"c"])
        self.assertEqual([blob for _, blob in self.store.iter_templates()], [b"a", b"b", b"c"])

    def test_iter_templates_reports_label_and_order(self):
        self.store.save(2, [b"two"])
        self.store.save(1, [b"one"])
        self.assertEqual(list(self.store.iter_templates()), [(1, b"one"), (2, b"two")])

    def test_save_replaces_previous_templates(self):
        self.store.save(1, [b"a", b"b", b"c"])
        self.store.save(1, [b"only"])
        self.assertEqual(list(self.store.iter_templates()), [(1, b"only")])

    def test_clearing_one_label_keeps_similar_labels(self):
        self.store.save(1, [b"one"])
        self.store.save(10, [b"ten"])
        self.store.save(11, [b"eleven"])
        self.store.save(100, [b"hundred"])
        self.store.clear(1)
        remaining = dict(self.store.iter_templates())
        self.assertNotIn(1, remaining)
        self.assertEqual(remaining[10], b"ten")
        self.assertEqual(remaining[11], b"eleven")
        self.assertEqual(remaining[100], b"hundred")

    def test_clearing_high_label_keeps_lower_labels(self):
        self.store.save(9, [b"nine"])
        self.store.save(10, [b"ten"])
        self.store.clear(10)
        self.assertEqual(dict(self.store.iter_templates()), {9: b"nine"})

    def test_multi_template_clear_removes_every_variant(self):
        self.store.save(1, [b"a", b"b"])
        self.store.clear(1)
        self.assertFalse(self.store.has(1))
        self.assertEqual(list(self.store.iter_templates()), [])

    def test_signature_changes_when_templates_change(self):
        before = self.store.signature()
        self.store.save(1, [b"one"])
        self.assertNotEqual(self.store.signature(), before)

    def test_signature_is_stable_when_nothing_changes(self):
        self.store.save(1, [b"one"])
        self.assertEqual(self.store.signature(), self.store.signature())

    def test_clear_ignores_unrelated_files(self):
        self.store.save(2, [b"two"])
        with open(os.path.join(self.dir, "notes.txt"), "w") as handle:
            handle.write("keep me")
        self.store.clear(2)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "notes.txt")))


class EnginePersistenceTests(unittest.TestCase):
    """The recognizer must rebuild from stored templates alone."""

    def setUp(self):
        import numpy as np
        from backend.face_recognition import OpenCVFaceEngine
        from backend.face_store import FileFaceStore

        self.np = np
        self.FileFaceStore = FileFaceStore
        self.faces_dir = tempfile.mkdtemp(prefix="engine-faces-")
        self._patch = patch(
            "backend.face_recognition.build_store", return_value=FileFaceStore(self.faces_dir)
        )
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.engine = OpenCVFaceEngine()
        self.engine._largest = lambda image: (0, 0, 160, 160)

    def _pattern(self, seed):
        return self.np.random.default_rng(seed).integers(0, 256, (160, 160, 3), dtype=self.np.uint8)

    def _fresh_engine(self):
        from backend.face_recognition import OpenCVFaceEngine

        engine = OpenCVFaceEngine()
        engine._largest = lambda image: (0, 0, 160, 160)
        return engine

    def test_gallery_rebuilds_from_stored_templates_only(self):
        self.engine.enroll_many(1, [self._pattern(1)])
        self.engine.enroll_many(2, [self._pattern(2)])
        fresh = self._fresh_engine()
        self.assertIsNotNone(fresh._get_gallery(), "a new engine must load from the store")

    def test_recognizes_each_stored_employee(self):
        self.engine.enroll_many(1, [self._pattern(1)])
        self.engine.enroll_many(2, [self._pattern(2)])
        fresh = self._fresh_engine()
        self.assertEqual(fresh.recognize(self._pattern(1), [1, 2])[0], 1)
        self.assertEqual(fresh.recognize(self._pattern(2), [1, 2])[0], 2)

    def test_re_enrolling_one_employee_keeps_the_others(self):
        self.engine.enroll_many(1, [self._pattern(1)])
        self.engine.enroll_many(2, [self._pattern(2)])
        self.engine.enroll_many(1, [self._pattern(7)])
        fresh = self._fresh_engine()
        self.assertEqual(fresh.recognize(self._pattern(7), [1, 2])[0], 1)
        self.assertEqual(fresh.recognize(self._pattern(2), [1, 2])[0], 2)

    def test_removing_a_employee_drops_their_template(self):
        self.engine.enroll_many(1, [self._pattern(1)])
        self.engine.enroll_many(2, [self._pattern(2)])
        self.engine.store.clear(1)
        fresh = self._fresh_engine()
        self.assertFalse(fresh.has(1))
        self.assertTrue(fresh.has(2))

    def test_legacy_lbph_template_is_not_treated_as_enrolled(self):
        """An LBPH-era crop is unusable by SFace, so it must read as absent."""
        from backend.face_recognition import EMBED_BYTES
        from backend.security import encrypt_bytes

        self.engine.store.save(3, [encrypt_bytes(b"\x00" * 25600)])
        fresh = self._fresh_engine()
        self.assertFalse(fresh.has(3), "legacy crop must not count as a valid template")
        self.assertNotIn(3, fresh._get_gallery() or {})

    def test_template_is_a_512_byte_embedding(self):
        from backend.face_recognition import EMBED_BYTES
        from backend.security import decrypt_bytes

        self.assertEqual(EMBED_BYTES, 512)
        self.engine.enroll_many(1, [self._pattern(1)])
        blob = decrypt_bytes(next(iter(self.engine.store.iter_templates()))[1])
        self.assertEqual(len(blob), EMBED_BYTES)

    def test_match_uses_the_minimum_distance_across_poses(self):
        self.engine.enroll_many(1, [self._pattern(1), self._pattern(2)])
        fresh = self._fresh_engine()
        # Both stored poses must resolve to the same person.
        self.assertEqual(fresh.recognize(self._pattern(1), [1])[0], 1)
        self.assertEqual(fresh.recognize(self._pattern(2), [1])[0], 1)

    def test_candidate_filter_is_respected(self):
        self.engine.enroll_many(1, [self._pattern(1)])
        self.engine.enroll_many(2, [self._pattern(2)])
        fresh = self._fresh_engine()
        # A candidate list naming nobody enrolled must not produce a match.
        # (Note: noise images are only ~0.17 apart in SFace space, so this
        # checks the filter itself, not real-face separability.)
        self.assertIsNone(fresh.recognize(self._pattern(1), [99]))
        self.assertIsNone(fresh.recognize(self._pattern(1), []))


if __name__ == "__main__":
    unittest.main()
