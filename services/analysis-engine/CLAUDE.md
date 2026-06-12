# Claude Notes for services/analysis-engine

Read the local `AGENTS.md` first.

Claude reminders:
- This container runs the local `server.py` entrypoint, which builds GilJobE's own HTTP app and adds
  GilJob-v2 Realtime-native MMM/RNAS routes: `/realtime/turn-events` and `/realtime/turn-results`.
- Owns the priority-1 answer → analysis-engine MMM/RNAS → API `response.create` → OpenAI Realtime output boundary. Legacy `/subscriber/start|stop` and `/signals` remain compatibility surfaces only.
- Keep token handling redacted; never log raw LiveKit tokens/JWTs/API secrets, SDP, media, or transcripts. Internal Realtime sideband may consume STT text and low-resolution vision samples only to produce structured candidate-safe results.
- Ordinary OpenAI Realtime RNAS does not call `/subscriber/start`; `ANALYSIS_ENGINE_ENABLE_SUBSCRIBER` is a legacy scaffold flag and is not consulted.
- Objective grounding lanes (vision/prosody) are optional-by-design: extras + baked models +
  `GILJOBE_VISION`/`GILJOBE_PROSODY` env. Never gate startup or health on them.
- Local Whisper is not an STT path for this service.
