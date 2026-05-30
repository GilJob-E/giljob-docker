# GilJob v2

Single-server Docker Compose MVP workspace for GilJob v2.

This folder is intentionally separate from `/home/hoddukzoa/GilJob`.
Do not copy or modify legacy GilJob files without an explicit later decision.

## Current status

- Source docs and ralplan artifacts are under `docs/`.
- Stack decisions are under `docs/decisions/`.
- Initial scaffold only; no full implementation yet.
- Minimal Dockerfiles and stdlib placeholder health servers exist for web, api, ai-engine, and agent1.
- Compose is fail-closed for `POSTGRES_PASSWORD`; copy `.env.example` to `.env` or export it before running.
- LiveKit/coturn are opt-in through `infra/docker-compose.media.yml`; the local media contract is documented in `docs/runbooks/local-livekit-media.md`. The API can issue signed LiveKit candidate join tokens when those env vars are configured, and `apps/web` now has a minimal browser join/leave UI.

## Fixed envelope

- One server.
- Docker Compose.
- Caddy for frontend/API ingress.
- LiveKit dedicated subdomain/direct route via optional media overlay.
- coturn direct TURN/STUN via optional media overlay.
- Postgres from Phase 0.
- Redis deferred behind EventBus adapter until after fake 3-turn loop, per ADR 0001.


## Local smoke

```bash
./scripts/smoke.sh config
./scripts/smoke.sh media-up
```

`media-up` starts the local self-hosted media overlay (`api`, `web`, `livekit`, `coturn`, `postgres`), checks session token issuance and LiveKit signaling reachability, then tears the stack down unless `KEEP_STACK=1` is set.
