# services/analysis-engine Agent Contract

This module owns the GilJobE-backed analysis boundary. Follow the root `AGENTS.md` plus these local rules.

## How it runs
- The container installs the pinned `GilJobE` package (`requirements.txt`) and runs its own module
  entrypoint `python -m giljobe.server`. There is no local wrapper to maintain here — GilJobE owns
  the HTTP contract server (`server/http_app.py`).
- Keep the image thin: `python:3.12-slim` + `git` + `ffmpeg` (livekit/av wheels need glibc, not alpine).
- Bump behaviour by bumping the pinned ref in `requirements.txt` (and the informational
  `GILJOBE_GIT_REF`), not by forking logic into this directory.

## Current responsibilities
- Treat `GilJobE` as the STT and multimodal input-analysis source of truth.
- Serve the hidden LiveKit analyzer HTTP contract: `/subscriber/start`, `/subscriber/stop`,
  `/signals`, `/healthz`, `/readyz`. The subscriber joins `giljob-session-{sessionId}` per turn.
- Report dependency/config readiness without exposing raw LiveKit tokens, JWTs, API secrets, media,
  or transcript payloads in logs. `/healthz` and `/readyz` are token-safe.

## Boundaries
- Do not mint browser/candidate tokens here; the API owns token contracts. This service only
  self-mints (or accepts) a hidden subscriber token for its own room join.
- Do not reintroduce alternate STT paths in this service; STT belongs to GilJobE.
- Do not add the Main LLM loop, avatar/TTS, or final report generation here — those are out of scope
  and are not complete product features yet.
- `ANALYSIS_ENGINE_ENABLE_SUBSCRIBER` is a legacy scaffold flag; the GilJobE server starts the
  subscriber per turn via `/subscriber/start`, so it is not consulted.

## Tests
```bash
# Doc-pair contract (this directory is part of DOC_PAIRS):
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -p 'test_agent_docs_contract.py' -v
# Build smoke (installs the pinned GilJobE package and runs the module entrypoint):
docker build -t analysis-engine services/analysis-engine \
  && docker run --rm -p 8200:8200 analysis-engine &  # then GET /healthz
```
GilJobE owns its own unit/contract/live tests in the GilJobE repo; run those there when bumping the pin.
