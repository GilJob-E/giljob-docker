# services/analysis-engine

GilJobE-backed analysis boundary for GilJob v2.

This service is the hidden LiveKit analyzer participant:

```text
Candidate browser -> LiveKit room -> services/analysis-engine (GilJobE)
  -> transcript_full + non-verbal signals -> API/Realtime readiness gate
API Realtime sideband -> services/analysis-engine /realtime/turn-events
  -> sanitized MMM audit/readiness metadata
```

## How it runs

The container installs the pinned `GilJobE` package and runs `services/analysis-engine/server.py`.
That entrypoint builds the same GilJobE aiohttp app (`server/http_app.py`) for `/subscriber/*`,
`/signals`, `/healthz`, and `/readyz`, then adds one GilJob-v2-specific Realtime sideband route:
`POST /realtime/turn-events`.

HTTP contract served on `:8200` (Caddy prefixes `/analysis` externally; internal paths have no prefix):

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/subscriber/start` `{sessionId, criticMode}` | Begin an answer turn — join `giljob-session-{sessionId}` as a hidden subscriber and reset the turn. |
| `POST` | `/subscriber/stop` `{}` | End the turn — flush `end_turn` and produce `transcript_full`. |
| `GET` | `/signals?sessionId=` | Poll the turn's records: `{records, transcriptFull, windowTranscripts, latestTurnEnd, rawMediaExposed:false, rawSecretsExposed:false, ...}`. |
| `POST` | `/realtime/turn-events` | Accept sanitized Realtime MMM sideband records from `services/api`; rejects raw media/transcript/token shapes. |
| `GET` | `/realtime/turn-events?sessionId=&turnIndex=` | Inspect the in-memory tail of accepted sideband records for smoke/debug only. |
| `GET` | `/healthz` `/readyz` | Liveness / readiness (token-safe, never prints secrets). |

The subscriber is created per turn on `POST /subscriber/start` (HTTP-driven), so there is no
background auto-start to gate. `transcript_full` is bounded candidate-answer evidence that the API/Realtime readiness gate can use without exposing raw provider secrets or media.

## Status

- Runs GilJobE's HTTP contract server (`/subscriber/start|stop`, `/signals`, `/healthz`, `/readyz`) plus the GilJob-v2 Realtime MMM sideband ingress (`/realtime/turn-events`).
- The per-turn LiveKit room subscription + transcript + non-verbal signal path is exercised end to end
  by GilJobE against this stack's `livekit` and shared `gemma-e4b` (vLLM) backend.
- Realtime MMM sideband delivery from `services/api` is push-based: `/realtime/turn-events`
  accepts sanitized answer-state/readiness records. It does not store raw transcript/media and it does
  not replace GilJobE's LiveKit subscriber path.
- Realtime sentence-lane mode (GilJobE `5ba7249`) consumes API sideband transcript events when
  `GILJOBE_TRANSCRIPT_SOURCE=external`; this is the Realtime branch default. Set
  `GILJOBE_TRANSCRIPT_SOURCE=internal` only for legacy LiveKit/Gemma STT grid testing.
- If the Realtime base stack has no LiveKit media service, `/subscriber/start` falls back to an
  event-only external-transcript turn. It accepts API sideband sentence events and still emits a
  candidate-safe `turnHandoff`; full audio/video measurement remains a LiveKit media-path feature.
- Objective grounding lanes (GilJobE `5ba7249`): CPU-only vision (MediaPipe Face+Pose at full fps)
  and audio prosody (pitch/rate/pauses/energy) measurements are injected into the Gemma prompts
  with anti-hallucination rules and additionally emitted raw on records as `objective_nonverbal`
  / `objective_vocal` / `objective_visual` (additive fields — existing consumers are unaffected).
  The lanes self-disable when their deps/models are absent; this image bakes both.

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
| `ANALYSIS_ENGINE_ENABLE_SUBSCRIBER` | Legacy scaffold flag. The GilJobE server starts per turn via `/subscriber/start`, so this is not consulted. | no |
| `GILJOBE_VISION_MODELS_DIR` | MediaPipe `.task` model directory for the vision grounding lane (baked at `/app/models`). | no |
| `GILJOBE_VISION` / `GILJOBE_PROSODY` | Grounding lane toggles: `auto` (default — on when deps/models exist) or `off`. | no |

`/healthz` is intentionally non-secret and redacted. `/readyz` only reports readiness; it never prints token values.
