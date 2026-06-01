# Claude Notes for services/stt-whisper

Read the local `AGENTS.md` first.

Claude reminders:
- This service is the local faster-whisper STT boundary only.
- Preserve host GPU `1` assignment in Docker Compose unless a human explicitly changes the deployment plan.
- Never print raw transcript text, raw audio, tokens, or secret env values in logs or examples.
