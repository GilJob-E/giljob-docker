# GilJob v2 Agent Contract

This file is the canonical repository-level contract for coding agents working on GilJob v2. Follow any deeper `AGENTS.md` file for module-specific overrides.

## Product intent
GilJob v2 is a self-hosted AI interview scaffold for a single-server, multi-container Docker Compose deployment. The current implementation is intentionally a scaffold: Caddy ingress, production interview routes, API session/token contracts, an OpenAI Realtime-only interviewer voice boundary, a GilJobE-backed analysis-engine boundary, and disabled/deferred SpatialReal avatar metadata. LiveKit is optional legacy/media-overlay infrastructure, not the default Realtime/MMM path. The former local Whisper STT and ai-engine voice service have been removed from the default runtime; transcription and multimodal readiness belong to the GilJobE analysis-engine boundary.

## Hard boundaries
- Do not touch or migrate the legacy `/home/hoddukzoa/GilJob` tree. This repository/worktree represents GilJob v2.
- Do not read-print, commit, or quote `.env` values. Use `.env.example` and variable names only.
- Do not expose raw session tokens, report tokens, JWTs, LiveKit tokens, provider keys, or raw media in UI, logs, tests, docs, or examples. The only exception is the explicit `/api/interviews/{id}/avatar/session` contract returning a short-lived SpatialReal SDK `sessionToken`; never persist, log, or display that token.
- Preserve the `LIVEKIT_INTERNAL_URL` / `LIVEKIT_PUBLIC_URL` split. Browser clients use the public URL; server-side token issuing uses the internal URL.
- Preserve hash-only server storage for public tokens. Raw public tokens are returned once and must not be persisted.
- Mark future work honestly. Local Whisper STT and the ai-engine voice/TTS runtime have been removed from the default architecture; OpenAI Realtime is the only live interviewer voice path on the realtime branch; do not reintroduce non-Realtime fallback LLM/TTS flows for the main interview loop. SpatialReal SDK Mode Web may be API-owned and API-key-brokered, but production lip-sync to OpenAI Realtime audio is not claimed until kiostation browser proof verifies it. Full Main LLM orchestration, production-grade multimodal analysis, and final report generation are not complete product features yet.

## Source-of-truth documents
- `README.md` for current product status, architecture summary, and run instructions.
- `DESIGN.md` for web and interview-room design constraints.
- `docs/architecture.noml` as the editable architecture source; `docs/assets/architecture.svg` is rendered output.
- `docs/decisions/` for ADRs.
- `docs/runbooks/` for operational verification and LiveKit media notes.
- `tests/contract/` for behavior and security contracts.

## Module map
- `apps/web/`: browser UI, production interview routes, OpenAI Realtime WebRTC client flow, manual answer controls, visible/log redaction, and SpatialReal SDK Mode Web UI states.
- `services/api/`: session/report token issuing, hash-only records, OpenAI Realtime session/call broker, Realtime turn/MMM sideband routes, API-owned SpatialReal SDK token broker/metadata, and security contracts.
- `services/analysis-engine/`: GilJobE-backed STT and multimodal analysis boundary; `server.py` builds GilJobE's HTTP app and adds `/realtime/turn-events` for sanitized Realtime MMM sideband ingress. This service remains the exact-turn MMM/RNAS source of truth.
- `services/agent1/`: future multimodal placeholder; structured signal boundary only.
- `infra/`: Docker Compose, Caddy, optional LiveKit/coturn media overlay files, Postgres, and single-server deployment wiring. The default runtime services are API, Web, analysis-engine, agent1, Postgres, and Redis profile only when enabled.
- `tests/`: contract and integration test guidance.
- `docs/`: ADRs, runbooks, planning artifacts, and rendered architecture assets.
- `packages/shared/`: shared schemas/contracts only; avoid premature abstractions.
- `scripts/`: smoke and browser-join verification scripts; no secret printing.

## Generated/vendor scope
Skip or avoid editing `__pycache__/`, `node_modules/`, build/cache artifacts, and vendor residue unless the task explicitly asks for cleanup. Do not treat generated SVG/assets as the editable architecture source.

## Verification
Use the smallest test set that proves the claim. For documentation or contract updates, prefer:

```bash
node --check apps/web/static/app.js
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -v
git diff --check
```

Run Docker Compose or browser smoke only on the approved remote runtime (kiostation) when the change affects runtime wiring; do not run local Docker in this workspace.

## Reporting
Report changed files, verification evidence, and any known gaps. Keep user-facing discussion Korean when the user works in Korean, but keep `AGENTS.md` and `CLAUDE.md` prose in English.
