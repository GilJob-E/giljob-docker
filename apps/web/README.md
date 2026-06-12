# apps/web

Minimal GilJob v2 browser surface for the Realtime-first interview room, with optional LiveKit/AvatarKit compatibility surfaces.

Current scope:
- serves production-style interview routes, `/app.js`, `/styles.css`, and the vendored browser bundles;
- calls `/api/sessions` through Caddy to create a candidate session;
- requests OpenAI Realtime browser metadata only through `/api/interviews/{id}/realtime/session`, then sends SDP to `/api/interviews/{id}/realtime/call` for server-side provider attach;
- starts the Realtime-primary room without requiring `livekit.publicUrl`, `candidateToken`, or AvatarKit RTC readiness;
- keeps LiveKit candidate room join as a compatibility fallback only when Realtime is not marked primary;
- forwards bounded transcript/prosody/vision readiness events through `/api/interviews/...` sideband routes before ordinary next Realtime responses;
- consumes API-brokered AvatarKit session metadata only after the primary transport starts, and keeps Avatar disabled/deferred unless explicit non-LiveKit SDK Mode metadata is enabled;
- reads the experimental avatar audio bridge flag only from safe sibling metadata (`activeSession.realtimeAvatarBridge` and avatar-session `bridge.browserAudioBridgeEnabled`), not from token-bearing `client` metadata;
- keeps raw session/report/LiveKit tokens, Realtime client secrets, SDP bodies, and avatar session tokens out of visible UI/logs.

Stable defaults: `SPATIALREAL_BROWSER_AUDIO_BRIDGE_ENABLED=false` and `SPATIALREAL_NON_LIVEKIT_SDK_MODE_ENABLED` absent/false. Realtime remains audible, Avatar RTC media stays muted/separate, Avatar startup is deferred until after the primary transport, and no production lip-sync claim is made. If the browser-audio flag is explicitly enabled, the browser may run the experimental `AvatarPlayer.publishAudio(track)` probe with an OpenAI Realtime remote audio track and report only redacted `avatar_audio_bridge_*` statuses until kiostation QA records `bridge_verified`, `bridge_not_supported`, or `blocked`. Non-LiveKit SDK Mode also requires API metadata with `mode: "spatialreal-non-livekit-sdk-mode"`, `transport: "direct-sdk"`, `livekitRequired: false`, and no provider secrets or raw media exposure; otherwise the UI must remain honest disabled/deferred.

Out of scope for this slice: CV/job parsing, production-grade Main LLM orchestration, final report generation, production domain/TLS, direct provider-key ownership in the browser, and unverified production SpatialReal lip-sync claims.

Follow:
- docs/implementation-plan.md
- docs/decisions/0001-state-stack.md
- docs/decisions/0002-ingress-stack.md
- docs/decisions/0003-realtime-voice-flow.md
