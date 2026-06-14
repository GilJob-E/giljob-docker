# GilJob v2 Implementation Plan

Source of truth:

- `docs/source-manifest.md`
- `docs/decisions/0001-state-stack.md`
- `docs/decisions/0002-ingress-stack.md`
- `docs/planning/prd-giljob-v2-execution-prep-20260530T050637Z.md`
- `docs/planning/test-spec-giljob-v2-execution-prep-20260530T050637Z.md`

## Phase order

### M0 — Source and decision baseline

- Source docs copied from local approved docs.
- Source checksums recorded.
- ADR 0001 and ADR 0002 accepted for scaffold.

### M1 — Docker skeleton and health

- Add `infra/docker-compose.yml` services for frontend, api, analysis-engine, agent1, postgres, optional/profiled redis, and caddy; add `infra/docker-compose.media.yml` as the optional LiveKit/coturn overlay for the same single-server stack.
- Implement only health endpoints/placeholders first.
- Keep `/api/internal/*` blocked at Caddy and API middleware.

### M2 — Session/token/LiveKit minimal runtime

- `POST /api/sessions`.
- session/report token hash storage in Postgres.
- LiveKit room/token issue.
- Browser join and engine track subscribe.

Current bounded slices: G006 API token contract foundation is present: `POST /api/sessions`/`POST /sessions`, purpose-separated session/report hashes, required compose hash secrets, TTL defaults, HTTP handler contract tests, and a Postgres schema contract with token-hash lookup indexes. G007 adds optional LiveKit signed candidate join tokens when LiveKit env is configured. G008 adds the minimal `apps/web` LiveKit browser join/leave UI and local media smoke runbook. Real Postgres persistence, AI engine media track subscribe, real Main LLM, multimodal analysis, and final reports remain later slices.

### M3 — Fake 3-turn loop

- Fake STT.
- Fake Agent1 signal.
- Fake Agent2 follow-up.
- EventBus adapter, state transitions, fake report.

### M4 — Real adapters

- STT adapter.
- Agent2 LLM adapter.
- Agent1/Multi_Modal_Module integration.
- Redis migration checkpoint before concurrent real adapters are considered demo-ready.

### M5 — Demo hardening

- SpatialReal/TTS or text fallback.
- Report generator.
- External-network WebRTC/TURN smoke.
- Failure injection and runbook.
