"""Face detection, enrollment and recognition.

Primary stack: OpenCV Haar cascade (detection) + **SFace** (recognition), a
deep 128-dimensional face embedding model from the OpenCV model zoo. SFace is
substantially more accurate than the LBPH histogram model it replaces, which
matters at a kiosk where a false reject means a real person cannot clock in.

The stored "template" for an employee is therefore not a picture but a 512-byte
float32 embedding, encrypted before it touches the disk or the database. It
lives under data/faces on SQLite and in PostgreSQL tables when ``DATABASE_URL``
is set, so enrollment survives a container rebuild.

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
CASCADE_PATH = FACES_DIR / "haarcascade_frontalface_default.xml"
VENDORED_CASCADE = Path(__file__).parent / "face_recognition_data" / "haarcascade_frontalface_default.xml"

#: SFace is fetched during the Docker build; ``SFACE_MODEL`` can point elsewhere.
SFACE_MODEL = Path(
    os.getenv("SFACE_MODEL")
    or Path(__file__).parent / "models" / "face_recognition_sface_2021dec.onnx"
)
#: SFace expects a 112x112 crop and returns a 128-dim float32 embedding.
SFACE_INPUT = 112
EMBED_DIMS = 128
EMBED_BYTES = EMBED_DIMS * 4
#: LFW-masked cosine distance for the 2021dec SFace model.
DEFAULT_FACE_THRESHOLD = 0.363


def _installed() -> bool:
    try:
        import cv2  # noqa: F401
        return True
    except Exception:
        return False


def _load_sface():
    """Return a ready SFace recognizer, or raise if the model is unusable."""
    import cv2

    if not hasattr(cv2, "FaceRecognizerSF_create"):
        raise RuntimeError("This OpenCV build has no FaceRecognizerSF (need opencv-contrib-python).")
    if not SFACE_MODEL.exists():
        raise RuntimeError(f"SFace model not found at {SFACE_MODEL}.")
    recognizer = cv2.FaceRecognizerSF_create(str(SFACE_MODEL), "")
    # Force a forward pass so a corrupt/truncated model fails here, at build or
    # boot time, instead of silently mis-recognising people at the kiosk.
    probe = np.zeros((SFACE_INPUT, SFACE_INPUT, 3), dtype=np.uint8)
    embedding = recognizer.feature(probe)
    if embedding is None or embedding.size != EMBED_DIMS:
        raise RuntimeError("SFace model returned an unexpected embedding.")
    return recognizer


def build_engine():
    """Return the best available face engine."""
    if _installed():
        try:
            return OpenCVFaceEngine()
        except Exception as exc:  # pragma: no cover - env dependent
            log.error("OpenCV/SFace engine unavailable (%s); using demo engine.", exc)
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
    """OpenCV Haar cascade + SFace embedding recognizer."""

    name = "opencv"

    def __init__(self):
        import cv2  # noqa: WPS433 (imported lazily on purpose)

        self.cv2 = cv2
        self.recognizer = _load_sface()
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
        # Normalise uneven kiosk lighting on the L channel before embedding.
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        self.threshold = float(os.getenv("FACE_THRESHOLD", DEFAULT_FACE_THRESHOLD))
        self._gallery = None
        self._gallery_sig = None
        self._skipped_legacy = 0
        self.store = build_store(FACES_DIR)
        self._migrate_legacy_faces()

    def _migrate_legacy_faces(self) -> None:
        """Remove plaintext face crops left behind by pre-encryption builds.

        Older versions stored plain ``<label>.jpg`` crops. They are deleted
        rather than converted: SFace needs a photo to embed, and keeping a
        stale crop would only leave unusable templates behind.
        """
        if not isinstance(self.store, FileFaceStore):
            return
        for path in sorted(FACES_DIR.glob("*.jpg")):
            try:
                label = int(path.stem.split(".")[0])
            except ValueError:
                continue
            self.store.clear(label)
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

    def _prepare(self, image, crop):
        """Crop the detected face and return the 112x112 BGR buffer SFace wants."""
        x, y, w, h = crop
        face = image[y : y + h, x : x + w]
        if len(face.shape) == 2:
            face = self.cv2.cvtColor(face, self.cv2.COLOR_GRAY2BGR)
        face = self.cv2.resize(face, (SFACE_INPUT, SFACE_INPUT))
        # CLAHE per channel keeps shadows/uneven lighting from dominating the
        # embedding; SFace expects colour, so it is applied to all three.
        return self.cv2.merge([self._clahe.apply(ch) for ch in self.cv2.split(face)])

    def _embed(self, image, crop) -> np.ndarray | None:
        buffer = self._prepare(image, crop)
        embedding = self.recognizer.feature(buffer)
        if embedding is None or embedding.size != EMBED_DIMS:
            return None
        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else None

    @staticmethod
    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        if not denom:
            return 1.0
        return 1.0 - float(np.dot(a, b)) / denom

    def _rebuild_gallery(self):
        """Return ``{label: [embedding, ...]}`` from the stored templates."""
        gallery: dict[int, list[np.ndarray]] = {}
        skipped = 0
        for label, encrypted in self.store.iter_templates():
            try:
                raw = decrypt_bytes(encrypted)
            except Exception as exc:
                log.warning("Could not decrypt face template %s: %s", label, exc)
                continue
            if len(raw) != EMBED_BYTES:
                # An LBPH-era crop: unusable by SFace, needs re-enrollment.
                skipped += 1
                continue
            vector = np.frombuffer(raw, dtype=np.float32)
            norm = float(np.linalg.norm(vector))
            if not norm:
                continue
            gallery.setdefault(label, []).append(vector / norm)
        if skipped:
            log.warning(
                "Skipped %d legacy LBPH template(s); those employees must re-enrol once for SFace.",
                skipped,
            )
        self._skipped_legacy = skipped
        return gallery or None

    def _get_gallery(self):
        """Return the embedding gallery, cached until the templates change.

        Rebuilding on every frame made a live kiosk needlessly slow.
        """
        sig = self.store.signature()
        if sig != self._gallery_sig and self._gallery is not None:
            self._gallery = None  # templates changed -> drop cache
        if self._gallery is None:
            self._gallery = self._rebuild_gallery()
            self._gallery_sig = sig
        return self._gallery

    # ---- public api ------------------------------------------------------
    def enroll(self, label: int, image) -> bool:
        crop = self._largest(image)
        if crop is None:
            return False
        return self.enroll_many(label, [image])

    def enroll_many(self, label: int, images) -> bool:
        """Replace the templates for ``label`` with one per supplied image.

        Multiple poses/pictures improve recognition, since a match is the best
        (lowest) distance across the stored embeddings. Returns ``True`` if at
        least one image contained a usable face.
        """
        stored = []
        for image in images:
            crop = self._largest(image)
            if crop is None:
                continue
            vector = self._embed(image, crop)
            if vector is not None:
                stored.append(encrypt_bytes(vector.tobytes()))
        if not stored:
            return False
        self.store.save(label, stored)
        return True

    def has(self, label: int) -> bool:
        """Whether ``label`` has a template SFace can actually use.

        Validating the stored bytes (rather than just asking the store) means a
        leftover LBPH-era template counts as "not enrolled", so the startup seed
        and the admin UI both offer a re-enroll instead of leaving an employee
        permanently unrecognisable.
        """
        for _label, encrypted in self.store.iter_templates():
            if _label != label:
                continue
            try:
                if len(decrypt_bytes(encrypted)) == EMBED_BYTES:
                    return True
            except Exception:
                continue
        return False

    def recognize(self, image, candidates: list[int] | None = None) -> tuple[int, float] | None:
        crop = self._largest(image)
        if crop is None:
            return None
        query = self._embed(image, crop)
        if query is None:
            return None
        gallery = self._get_gallery()
        if not gallery:
            return None
        best_label, best = None, None
        for label, vectors in gallery.items():
            if candidates is not None and label not in candidates:
                continue
            distance = min(self._cosine(query, vector) for vector in vectors)
            if best is None or distance < best:
                best_label, best = label, distance
        decided = best if best is not None and best <= self.threshold else None
        log.info(
            "scan decision: label=%s distance=%.4f threshold=%.4f -> %s",
            best_label,
            best if best is not None else float("nan"),
            self.threshold,
            "MATCH" if decided is not None else "REJECT",
        )
        return (best_label, best) if decided is not None else None


engine = build_engine()
