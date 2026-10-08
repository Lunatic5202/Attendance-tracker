"""Face detection, enrollment and recognition.

Primary stack: a face **detector** (Haar cascade by default, YuNet DNN when
``FACE_DETECTOR=yunet``) + **SFace** (recognition), a deep 128-dimensional
face embedding model from the OpenCV model zoo. SFace is substantially more
accurate than the LBPH histogram model it replaces, which matters at a kiosk
where a false reject means a real person cannot clock in.

The stored "template" for an employee is therefore not a picture but a 512-byte
float32 embedding, encrypted before it touches the disk or the database. It
lives under data/faces on SQLite and in PostgreSQL tables when ``DATABASE_URL``
is set, so enrollment survives a container rebuild.

Because only embeddings are stored (never photos), the SFace model and the
``_prepare`` crop/CLAHE pipeline are frozen: changing either would invalidate
every template on disk. Improvements therefore live upstream of embedding
(detector choice, frame quality gates, multi-frame voting) and downstream of it
(the accept threshold, the runner-up margin, template dedup/cap on additive
enrollment) — all of which keep existing templates valid.

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
#: Optional YuNet detector, fetched during the Docker build when enabled.
YUNET_MODEL = Path(
    os.getenv("YUNET_MODEL")
    or Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"
)
#: SFace expects a 112x112 crop and returns a 128-dim float32 embedding.
SFACE_INPUT = 112
EMBED_DIMS = 128
EMBED_BYTES = EMBED_DIMS * 4
#: LFW-masked cosine distance for the 2021dec SFace model.
DEFAULT_FACE_THRESHOLD = 0.363
#: Minimum gap between the best and second-best label. A tighter gap means
#: two people are too close to call, so the scan is rejected as ambiguous.
DEFAULT_FACE_MARGIN = 0.04
#: Upper bound on stored templates per person; additive enrollment refuses
#: to grow past this instead of evicting (deleting) anything.
MAX_TEMPLATES = int(os.getenv("FACE_MAX_TEMPLATES", "5"))
#: New embeddings this close to an existing one are the same pose; storing
#: them would only waste gallery time, so they are skipped, not replaced.
DEDUPE_DISTANCE = float(os.getenv("FACE_DEDUPE_DISTANCE", "0.08"))


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
    detector_name = None

    def enroll(self, label: int, image=None) -> bool:
        FACES_DIR.mkdir(parents=True, exist_ok=True)
        for p in FACES_DIR.glob("*.jpg"):
            if p.name.startswith(f"{label}."):
                return True
        return True

    def enroll_many(self, label: int, images=None) -> bool:
        return True

    def enroll_more(self, label: int, images=None) -> dict:
        count = len(images or [])
        return {"added": count, "duplicates": 0, "no_face": 0, "over_capacity": 0, "total": count}

    def recognize(self, image, candidates: list[int] | None = None) -> tuple[int, float] | None:
        if not candidates:
            return None
        return candidates[0], 0.0

    def examine(self, image, candidates: list[int] | None = None) -> dict:
        match = self.recognize(image, candidates)
        if match is None:
            return {"status": "unknown", "label": None, "distance": None, "second": None, "reason": None}
        return {"status": "match", "label": match[0], "distance": match[1], "second": None, "reason": None}

    def examine_multi(self, frames, candidates: list[int] | None = None) -> dict:
        return self.examine(None, candidates)

    def has(self, label: int) -> bool:
        return label is not None


class OpenCVFaceEngine:
    """OpenCV face detection (Haar, or YuNet when enabled) + SFace embeddings."""

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
        # Optional DNN detector (FACE_DETECTOR=yunet). It needs a small extra
        # model; anything missing or broken falls back to Haar with a warning
        # so a kiosk never boots with no detector at all.
        self.detector_name = "haar"
        self._yunet = None
        if os.getenv("FACE_DETECTOR", "haar").strip().lower() == "yunet":
            self._yunet = self._load_yunet()
            if self._yunet is not None:
                self.detector_name = "yunet"
        # Normalise uneven kiosk lighting on the L channel before embedding.
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        self.threshold = float(os.getenv("FACE_THRESHOLD", DEFAULT_FACE_THRESHOLD))
        self.margin = float(os.getenv("FACE_MARGIN", DEFAULT_FACE_MARGIN))
        self.min_sharpness = float(os.getenv("FACE_MIN_SHARPNESS", "30"))
        self.brightness_min = float(os.getenv("FACE_BRIGHTNESS_MIN", "40"))
        self.brightness_max = float(os.getenv("FACE_BRIGHTNESS_MAX", "220"))
        self._gallery = None
        self._gallery_sig = None
        self._skipped_legacy = 0
        self.store = build_store(FACES_DIR)
        self._migrate_legacy_faces()

    def _load_yunet(self):
        """Build the YuNet DNN detector, or return None to stay on Haar."""
        cv2 = self.cv2
        if not hasattr(cv2, "FaceDetectorYN_create"):
            log.warning("FACE_DETECTOR=yunet but OpenCV has no FaceDetectorYN; staying on Haar.")
            return None
        if not YUNET_MODEL.exists():
            log.warning("YuNet model not found at %s; staying on Haar.", YUNET_MODEL)
            return None
        try:
            return cv2.FaceDetectorYN.create(
                str(YUNET_MODEL),
                "",
                (320, 320),
                score_threshold=float(os.getenv("FACE_YUNET_SCORE", "0.6")),
                nms_threshold=0.3,
                top_k=5000,
            )
        except Exception as exc:
            log.warning("YuNet failed to load (%s); staying on Haar.", exc)
            return None

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
        if self._yunet is not None:
            return self._detect_yunet(image)
        gray = self._gray(image)
        faces = self.detector.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
        )
        return faces

    def _detect_yunet(self, image):
        """Return ``(x, y, w, h)`` boxes ordered by detection confidence."""
        height, width = image.shape[:2]
        self._yunet.setInputSize((width, height))
        frame = image if len(image.shape) == 3 else self.cv2.cvtColor(image, self.cv2.COLOR_GRAY2BGR)
        result = self._yunet.detect(frame)
        faces = result[1] if isinstance(result, tuple) else result
        if faces is None or len(faces) == 0:
            return np.empty((0, 4), dtype=np.int32)
        faces = np.asarray(faces)
        if faces.shape[1] >= 15:
            faces = faces[np.argsort(-faces[:, 14])]  # confidence column
        return np.round(faces[:, :4]).astype(np.int32)

    def _largest(self, image):
        faces = self.detect(image)
        if faces is None or len(faces) == 0:
            return None
        if self._yunet is not None:
            # YuNet rows arrive confidence-sorted; take the most certain box.
            box = faces[0]
            return int(box[0]), int(box[1]), int(box[2]), int(box[3])
        return max(faces, key=lambda b: b[2] * b[3])

    def _quality(self, image, crop) -> str | None:
        """Return a user-facing reason the crop is unusable, else None.

        Quality gates live here (before embedding) so a smeared or badly lit
        frame is sent back as an actionable message instead of quietly
        producing an embedding that cannot match anyone.
        """
        x, y, w, h = crop
        face = image[max(y, 0) : y + h, max(x, 0) : x + w]
        if face.size == 0 or min(face.shape[:2]) < 16:
            return "Face too small — move closer to the camera."
        gray = self._gray(face)
        brightness = float(gray.mean())
        if brightness < self.brightness_min:
            return "Too dark — improve the lighting and try again."
        if brightness > self.brightness_max:
            return "Too bright — reduce glare and try again."
        sharpness = float(self.cv2.Laplacian(gray, self.cv2.CV_64F).var())
        if sharpness < self.min_sharpness:
            return "Blurry — hold still and try again."
        return None

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

    def enroll_more(self, label: int, images) -> dict:
        """Add templates for ``label`` without touching the stored ones.

        Existing embeddings are kept byte-for-byte; new samples are skipped
        when they duplicate a stored pose or would push the person past the
        per-person cap (which refuses additions rather than evicting).
        """
        gallery = self._get_gallery() or {}
        seen = list(gallery.get(label, []))
        existing = len(seen)
        blobs, duplicates, no_face = [], 0, 0
        for image in images:
            crop = self._largest(image)
            vector = None if crop is None else self._embed(image, crop)
            if vector is None:
                no_face += 1
                continue
            if any(self._cosine(vector, other) <= DEDUPE_DISTANCE for other in seen):
                duplicates += 1
                continue
            seen.append(vector)
            blobs.append(encrypt_bytes(vector.tobytes()))
        capacity = max(0, MAX_TEMPLATES - existing)
        over_capacity = max(0, len(blobs) - capacity)
        blobs = blobs[:capacity]
        if blobs:
            self.store.append(label, blobs)
        outcome = {
            "added": len(blobs),
            "duplicates": duplicates,
            "no_face": no_face,
            "over_capacity": over_capacity,
            "total": existing + len(blobs),
        }
        log.info("additive enrollment label=%s -> %s", label, outcome)
        return outcome

    def examine(self, image, candidates: list[int] | None = None) -> dict:
        """Recognise ``image`` and explain the outcome.

        Returns a verdict dict: ``status`` is ``match``, ``unknown``,
        ``ambiguous``, ``low_quality`` or ``no_face``; ``label``/``distance``
        carry the best guess for logging, and ``reason`` a user-facing message.
        Only ``status == "match"`` may create attendance.
        """
        verdict = {"label": None, "distance": None, "second": None, "reason": None}
        crop = self._largest(image)
        if crop is None:
            return {**verdict, "status": "no_face", "reason": "No face detected."}
        reason = self._quality(image, crop)
        if reason:
            return {**verdict, "status": "low_quality", "reason": reason}
        query = self._embed(image, crop)
        if query is None:
            return {**verdict, "status": "no_face", "reason": "No face detected."}
        gallery = self._get_gallery()
        if not gallery:
            return {**verdict, "status": "unknown", "reason": "No templates enrolled."}
        best_label, best, second = None, None, None
        for label, vectors in gallery.items():
            if candidates is not None and label not in candidates:
                continue
            distance = min(self._cosine(query, vector) for vector in vectors)
            if best is None or distance < best:
                best, second = distance, best
                best_label = label
            elif second is None or distance < second:
                second = distance
        if best is None:
            return {**verdict, "status": "unknown", "reason": "No candidates to match."}
        gap = None if second is None else second - best
        if best > self.threshold:
            status = "unknown"
        elif gap is not None and gap < self.margin:
            status = "ambiguous"
        else:
            status = "match"
        log.info(
            "scan decision: label=%s distance=%.4f second=%s threshold=%.4f margin=%.4f -> %s",
            best_label,
            best,
            "n/a" if second is None else f"{second:.4f}",
            self.threshold,
            self.margin,
            status.upper(),
        )
        return {"status": status, "label": best_label, "distance": best, "second": second, "reason": None}

    def examine_multi(self, frames, candidates: list[int] | None = None) -> dict:
        """Vote across a short burst of frames of the same person.

        A frame only votes when it passes the quality gate and matches on its
        own, and a label must win a strict majority of the usable frames. One
        smeared frame no longer fails the whole scan, while one lucky frame is
        no longer enough to clock a stranger in. A lone usable frame keeps the
        old single-frame power, so nothing gets stricter by accident.
        """
        verdict = {"label": None, "distance": None, "second": None, "reason": None}
        if not frames:
            return {**verdict, "status": "no_face", "reason": "No face detected."}
        if len(frames) == 1:
            return self.examine(frames[0], candidates)
        results = [self.examine(frame, candidates) for frame in frames]
        usable = [r for r in results if r["status"] in ("match", "unknown")]
        votes: dict[int, list[float]] = {}
        for result in results:
            if result["status"] == "match" and result["label"] is not None:
                votes.setdefault(result["label"], []).append(result["distance"])
        needed = len(usable) // 2 + 1
        winner, winner_dists = None, []
        for label, distances in votes.items():
            if len(distances) < needed:
                continue
            if (
                winner is None
                or len(distances) > len(winner_dists)
                or (len(distances) == len(winner_dists) and min(distances) < min(winner_dists))
            ):
                winner, winner_dists = label, distances
        if winner is not None:
            log.info(
                "multi-frame decision: %d/%d usable frames agreed on label=%d (needed %d)",
                len(winner_dists), len(usable), winner, needed,
            )
            return {"status": "match", "label": winner, "distance": min(winner_dists), "second": None, "reason": None}
        if usable:
            log.info(
                "multi-frame decision: no consensus across %d usable frames (needed %d)",
                len(usable), needed,
            )
            return {**verdict, "status": "unknown", "reason": "No consensus across frames."}
        low_quality = next((r for r in results if r["status"] == "low_quality"), None)
        if low_quality is not None:
            return low_quality
        return {**verdict, "status": "no_face", "reason": "No face detected."}

    def recognize(self, image, candidates: list[int] | None = None) -> tuple[int, float] | None:
        outcome = self.examine(image, candidates)
        if outcome["status"] == "match":
            return outcome["label"], outcome["distance"]
        return None


engine = build_engine()
