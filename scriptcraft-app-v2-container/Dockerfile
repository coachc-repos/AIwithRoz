# ScriptCraft v2 — container/cloud build
# Headless variant: NO DaVinci Resolve, NO local Whisper, NO local-disk
# video/audio saves. Designed for Azure Container Apps.

FROM python:3.12-slim

ARG BUILD_VERSION=v2-container
ENV APP_VERSION=${BUILD_VERSION}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    PYTHONPATH=/app

WORKDIR /app

# Minimal system deps (Pillow needs a few libs; curl for healthcheck; ffmpeg to mute Grok B-roll)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ffmpeg \
        libjpeg62-turbo \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# App source
COPY container_app.py web_gui.py ./
COPY templates/ ./templates/
COPY static/ ./static/
COPY console_ui/ ./console_ui/
COPY linedrive_azure/ ./linedrive_azure/
COPY tools/ ./tools/

# Non-root
RUN useradd --create-home --shell /bin/bash scriptcraft \
    && mkdir -p /tmp/scriptcraft_output \
    && chown -R scriptcraft:scriptcraft /app /tmp/scriptcraft_output
USER scriptcraft

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8080/healthz || exit 1

# SINGLE worker (many threads) — progress/SSE job state lives in an in-process
# dict (progress_streams), so all requests for a session MUST hit the same
# process. Multiple workers/replicas caused /progress/<id> to 404 intermittently
# ("connection error" during script processing). Threads give I/O concurrency
# for the agent/API calls without splitting in-memory state. Pair with
# minReplicas=maxReplicas=1 on the Container App.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", \
     "--workers", "1", "--threads", "8", \
     "--timeout", "600", "--graceful-timeout", "30", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "container_app:app"]
