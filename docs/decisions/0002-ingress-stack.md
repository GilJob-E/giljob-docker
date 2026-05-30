# ADR 0002 — Public Ingress Shape for GilJob v2 MVP

- Status: Accepted for scaffold; revisit after first external-network WebRTC smoke
- Date: 2026-05-30
- Gate: B — Caddy/reverse-proxy ingress
- Source: `docs/planning/prd-giljob-v2-execution-prep-20260530T050637Z.md`, `docs/planning/test-spec-giljob-v2-execution-prep-20260530T050637Z.md`

## Context

GilJob v2 runs on one server with Docker Compose. Public access must support frontend/API HTTPS, API health routes, LiveKit WSS/API, and TURN/STUN media fallback. Preserved constraints are:

- public health routes are `/healthz` and `/readyz`
- `/api/internal/*` is blocked at public ingress and protected again by API middleware
- browser accesses frontend/API over HTTPS/WSS
- LiveKit/TURN must be smoke-tested from a different network before demo readiness
- Postgres/Redis/AI Engine/Agent1 internal ports are not public

The reopened question is whether to use Caddy, Nginx, or a split ingress shape.

## Options considered

### Option A — Caddy for everything, including LiveKit path proxy

Pros:
- Single ingress config.
- Automatic TLS is simple.

Cons:
- LiveKit WSS/path proxying can be tricky.
- WebRTC media still needs direct UDP/TURN exposure.

### Option B — Caddy for frontend/API, LiveKit on separate subdomain/direct service port, coturn direct

Pros:
- Keeps frontend/API/internal route blocking simple.
- Avoids overloading path proxy with LiveKit media/WSS concerns.
- Matches docs guidance that LiveKit subdomain is preferable.
- Easier to test Caddy health separately from RTC/TURN.

Cons:
- Requires multiple DNS names or clear port/subdomain setup.
- More public network matrix entries to document.

### Option C — Nginx instead of Caddy

Pros:
- Familiar to many operators and certbot flows.

Cons:
- More manual TLS/cert management.
- No clear advantage unless station environment has Caddy blockers.

## Decision

Choose **Option B: Caddy for frontend/API public ingress, LiveKit exposed via dedicated subdomain/direct service route, coturn exposed directly for TURN/STUN**.

Caddy remains the default for frontend/API because automatic TLS and route matching are enough for MVP. LiveKit should not be hidden behind an API path proxy in the first scaffold; prefer a dedicated `LIVEKIT_DOMAIN` or clearly documented direct `:7880` route. coturn remains direct because TURN relay ports are media infrastructure, not HTTP ingress.

## Public route contract

- `https://${PUBLIC_DOMAIN}/` → frontend
- `https://${PUBLIC_DOMAIN}/api/*` → API server
- `https://${PUBLIC_DOMAIN}/healthz` → API aggregate health
- `https://${PUBLIC_DOMAIN}/readyz` → blocked publicly with 404; API `/readyz` is container-internal readiness
- `https://${PUBLIC_DOMAIN}/api/internal/*` → blocked at Caddy before proxying
- `${LIVEKIT_DOMAIN}` or documented direct `:7880` → LiveKit WSS/API
- TURN/STUN `3478` and relay range → coturn direct

## Consequences

- `infra/caddy/Caddyfile` should not attempt a complicated LiveKit path proxy in the first scaffold.
- Compose/runbook must document both HTTP ingress and RTC/TURN network checks.
- Security tests must check public internal route blocking at Caddy and API middleware rejection.
- Demo readiness requires external-network RTC evidence, not only local health checks.

## External-network smoke criteria

Before demo readiness, collect:

- browser join from normal Wi-Fi/network
- browser join from phone hotspot or another external network
- LiveKit logs/stats for join, publish, subscribe
- coturn allocation evidence when relay fallback is exercised
- Caddy access logs for public `/healthz` and public `/readyz` 404 checks

## Verification

- `curl -fsS https://${PUBLIC_DOMAIN}/healthz`
- `test "$(curl -sS -o /dev/null -w "%{http_code}" https://${PUBLIC_DOMAIN}/readyz)" = "404"`
- `POSTGRES_PASSWORD=... docker compose -f infra/docker-compose.yml exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz', timeout=2).read()"` returns success
- public `/api/internal/*` returns blocked response
- direct API internal route without internal token/HMAC returns 401/403
- browser can join LiveKit room from at least one non-local network
- coturn logs show allocation when TURN fallback is used

## Follow-ups

- Add explicit `PUBLIC_DOMAIN`, `LIVEKIT_DOMAIN`, and TURN env variables to `.env.example` during scaffold.
- Keep Nginx as fallback only if Caddy cannot satisfy station TLS/routing constraints.
- Revisit after first WebRTC smoke if LiveKit subdomain/direct route is blocked by the station network.
