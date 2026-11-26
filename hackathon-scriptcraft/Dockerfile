# ScriptCraft v3 hackathon image.
# Same web app as scriptcraft-app-v3-container, plus Chromium (explainer
# render), ffmpeg, Piper (offline narration), and a small faster-whisper model.
# Build context is this folder. Do not refer to a parent directory.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080 \
    PYTHONPATH=/app \
    SCRIPTCRAFT_DISABLE_LOCAL_FEATURES=1 \
    SCRIPTCRAFT_SETTINGS_BLOB_CONTAINER= \
    SCRIPTCRAFT_CHROME_NO_SANDBOX=1 \
    SCRIPTCRAFT_OUTPUT_PARENT=/tmp/scriptcraft_output \
    TTS_PROVIDER=azure \
    TTS_VOICE=en-US-AvaMultilingualNeural \
    TTS_WPM=175 \
    TTS_BASELINE_WPM=150 \
    PIPER_BIN=/opt/piper/piper \
    PIPER_MODEL=/opt/piper/en_US-lessac-medium.onnx \
    WHISPER_MODEL_DIR=/opt/whisper \
    WHISPER_MODEL=tiny.en \
    HF_HOME=/opt/hf \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        ffmpeg \
        chromium \
        fonts-liberation \
        libjpeg62-turbo \
        zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && if [ -x /usr/bin/chromium ]; then ln -sf /usr/bin/chromium /usr/local/bin/scriptcraft-chrome; \
       elif [ -x /usr/bin/chromium-browser ]; then ln -sf /usr/bin/chromium-browser /usr/local/bin/scriptcraft-chrome; \
       else echo "Chromium was not installed" >&2; exit 1; fi

ENV SCRIPTCRAFT_CHROME=/usr/local/bin/scriptcraft-chrome

# Piper binary and the lessac medium English voice. Runtime needs no network.
ARG PIPER_VERSION=2023.11.14-2
RUN curl -fsSL -o /tmp/piper.tar.gz \
        "https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_linux_x86_64.tar.gz" \
    && mkdir -p /opt/piper \
    && tar -xzf /tmp/piper.tar.gz -C /opt/piper --strip-components=1 \
    && curl -fsSL -o /opt/piper/en_US-lessac-medium.onnx \
        "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx?download=true" \
    && curl -fsSL -o /opt/piper/en_US-lessac-medium.onnx.json \
        "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json?download=true" \
    && chmod -R a+rX /opt/piper \
    && rm -f /tmp/piper.tar.gz

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt \
    && python -c "from faster_whisper import WhisperModel; WhisperModel('tiny.en', device='cpu', compute_type='int8', download_root='/opt/whisper')" \
    && chmod -R a+rX /opt/whisper \
    && if [ -d /opt/hf ]; then chmod -R a+rX /opt/hf; fi

COPY narration.py container_app.py web_gui.py \
     explainer_articles.py explainer_brands.py explainer_imagery.py \
     explainer_scenes.py explainer_styles.py explainer_video.py ./
COPY templates/ ./templates/
COPY static/ ./static/
COPY console_ui/ ./console_ui/
COPY linedrive_azure/ ./linedrive_azure/
COPY tools/ ./tools/
COPY agent_instructions/ ./agent_instructions/

RUN useradd --create-home --shell /bin/bash scriptcraft \
    && mkdir -p /tmp/scriptcraft_output \
    && chown -R scriptcraft:scriptcraft /app /tmp/scriptcraft_output
USER scriptcraft

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:8080", \
     "--workers", "1", "--threads", "8", \
     "--timeout", "600", "--graceful-timeout", "30", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "container_app:app"]
