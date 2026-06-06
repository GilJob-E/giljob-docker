# TTS and Avatar Provider Contract

This runbook defines the Phase 0B/1 contract for interviewer voice and future avatar integration. It does not implement ElevenLabs STT, SpatialReal browser avatar rendering, or LiveKit interviewer audio publication. Candidate STT remains owned by the GilJobE-backed `services/analysis-engine` boundary.

## Current phase

- `VOICE_PROVIDER=fake` is the mandatory keyless local smoke path.
- `VOICE_PROVIDER=gemini` uses Gemini native TTS (`gemini-3.1-flash-tts-preview`) with the existing server-side `GEMINI_API_KEY`.
- `VOICE_PROVIDER=elevenlabs` remains supported only when `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` are supplied in the runtime `.env`.
- `TTS_PROVIDER_FAILURE_FALLBACK=fake` may be enabled for local demos so provider quota/payment failures do not block the interview room.
- `AVATAR_PROVIDER=disabled` remains the default. SpatialReal is a future Phase 3 provider after the LiveKit client compatibility gate is resolved.
- `AVATAR_PROVIDER_FAILURE_FALLBACK=disabled` may be enabled for local demos so SpatialReal provider failures do not block the interview room.
- Do not downgrade `livekit-client` from the current `2.19.1` just to satisfy SpatialReal.

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
| `AVATAR_PROVIDER` | Future avatar provider switch. | no | `disabled` |
| `SPATIALREAL_API_KEY` | SpatialReal API key. | yes | empty |
| `SPATIALREAL_APP_ID` | SpatialReal app identifier. | no, but server-mediated | empty |
| `SPATIALREAL_AVATAR_ID` | SpatialReal avatar identifier. | no, but server-mediated | empty |
| `SPATIALREAL_REGION` | Region used to derive the SpatialReal console endpoint. | no | `ap-northeast` |
| `SPATIALREAL_SESSION_TTL_SECONDS` | Short-lived avatar session token TTL. | no | `900` |
| `AVATAR_PROVIDER_FAILURE_FALLBACK` | Optional fail-open mode for room UX when SpatialReal returns a provider error. | no | empty; set `disabled` for local demos |
| `SPATIALREAL_AUDIO_SAMPLE_RATE` | Avatar audio input sample rate metadata. | no | `16000` |
| `SPATIALREAL_AUDIO_CHANNEL_COUNT` | Avatar audio channel count metadata. | no | `1` |

SpatialReal console/ingress endpoint overrides are intentionally not part of the default `.env` surface. Use `SPATIALREAL_REGION` first; add provider-specific endpoint overrides only in a future compatibility-gated change.

## Token and secret surface

The browser may receive short-lived LiveKit join JWTs or avatar session tokens only through explicit token contracts. Opaque GilJob session/report bearer tokens are separate application tokens. Neither token class nor provider secrets may appear in static files, visible UI, logs, smoke output, or third-party provider responses.

Provider calls are backend-owned. Browser-facing voice/avatar status must be routed through `services/api` and return sanitized metadata or object references only. Direct public `/tts/*` routes must not be exposed through Caddy.

## Non-goals for Phase 1

- No ElevenLabs STT replacement.
- No SpatialReal browser avatar tile.
- No interviewer/avatar audio publication into the candidate LiveKit room.
- No Realtime or LiveKit Agents migration.
- No `livekit-client` downgrade.

## Future gates

Before Phase 2/3, confirm candidate-only STT isolation so `interviewer-audio` and `spatialreal-avatar` tracks cannot affect `transcript_full`. Before browser avatar rendering, resolve SpatialReal RTC compatibility with the current LiveKit client or choose an isolated bundle/page strategy.
