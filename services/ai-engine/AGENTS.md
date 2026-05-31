# services/ai-engine Agent Contract

This module owns the bounded AI engine scaffold. Follow the root `AGENTS.md` plus these local rules.

## Current responsibilities
- Provide health/readiness endpoints for the AI engine container.
- Provide a Gemini-backed next-question provider boundary for interview question generation.
- Use `GEMINI_API_KEY` only from environment configuration; never commit or print its value.
- When `LLM_PROVIDER=gemini`, fail closed if `GEMINI_API_KEY` is missing or the Gemini request fails.
- Keep fake-provider behavior available for local scaffold/testing when explicitly configured.

## Not implemented here yet
- Full Main LLM loop orchestration.
- STT or audio transcription.
- SpatialReal or ElevenLabs avatar/TTS integration.
- Final report generation.
- Direct raw media or raw token handling.

## Tests
Run AI engine contract tests after changes:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.contract.test_ai_engine_contract -v
```
