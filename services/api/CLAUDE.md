# Claude Notes for services/api

Read the local `AGENTS.md` first.

Claude reminders:
- Preserve hash-only storage and never print raw token values.
- Keep `LIVEKIT_INTERNAL_URL` server-side and `LIVEKIT_PUBLIC_URL` browser-facing.
- Keep OpenAI Realtime provider keys server-only; return only ephemeral client-secret metadata and keep MMM readiness gating intact.
- Keep Realtime STT/vision sideband internal-only: API may forward transcript text and low-resolution vision samples to analysis-engine, but public responses, logs, and durable JSONL stay redacted.
- Run API/token contract tests after edits.
