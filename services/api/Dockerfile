FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVICE_NAME=api \
    SERVICE_PORT=8000

WORKDIR /app
# libpq is the runtime shared library pure-Python psycopg loads to reach Postgres
# (the prebuilt psycopg[binary] wheel is glibc-only, so on Alpine we use libpq).
RUN apk add --no-cache libpq
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY app /app/app
COPY db /app/db
COPY server.py /app/server.py

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).read()"

USER nobody
CMD ["python", "/app/server.py"]
