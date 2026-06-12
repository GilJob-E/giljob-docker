# TTS and Avatar Provider Contract

This runbook defines the Phase 0B/1 contract for interviewer voice and avatar integration. It does not implement ElevenLabs STT, OpenAI Realtime remote-audio injection into SpatialReal, or default LiveKit interviewer/avatar audio publication. Candidate STT remains owned by the GilJobE-backed `services/analysis-engine` boundary.

## Current phase

- `OPENAI_REALTIME_PRIMARY=true` is the intended realtime branch voice mode when OpenAI credentials and runtime are ready.
- `VOICE_PROVIDER=fake` is the mandatory keyless local smoke path for legacy/internal TTS routes.
- Gemini TTS fallback is removed; do not configure or document it as a supported route.
- `VOICE_PROVIDER=elevenlabs` remains supported only as an internal compatibility adapter when `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` are supplied in the runtime `.env`.
- `TTS_PROVIDER_FAILURE_FALLBACK=fake` may be enabled for local demos so provider quota/payment failures do not block the interview room.
- `AVATAR_PROVIDER=disabled` remains the default. SpatialReal session brokering is backend-only until the browser avatar rendering gate is resolved.
- `AVATAR_PROVIDER_FAILURE_FALLBACK=disabled` may be enabled for local demos so SpatialReal provider failures do not block the interview room.
- `SPATIALREAL_RTC_EGRESS_ENABLED=false` remains the safe default. Enabling SpatialReal-to-LiveKit avatar publishing requires a LiveKit URL reachable from SpatialReal cloud, not only local Docker or `127.0.0.1`.
- SpatialReal RTC egress is a post-TTS publisher only: it sends mono PCM16/WAV audio bytes produced by `/tts/synthesize` into SpatialReal via `send_audio(end=True)`. It does not ingest OpenAI Realtime remote audio, Realtime datachannel events, or candidate LiveKit media.
- `SPATIALREAL_BROWSER_AUDIO_BRIDGE_ENABLED=false` remains the stable default. Setting it true only enables an experimental browser `AvatarPlayer.publishAudio(track)` probe using the OpenAI Realtime remote audio track; it is not a production lip-sync claim until kiostation browser evidence marks `bridge_verified`.
- Do not downgrade `livekit-client` from the current `2.19.1` just to satisfy SpatialReal.

## Environment variables

| Variable | Purpose | Secret | Default / phase |
|---|---|---:|---|
| `VOICE_PROVIDER` | Selects `fake` or `elevenlabs` for internal route smoke/compatibility only. | no | `fake` |
| `ELEVENLABS_API_KEY` | ElevenLabs API key for real TTS smoke. | yes | empty |
| `ELEVENLABS_VOICE_ID` | Voice ID used by ElevenLabs TTS. | no, but server-side config | empty |
| `ELEVENLABS_TTS_MODEL` | TTS model ID. | no | `eleven_flash_v2_5` |
| `ELEVENLABS_OUTPUT_FORMAT` | Initial TTS output format. | no | `mp3_22050_32` |
| `TTS_PROVIDER_FAILURE_FALLBACK` | Optional fail-open provider for route smoke when ElevenLabs returns a provider error. | no | empty; set `fake` for local demos |
| `AVATAR_PROVIDER` | Future avatar provider switch. | no | `disabled` |
| `SPATIALREAL_API_KEY` | SpatialReal API key. | yes | empty |
| `SPATIALREAL_APP_ID` | SpatialReal app identifier. | no, but server-mediated | empty |
| `SPATIALREAL_AVATAR_ID` | SpatialReal avatar identifier. | no, but server-mediated | empty |
| `SPATIALREAL_REGION` | Region used to derive the SpatialReal console endpoint. | no | `ap-northeast` |
| `SPATIALREAL_SESSION_TTL_SECONDS` | Short-lived avatar session token TTL. | no | `900` |
| `AVATAR_PROVIDER_FAILURE_FALLBACK` | Optional fail-open mode for room UX when SpatialReal returns a provider error. | no | empty; set `disabled` for local demos |
| `SPATIALREAL_AUDIO_SAMPLE_RATE` | Avatar audio input sample rate metadata. | no | `16000` |
| `SPATIALREAL_AUDIO_CHANNEL_COUNT` | Avatar audio channel count metadata. | no | `1` |
| `SPATIALREAL_RTC_EGRESS_ENABLED` | Enables optional SpatialReal-to-LiveKit avatar publishing. | no | `false` |
| `SPATIALREAL_RTC_LIVEKIT_URL` | Public LiveKit signaling URL supplied to SpatialReal for RTC egress. | no, but server-mediated | empty; falls back to `LIVEKIT_PUBLIC_URL` / `LIVEKIT_URL` if unset |
| `SPATIALREAL_RTC_PUBLISHER_ID_PREFIX` | Prefix for SpatialReal publisher identity metadata. | no | `spatialreal-avatar` |
| `SPATIALREAL_RTC_IDLE_TIMEOUT_SECONDS` | Avatar RTC idle timeout. | no | `30` |
| `SPATIALREAL_RTC_SETTLE_SECONDS` | Startup settle delay before RTC egress readiness checks. | no | `1.0` |
| `SPATIALREAL_BROWSER_AUDIO_BRIDGE_ENABLED` | Enables sibling API metadata (`realtimeAvatarBridge` on `/api/sessions`, `bridge.browserAudioBridgeEnabled` on avatar sessions) for the experimental browser `AvatarPlayer.publishAudio(track)` probe. | no | `false` |

SpatialReal console/ingress endpoint overrides are intentionally not part of the default `.env.example` surface. Use `SPATIALREAL_REGION` first; add provider-specific endpoint overrides only in a compatibility-gated deployment change. RTC egress variables are present because the backend may broker post-TTS avatar publishing, but they do not make the browser render an avatar tile by themselves and do not bridge OpenAI Realtime remote audio into SpatialReal.

## Experimental Realtime audio bridge probe

The browser bridge is opt-in and metadata-gated. When `SPATIALREAL_BROWSER_AUDIO_BRIDGE_ENABLED=true`, `services/api` may include safe sibling metadata: `realtimeAvatarBridge` on `/api/sessions` and a sibling `bridge` object on the avatar session payload, for example `bridge.browserAudioBridgeEnabled`, `mode=experimental-openai-realtime-audio-to-avatar`, and redacted status fields. These objects must remain outside `client` because `client` can contain short-lived token-bearing SpatialReal/LiveKit metadata.

The probe publishes the OpenAI Realtime remote audio track to `AvatarPlayer.publishAudio(track)` only after Avatar RTC is connected. Realtime remains the audible interviewer voice owner, MMM readiness remains authoritative before ordinary `response.create`, and logs/docs/tests must use only safe statuses such as `avatar_audio_bridge_disabled`, `avatar_audio_bridge_waiting_avatar`, `avatar_audio_bridge_waiting_realtime_track`, `avatar_audio_bridge_published`, `avatar_audio_bridge_unpublished`, or `avatar_audio_bridge_failed:<safe_reason>`. Never print raw SDP, provider keys, client secrets, SpatialReal/LiveKit token values, transcripts, or raw audio/video. Runtime outcomes are `bridge_verified`, `bridge_not_supported`, or `blocked`; anything short of kiostation browser proof remains experimental.

## Token and secret surface

The browser may receive short-lived LiveKit join JWTs or avatar session tokens only through explicit token contracts. Opaque GilJob session/report bearer tokens are separate application tokens. Neither token class nor provider secrets may appear in static files, visible UI, logs, smoke output, or third-party provider responses.

Provider calls are backend-owned. Browser-facing voice/avatar status must be routed through `services/api` and return sanitized metadata or object references only. Direct public `/tts/*`, `/avatar/*`, `/ai/tts/*`, `/ai/avatar/*`, or broad `/ai/*` routes must not be exposed through Caddy.

## Non-goals for Phase 1

- No ElevenLabs STT replacement.
- No production SpatialReal browser avatar lip-sync claim.
- No OpenAI Realtime remote-audio injection into SpatialReal by default; the only allowed carve-out is the feature-flagged experimental browser `AvatarPlayer.publishAudio(track)` probe above.
- No interviewer/avatar audio publication into the candidate LiveKit room by default. SpatialReal RTC egress remains opt-in, post-TTS only, and requires a public LiveKit path plus provider credentials.
- No Realtime or LiveKit Agents migration.
- No `livekit-client` downgrade.

## Future gates

Before Phase 2/3, confirm candidate-only STT isolation so `interviewer-audio` and `spatialreal-avatar` tracks cannot affect `transcript_full`. Before browser avatar rendering, resolve SpatialReal RTC compatibility with the current LiveKit client or choose an isolated bundle/page strategy. Before enabling RTC egress outside local smoke, verify `SPATIALREAL_RTC_LIVEKIT_URL` is externally reachable by SpatialReal and is not a loopback/container-only address. Before claiming Realtime avatar lip-sync, add evidence for a safe bridge from OpenAI Realtime output audio to SpatialReal that does not expose provider keys, raw tokens, or raw media in browser logs.
