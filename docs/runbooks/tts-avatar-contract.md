# TTS and Avatar Provider Contract

This runbook defines the current interviewer voice and avatar-provider boundary for GilJob v2. It distinguishes implemented scaffold boundaries from end-to-end media guarantees.

## Current phase

- `VOICE_PROVIDER=fake` is the mandatory keyless local smoke path.
- `VOICE_PROVIDER=gemini` uses Gemini native TTS (`gemini-3.1-flash-tts-preview`) with the existing server-side `GEMINI_API_KEY`.
- `VOICE_PROVIDER=elevenlabs` remains supported only when `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` are supplied in the runtime `.env`.
- `TTS_PROVIDER_FAILURE_FALLBACK=fake` may be enabled for local demos so provider quota/payment failures do not block the interview room.
- `AVATAR_PROVIDER=disabled` remains the default.
- `AVATAR_PROVIDER=spatialreal` is implemented as a bounded session-token broker through `services/ai-engine` and `services/api`.
- The browser has a SpatialReal AvatarKit RTC renderer shell and uses the vendored AvatarKit bundle path.
- Optional SpatialReal RTC/LiveKit egress is attempted when `SPATIALREAL_RTC_EGRESS_ENABLED=true`, but avatar media e2e success requires a LiveKit URL and WebRTC media path reachable by SpatialReal cloud.
- Keep `livekit-client` pinned to the version required by `@spatialwalk/avatarkit-rtc`; at this audit point the repository uses `livekit-client@2.16.1`. Do not upgrade or downgrade the lockfile without a SpatialReal compatibility smoke.

## Environment variables

| Variable | Purpose | Secret | Default / phase |
|---|---|---:|---|
| `VOICE_PROVIDER` | Selects `fake`, `gemini`, or `elevenlabs` TTS provider. | no | `fake` |
| `GEMINI_TTS_MODEL` | Gemini native TTS model ID. | no | `gemini-3.1-flash-tts-preview` |
| `GEMINI_TTS_VOICE` | Gemini prebuilt voice name. | no | `Kore` |
| `ELEVENLABS_API_KEY` | ElevenLabs API key for real TTS smoke. | yes | empty |
| `ELEVENLABS_VOICE_ID` | Voice ID used by ElevenLabs TTS. | no, but server-side config | empty |
| `ELEVENLABS_TTS_MODEL` | TTS model ID. | no | `eleven_flash_v2_5` |
| `ELEVENLABS_OUTPUT_FORMAT` | Initial TTS output format. | no | `mp3_22050_32` |
| `TTS_PROVIDER_FAILURE_FALLBACK` | Optional fail-open provider for room UX when Gemini or ElevenLabs returns a provider error. | no | empty; set `fake` for local demos |
| `AVATAR_PROVIDER` | Selects `disabled` or `spatialreal`. | no | `disabled` |
| `SPATIALREAL_API_KEY` | SpatialReal API key. | yes | empty |
| `SPATIALREAL_APP_ID` | SpatialReal app identifier. | no, but server-mediated | empty |
| `SPATIALREAL_AVATAR_ID` | SpatialReal avatar identifier. | no, but server-mediated | empty |
| `SPATIALREAL_REGION` | Region used to derive the SpatialReal console endpoint. | no | `ap-northeast` |
| `SPATIALREAL_CONSOLE_ENDPOINT` | Optional provider endpoint override. | no | empty |
| `SPATIALREAL_INGRESS_ENDPOINT` | Optional provider ingress endpoint override. | no | empty |
| `SPATIALREAL_SESSION_TTL_SECONDS` | Short-lived avatar session token TTL. | no | `900` |
| `AVATAR_PROVIDER_FAILURE_FALLBACK` | Optional fail-open mode for room UX when SpatialReal returns a provider error. | no | empty; set `disabled` for local demos |
| `SPATIALREAL_AUDIO_SAMPLE_RATE` | Avatar audio input sample rate metadata. | no | `16000` |
| `SPATIALREAL_AUDIO_CHANNEL_COUNT` | Avatar audio channel count metadata. | no | `1` |
| `SPATIALREAL_RTC_EGRESS_ENABLED` | Enables the SpatialReal -> LiveKit publishing attempt. | no | `false` |
| `SPATIALREAL_RTC_LIVEKIT_URL` | LiveKit URL reachable by SpatialReal cloud. | no, but deployment-sensitive | empty |
| `SPATIALREAL_RTC_PUBLISHER_ID_PREFIX` | Publisher identity prefix for avatar media. | no | `spatialreal-avatar` |
| `SPATIALREAL_RTC_IDLE_TIMEOUT_SECONDS` | Egress idle timeout. | no | `30` |
| `SPATIALREAL_RTC_SETTLE_SECONDS` | Small wait before egress settle/return. | no | `1.0` |

## Token and secret surface

The browser may receive short-lived LiveKit join JWTs or avatar session tokens only through explicit token contracts. Opaque GilJob session/report bearer tokens are separate application tokens. Neither token class nor provider secrets may appear in static files, visible UI, logs, smoke output, or third-party provider responses.

Provider calls are backend-owned. Browser-facing voice/avatar status must be routed through `services/api` and return sanitized metadata or object references only. Direct public `/tts/*`, `/avatar/*`, or `/ai/*` routes must not be exposed through Caddy.

## Non-goals / not guaranteed yet

- No ElevenLabs STT replacement.
- No guarantee that SpatialReal cloud can publish avatar media into a local-only LiveKit room.
- No production-ready interviewer/avatar audio publication until public `wss://...` signaling plus WebRTC media/TURN are verified.
- No Realtime or LiveKit Agents migration.
- No `livekit-client` lockfile change without AvatarKit compatibility proof.

## Future gates

Before production avatar/TTS, confirm candidate-only STT isolation so `interviewer-audio` and `spatialreal-avatar` tracks cannot affect `transcript_full`. Before calling browser avatar rendering complete, verify SpatialReal RTC compatibility, public LiveKit access from SpatialReal cloud, and media/TURN connectivity with a repeatable browser/runtime smoke.
