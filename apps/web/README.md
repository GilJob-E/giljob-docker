# apps/web

Minimal GilJob v2 browser surface for the self-hosted LiveKit room and Realtime interview slice.

Current scope:
- serves production-style interview routes, `/app.js`, `/styles.css`, and the vendored `livekit-client` browser bundle;
- calls `/api/sessions` through Caddy to create a candidate session;
- uses the returned `livekit.publicUrl`/`candidateToken` to join and leave the candidate room;
- requests OpenAI Realtime browser metadata only through `/api/interviews/{id}/realtime/session`, then attaches SDP with the ephemeral secret;
- forwards bounded transcript/prosody/vision readiness events through `/api/interviews/...` sideband routes before ordinary next Realtime responses;
- consumes API-brokered AvatarKit RTC viewer/session metadata for the SpatialReal renderer shell;
- keeps raw session/report/LiveKit tokens, Realtime client secrets, SDP bodies, and avatar session tokens out of visible UI/logs.

Out of scope for this slice: CV/job parsing, production-grade Main LLM orchestration, final report generation, production domain/TLS, and direct provider-key ownership in the browser.

Follow:
- docs/implementation-plan.md
- docs/decisions/0001-state-stack.md
- docs/decisions/0002-ingress-stack.md
- docs/decisions/0003-realtime-voice-flow.md
