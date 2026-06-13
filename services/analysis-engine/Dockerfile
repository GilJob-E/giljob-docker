FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVICE_NAME=analysis-engine \
    SERVICE_PORT=8200 \
    ANALYSIS_ENGINE_PORT=8200 \
    GILJOBE_GIT_REF=a26045d \
    ANALYSIS_ENGINE_ENABLE_SUBSCRIBER=false \
    GILJOBE_VISION_MODELS_DIR=/app/models \
    # matplotlib (mediapipe dep) and fontconfig need a writable cache dir; USER nobody has
    # HOME=/nonexistent, so point both at /tmp to avoid warnings and slow imports.
    MPLCONFIGDIR=/tmp/matplotlib \
    XDG_CACHE_HOME=/tmp/.cache

WORKDIR /app

# livekit's Python wheel targets glibc, so use slim instead of alpine.
# git is required for the pinned GitHub dependency; ffmpeg is kept for media tooling parity;
# curl fetches the pinned MediaPipe models below; libegl1+libgles2 are required by MediaPipe's
# C bindings even for CPU-only inference (dlopen of libGLESv2 — verified in-container).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ffmpeg ca-certificates curl libegl1 libgles2 \
    && rm -rf /var/lib/apt/lists/*

# GilJobE owns the STT/subscriber HTTP contract surface itself (server/http_app.py):
# /subscriber/start|stop, /signals, /healthz, /readyz. The local entrypoint below builds
# that same GilJobE app and adds GilJob v2's Realtime MMM ingress route
# (/realtime/turn-events) so services/api can forward answer-state STT/prosody/vision sideband.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY server.py /app/server.py

# MediaPipe Face/Pose/Hand Landmarker models for GilJobE's objective vision grounding lane
# (Hands adds finger-count segments that ride the turn_handoff fragment as finger_sequence).
# Baked at build time from version-pinned URLs so the runtime needs no network fetch.
# The lane self-disables when models/deps are missing, so this stays optional-by-design.
RUN mkdir -p /app/models \
    && curl -fsSL -o /app/models/face_landmarker.task \
       https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task \
    && curl -fsSL -o /app/models/pose_landmarker.task \
       https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task \
    && curl -fsSL -o /app/models/hand_landmarker.task \
       https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task

EXPOSE 8200
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8200/healthz', timeout=2).read()"

USER nobody
CMD ["python", "/app/server.py"]
