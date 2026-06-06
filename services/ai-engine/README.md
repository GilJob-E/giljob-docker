# services/ai-engine

Bounded AI provider service for the GilJob v2 interview scaffold.

Follow:
- docs/implementation-plan.md
- docs/decisions/0001-state-stack.md
- docs/decisions/0002-ingress-stack.md

## Main LLM env contract

Gemini is the selected Main LLM provider for the next interview-controller slice.
Copy `.env.example` to `.env`, then set:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-google-ai-studio-key
GEMINI_MODEL=gemini-3.5-flash
GEMINI_TIMEOUT_SECONDS=30
```

The official Gemini quickstart expects the API key in `GEMINI_API_KEY`.
Do not commit `.env` or real API keys.


## STT boundary

STT is not implemented in this service. The former local Whisper boundary has been removed; transcription belongs to the future `services/analysis-engine` integration based on `GilJobE` subscribing to LiveKit tracks.


## TTS adapter contract

The TTS adapter lives inside `ai-engine` and is internal/container-facing only. `POST /tts/synthesize` is called by `services/api`, which exposes the browser-facing `/api/interviews/{interviewId}/turns/{turnIndex}/tts` broker route. Caddy must not expose direct `/tts/*` or `/ai/tts/*` routes. Provider failures are redacted before leaving the API boundary.

```env
VOICE_PROVIDER=fake
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
ELEVENLABS_TTS_MODEL=eleven_flash_v2_5
ELEVENLABS_OUTPUT_FORMAT=mp3_22050_32
```

`VOICE_PROVIDER=fake` returns deterministic keyless WAV bytes plus metadata for smoke tests. `VOICE_PROVIDER=elevenlabs` requires both `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID`; missing values fail closed with `tts_provider_unavailable` and never print the key.


## Avatar session adapter contract

SpatialReal session creation is handled as an internal provider adapter. `POST /avatar/session` is called by `services/api`, which exposes the browser-facing `/api/interviews/{interviewId}/avatar/session` broker route. Caddy must not expose direct `/avatar/*`, `/ai/avatar/*`, or broad `/ai/*` routes.

```env
AVATAR_PROVIDER=disabled
SPATIALREAL_API_KEY=
SPATIALREAL_APP_ID=
SPATIALREAL_AVATAR_ID=
SPATIALREAL_REGION=ap-northeast
SPATIALREAL_SESSION_TTL_SECONDS=900
SPATIALREAL_AUDIO_SAMPLE_RATE=16000
SPATIALREAL_AUDIO_CHANNEL_COUNT=1
```

`AVATAR_PROVIDER=disabled` returns a safe disabled response without a `sessionToken`. `AVATAR_PROVIDER=spatialreal` requires the server-side API key and app id; missing values fail closed with `avatar_provider_unavailable`. Successful responses may include short-lived client session metadata, but raw provider keys are never returned.
