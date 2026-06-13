# Claude Notes for services/hashimoto

Read the local `AGENTS.md` first.

Claude reminders:
- Treat this as a reference-only interviewer strategy provider, not the interview brain. The AI engine (Agent2) generates the actual question; hashimoto only updates a strategy package that Agent2 may consult.
- Never print `GEMINI_API_KEY` or prompts containing sensitive candidate data (resume text, transcripts).
- Keep one engine instance per `session_id`; never let one session read or mutate another session's state.
- Deduplicate by `(session_id, turn_id)`; do not advance engine state twice for the same turn.
- The `/strategy` pull must be non-blocking and degrade gracefully: if the engine is cold or busy, return `ready=false` rather than blocking the question generator.
- Slot fulfillment scores are internal state only; do not surface them as an evaluation or rubric.
