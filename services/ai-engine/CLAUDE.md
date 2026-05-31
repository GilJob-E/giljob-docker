# Claude Notes for services/ai-engine

Read the local `AGENTS.md` first.

Claude reminders:
- Treat this as a Gemini-backed next-question provider boundary, not the full interview brain.
- Never print `GEMINI_API_KEY` or prompts containing sensitive candidate data.
- Preserve fail-closed behavior when `LLM_PROVIDER=gemini` lacks a key.
