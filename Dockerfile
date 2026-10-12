# syntax=docker/dockerfile:1

# ---------- 1. Build the web UI ----------
FROM node:20.18.1-bookworm-slim AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2. Python runtime with fonts ----------
FROM python:3.12.8-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OMP_THREAD_LIMIT=1 \
    PDF_STUDIO_DATA=/data \
    PDF_STUDIO_STATIC=/app/static

# Fonts: metric-compatible substitutes for common fonts (Arial/Times/Courier ->
# Liberation, Calibri -> Carlito, Cambria -> Caladea) plus wide Unicode coverage.
# OCR: Tesseract with a set of common languages (add more tesseract-ocr-<lang> here).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      fonts-liberation2 fonts-crosextra-carlito fonts-crosextra-caladea \
      fonts-dejavu-core fonts-noto-core fonts-open-sans fonts-lato fonts-roboto-unhinted \
      tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-deu tesseract-ocr-fra \
      tesseract-ocr-spa tesseract-ocr-ita tesseract-ocr-por \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY --from=frontend /src/dist ./static

RUN useradd --create-home --uid 10001 studio \
 && mkdir -p /data \
 && chown studio:studio /data
USER studio
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4).status == 200 else 1)"

# One worker on purpose: MuPDF is not thread-safe and all PDF work is serialized.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]

# ---------- 3. Optional: run the test-suite (docker build --target test .) ----------
FROM runtime AS test
USER root
COPY backend/requirements-dev.txt backend/pytest.ini ./
COPY backend/tests ./tests
RUN pip install -r requirements-dev.txt && python -m pytest -q

# Default target is the runtime image.
FROM runtime
