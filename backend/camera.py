"""Webcam capture helper (kiosk/server-side capture).

The primary flow captures frames in the browser via getUserMedia and posts
them to the API; this module optionally powers a server-side kiosk camera.
"""

import logging

log = logging.getLogger("camera")


class Camera:
    """Thin wrapper around OpenCV's VideoCapture, with graceful fallback."""

    def __init__(self, index: int = 0):
        self.index = index
        self._cap = None
        self.available = False
        try:
            import cv2  # noqa: F401

            self._cv2 = __import__("cv2")
            self.available = True
        except Exception as exc:
            log.warning("OpenCV unavailable, camera disabled (%s).", exc)
            self._cv2 = None

    def open(self) -> bool:
        if not self.available:
            return False
        self._cap = self._cv2.VideoCapture(self.index)
        return self._cap is not None and self._cap.isOpened()

    def read(self):
        if not self.available or self._cap is None or not self._cap.isOpened():
            return None
        ok, frame = self._cap.read()
        return frame if ok else None

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_args):
        self.close()


def capture_frame(index: int = 0):
    """Capture a single frame, returning a numpy array or None."""
    cam = Camera(index)
    try:
        if not cam.open():
            return None
        frame = cam.read()
        return frame
    finally:
        cam.close()