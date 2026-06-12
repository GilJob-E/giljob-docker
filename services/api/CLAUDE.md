# Claude Notes for services/api

Read the local `AGENTS.md` first.

Claude reminders:
- Preserve hash-only storage and never print raw token values.
- Keep `LIVEKIT_INTERNAL_URL` server-side and `LIVEKIT_PUBLIC_URL` browser-facing.
- Keep OpenAI Realtime provider keys server-only; return only ephemeral client-secret metadata and keep MMM readiness gating intact.
- Run API/token contract tests after edits.
