# services/ai-engine Agent Contract

This module owns bounded AI provider adapters for the interview scaffold. Follow the root `AGENTS.md` plus these local rules.

## Current responsibilities
- Provide health/readiness endpoints for the AI engine container.
- Provide a Gemini-backed next-question provider boundary for interview question generation.
- Use `GEMINI_API_KEY` only from environment configuration; never commit or print its value.
- When `LLM_PROVIDER=gemini`, fail closed if `GEMINI_API_KEY` is missing or the Gemini request fails.
- Keep fake-provider behavior available for local scaffold/testing when explicitly configured.
- Provide an internal TTS adapter at `POST /tts/synthesize`; `VOICE_PROVIDER=fake` is keyless, `VOICE_PROVIDER=gemini` uses Gemini native TTS, and `VOICE_PROVIDER=elevenlabs` requires server-side ElevenLabs env values.
- Provide an internal avatar session adapter at `POST /avatar/session`; `AVATAR_PROVIDER=disabled` degrades cleanly, and `AVATAR_PROVIDER=spatialreal` exchanges the server-side key for short-lived client session metadata.
- Provide the bounded SpatialReal RTC/LiveKit egress attempt path when `SPATIALREAL_RTC_EGRESS_ENABLED=true`; e2e avatar media still depends on a LiveKit URL reachable by SpatialReal cloud plus verified WebRTC media/TURN routing.
- Treat `sessionToken`, provider keys, request failures, prompts containing candidate data, and upstream error bodies as sensitive. Public API responses must stay redacted.

## Not complete product features yet
- Full Main LLM loop orchestration or production interview state machine.
- STT or audio transcription; local Whisper STT has been removed and transcription belongs to the GilJobE analysis-engine boundary, not this service.
- Ownership of browser avatar rendering; the browser has an AvatarKit RTC shell, while this service owns provider/session/egress boundaries only.
- Guaranteed SpatialReal avatar media e2e success in local-only networking. Public LiveKit/WebRTC media routing is still a deployment gate.
- Final report generation.
- Direct raw media or raw token handling.

## Ingress contract
- Browser traffic must go through `services/api`; this service is internal/container-facing.
- Caddy must not expose direct `/ai/*`, `/tts/*`, or `/avatar/*` routes.
- Any new provider route must have fail-closed, no-secret-leak contract tests before being wired to the browser.

## Tests
Run AI engine contract tests after changes:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.contract.test_ai_engine_contract -v
```
