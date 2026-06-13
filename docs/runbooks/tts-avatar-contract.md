# TTS and Avatar Provider Contract

This runbook defines the current contract for interviewer voice and avatar integration. The default interview path is OpenAI Realtime + MMM without LiveKit. Legacy question/TTS routes return deprecated_ai_engine_removed with reason=realtime_only and do not call ai-engine. Avatar metadata is API-owned and disabled/deferred unless a verified opt-in proof exists. Candidate STT remains owned by the GilJobE-backed `services/analysis-engine` boundary.

## Current phase

- `OPENAI_REALTIME_PRIMARY=true` is the intended realtime branch voice mode when OpenAI credentials and runtime are ready.
- Legacy question/TTS routes return `deprecated_ai_engine_removed` with `reason=realtime_only`; the browser default path must not call them.
- Gemini TTS fallback is removed; do not configure or document it as a supported route.
- Avatar metadata is API-owned. SpatialReal session brokering is disabled/deferred until the browser avatar rendering gate is resolved. Avatar UI must be disabled/deferred unless a non-LiveKit SDK Mode proof or explicitly legacy RTC proof is verified.
- `SPATIALREAL_RTC_EGRESS_ENABLED=false` remains the safe default and belongs only to legacy AvatarKit RTC / SpatialReal-to-LiveKit publishing. Enabling it requires a LiveKit URL reachable from SpatialReal cloud, not only local Docker or `127.0.0.1`. It is not required for the default Realtime/MMM path.
- SpatialReal RTC egress is a deprecated compatibility publisher only and is disabled by default. It must not be used by the default Realtime/MMM path, must not depend on ai-engine, and does not ingest OpenAI Realtime remote audio, Realtime datachannel events, or candidate LiveKit media.
- `SPATIALREAL_BROWSER_AUDIO_BRIDGE_ENABLED=false` remains the stable default. Setting it true only enables an experimental browser `AvatarPlayer.publishAudio(track)` probe using the OpenAI Realtime remote audio track; it is not a production lip-sync claim until kiostation browser evidence marks `bridge_verified`.
- Do not downgrade `livekit-client` just to satisfy SpatialReal. Also do not upgrade it in this docs-only lane without a separate dependency spike. This checkout declares `livekit-client` `2.16.1`; keep version changes out of this lane unless proven needed.

## Environment variables

| Variable | Purpose | Secret | Default / phase |
|---|---|---:|---|
| `SPATIALREAL_API_KEY` | Future SpatialReal API key for a separately verified avatar metadata broker. | yes | empty |
| `SPATIALREAL_APP_ID` | Future SpatialReal app identifier. | no, but server-mediated | empty |
| `SPATIALREAL_AVATAR_ID` | Future SpatialReal avatar identifier. | no, but server-mediated | empty |
| `SPATIALREAL_REGION` | Region for future SpatialReal API-owned metadata. | no | `ap-northeast` |
| `SPATIALREAL_SESSION_TTL_SECONDS` | Future short-lived avatar session token TTL if metadata brokering is re-enabled. | no | `900` |
| `SPATIALREAL_AUDIO_SAMPLE_RATE` | Avatar audio input sample rate metadata. | no | `16000` |
| `SPATIALREAL_AUDIO_CHANNEL_COUNT` | Avatar audio channel count metadata. | no | `1` |
| `SPATIALREAL_RTC_EGRESS_ENABLED` | Enables optional SpatialReal-to-LiveKit avatar publishing after separate verification. | no | `false` |
| `SPATIALREAL_RTC_LIVEKIT_URL` | Public LiveKit signaling URL supplied to SpatialReal for RTC egress. | no, but server-mediated | empty; falls back to `LIVEKIT_PUBLIC_URL` / `LIVEKIT_URL` if unset |
| `SPATIALREAL_RTC_PUBLISHER_ID_PREFIX` | Prefix for SpatialReal publisher identity metadata. | no | `spatialreal-avatar` |
| `SPATIALREAL_RTC_IDLE_TIMEOUT_SECONDS` | Avatar RTC idle timeout. | no | `30` |
| `SPATIALREAL_RTC_SETTLE_SECONDS` | Startup settle delay before RTC egress readiness checks. | no | `1.0` |
| `SPATIALREAL_BROWSER_AUDIO_BRIDGE_ENABLED` | Enables sibling API metadata (`realtimeAvatarBridge` on `/api/sessions`, `bridge.browserAudioBridgeEnabled` on avatar sessions) for the experimental browser `AvatarPlayer.publishAudio(track)` probe. | no | `false` |

SpatialReal console/ingress endpoint overrides are intentionally not part of the default `.env.example` surface. Use `SPATIALREAL_REGION` first; add provider-specific endpoint overrides only in a compatibility-gated deployment change. RTC egress variables are retained only as deferred compatibility placeholders; they do not make the browser render an avatar tile by themselves and do not bridge OpenAI Realtime remote audio into SpatialReal.

## SpatialReal SDK Mode Web spike status

Current outcome: `sdk_mode_deferred`. The approved research says SpatialReal SDK Mode can be non-LiveKit, but this worker checkout has no installed `apps/web/node_modules/@spatialwalk/avatarkit` package files to verify current SDK Mode Web exports, method names, or audio-feed lifecycle. The next spike should install/inspect the current package or official docs, prove a muted PCM16 mono audio feed without LiveKit, and then record one of `sdk_mode_verified`, `sdk_mode_not_supported_current_version`, `sdk_mode_blocked_by_audio_feed`, or `sdk_mode_deferred`. Until then, do not claim production Realtime avatar lip-sync.

## Experimental Realtime audio bridge probe

The browser bridge is opt-in and metadata-gated. When `SPATIALREAL_BROWSER_AUDIO_BRIDGE_ENABLED=true`, `services/api` may include safe sibling metadata: `realtimeAvatarBridge` on `/api/sessions` and a sibling `bridge` object on the avatar session payload, for example `bridge.browserAudioBridgeEnabled`, `mode=experimental-openai-realtime-audio-to-avatar`, and redacted status fields. These objects must remain outside `client` because `client` can contain short-lived token-bearing SpatialReal/LiveKit metadata.

The probe publishes the OpenAI Realtime remote audio track to `AvatarPlayer.publishAudio(track)` only after Avatar RTC is connected. Realtime remains the audible interviewer voice owner, MMM readiness remains authoritative before ordinary `response.create`, and logs/docs/tests must use only safe statuses such as `avatar_audio_bridge_disabled`, `avatar_audio_bridge_waiting_avatar`, `avatar_audio_bridge_waiting_realtime_track`, `avatar_audio_bridge_published`, `avatar_audio_bridge_unpublished`, or `avatar_audio_bridge_failed:<safe_reason>`. Never print raw SDP, provider keys, client secrets, SpatialReal/LiveKit token values, transcripts, or raw audio/video. Runtime outcomes are `bridge_verified`, `bridge_not_supported`, or `blocked`; anything short of kiostation browser proof remains experimental.

## Token and secret surface

The browser may receive short-lived LiveKit join JWTs or avatar session tokens only through explicit token contracts. Opaque GilJob session/report bearer tokens are separate application tokens. Neither token class nor provider secrets may appear in static files, visible UI, logs, smoke output, or third-party provider responses.

Provider calls are backend-owned. Browser-facing voice/avatar status must be routed through `services/api` and return sanitized metadata or object references only. Direct public provider routes such as `/tts/*`, `/avatar/*`, `/ai/tts/*`, `/ai/avatar/*`, or broad `/ai/*` must not be exposed through Caddy. Legacy `/api/interviews/.../question` and TTS routes are deprecated and must not be used by the default Realtime flow. API-owned avatar metadata routes may remain disabled/deferred, but must never call ai-engine or expose token-bearing provider payloads by default.

## Non-goals for Phase 1

- No ElevenLabs STT replacement.
- No production SpatialReal browser avatar lip-sync claim.
- No OpenAI Realtime remote-audio injection into SpatialReal by default; the only allowed carve-out is the feature-flagged experimental browser `AvatarPlayer.publishAudio(track)` probe above.
- No interviewer/avatar audio publication into the candidate LiveKit room by default. SpatialReal RTC egress remains opt-in, post-TTS only, and requires a public LiveKit path plus provider credentials.
- No Realtime or LiveKit Agents migration.
- No `livekit-client` downgrade.

## Future gates

Before Phase 2/3, confirm candidate-only STT isolation so `interviewer-audio` and `spatialreal-avatar` tracks cannot affect `transcript_full`. Before browser avatar rendering, resolve SpatialReal RTC compatibility with the current LiveKit client or choose an isolated bundle/page strategy. Before enabling RTC egress outside local smoke, verify `SPATIALREAL_RTC_LIVEKIT_URL` is externally reachable by SpatialReal and is not a loopback/container-only address. Before claiming Realtime avatar lip-sync, add evidence for a safe bridge from OpenAI Realtime output audio to SpatialReal that does not expose provider keys, raw tokens, or raw media in browser logs.
