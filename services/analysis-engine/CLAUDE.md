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
- Product-path objective lanes live in the `GET /analysis/signals` payload
  (`records` + `turnHandoff.{speech,visual,nonverbal,prompt_block}`), wrapping GilJobE.
  `/realtime/turn-results` returns only a candidate-safe 880-char fragment (a lossy
  projection the API feeds the consumer LLM), not the rich lanes.
- RNAS (`_EventOnlyRealtimeTurns`) is dormant under pin `f817f81`: GilJobE owns
  `POST /realtime/turn-events`, so `turn-results` falls back to the turnHandoff fragment
  (`schemaVersion: …turn-handoff-fragment.v2`). Don't expect `visionSignals`/`prosodySignals`
  from turn-results; read `turnHandoff` instead.
- Verifying the product path end-to-end: see `qa/CLAUDE.md` (the `productpath_signals.mjs`
  harness, lane read-out structure, hot-patch deploy, and current uncommitted giljobe patches).
