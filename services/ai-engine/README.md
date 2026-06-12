# services/ai-engine

Bounded AI provider service for the GilJob v2 interview scaffold.

Follow:
- `docs/implementation-plan.md`
- `docs/decisions/0001-state-stack.md`
- `docs/decisions/0002-ingress-stack.md`
- `docs/decisions/0003-realtime-voice-flow.md`
- Root `README.md` for current install/run instructions.

## Dependency install

Docker images install this module's Python dependencies from:

```bash
services/ai-engine/requirements.txt
```

For local development from the repository root, use the aggregate file:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Main LLM env contract

Gemini is the bounded next-question provider and non-primary/fallback path for the current scaffold. OpenAI Realtime browser-session brokering is owned by `services/api`. Copy `.env.example` to `.env`, then set provider values there. Do not commit `.env` or real API keys.

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-google-ai-studio-key
GEMINI_MODEL=gemini-3.5-flash
GEMINI_TIMEOUT_SECONDS=30
```

The Gemini key is read only from `GEMINI_API_KEY`. Provider failures fail closed and are redacted at the API boundary.

## Realtime boundary

This service does not broker OpenAI Realtime ephemeral sessions, SDP attach, or MMM readiness. Those browser-facing routes are API-owned:

- `/api/interviews/{interviewId}/realtime/session`
- `/api/interviews/{interviewId}/realtime/call`
- `/api/interviews/{interviewId}/turns/{turnIndex}/events`
- `/api/interviews/{interviewId}/turns/{turnIndex}/vision-events`
- `/api/interviews/{interviewId}/turns/{turnIndex}/mmm-ready`

Keep standard provider keys, Realtime client secrets, SDP bodies, and upstream errors out of this service's public responses and logs.

## STT boundary

STT is not implemented in this service. The former local Whisper boundary has been removed; transcription belongs to `services/analysis-engine`, which integrates GilJobE and subscribes to LiveKit tracks.

## TTS adapter contract

The TTS adapter is internal/container-facing only. `POST /tts/synthesize` is called by `services/api`, which exposes the browser-facing `/api/interviews/{interviewId}/turns/{turnIndex}/tts` broker route. Caddy must not expose direct `/tts/*` or `/ai/tts/*` routes. Provider failures are redacted before leaving the API boundary.

Current provider options:

```env
# Keyless smoke provider
VOICE_PROVIDER=fake

# Gemini native TTS provider
VOICE_PROVIDER=gemini
GEMINI_API_KEY=your-google-ai-studio-key
GEMINI_TTS_MODEL=gemini-3.1-flash-tts-preview
GEMINI_TTS_VOICE=Kore

# Legacy supported provider, not the default path
VOICE_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
ELEVENLABS_TTS_MODEL=eleven_flash_v2_5
ELEVENLABS_OUTPUT_FORMAT=mp3_22050_32
```

`VOICE_PROVIDER=fake` returns deterministic keyless WAV bytes plus metadata for smoke tests. `VOICE_PROVIDER=gemini` requires `GEMINI_API_KEY`. `VOICE_PROVIDER=elevenlabs` requires both `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID`. Missing values fail closed with a provider-unavailable response and never print the secret value.

## Avatar session and RTC egress contract

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

# Optional SpatialReal -> LiveKit avatar publishing path.
# This URL must be reachable from SpatialReal cloud, not only from local Docker.
SPATIALREAL_RTC_EGRESS_ENABLED=true
SPATIALREAL_RTC_LIVEKIT_URL=wss://public-livekit.example.com
SPATIALREAL_RTC_PUBLISHER_ID_PREFIX=spatialreal-avatar
SPATIALREAL_RTC_IDLE_TIMEOUT_SECONDS=30
SPATIALREAL_RTC_SETTLE_SECONDS=1.0
```

`AVATAR_PROVIDER=disabled` returns a safe disabled response without a `sessionToken`. `AVATAR_PROVIDER=spatialreal` requires the server-side API key, app id, and avatar id. Successful responses may include short-lived client session metadata, but raw provider keys are never returned. RTC egress also requires a public LiveKit signaling/media path; a local-only `ws://127.0.0.1:7880` URL is not enough for cloud-side avatar publishing.

## Security contract

- Browser traffic must go through `services/api`.
- Caddy must not expose direct `/ai/*`, `/tts/*`, or `/avatar/*` provider routes.
- Do not log or return provider keys, raw JWTs, raw LiveKit tokens, or upstream provider error bodies.
- Do not log or return Realtime client secrets, SDP bodies, SpatialReal session tokens, or raw media.
- Any new provider route must have fail-closed, no-secret-leak contract tests before being wired to the browser.

## Tests

Run AI engine contract tests after changes:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.contract.test_ai_engine_contract -v
```
