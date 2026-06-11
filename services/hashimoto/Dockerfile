# GilJob v2 hashimoto strategy engine (internal sidecar).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

# 비-root 사용자로 실행(컨테이너 탈취 시 권한 최소화). 앱은 쓰기 권한이 필요 없다.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

# Internal only — not routed through Caddy. GEMINI_API_KEY injected via env.
EXPOSE 8200

CMD ["python", "server.py"]
