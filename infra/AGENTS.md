# infra Agent Contract

This module owns single-server, multi-container deployment wiring. Follow the root `AGENTS.md` plus these local rules.

## Current responsibilities
- Maintain Docker Compose wiring for Caddy, web, API, ai-engine, analysis-engine, agent1 placeholders, Postgres, LiveKit, and coturn.
- Keep Caddy ingress explicit and block internal API surfaces such as `/api/internal/*`.
- Keep browser-facing provider integrations behind `/api/interviews/...` broker routes; do not expose service-internal provider routes directly.
- Preserve self-hosted LiveKit direct media behavior: `7880/tcp` signaling, `7881/tcp` ICE/TCP, and `50000-50100/udp` media ports.
- Preserve TURN/coturn notes and direct media port documentation.
- Preserve `LIVEKIT_INTERNAL_URL` for server/container access and `LIVEKIT_PUBLIC_URL` for browser access.

## Ingress invariants
Caddy keeps provider and AI engine routes internal. Browser traffic for question generation, TTS, avatar session metadata, Realtime session metadata, and MMM readiness must go through `services/api` broker routes under `/api/interviews/...`. Direct public `/ai/*`, `/tts/*`, and `/avatar/*` routes must stay blocked. Do not reintroduce a public `/stt/*` route; STT belongs to the GilJobE analysis-engine boundary unless a later ADR changes it.

## Security
- Do not commit `.env` files or real secrets.
- Do not print secret env values in troubleshooting output.
- Do not widen public ports or proxy rules without updating docs and tests.

## Tests
For infra changes, run compose config and relevant contract tests:

```bash
./scripts/smoke.sh config
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -v
```
