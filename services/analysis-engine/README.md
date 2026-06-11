# services/analysis-engine

GilJobE-backed analysis boundary for GilJob v2.

This service is the hidden LiveKit analyzer participant:

```text
Candidate browser -> LiveKit room -> services/analysis-engine (GilJobE)
  -> transcript_full + non-verbal signals -> ai-engine / interview controller
```

## How it runs

The container installs the pinned `GilJobE` package and runs **its own module entrypoint**
`python -m giljobe.server` (GilJobE owns `server/http_app.py`). There is no local wrapper:
the container runs the same HTTP server GilJobE smoke-tests, so behaviour stays in lockstep
with the source of truth.

HTTP contract served on `:8200` (Caddy prefixes `/analysis` externally; internal paths have no prefix):

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/subscriber/start` `{sessionId, criticMode}` | Begin an answer turn — join `giljob-session-{sessionId}` as a hidden subscriber and reset the turn. |
| `POST` | `/subscriber/stop` `{}` | End the turn — flush `end_turn` and produce `transcript_full`. |
| `GET` | `/signals?sessionId=` | Poll the turn's records: `{records, transcriptFull, windowTranscripts, latestTurnEnd, rawMediaExposed:false, rawSecretsExposed:false, ...}`. |
| `GET` | `/healthz` `/readyz` | Liveness / readiness (token-safe, never prints secrets). |

The subscriber is created per turn on `POST /subscriber/start` (HTTP-driven), so there is no
background auto-start to gate. `transcript_full` is the candidate answer the interview
controller relays to `services/ai-engine` as `lastAnswer`.

## Status

- Runs GilJobE's HTTP contract server (`/subscriber/start|stop`, `/signals`, `/healthz`, `/readyz`).
- The per-turn LiveKit room subscription + transcript + non-verbal signal path is exercised end to end
  by GilJobE against this stack's `livekit` and shared `gemma-e4b` (vLLM) backend.
- Record delivery to `services/ai-engine` is pull-based: the interview controller polls `/signals`
  and forwards `transcriptFull` to the next-question endpoint.
- Objective grounding lanes (GilJobE `e0671f5`): CPU-only vision (MediaPipe Face+Pose at full fps)
  and audio prosody (pitch/rate/pauses/energy) measurements are injected into the Gemma prompts
  with anti-hallucination rules and additionally emitted raw on records as `objective_nonverbal`
  / `objective_vocal` / `objective_visual` (additive fields — existing consumers are unaffected).
  The lanes self-disable when their deps/models are absent; this image bakes both.

Not owned here: candidate/browser token minting (the API owns token contracts), the Main LLM
interview loop, avatar/TTS, and final report generation.

## Known current issues

- Docker build is not currently green at reviewed main commit `34403b7`: `giljobe[vision,prosody]` pulls `praat-parselmouth`, and the Dockerfile does not yet install the native build toolchain (`build-essential`, `cmake`, `ninja-build` or equivalent).
- Caddy currently exposes this service externally under `/analysis/*` as a development boundary. Production should move subscriber start/stop/signals behind authenticated API broker routes that validate session token + turn id.
- The pinned `GILJOBE_GIT_REF` is a short SHA. Prefer a full 40-character SHA plus checksum/provenance notes for production supply-chain review.


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
