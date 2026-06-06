FROM node:20-alpine AS deps

WORKDIR /deps
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts

FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVICE_NAME=web \
    SERVICE_PORT=3000 \
    STATIC_ROOT=/app/static

WORKDIR /app
COPY server.py /app/server.py
COPY static /app/static
COPY --from=deps /deps/node_modules/livekit-client/dist /app/static/vendor/livekit-client/dist
COPY --from=deps /deps/node_modules/@spatialwalk/avatarkit/dist /app/static/vendor/@spatialwalk/avatarkit/dist
COPY --from=deps /deps/node_modules/@spatialwalk/avatarkit-rtc/dist /app/static/vendor/@spatialwalk/avatarkit-rtc/dist

EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/healthz', timeout=2).read()"

USER nobody
CMD ["python", "/app/server.py"]
