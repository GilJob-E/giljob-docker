# Claude Notes for services/analysis-engine

Read the local `AGENTS.md` first.

Claude reminders:
- This container runs the local `server.py` entrypoint, which builds GilJobE's own HTTP app and adds
  only the GilJob-v2 `/realtime/turn-events` MMM sideband ingress route.
- Owns the GilJobE-backed STT + non-verbal analysis boundary and its HTTP contract
  (`/subscriber/start|stop`, `/signals`, `/healthz`, `/readyz`) plus sanitized Realtime MMM ingress.
- Keep token handling redacted; never log raw LiveKit tokens/JWTs/API secrets, SDP, media, or transcripts.
- The subscriber starts per turn via `/subscriber/start`; `ANALYSIS_ENGINE_ENABLE_SUBSCRIBER` is a
  legacy scaffold flag and is not consulted.
- Objective grounding lanes (vision/prosody) are optional-by-design: extras + baked models +
  `GILJOBE_VISION`/`GILJOBE_PROSODY` env. Never gate startup or health on them.
- Local Whisper is not an STT path for this service.
