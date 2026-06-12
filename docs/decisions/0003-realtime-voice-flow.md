# ADR 0003 — Realtime Voice Flow and MMM Readiness Gate

- Status: Accepted for current Realtime WebRTC scaffold; revisit after external provider smoke and integrated LiveKit/analysis evidence
- Date: 2026-06-12
- Gate: Realtime interviewer voice flow
- Source: `services/api/server.py`, `apps/web/static/app.js`, `docs/architecture.noml`

## Context

GilJob v2 needs a browser-facing live interviewer voice path without exposing provider keys, raw tokens, raw media, or internal analysis prompts. The current room already has LiveKit candidate media, GilJobE/analysis-engine boundaries, Gemini question/TTS fallback support, and SpatialReal avatar scaffolding. The new Realtime path must fit that scaffold rather than replacing all room state with a direct browser-to-provider integration.

The preserved constraints are:

- standard provider keys remain server-only
- browser-visible diagnostics and event logs do not print raw JWTs, ephemeral secrets, provider keys, SDP bodies, or raw media
- public browser routes use `/api/*` brokers; direct `/ai/*`, `/tts/*`, and `/avatar/*` remain blocked
- Realtime audio generation is not allowed to skip internal multimodal readiness for ordinary next-question turns
- transcript/prosody/vision signals are treated as bounded sideband metadata, not raw media archives

## Options considered

### Option A — Browser calls OpenAI Realtime directly with a standard API key

Pros:
- Simplest WebRTC attach path.

Cons:
- Violates the server-only provider-key contract.
- Makes public browser code a trusted business-logic boundary.
- Increases the blast radius of logs, screenshots, and browser devtools.

### Option B — API broker issues an ephemeral Realtime client secret, browser attaches SDP to Realtime

Pros:
- Keeps the standard OpenAI API key server-only.
- Lets the browser use WebRTC for low-latency interviewer audio.
- Keeps room UI and diagnostics token-safe.
- Allows the API to publish route metadata and readiness gates without proxying media.

Cons:
- The browser still talks to the provider SDP endpoint with an ephemeral secret, so the endpoint and secret-shape contract must be tested.
- Provider failure must degrade cleanly without exposing upstream error bodies.

### Option C — Server proxies all Realtime media and datachannel traffic

Pros:
- Strongest centralization of provider traffic.

Cons:
- Much larger implementation surface.
- Adds avoidable media latency and operational complexity for the current scaffold.
- Duplicates work already handled by WebRTC provider infrastructure.

## Decision

Choose **Option B: API-mediated ephemeral Realtime session plus browser WebRTC SDP attach**.

The API owns `/api/interviews/:id/realtime/session` and `/api/interviews/:id/realtime/call`. It uses the standard server-side provider key to request a short-lived Realtime client secret and returns only browser-safe metadata. The browser attaches SDP to `https://api.openai.com/v1/realtime/calls` with that ephemeral secret. The browser must not receive or log the standard provider key.

Ordinary next-question audio is gated. After the candidate answer ends, the browser forwards bounded transcript/prosody/vision sideband events to:

- `/api/interviews/:id/turns/:turnIndex/events`
- `/api/interviews/:id/turns/:turnIndex/vision-events`
- `/api/interviews/:id/turns/:turnIndex/mmm-ready`

The next ordinary `realtime.response.create` is allowed only when the API reports `full_mmm_ready: true` for the prior turn. Degraded or incomplete readiness blocks ordinary next-question audio rather than silently bypassing the analysis contract.

## Public contract

- `OPENAI_API_KEY` is the only OpenAI server key and remains server-only; do not add `OPENAI_REALTIME_API_KEY`.
- `OPENAI_REALTIME_PRIMARY=true` enables the Realtime primary browser path and is the default documented primary voice mode.
- `/api/interviews/:id/realtime/session` returns provider status, route metadata, and an ephemeral client secret shape only.
- The SDP attach endpoint is `/v1/realtime/calls`; no `?model=` fallback is part of the locked browser attach contract.
- Browser logs may mention that a client secret or SDP exists, but must not print the secret value or SDP body.
- Sideband events may include bounded transcript text needed for conversation continuity, but raw audio/video media is not accepted or logged by this path.

## Consequences

- Caddy continues to expose only the public web/API broker surface for GilJob services.
- Browser Realtime datachannel handling is allowed, but backend sideband routes remain the trusted business-logic boundary.
- Gemini next-question/TTS remains available as a separate provider boundary and fallback path; it is not the primary Realtime WebRTC audio path when `OPENAI_REALTIME_PRIMARY=true`.
- SpatialReal avatar rendering remains separate from interviewer audio; avatar RTC media is muted where needed to avoid dual-audio drift. The current SpatialReal RTC egress path accepts server-generated TTS WAV payloads, not OpenAI Realtime remote audio, so Realtime-avatar lip-sync is a known gap rather than a supported claim.
- Provider smoke tests must distinguish session brokering readiness from provider/network attach failures.

## Verification

Minimum verification before claiming this contract is intact:

- `node --check apps/web/static/app.js`
- `PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile services/api/server.py services/ai-engine/server.py`
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -v`
- targeted smoke evidence that `/api/interviews/:id/realtime/session` does not expose a standard provider key
- targeted smoke evidence that the browser uses `/v1/realtime/calls` for SDP attach and gates ordinary `realtime.response.create` on `full_mmm_ready`

Provider or external-network failures should be reported as runtime blockers with redacted evidence, not patched around by exposing direct provider secrets.

## Follow-ups

- Keep the Realtime smoke harness redacted and split provider-session, SDP attach, and MMM-readiness failures.
- Add external-network WebRTC evidence before demo readiness.
- Do not claim SpatialReal lip-sync with OpenAI Realtime audio until a tested bridge captures or routes Realtime output audio into SpatialReal without exposing secrets, raw media, or high-latency browser recording loops.
- Revisit server-proxying only if WebRTC provider/network constraints make the ephemeral browser attach path unsuitable.
