# apps/web

Minimal GilJob v2 browser surface for the self-hosted LiveKit room and Realtime interview slice.

Current scope:
- serves production-style interview routes, `/app.js`, `/styles.css`, and the vendored `livekit-client` browser bundle;
- calls `/api/sessions` through Caddy to create a candidate session;
- uses the returned `livekit.publicUrl`/`candidateToken` to join and leave the candidate room;
- requests OpenAI Realtime browser metadata only through `/api/interviews/{id}/realtime/session`, then sends SDP to `/api/interviews/{id}/realtime/call` for server-side provider attach;
- forwards bounded transcript/prosody/vision readiness events through `/api/interviews/...` sideband routes before ordinary next Realtime responses;
- consumes API-brokered AvatarKit RTC viewer/session metadata for the SpatialReal renderer shell;
- reads the experimental avatar audio bridge flag only from safe sibling metadata (`activeSession.realtimeAvatarBridge` and avatar-session `bridge.browserAudioBridgeEnabled`), not from token-bearing `client` metadata;
- keeps raw session/report/LiveKit tokens, Realtime client secrets, SDP bodies, and avatar session tokens out of visible UI/logs.

Stable default: `SPATIALREAL_BROWSER_AUDIO_BRIDGE_ENABLED=false`; Realtime remains audible, Avatar RTC media stays muted/separate, and no production lip-sync claim is made. If the flag is explicitly enabled, the browser may run the experimental `AvatarPlayer.publishAudio(track)` probe with an OpenAI Realtime remote audio track and report only redacted `avatar_audio_bridge_*` statuses until kiostation QA records `bridge_verified`, `bridge_not_supported`, or `blocked`.

Out of scope for this slice: CV/job parsing, production-grade Main LLM orchestration, final report generation, production domain/TLS, direct provider-key ownership in the browser, and unverified production SpatialReal lip-sync claims.

Follow:
- docs/implementation-plan.md
- docs/decisions/0001-state-stack.md
- docs/decisions/0002-ingress-stack.md
- docs/decisions/0003-realtime-voice-flow.md
