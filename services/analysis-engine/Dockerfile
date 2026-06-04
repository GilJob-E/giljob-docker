FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVICE_NAME=analysis-engine \
    SERVICE_PORT=8200 \
    GILJOBE_GIT_REF=b769120 \
    ANALYSIS_ENGINE_ENABLE_SUBSCRIBER=false

WORKDIR /app

# livekit's Python wheel targets glibc, so use slim instead of alpine.
# git is required for the pinned GitHub dependency; ffmpeg is kept for media tooling parity.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY server.py /app/server.py

EXPOSE 8200
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8200/healthz', timeout=2).read()"

USER nobody
CMD ["python", "/app/server.py"]
