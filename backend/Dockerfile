# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System packages: build tools for wheels, plus the GTK/Cairo stack WeasyPrint needs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first so a code change doesn't invalidate the layer.
COPY requirements.txt requirements-pdf.txt ./
RUN pip install -r requirements.txt && pip install -r requirements-pdf.txt

COPY . .

# Run as a non-root user; give it the storage directory.
RUN useradd --create-home --uid 1000 karobar \
    && mkdir -p /app/storage /app/logs \
    && chown -R karobar:karobar /app
USER karobar

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/ready || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
