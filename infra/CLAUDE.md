# Claude Notes for infra

Read the local `AGENTS.md` first.

Claude reminders:
- Preserve single-server, multi-container deployment boundaries.
- Keep LiveKit internal/public URL split and direct media ports clear.
- Keep provider routes internal; browser-facing Realtime/TTS/avatar traffic must remain API-brokered.
- Do not print `.env` or secret values while debugging Compose.
