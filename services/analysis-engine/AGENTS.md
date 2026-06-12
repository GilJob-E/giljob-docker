# services/analysis-engine Agent Contract

This module owns the GilJobE-backed analysis boundary. Follow the root `AGENTS.md` plus these local rules.

## How it runs
- The container installs the pinned `GilJobE` package (`requirements.txt`) and runs the local
  `server.py` entrypoint. That entrypoint builds GilJobE's own HTTP contract app
  (`server/http_app.py`) and adds only the GilJob-v2 Realtime MMM sideband ingress route
  (`/realtime/turn-events`).
- Keep the image thin: `python:3.12-slim` + `git` + `ffmpeg` + `curl` (livekit/av wheels need glibc,
  not alpine; curl fetches the pinned MediaPipe models at build time).
- Bump behaviour by bumping the pinned ref in `requirements.txt` (and the informational
  `GILJOBE_GIT_REF`), not by forking logic into this directory.
- The `[vision,prosody]` extras enable GilJobE's objective grounding lanes (CPU-only); the
  MediaPipe `.task` models are baked at `/app/models` (`GILJOBE_VISION_MODELS_DIR`). The lanes
  self-disable when deps/models are missing — never make container startup depend on them.
  Licence note: `praat-parselmouth` (prosody extra) is GPL-3; revisit before distributing the
  image outside this self-hosted deployment.

## Current responsibilities
- Treat `GilJobE` as the STT and multimodal input-analysis source of truth.
- Serve the legacy hidden LiveKit analyzer HTTP contract: `/subscriber/start`, `/subscriber/stop`,
  `/signals`, `/healthz`, `/readyz` for compatibility/non-main-path testing.
- Own the priority-1 Realtime-native analysis session (RNAS): accept sanitized API-forwarded answer lifecycle/sideband records at `/realtime/turn-events`, store exact `(interviewId, turnIndex)` state/results, and expose `/realtime/turn-results` for the API `response.create` gate. Reject raw media, raw transcripts, provider tokens, SDP, and browser secrets.
- Report dependency/config readiness without exposing raw LiveKit tokens, JWTs, API secrets, media,
  or transcript payloads in logs. `/healthz` and `/readyz` are token-safe.

## Boundaries
- Do not mint browser/candidate tokens here; the API owns token contracts. This service only
  self-mints (or accepts) a hidden subscriber token for its own room join.
- Do not reintroduce alternate STT paths in this service; STT belongs to GilJobE.
- Do not add the Main LLM loop, avatar/TTS, or final report generation here — those are out of scope
  and are not complete product features yet.
- `ANALYSIS_ENGINE_ENABLE_SUBSCRIBER` is a legacy scaffold flag. Ordinary OpenAI Realtime RNAS does not call `/subscriber/start`; LiveKit subscriber start/stop is compatibility-only, not a fallback for API `response.create`.

## Tests
```bash
# Doc-pair contract (this directory is part of DOC_PAIRS):
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -p 'test_agent_docs_contract.py' -v
# Build smoke (installs the pinned GilJobE package and runs the wrapped entrypoint):
docker build -t analysis-engine services/analysis-engine \
  && docker run --rm -p 8200:8200 analysis-engine &  # then GET /healthz
```
GilJobE owns its own unit/contract/live tests in the GilJobE repo; run those there when bumping the pin.
