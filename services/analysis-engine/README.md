# services/analysis-engine

GilJobE-backed analysis boundary for GilJob v2.

This service is the hidden LiveKit analyzer participant:

```text
Candidate browser -> API Realtime sideband
  -> Realtime STT transcript + prosody + low-res internal vision sample
  -> services/analysis-engine /realtime/turn-events
  -> exact-turn structured MMM/RNAS result
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
| `POST` | `/realtime/turn-events` | Primary RNAS ingress for Realtime answer lifecycle, transcript/prosody signals, and optional low-resolution internal vision sample from `services/api`; public/durable records stay redacted and token-safe. |
| `GET` | `/realtime/turn-results?interviewId=&turnIndex=` | Primary RNAS result endpoint for exact `(interviewId, turnIndex)` lookup. No active/last/session-wide fallback is allowed for the API `response.create` gate. |
| `GET` | `/realtime/turn-events?sessionId=&turnIndex=` | Inspect the in-memory tail of accepted sideband records for smoke/debug only. |
| `GET` | `/healthz` `/readyz` | Liveness / readiness (token-safe, never prints secrets). |

The priority-1 Realtime architecture is **answer → analysis-engine MMM/RNAS → API `response.create` → OpenAI Realtime output**. Analysis-engine is the sole RNAS session/readiness/result owner; the API forwards lifecycle/sideband events and consumes only exact-turn candidate-safe results. `/subscriber/start|stop` remains a legacy compatibility surface and is not an ordinary Realtime main-path fallback.

## Status

- Runs GilJobE's HTTP contract server (`/subscriber/start|stop`, `/signals`, `/healthz`, `/readyz`) plus the GilJob-v2 Realtime-native MMM/RNAS ingress/result routes (`/realtime/turn-events`, `/realtime/turn-results`).
- The priority-1 Realtime path does not start a LiveKit subscriber per answer. API sideband events open/finalize exact-turn RNAS state, and `/realtime/turn-results` is the only result authority used by the API `response.create` gate.
- Legacy LiveKit room subscription + transcript + non-verbal signal paths remain available for compatibility testing, but they are not a fallback for ordinary Realtime follow-up generation.
- Realtime MMM sideband delivery from `services/api` is push-based: `/realtime/turn-events`
  accepts answer-state/readiness records plus internal STT/vision detail needed for MMM. It derives
  structured `transcriptSignals`, `visionSignals`, `prosodySignals`, `behavioralSignals`, and
  `candidateSafePromptFragment`; it does not store raw transcript/media or expose provider secrets.
- Realtime sentence-lane mode (GilJobE `a26045d`) consumes API sideband transcript events when
  `GILJOBE_TRANSCRIPT_SOURCE=external`; this is the Realtime branch default. Set
  `GILJOBE_TRANSCRIPT_SOURCE=internal` only for legacy LiveKit/Gemma STT grid testing.
- RNAS does not require `/subscriber/start`. Missing transcript/prosody/vision/end/result keeps the exact turn pending, so API `response.create` fails closed with a lane/result reason. If `/subscriber/start` is invoked manually in a stack without LiveKit media, it remains an event-only external-transcript compatibility path, not an ordinary Realtime follow-up fallback.
- Objective grounding lanes (GilJobE `a26045d`): CPU-only vision (MediaPipe Face+Pose+Hands at
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
| `ANALYSIS_ENGINE_ENABLE_SUBSCRIBER` | Legacy scaffold flag. Ordinary Realtime RNAS does not consult this and does not call `/subscriber/start`; the legacy subscriber path can still be invoked manually for compatibility tests. | no |
| `GILJOBE_VISION_MODELS_DIR` | MediaPipe `.task` model directory for the vision grounding lane (baked at `/app/models`). | no |
| `GILJOBE_VISION` / `GILJOBE_PROSODY` | Grounding lane toggles: `auto` (default — on when deps/models exist) or `off`. | no |

`/healthz` is intentionally non-secret and redacted. `/readyz` only reports readiness; it never prints token values.
