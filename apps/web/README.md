# apps/web

Minimal GilJob v2 browser surface for the Realtime-first interview room, with optional LiveKit/AvatarKit compatibility surfaces.

Current scope:
- serves production-style interview routes, `/app.js`, `/styles.css`, and the allowed SDK vendor path `/vendor/@spatialwalk/avatarkit/dist/*`;
- calls `/api/sessions` through Caddy to create a candidate session;
- requests OpenAI Realtime browser metadata only through `/api/interviews/{id}/realtime/session`, then sends SDP to `/api/interviews/{id}/realtime/call` for server-side provider attach;
- starts the Realtime-primary room without requiring `livekit.publicUrl`, `candidateToken`, or AvatarKit RTC readiness;
- keeps LiveKit candidate room join legacy-only; the default Realtime/MMM/SDK path must not require LiveKit readiness;
- forwards bounded transcript/prosody/vision readiness events through `/api/interviews/...` sideband routes before ordinary next Realtime responses;
- consumes API-brokered SpatialReal SDK Mode metadata only after the primary transport starts, and keeps Avatar disabled/deferred unless canonical `/avatar/session` returns ready SDK metadata;
- reads SDK gating only from safe sibling `avatarSdkMode`/`sdkMode` metadata and reads token-bearing `client.spatialrealSdk` only after that gate is accepted;
- keeps raw session/report/LiveKit tokens, Realtime client secrets, SDP bodies, and avatar session tokens out of visible UI/logs.

Actual SDK activation contract:
- Ready SDK metadata uses API-owned `client.spatialrealSdk` with browser-approved `appId`, short-lived `sessionToken`, `avatarId`, and `audioFormat: { encoding: "pcm16", channelCount: 1, sampleRateHz: 16000 }`; it must not include LiveKit `token`, `url`, or `roomName` fields.
- The web room must dynamically import `@spatialwalk/avatarkit` only after ready metadata, call `AvatarSDK.initialize`, `AvatarSDK.setSessionToken`, `AvatarManager.shared.load`, create `new AvatarView`, mute SDK playback with `controller.setVolume(0)` or fail closed, feed PCM16 chunks with `controller.send(pcm, false)`, and send one end marker on Realtime `response.done`.
- Safe blocked reasons include `sdk_flag_disabled`, `spatialreal_config_missing`, `sdk_mode_blocked_missing_vendor_asset`, `sdk_mode_blocked_wasm_mime`, `sdk_mode_blocked_dynamic_import`, `sdk_mode_blocked_double_audio_or_mute`, `sdk_mode_blocked_pcm_feed_setup_failed`, and `sdk_mode_blocked_pcm_send_failed`. None of these may bypass `full_mmm_ready`.

Static vendor contract:
- `@spatialwalk/avatarkit` is the only allowed browser SDK vendor prefix; legacy `livekit-client` and `@spatialwalk/avatarkit-rtc` bundles must stay unserved on the default path.
- The import map may point at `/vendor/@spatialwalk/avatarkit/dist/index.js` only for deferred SDK Mode Web metadata; it must not imply avatar readiness or expose provider secrets.
- Runtime/build checks should run `npm --prefix apps/web ci` before archive-style verification when `node_modules` is absent, because the allowed SDK vendor path is copied from the installed package rather than committed source.
- The static server must return JavaScript assets as `text/javascript` and WASM assets as `application/wasm`; failing MIME checks are deployment blockers, not reasons to re-enable LiveKit RTC.

Stable default: `SPATIALREAL_SDK_MODE_WEB_ENABLED=false`. Realtime remains the single audible interviewer path, SpatialReal SDK receives only a muted/silent PCM16 copy after ready metadata and trusted audio unlock, and no production lip-sync claim is made until kiostation browser QA records a verified SDK outcome. SDK Mode requires API metadata with `mode: "spatialreal-sdk-mode-web"`, `transport: "spatialreal-sdk-websocket"`, `livekitRequired: false`, and no provider secrets or raw media exposure; otherwise the UI remains honest disabled/deferred.

Out of scope for this slice: CV/job parsing, production-grade Main LLM orchestration, final report generation, production domain/TLS, direct provider-key ownership in the browser, and unverified production SpatialReal lip-sync claims.

Follow:
- docs/implementation-plan.md
- docs/decisions/0001-state-stack.md
- docs/decisions/0002-ingress-stack.md
- docs/decisions/0003-realtime-voice-flow.md
