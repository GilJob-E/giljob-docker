# services/ai-engine Agent Contract

This module owns bounded AI provider adapters for the interview scaffold. Follow the root `AGENTS.md` plus these local rules.

## Current responsibilities
- Provide health/readiness endpoints for the AI engine container.
- Keep fake-provider behavior available for local scaffold/route smoke when explicitly configured.
- Do not reintroduce non-Realtime LLM/TTS fallback. The live interviewer path is OpenAI Realtime-only and is brokered by `services/api`.
- Provide an internal TTS adapter at `POST /tts/synthesize`; `VOICE_PROVIDER=fake` is keyless and `VOICE_PROVIDER=elevenlabs` requires server-side ElevenLabs env values. This adapter is compatibility/smoke only, not the main voice loop.
- Provide an internal avatar session adapter at `POST /avatar/session`; `AVATAR_PROVIDER=disabled` degrades cleanly, and `AVATAR_PROVIDER=spatialreal` exchanges the server-side key for short-lived client session metadata.
- Keep SpatialReal RTC egress attempts server-side and require a LiveKit URL reachable from SpatialReal cloud; local-only LiveKit URLs are not valid for cloud publishing.
- Treat `sessionToken`, provider keys, request failures, and upstream error bodies as sensitive. Public API responses must stay redacted.

## Not complete product features yet
- Full Main LLM loop orchestration.
- OpenAI Realtime browser WebRTC session brokering; the API owns ephemeral Realtime session routes and readiness gates.
- STT or audio transcription; local Whisper STT has been removed and transcription belongs to the GilJobE analysis-engine boundary, not this service.
- Full avatar rendering, avatar media streaming, or SpatialReal Web SDK lifecycle ownership in this service; this service only creates bounded session metadata for the browser surface through the API broker.
- Final report generation.
- Direct raw media or raw token handling.

## Ingress contract
- Browser traffic must go through `services/api`; this service is internal/container-facing.
- Caddy must not expose direct `/ai/*`, `/tts/*`, or `/avatar/*` routes.
- Any new provider route must have fail-closed, no-secret-leak contract tests before being wired to the browser.
- Any attempt to add a non-Realtime main voice fallback must be rejected unless the product architecture is explicitly changed first.

## Tests
Run AI engine contract tests after changes:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.contract.test_ai_engine_contract -v
```
