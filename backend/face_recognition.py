"""Face detection, enrollment and recognition.

Primary stack: OpenCV Haar cascade (detection) + OpenCV LBPH model
(recognition), trained on enrolled face crops. Those crops are kept under
data/faces on SQLite and in PostgreSQL tables when ``DATABASE_URL`` is set,
so enrollment survives a container rebuild.

The engine degrades gracefully when OpenCV is not installed so the rest
of the application can still be developed and demoed: DemoFaceEngine
simply trusts a client-provided employee id.
"""

import os
import logging
from pathlib import Path

import numpy as np

from backend.face_store import FileFaceStore, build_store
from backend.security import decrypt_bytes, encrypt_bytes

log = logging.getLogger("face")

DATA_DIR = Path(os.getenv("ATTENDANCE_DATA", "data"))
FACES_DIR = DATA_DIR / "faces"
MODEL_PATH = FACES_DIR / "recognizer.yml"
CASCADE_PATH = FACES_DIR / "haarcascade_frontalface_default.xml"
VENDORED_CASCADE = Path(__file__).parent / "face_recognition_data" / "haarcascade_frontalface_default.xml"


def _installed() -> bool:
    try:
        import cv2  # noqa: F401
        return True
    except Exception:
        return False


def build_engine():
    """Return the best available face engine."""
    if _installed():
        try:
            return OpenCVFaceEngine()
        except Exception as exc:  # pragma: no cover - env dependent
            log.warning("OpenCV engine unavailable (%s); using demo engine.", exc)
    log.warning("OpenCV not installed; using demo (manual) face engine.")
    return DemoFaceEngine()


class DemoFaceEngine:
    """Fallback engine used when OpenCV is missing.

    Enrollment is a no-op that marks the employee as face-ready; the
    recognise() call returns the explicitly provided candidate.
    """

    name = "demo"

    def enroll(self, label: int, image=None) -> bool:
        FACES_DIR.mkdir(parents=True, exist_ok=True)
        for p in FACES_DIR.glob("*.jpg"):
            if p.name.startswith(f"{label}."):
                return True
        return True

    def enroll_many(self, label: int, images=None) -> bool:
        return True

    def recognize(self, image, candidates: list[int] | None = None) -> tuple[int, float] | None:
        if not candidates:
            return None
        return candidates[0], 0.0

    def has(self, label: int) -> bool:
        return label is not None


class OpenCVFaceEngine:
    """OpenCV Haar + LBPH face engine."""

    name = "opencv"

    def __init__(self):
        import cv2  # noqa: WPS433 (imported lazily on purpose)

        self.cv2 = cv2
        cascade = None
        # 1) repo-vendored copy baked into the image (reliable on every host,
        #    including minimal opencv wheels that drop cv2.data.haarcascades).
        if VENDORED_CASCADE.exists():
            cascade = str(VENDORED_CASCADE)
        # 2) runtime data dir copy (first enroll writes it there too).
        elif CASCADE_PATH.exists():
            cascade = str(CASCADE_PATH)
        # 3) the wheel's bundled data dir.
        elif hasattr(cv2, "data"):
            cascade = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        self.detector = cv2.CascadeClassifier(cascade)
        if self.detector.empty():
            raise RuntimeError("Haar cascade classifier failed to load.")
        self.confidence_threshold = float(os.getenv("FACE_CONFIDENCE", "120"))
        self._model = None
        self._model_sig = None
        self.store = build_store(FACES_DIR)
        self._migrate_legacy_faces()

    def _migrate_legacy_faces(self) -> None:
        """Encrypt templates left behind by pre-encryption builds.

        Older versions stored plain ``<label>.jpg`` crops. Newer versions keep
        only ``<label>.enc`` (Fernet-encrypted). Re-encrypt any legacy crop in
        place so existing enrollments keep working after an upgrade.
        """
        if not isinstance(self.store, FileFaceStore):
            return
        for path in sorted(FACES_DIR.glob("*.jpg")):
            try:
                label = int(path.stem.split(".")[0])
            except ValueError:
                continue
            target = FACES_DIR / f"{label}.enc"
            if not target.exists():
                try:
                    target.write_bytes(encrypt_bytes(path.read_bytes()))
                except Exception as exc:
                    log.warning("Could not migrate face template %s: %s", path, exc)
                    continue
            path.unlink(missing_ok=True)

    # ---- helpers ---------------------------------------------------------
    def _gray(self, image):
        if len(image.shape) == 3:
            return self.cv2.cvtColor(image, self.cv2.COLOR_BGR2GRAY)
        return image

    def detect(self, image):
        gray = self._gray(image)
        faces = self.detector.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
        )
        return faces

    def _largest(self, image):
        faces = self.detect(image)
        if len(faces) == 0:
            return None
        return max(faces, key=lambda b: b[2] * b[3])

    def _encode(self, image, crop):
        x, y, w, h = crop
        face = self._gray(image)[y : y + h, x : x + w]
        face = self.cv2.resize(face, (160, 160))
        return face

    def _rebuild_model(self):
        images, labels = [], []
        for label, encrypted in self.store.iter_templates():
            try:
                raw = np.frombuffer(decrypt_bytes(encrypted), dtype=np.uint8)
                img = self.cv2.imdecode(raw, self.cv2.IMREAD_GRAYSCALE)
            except Exception as exc:
                log.warning("Could not decrypt face template %s: %s", label, exc)
                continue
            if img is None or img.size == 0:
                log.warning("Could not read face crop %s", label)
                continue
            if img.shape != (160, 160):
                img = self.cv2.resize(img, (160, 160))
            images.append(img)
            labels.append(label)
        if not images:
            return None
        model = self.cv2.face.LBPHFaceRecognizer_create()
        model.train(images, np.asarray(labels, dtype=np.int32))
        return model

    def _get_model(self):
        """Return the trained recognizer, cached until the templates change.

        Rebuilding on every frame made a live kiosk needlessly slow (and a
        stale build once broke recognition entirely after an enrollment).
        """
        sig = self.store.signature()
        if sig != self._model_sig and self._model is not None:
            self._model = None  # templates changed -> drop cache
        if self._model is None:
            self._model = self._rebuild_model()
            self._model_sig = sig
        return self._model

    # ---- public api ------------------------------------------------------
    def enroll(self, label: int, image) -> bool:
        crop = self._largest(image)
        if crop is None:
            return False
        face = self._encode(image, crop)
        ok, encoded = self.cv2.imencode(".png", face)
        if not ok:
            return False
        self.store.save(label, [encrypt_bytes(encoded.tobytes())])
        return True

    def enroll_many(self, label: int, images) -> bool:
        """Replace the templates for ``label`` with one per supplied image.

        Multiple poses/pictures improve recognition. Returns ``True`` if at
        least one image contained a usable face.
        """
        crops = []
        for image in images:
            crop = self._largest(image)
            if crop is None:
                continue
            face = self._encode(image, crop)
            ok, encoded = self.cv2.imencode(".png", face)
            if ok:
                crops.append(encrypt_bytes(encoded.tobytes()))
        if not crops:
            return False
        self.store.save(label, crops)
        return True

    def has(self, label: int) -> bool:
        return self.store.has(label)

    def recognize(self, image, candidates: list[int] | None = None) -> tuple[int, float] | None:
        crop = self._largest(image)
        if crop is None:
            return None
        face = self._encode(image, crop)
        model = self._get_model()
        if model is None:
            return None
        label, confidence = model.predict(face)
        decided = (
            (label, float(confidence))
            if confidence <= self.confidence_threshold
            and (candidates is None or label in candidates)
            else None
        )
        log.info(
            "scan decision: label=%s distance=%.1f threshold=%.1f -> %s",
            label,
            confidence,
            self.confidence_threshold,
            "MATCH" if decided else "REJECT",
        )
        return decided


engine = build_engine()
