# Claude Notes for services/ai-engine

Read the local `AGENTS.md` first.

Claude reminders:
- Treat this as a Gemini legacy/non-primary next-question/TTS fallback and SpatialReal post-TTS provider boundary, not the full interview brain or OpenAI Realtime session broker.
- Never print `GEMINI_API_KEY` or prompts containing sensitive candidate data.
- Preserve fail-closed behavior when `LLM_PROVIDER=gemini` lacks a key.
- Do not move OpenAI Realtime ephemeral-session brokering into this service; the API owns that browser-facing contract.
