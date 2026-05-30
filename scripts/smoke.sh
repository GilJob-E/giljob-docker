#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT_DIR/infra/docker-compose.yml")
MEDIA_COMPOSE=(docker compose -f "$ROOT_DIR/infra/docker-compose.yml" -f "$ROOT_DIR/infra/docker-compose.media.yml")

export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-giljob-dev-password}"
export SESSION_TOKEN_HASH_SECRET="${SESSION_TOKEN_HASH_SECRET:-giljob-dev-session-secret}"
export REPORT_TOKEN_HASH_SECRET="${REPORT_TOKEN_HASH_SECRET:-giljob-dev-report-secret}"
export LIVEKIT_INTERNAL_URL="${LIVEKIT_INTERNAL_URL:-ws://livekit:7880}"
export LIVEKIT_PUBLIC_URL="${LIVEKIT_PUBLIC_URL:-ws://127.0.0.1:7880}"
export LIVEKIT_API_KEY="${LIVEKIT_API_KEY:-devkey}"
export LIVEKIT_API_SECRET="${LIVEKIT_API_SECRET:-devsecret-with-at-least-32-bytes}"
export LIVEKIT_TOKEN_TTL_SECONDS="${LIVEKIT_TOKEN_TTL_SECONDS:-7200}"
export TURN_DOMAIN="${TURN_DOMAIN:-turn.localhost}"
export TURN_REALM="${TURN_REALM:-localhost}"
export TURN_STATIC_AUTH_SECRET="${TURN_STATIC_AUTH_SECRET:-turn-secret-with-at-least-32-bytes}"
export LIVEKIT_NODE_IP="${LIVEKIT_NODE_IP:-127.0.0.1}"

mode="${1:-config}"

wait_for_tcp() {
  local host="$1"
  local port="$2"
  local label="$3"
  for _ in $(seq 1 60); do
    if python3 - "$host" "$port" <<'PY'
import socket
import sys
host, port = sys.argv[1], int(sys.argv[2])
with socket.create_connection((host, port), timeout=1):
    pass
PY
    then
      echo "OK $label $host:$port"
      return 0
    fi
    sleep 1
  done
  echo "FAILED waiting for $label $host:$port" >&2
  return 1
}

config_check() {
  echo "== base compose config =="
  "${COMPOSE[@]}" config --services

  echo "== media overlay fail-closed check =="
  if env -u LIVEKIT_PUBLIC_URL "${MEDIA_COMPOSE[@]}" config >/tmp/giljob-v2-media-missing.out 2>&1; then
    echo "Expected media overlay to fail without LIVEKIT_PUBLIC_URL" >&2
    cat /tmp/giljob-v2-media-missing.out >&2
    return 1
  fi
  grep -q "LIVEKIT_PUBLIC_URL" /tmp/giljob-v2-media-missing.out
  echo "OK media overlay refuses missing LIVEKIT_PUBLIC_URL"

  echo "== media overlay config =="
  "${MEDIA_COMPOSE[@]}" config --services
}

media_up() {
  config_check >/tmp/giljob-v2-smoke-config.log
  echo "== media stack up =="
  "${MEDIA_COMPOSE[@]}" up -d --build postgres api web livekit coturn
  cleanup() {
    if [[ "${KEEP_STACK:-0}" != "1" ]]; then
      "${MEDIA_COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
    fi
  }
  trap cleanup EXIT

  echo "== compose ps =="
  "${MEDIA_COMPOSE[@]}" ps

  echo "== service health =="
  "${MEDIA_COMPOSE[@]}" exec -T api python - <<'PY'
import urllib.request
for path in ("/healthz", "/readyz"):
    with urllib.request.urlopen(f"http://127.0.0.1:8000{path}", timeout=5) as res:
        assert res.status == 200, (path, res.status)
print("OK api health/ready")
PY
  "${MEDIA_COMPOSE[@]}" exec -T web python - <<'PY'
import urllib.request
for path in ("/healthz", "/readyz", "/"):
    with urllib.request.urlopen(f"http://127.0.0.1:3000{path}", timeout=5) as res:
        assert res.status == 200, (path, res.status)
print("OK web health/root")
PY

  echo "== session token smoke =="
  "${MEDIA_COMPOSE[@]}" exec -T api python - <<'PY'
import json
import urllib.request
req = urllib.request.Request(
    "http://127.0.0.1:8000/sessions",
    data=b'{"role":"candidate"}',
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=5) as res:
    payload = json.loads(res.read().decode("utf-8"))
livekit = payload.get("livekit") or {}
token_status = livekit.get("tokenStatus")
public_url = livekit.get("publicUrl")
room_name = livekit.get("roomName")
candidate_token = livekit.get("candidateToken")
assert token_status == "issued", f"unexpected LiveKit token status: {token_status!r}"
assert public_url, "missing LiveKit publicUrl"
assert isinstance(candidate_token, str) and candidate_token.count(".") == 2, "invalid LiveKit candidate token shape"
print("OK session livekit token", public_url, room_name)
PY

  echo "== LiveKit port smoke =="
  wait_for_tcp "127.0.0.1" "7880" "livekit signaling"

  echo "media smoke OK"
}

browser_join() {
  media_up
  echo "== browser join smoke with caddy =="
  "${MEDIA_COMPOSE[@]}" up -d --build caddy
  for _ in $(seq 1 60); do
    if curl -fsS http://127.0.0.1/healthz >/dev/null 2>&1 && curl -fsS http://127.0.0.1/ >/tmp/giljob-v2-browser-index.html 2>/dev/null; then
      break
    fi
    sleep 1
  done
  grep -q "Self-hosted LiveKit" /tmp/giljob-v2-browser-index.html
  local tmp_dir
  tmp_dir="$(mktemp -d)"
  cp "$ROOT_DIR/scripts/browser-join-smoke.mjs" "$tmp_dir/browser-join-smoke.mjs"
  (
    cd "$tmp_dir"
    npm init -y >/dev/null
    npm install --ignore-scripts --no-audit --no-fund playwright@1.60.0 >/dev/null
    node browser-join-smoke.mjs
  )
  rm -rf "$tmp_dir"
}

case "$mode" in
  config)
    config_check
    ;;
  media-up)
    media_up
    ;;
  browser-join)
    KEEP_STACK=1 browser_join
    "${MEDIA_COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
    ;;
  *)
    echo "usage: $0 [config|media-up|browser-join]" >&2
    exit 2
    ;;
esac
