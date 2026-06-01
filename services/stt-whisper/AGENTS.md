# services/stt-whisper Agent Contract

This module owns local faster-whisper STT for manual answer turns. Follow the root `AGENTS.md` plus these local rules.

## Current responsibilities
- Warm the faster-whisper model when the room starts, then transcribe candidate answer audio after the manual answer-end button submits raw browser audio.
- Use `Systran/faster-whisper-large-v3` by default through the `faster-whisper` Python package.
- Run on CUDA with Docker Compose reserving host GPU `1`; inside the container use `WHISPER_DEVICE_INDEX=0` for the selected GPU.
- Keep `STT_LANGUAGE=ko` as the default language for the current Korean interview flow.
- Return structured warmup and transcript JSON to the browser/Main LLM boundary.

## Boundaries
- Do not subscribe directly to LiveKit tracks in this service yet.
- Do not implement TTS, SpatialReal/ElevenLabs avatar, Agent1 multimodal analysis, or final report generation here.
- Do not log raw audio, raw transcript text, JWTs, session/report tokens, LiveKit tokens, API keys, or Hugging Face tokens.
- Do not change the GPU assignment away from host GPU `1` without updating infra docs and tests.

## Tests
Run STT and infra contracts after changes:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.contract.test_stt_whisper_contract -v
./scripts/smoke.sh config
```
