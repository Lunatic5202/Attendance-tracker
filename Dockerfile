FROM python:3.12-slim

# System libs OpenCV needs at runtime (libgl1/libglib2.0-0) and Node to build
# the React frontend (nodejs/npm).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        nodejs \
        npm \
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
RUN mkdir -p data

EXPOSE 8000

CMD ["python", "main.py"]