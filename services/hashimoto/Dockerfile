# GilJob v2 hashimoto strategy engine (internal sidecar).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

# Internal only — not routed through Caddy. GEMINI_API_KEY injected via env.
EXPOSE 8200

CMD ["python", "server.py"]
