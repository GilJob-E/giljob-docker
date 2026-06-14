# services/analysis-engine

GilJobE-backed analysis boundary for GilJob v2.

This service is the hidden LiveKit analyzer participant:

```text
Candidate browser -> API Realtime sideband
  -> Realtime STT transcript + prosody + low-res internal vision sample
  -> services/analysis-engine /realtime/turn-events
  -> GilJobE /signals.turnHandoff gold + candidate-safe fragment
Legacy LiveKit room -> services/analysis-engine (GilJobE)
  -> compatibility-only subscriber signals
```

## How it runs

The container installs the pinned `GilJobE` package and runs `services/analysis-engine/server.py`.
That entrypoint builds the same GilJobE aiohttp app (`server/http_app.py`) for `/subscriber/*`,
`/signals`, `/healthz`, and `/readyz`, then adds one GilJob-v2-specific Realtime sideband route:
`POST /realtime/turn-events`.

HTTP contract served on `:8200` (Caddy prefixes `/analysis` externally; internal paths have no prefix):

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/subscriber/start` `{sessionId, criticMode}` | Legacy/non-main-path LiveKit analyzer start for compatibility testing. Not used by ordinary OpenAI Realtime follow-up gating. |
| `POST` | `/subscriber/stop` `{}` | Legacy/non-main-path LiveKit analyzer stop/flush. |
| `GET` | `/signals?sessionId=` | Legacy signal inspection for the LiveKit analyzer path. |
| `POST` | `/realtime/turn-events` | Realtime answer lifecycle, transcript/prosody signals, and optional low-resolution internal vision sample from `services/api`; GilJobE uses these to build `/signals.turnHandoff`; public/durable records stay redacted and token-safe. |
| `GET` | `/realtime/turn-results?interviewId=&turnIndex=` | Candidate-safe projection of the current GilJobE `turnHandoff` for the API `response.create` gate. `turnHandoff` remains the gold payload; this route is a lossy fragment transport. |
| `GET` | `/realtime/turn-events?sessionId=&turnIndex=` | Inspect the in-memory tail of accepted sideband records for smoke/debug only. |
| `GET` | `/healthz` `/readyz` | Liveness / readiness (token-safe, never prints secrets). |

The priority-1 Realtime architecture is **answer → analysis-engine `turnHandoff` → Hashimoto strategy adapter → API `response.create` → OpenAI Realtime output**. Analysis-engine owns the GilJobE signal/handoff boundary; the API forwards lifecycle/sideband events, consumes only the candidate-safe fragment projected from `turnHandoff`, and may merge candidate-safe Hashimoto strategy guidance. `/subscriber/start|stop` remains a legacy compatibility surface and is not an ordinary Realtime main-path fallback.

## Status

- Runs GilJobE's HTTP contract server (`/subscriber/start|stop`, `/signals`, `/healthz`, `/readyz`) plus the GilJob-v2 Realtime sideband/fragment routes (`/realtime/turn-events`, `/realtime/turn-results`).
- The priority-1 Realtime path does not start a LiveKit subscriber per answer. API sideband events feed GilJobE's sentence lane, `/signals.turnHandoff` is the analysis gold, and `/realtime/turn-results` only carries the safe fragment used by the API `response.create` gate.
- Legacy LiveKit room subscription + transcript + non-verbal signal paths remain available for compatibility testing, but they are not a fallback for ordinary Realtime follow-up generation.
- Realtime MMM sideband delivery from `services/api` is push-based: `/realtime/turn-events`
  accepts answer-state/readiness records plus internal STT/vision detail needed for GilJobE
  to derive the structured `turnHandoff`. `/realtime/turn-results` returns only
  `candidatePromptFragment`; it does not store raw transcript/media or expose provider secrets.
- Realtime sentence-lane mode (GilJobE `f7307fc`) consumes API sideband transcript events when
  `GILJOBE_TRANSCRIPT_SOURCE=external`; this is the Realtime branch default. Set
  `GILJOBE_TRANSCRIPT_SOURCE=internal` only for legacy LiveKit/Gemma STT grid testing.
- Realtime follow-up gating does not require `/subscriber/start`. Missing `turnHandoff` or a missing/unsafe `candidatePromptFragment` keeps the API `response.create` gate closed. If `/subscriber/start` is invoked manually in a stack without LiveKit media, it remains an event-only external-transcript compatibility path, not an ordinary Realtime follow-up fallback.
- Objective grounding lanes (GilJobE `f7307fc`): CPU-only vision (MediaPipe Face+Pose+Hands at
  full fps — Hands adds finger-count segments carried on the turn_handoff fragment as
  `finger_sequence`) and audio prosody (pitch/rate/pauses/energy) measurements are injected into
  the Gemma prompts with anti-hallucination rules and additionally emitted raw on records as
  `objective_nonverbal` / `objective_vocal` / `objective_visual` (additive fields — existing
  consumers are unaffected). The lanes self-disable when their deps/models are absent; this
  image bakes all three models.

Not owned here: candidate/browser token minting (the API owns token contracts), the Main LLM
interview loop, avatar/TTS, and final report generation.

## Environment contract

| Variable | Purpose | Secret |
|---|---|---|
| `LIVEKIT_URL` | Internal/container LiveKit URL, for example `ws://livekit:7880`. | no |
| `LIVEKIT_TOKEN` | Optional pre-issued hidden analyzer participant token. | yes |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | Fallback for GilJobE self-minting a hidden subscriber token. | yes |
| `LIVEKIT_SESSION_ID` | Default session id for GilJobE room naming (`giljob-session-{id}`); `/subscriber/start` overrides per turn. | no |
| `VLLM_BASE_URL` | vLLM (Gemma E4B) backend for transcription + non-verbal critique, e.g. `http://gemma-e4b:8000`. | no |
| `ANALYSIS_ENGINE_PORT` | HTTP port (defaults to `8200`). | no |
| `GILJOBE_GIT_REF` | Pinned GilJobE source reference (informational; the real pin is `requirements.txt`). | no |
| `ANALYSIS_ENGINE_ENABLE_SUBSCRIBER` | Legacy scaffold flag. Ordinary Realtime follow-up gating uses `turnHandoff` and does not call `/subscriber/start`; the legacy subscriber path can still be invoked manually for compatibility tests. | no |
| `GILJOBE_VISION_MODELS_DIR` | MediaPipe `.task` model directory for the vision grounding lane (baked at `/app/models`). | no |
| `GILJOBE_VISION` / `GILJOBE_PROSODY` | Grounding lane toggles: `auto` (default — on when deps/models exist) or `off`. | no |

`/healthz` is intentionally non-secret and redacted. `/readyz` only reports readiness; it never prints token values.
