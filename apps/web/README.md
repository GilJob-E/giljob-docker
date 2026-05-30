# apps/web

Minimal GilJob v2 browser surface for the local self-hosted LiveKit room slice.

Current scope:
- serves `/`, `/app.js`, `/styles.css`, and the vendored `livekit-client` browser bundle;
- calls `/api/sessions` through Caddy to create a candidate session;
- uses the returned `livekit.publicUrl`/`candidateToken` to join and leave a room;
- keeps raw session/report/LiveKit tokens out of the visible UI/log.

Out of scope for this slice: CV/job parsing, real Main LLM loop, SpatialReal/ElevenLabs avatar or TTS, multimodal analysis, final reports, production domain/TLS.

Follow:
- docs/implementation-plan.md
- docs/decisions/0001-state-stack.md
- docs/decisions/0002-ingress-stack.md
