# Claude Notes for apps/web

Read the local `AGENTS.md` first.

Claude reminders:
- Keep the room page light, non-scrolling, and free of prejoin controls.
- Do not cover the interviewer tile when opening context; use the right sidebar pattern.
- Preserve manual answer button semantics and token redaction.
- Preserve Realtime ephemeral-secret handling: no standard provider key, no client-secret/SDP logging, and ordinary responses gated on `full_mmm_ready`.
- Run `node --check apps/web/static/app.js` and the web contract tests for UI changes.
