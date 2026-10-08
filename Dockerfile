FROM python:3.12-slim

# System libs OpenCV needs at runtime (libgl1/libglib2.0-0) and Node to build
# the React frontend (nodejs/npm). curl is used to fetch the recognition models.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        nodejs \
        npm \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci

COPY frontend ./frontend
RUN cd frontend && npm run build && rm -rf node_modules

COPY backend ./backend
COPY main.py .

# SFace recognition model (2021dec, 37 MB) and the optional YuNet detector
# (230 KB) from the OpenCV model zoo. Both are baked into the image rather than
# committed to git, and the checksums plus the load tests below make a bad
# download fail the build instead of shipping a kiosk that cannot recognise
# anyone. YuNet only activates with FACE_DETECTOR=yunet; Haar stays the default.
ENV SFACE_URL=https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx
ENV SFACE_SHA256=0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79
ENV YUNET_URL=https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
ENV YUNET_SHA256=8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4
RUN mkdir -p backend/models \
    && curl -fsSL --retry 3 --retry-delay 2 -o backend/models/face_recognition_sface_2021dec.onnx "$SFACE_URL" \
    && echo "$SFACE_SHA256  backend/models/face_recognition_sface_2021dec.onnx" | sha256sum -c - \
    && curl -fsSL --retry 3 --retry-delay 2 -o backend/models/face_detection_yunet_2023mar.onnx "$YUNET_URL" \
    && echo "$YUNET_SHA256  backend/models/face_detection_yunet_2023mar.onnx" | sha256sum -c - \
    && ATTENDANCE_MASTER_KEY=build-test python -c "\
from backend.face_recognition import OpenCVFaceEngine; \
e = OpenCVFaceEngine(); \
print('SFace engine ready:', e.name, e.threshold)" \
    && FACE_DETECTOR=yunet ATTENDANCE_MASTER_KEY=build-test python -c "\
from backend.face_recognition import OpenCVFaceEngine; \
e = OpenCVFaceEngine(); \
assert e.detector_name == 'yunet', 'YuNet failed to activate'; \
print('YuNet detector ready')"

RUN mkdir -p data

EXPOSE 8000

CMD ["python", "main.py"]