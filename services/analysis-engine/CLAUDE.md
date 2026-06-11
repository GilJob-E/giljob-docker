# Claude Notes for services/analysis-engine

Read the local `AGENTS.md` first.

Claude reminders:
- This container runs GilJobE's own entrypoint `python -m giljobe.server`; do not add a local wrapper.
  Change behaviour by bumping the pinned ref in `requirements.txt`, not by forking logic here.
- Owns the GilJobE-backed STT + non-verbal analysis boundary and its HTTP contract
  (`/subscriber/start|stop`, `/signals`, `/healthz`, `/readyz`).
- Keep token handling redacted; never log raw LiveKit tokens/JWTs/API secrets, media, or transcripts.
- The subscriber starts per turn via `/subscriber/start`; `ANALYSIS_ENGINE_ENABLE_SUBSCRIBER` is a
  legacy scaffold flag and is not consulted.
- Local Whisper is not an STT path for this service.
