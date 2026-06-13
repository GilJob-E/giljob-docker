# TTS and Avatar Provider Contract

This runbook defines the current contract for interviewer voice and avatar integration. The default interview path is OpenAI Realtime + MMM without LiveKit. Legacy question/TTS routes return deprecated_ai_engine_removed with reason=realtime_only and do not call ai-engine. Avatar metadata is API-owned and disabled/deferred unless a verified opt-in proof exists. Candidate STT remains owned by the GilJobE-backed `services/analysis-engine` boundary.

## Current phase

- `OPENAI_REALTIME_PRIMARY=true` is the intended realtime branch voice mode when OpenAI credentials and runtime are ready.
- Legacy question/TTS routes return `deprecated_ai_engine_removed` with `reason=realtime_only`; the browser default path must not call them.
- Gemini TTS fallback is removed; do not configure or document it as a supported route.
- Avatar metadata is API-owned. The canonical `/api/interviews/{id}/avatar/session` route is the SpatialReal SDK Mode Web bootstrap; avatar UI must be disabled/deferred unless ready SDK metadata and browser initialization succeed.
- `SPATIALREAL_RTC_EGRESS_ENABLED=false` remains the safe default and belongs only to legacy AvatarKit RTC / SpatialReal-to-LiveKit publishing. Enabling it requires a LiveKit URL reachable from SpatialReal cloud, not only local Docker or `127.0.0.1`. It is not required for the default Realtime/MMM path.
- SpatialReal RTC egress is a deprecated compatibility publisher only and is disabled by default. It must not be used by the default Realtime/MMM path, must not depend on ai-engine, and does not ingest OpenAI Realtime remote audio, Realtime datachannel events, or candidate LiveKit media.
- `SPATIALREAL_SDK_MODE_WEB_ENABLED=false` remains the stable default. Setting it true enables only API-brokered SDK Mode Web metadata; it is not a production lip-sync claim until kiostation browser evidence marks the SDK outcome verified.
- Do not downgrade `livekit-client` just to satisfy SpatialReal. Also do not upgrade it in this docs-only lane without a separate dependency spike. This checkout declares `livekit-client` `2.16.1`; keep version changes out of this lane unless proven needed.

## Environment variables

| Variable | Purpose | Secret | Default / phase |
|---|---|---:|---|
| `SPATIALREAL_API_KEY` | Future SpatialReal API key for a separately verified avatar metadata broker. | yes | empty |
| `SPATIALREAL_APP_ID` | Future SpatialReal app identifier. | no, but server-mediated | empty |
| `SPATIALREAL_AVATAR_ID` | Future SpatialReal avatar identifier. | no, but server-mediated | empty |
| `SPATIALREAL_ENVIRONMENT` | SpatialReal SDK environment for browser initialization. | no | `intl` |
| `SPATIALREAL_SESSION_TOKEN` | QA-only/manual SpatialReal SDK session token until replaced by API-brokered short-lived token issuance. | yes | empty |
| `SPATIALREAL_AUDIO_SAMPLE_RATE` | Avatar audio input sample rate metadata. | no | `16000` |
| `SPATIALREAL_AUDIO_CHANNEL_COUNT` | Avatar audio channel count metadata. | no | `1` |
| `SPATIALREAL_RTC_EGRESS_ENABLED` | Enables optional SpatialReal-to-LiveKit avatar publishing after separate verification. | no | `false` |
| `SPATIALREAL_RTC_LIVEKIT_URL` | Public LiveKit signaling URL supplied to SpatialReal for RTC egress. | no, but server-mediated | empty; falls back to `LIVEKIT_PUBLIC_URL` / `LIVEKIT_URL` if unset |
| `SPATIALREAL_RTC_PUBLISHER_ID_PREFIX` | Prefix for SpatialReal publisher identity metadata. | no | `spatialreal-avatar` |
| `SPATIALREAL_RTC_IDLE_TIMEOUT_SECONDS` | Avatar RTC idle timeout. | no | `30` |
| `SPATIALREAL_RTC_SETTLE_SECONDS` | Startup settle delay before RTC egress readiness checks. | no | `1.0` |
| `SPATIALREAL_SDK_MODE_WEB_ENABLED` | Enables canonical SDK Mode Web bootstrap metadata on `/avatar/session`. | no | `false` |

SpatialReal console/ingress endpoint overrides are intentionally not part of the default `.env.example` surface. Use `SPATIALREAL_REGION` first; add provider-specific endpoint overrides only in a compatibility-gated deployment change. RTC egress variables are retained only as deferred compatibility placeholders; they do not make the browser render an avatar tile by themselves and do not bridge OpenAI Realtime remote audio into SpatialReal.

## SpatialReal SDK Mode Web bootstrap

Current default outcome without credentials: `sdk_mode_deferred` or a safe blocked reason. With `SPATIALREAL_SDK_MODE_WEB_ENABLED=true` and configured SDK metadata, `/api/interviews/{id}/avatar/session` returns SDK-shaped metadata (`sdkMode.mode=spatialreal-sdk-mode-web`, `transport=spatialreal-sdk-websocket`, `livekitRequired=false`) plus `client.spatialrealSdk` fields approved for browser use. It must not return LiveKit viewer-token fields such as `token`, `url`, `roomName`, `candidateToken`, or `avatarClientToken`.

The browser dynamically imports `@spatialwalk/avatarkit`, calls `AvatarSDK.setSessionToken`, `AvatarSDK.initialize`, `AvatarManager.shared.load`, creates `new AvatarView`, mutes SDK playback, and feeds a PCM16 mono 16 kHz copy of OpenAI Realtime output through `AvatarController.send(pcm, false)`. On Realtime `response.done`, it sends one safe end marker. Realtime remains the audible interviewer voice owner, and MMM readiness remains authoritative before ordinary `response.create`.

Valid runtime outcomes are `sdk_mode_verified`, `sdk_mode_not_supported_current_version`, `sdk_mode_blocked_missing_provider_token`, `sdk_mode_blocked_dynamic_import`, `sdk_mode_blocked_wasm_mime`, `sdk_mode_blocked_pcm_send_failed`, `sdk_mode_blocked_double_audio_or_mute`, or `sdk_mode_deferred`. Never print raw SDP, provider keys, client secrets, SpatialReal/LiveKit token values, transcripts, or raw audio/video.

## Token and secret surface

The browser may receive short-lived LiveKit join JWTs or avatar session tokens only through explicit token contracts. Opaque GilJob session/report bearer tokens are separate application tokens. Neither token class nor provider secrets may appear in static files, visible UI, logs, smoke output, or third-party provider responses.

Provider calls are backend-owned. Browser-facing voice/avatar status must be routed through `services/api` and return sanitized metadata or object references only. Direct public provider routes such as `/tts/*`, `/avatar/*`, `/ai/tts/*`, `/ai/avatar/*`, or broad `/ai/*` must not be exposed through Caddy. Legacy `/api/interviews/.../question` and TTS routes are deprecated and must not be used by the default Realtime flow. API-owned avatar metadata routes may remain disabled/deferred, but must never call ai-engine or expose token-bearing provider payloads by default.

## Non-goals for Phase 1

- No ElevenLabs STT replacement.
- No production SpatialReal browser avatar lip-sync claim.
- No AvatarKit RTC / LiveKit audio injection by default. The only default avatar path is feature-flagged SpatialReal SDK Mode Web receiving a muted PCM16 copy after API-owned ready metadata.
- No interviewer/avatar audio publication into the candidate LiveKit room by default. SpatialReal RTC egress remains opt-in, post-TTS only, and requires a public LiveKit path plus provider credentials.
- No Realtime or LiveKit Agents migration.
- No `livekit-client` downgrade.

## Future gates

Before Phase 2/3, confirm candidate-only STT isolation so `interviewer-audio` and `spatialreal-avatar` tracks cannot affect `transcript_full`. Before enabling RTC egress outside local smoke, verify `SPATIALREAL_RTC_LIVEKIT_URL` is externally reachable by SpatialReal and is not a loopback/container-only address. Before claiming Realtime avatar lip-sync, record kiostation browser evidence for SDK render/connection, muted PCM feed, no double audio, and no provider key/token/raw media leakage.
