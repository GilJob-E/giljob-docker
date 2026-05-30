FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVICE_NAME=agent1 \
    SERVICE_PORT=8010

WORKDIR /app
COPY server.py /app/server.py

EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/healthz', timeout=2).read()"

USER nobody
CMD ["python", "/app/server.py"]
