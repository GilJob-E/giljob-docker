# ADR 0003 — Realtime Voice Flow and MMM Readiness Gate

- Status: Accepted for current Realtime WebRTC scaffold; revisit after external provider smoke and integrated LiveKit/analysis evidence
- Date: 2026-06-12
- Gate: Realtime interviewer voice flow
- Source: `services/api/server.py`, `apps/web/static/app.js`, `docs/architecture.noml`

## Context

GilJob v2 needs a browser-facing live interviewer voice path without exposing provider keys, raw tokens, raw media, or internal analysis prompts. The current room already has LiveKit candidate media, GilJobE/analysis-engine boundaries, Realtime sideband/MMM readiness gates, and SpatialReal avatar scaffolding. The Realtime path must fit that scaffold rather than replacing all room state with a direct browser-to-provider integration.

The preserved constraints are:

- standard provider keys remain server-only
- browser-visible diagnostics and event logs do not print raw JWTs, ephemeral secrets, provider keys, SDP bodies, or raw media
- public browser routes use `/api/*` brokers; direct `/ai/*`, `/tts/*`, and `/avatar/*` remain blocked
- Realtime audio generation is not allowed to skip internal multimodal readiness for ordinary next-question turns
- transcript/prosody/vision signals are treated as bounded sideband inputs; low-resolution vision samples may cross only the internal API→analysis-engine hop and must never be stored or exposed as raw media archives

## Options considered

### Option A — Browser calls OpenAI Realtime directly with a standard API key

Pros:
- Simplest WebRTC attach path.

Cons:
- Violates the server-only provider-key contract.
- Makes public browser code a trusted business-logic boundary.
- Increases the blast radius of logs, screenshots, and browser devtools.

### Option B — API brokers Realtime session metadata, browser attaches SDP through the API

Pros:
- Keeps the standard OpenAI API key server-only.
- Lets the browser use WebRTC for low-latency interviewer audio.
- Keeps room UI and diagnostics token-safe.
- Allows the API to publish route metadata and readiness gates without proxying media.

Cons:
- The browser does not talk to the provider SDP endpoint; the API call broker owns provider attach with the server key, so route and redaction contracts must be tested.
- Provider failure must degrade cleanly without exposing upstream error bodies.

### Option C — Server proxies all Realtime media and datachannel traffic

Pros:
- Strongest centralization of provider traffic.

Cons:
- Much larger implementation surface.
- Adds avoidable media latency and operational complexity for the current scaffold.
- Duplicates work already handled by WebRTC provider infrastructure.

## Decision

Choose **Option B: API-mediated Realtime session plus API-brokered browser WebRTC SDP attach**.

The API owns `/api/interviews/:id/realtime/session` and `/api/interviews/:id/realtime/call`. It uses the standard server-side provider key for Realtime session checks and `/v1/realtime/calls` SDP attach, then returns only browser-safe route/session metadata and SDP answers. The browser must not call provider routes directly or receive/log the standard provider key, provider client-secret values, or raw SDP bodies.

The first interviewer question is a bootstrap Realtime response and does not require MMM because there is no prior candidate answer. Ordinary follow-up next-question audio is gated. After the candidate answer ends, the browser forwards bounded transcript/prosody/vision sideband events to:

- `/api/interviews/:id/turns/:turnIndex/events`
- `/api/interviews/:id/turns/:turnIndex/vision-events`
- `/api/interviews/:id/turns/:turnIndex/mmm-ready`

For turn `N >= 2`, the next ordinary `realtime.response.create` is allowed only when the API reports `full_mmm_ready: true` for prior answer turn `N-1` and resolves a candidate-safe MMM result. Degraded or incomplete readiness blocks ordinary next-question audio rather than silently bypassing the analysis contract. The browser may relay the API-approved command over the already-attached Realtime data channel, but it must not author the prompt or bypass the API decision.

## Public contract

- `OPENAI_API_KEY` is the only OpenAI server key and remains server-only; do not add `OPENAI_REALTIME_API_KEY`.
- `OPENAI_REALTIME_PRIMARY=true` enables the Realtime primary browser path and is the default documented primary voice mode.
- `/api/interviews/:id/realtime/session` returns provider status, route metadata, and an ephemeral client secret shape only.
- The SDP attach endpoint is `/v1/realtime/calls`; no `?model=` fallback is part of the locked browser attach contract.
- Browser logs may mention that a client secret or SDP exists, but must not print the secret value or SDP body.
- Sideband events may include bounded transcript text and low-resolution vision samples needed for exact-turn MMM, but public responses, durable JSONL, browser logs, and docs expose only structured signals/candidate-safe fragments rather than raw transcript/audio/video.

## Consequences

- Caddy continues to expose only the public web/API broker surface for GilJob services.
- Browser Realtime datachannel handling is allowed, but backend sideband routes remain the trusted business-logic boundary.
- Gemini next-question/TTS fallback is intentionally removed from the accepted architecture. OpenAI Realtime is the only live interviewer voice path when `OPENAI_REALTIME_PRIMARY=true`; internal fake/ElevenLabs adapters are smoke/compatibility surfaces only and must not become ordinary fallback voice paths.
- SpatialReal avatar rendering remains separate from interviewer audio; avatar RTC media is muted where needed to avoid dual-audio drift. The current SpatialReal RTC egress path accepts server-generated TTS WAV payloads, not OpenAI Realtime remote audio, so Realtime-avatar lip-sync is a known gap rather than a supported claim.
- SpatialReal SDK Mode Web may be enabled with `SPATIALREAL_SDK_MODE_WEB_ENABLED=true`. The API exposes safe sibling metadata (`avatarSdkMode` on `/api/sessions`, `sdkMode` on avatar session responses) and returns token-bearing `client.spatialrealSdk` only from the canonical `/avatar/session` bootstrap after the SDK gate is enabled/configured. The browser may feed a muted PCM16 copy of OpenAI Realtime output to `AvatarController.send(pcm, false)` and must fail closed with safe SDK reasons until kiostation QA proves the runtime outcome.
- Provider smoke tests must distinguish session brokering readiness from provider/network attach failures.

## Verification

Minimum verification before claiming this contract is intact:

- `node --check apps/web/static/app.js`
- `PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile services/api/server.py services/analysis-engine/server.py`
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -v`
- targeted smoke evidence that `/api/interviews/:id/realtime/session` does not expose a standard provider key
- targeted smoke evidence that the browser uses `/api/interviews/:id/realtime/call` for SDP attach and gates ordinary `realtime.response.create` on `full_mmm_ready`

Provider or external-network failures should be reported as runtime blockers with redacted evidence, not patched around by exposing direct provider secrets.

## Follow-ups

- Keep the Realtime smoke harness redacted and split provider-session, SDP attach, and MMM-readiness failures.
- Add external-network WebRTC evidence before demo readiness.
- Do not claim production SpatialReal lip-sync with OpenAI Realtime audio until the feature-flagged bridge has kiostation browser evidence and remains free of secrets, raw media, and high-latency browser recording loops.
- Revisit browser-direct provider attach only if the API call broker proves unworkable and the product explicitly accepts browser-held ephemeral provider secrets.
