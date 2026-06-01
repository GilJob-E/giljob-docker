# infra Agent Contract

This module owns single-server, multi-container deployment wiring. Follow the root `AGENTS.md` plus these local rules.

## Current responsibilities
- Maintain Docker Compose wiring for Caddy, web, API, ai-engine, stt-whisper, agent1 placeholders, Postgres, LiveKit, and coturn.
- Keep Caddy ingress explicit and block internal API surfaces such as `/api/internal/*`.
- Preserve self-hosted LiveKit direct media behavior: `7880/tcp` signaling, `7881/tcp` ICE/TCP, and `50000-50100/udp` media ports.
- Preserve TURN/coturn notes and direct media port documentation.
- Preserve `LIVEKIT_INTERNAL_URL` for server/container access and `LIVEKIT_PUBLIC_URL` for browser access.

## Known architecture tension
Caddy currently proxies `/ai/*` to `ai-engine` for the current question-generation slice, while ADR 0002 treats AI Engine and Agent1 as internal components. Document this `/ai/*` ingress tension clearly before expanding public AI routes. `/stt/*` is currently public only for same-origin browser answer-turn uploads and proxies to the GPU-pinned STT service.

## Security
- Do not commit `.env` files or real secrets.
- Do not print secret env values in troubleshooting output.
- Do not widen public ports or proxy rules without updating docs and tests.
- Keep `stt-whisper` reserved to host GPU `1` unless an ADR/test update changes the resource plan.

## Tests
For infra changes, run compose config and relevant contract tests:

```bash
./scripts/smoke.sh config
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -v
```
