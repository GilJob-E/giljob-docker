FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVICE_NAME=stt-whisper \
    SERVICE_PORT=8200 \
    HF_HOME=/models/huggingface \
    HF_HUB_DISABLE_XET=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates python3 python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /models/huggingface \
    && chown -R nobody:nogroup /models

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt
COPY server.py /app/server.py

EXPOSE 8200
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8200/healthz', timeout=3).read()"

USER nobody
CMD ["python3", "/app/server.py"]
