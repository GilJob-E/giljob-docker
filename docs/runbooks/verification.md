# Verification Runbook

## Source/provenance

- Check `docs/source-manifest.md`.
- Do not use `/home/hoddukzoa/GilJob` as a source for v2 unless explicitly approved.

## State/security

- Test session token TTL = 7200 seconds.
- Test report token TTL = 2592000 seconds.
- Test raw tokens are not persisted.
- Test stale `state_version` CAS update fails.
- Test invalid transition fails.

## Ingress

- Public `/api/internal/*` must be blocked at ingress.
- API internal middleware must reject missing internal token/HMAC.
- Public `/healthz` must pass.
- Public `/readyz` must return 404; container-internal API `/readyz` must pass.
- Public `/api/internal/*` must be blocked at ingress before API proxying.

- Test `docker-compose.media.yml` fails without LiveKit URL/API/TURN secret env vars and passes once placeholders are explicitly set.
- With LiveKit env absent/blank, default `/api/sessions` must still support the Realtime/MMM path and must not require or return LiveKit token metadata as a prerequisite. With optional media env configured on the API service, `POST /api/sessions` may return `livekit.tokenStatus=issued`, `livekit.url`, and a JWT-shaped `livekit.candidateToken` while server-side session records remain hash-only.

## Remote-only final checks

Run final verification from the leader-approved checkout on `kiostation`; do not run these checks from a worker Mac/worktree when the lane is marked remote-only. Minimum final command set:

```bash
ssh hoddukzoa@kiostation 'cd /home/hoddukzoa/GilJob_v2 && node --check apps/web/static/app.js'
ssh hoddukzoa@kiostation 'cd /home/hoddukzoa/GilJob_v2 && PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile services/api/server.py services/analysis-engine/server.py'
ssh hoddukzoa@kiostation 'cd /home/hoddukzoa/GilJob_v2 && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -v'
ssh hoddukzoa@kiostation 'cd /home/hoddukzoa/GilJob_v2 && git diff --check'
```

The same command strings are part of the docs contract so worker lanes and leader integration use one verification vocabulary.

### Realtime smoke and latency evidence

Collect Realtime readiness and latency evidence only from the leader-approved `kiostation` checkout after the code slice is synced and the runtime has been restarted with that checkout. Local worker worktrees may run static checks, but they must not be used as final runtime evidence.

Minimum remote command shape:

```bash
ssh hoddukzoa@kiostation 'cd /home/hoddukzoa/GilJob_v2 && ./scripts/smoke.sh realtime-ready'
ssh hoddukzoa@kiostation 'cd /home/hoddukzoa/GilJob_v2 && REQUIRE_REALTIME_LIVE=1 ./scripts/smoke.sh realtime-ready'
```

Record only redacted summary fields from `scripts/realtime-smoke-readiness.py`:

- `primaryOk`, `liveReady`, `staticReadiness`, `sessionRoutes`, `realtimeSessionBroker`, `realtimeCallBoundary`, and `fullMmmGate` status.
- latency/span labels such as `realtime.first_audio`, session broker duration, SDP attach duration, and MMM gate duration when the harness/runtime emits them. Durations are allowed; raw SDP, client secrets, JWTs, transcript text, audio, video frames, and provider error bodies are not.
- runtime blockers exactly as categories, for example `realtime_not_configured`, `request_failed`, `realtime.call broker disabled/prepared`, `roomBlocker`, or `appBlocker`. These are evidence categories, not permission to add a non-Realtime fallback.

Do not claim live Realtime readiness from a local Mac/worktree. If `REQUIRE_REALTIME_LIVE=1` fails because provider credentials, DNS, TLS, or network reachability are missing, report it as a kiostation runtime blocker with the redacted category above.

## SpatialReal SDK activation contract

Contract tests must cover the actual SDK activation path, not only deferred metadata:

- Enabled/configured `POST /api/interviews/{id}/avatar/session` returns `ready=true`, `status=ready`, `sdkMode.mode=spatialreal-sdk-mode-web`, `sdkMode.transport=spatialreal-sdk-websocket`, `livekitRequired=false`, and `client.spatialrealSdk` with browser-approved `appId`, short-lived `sessionToken`, `avatarId`, and PCM16 mono 16 kHz `audioFormat`.
- SDK success responses must not include LiveKit viewer-token fields such as `token`, `url`, `roomName`, `candidateToken`, or `avatarClientToken`.
- Browser activation must dynamically import `@spatialwalk/avatarkit`, call `AvatarSDK.initialize`, `AvatarSDK.setSessionToken`, `AvatarManager.shared.load`, create `new AvatarView`, set SDK volume to silent or block, feed `controller.send(PCM16,false)`, and emit exactly one safe end marker on Realtime `response.done`.
- Missing config, missing vendor assets, bad WASM MIME, dynamic import failure, mute failure, or PCM feed failure must become safe blocked/deferred reasons and must not mark avatar active.
- SDK enabled/ready status never bypasses exact-turn `full_mmm_ready`; ordinary follow-up `response.create` remains API-owned and gated.

## Web static vendor/WASM/MIME contract

Before blaming Realtime or avatar code for a browser startup failure, verify the static asset contract from a checkout with web dependencies installed:

```bash
npm --prefix apps/web ci
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.contract.test_web_static_contract -v
node --check apps/web/static/app.js
```

Expected result: the room import map may reference the deferred base SDK path `/vendor/@spatialwalk/avatarkit/dist/index.js`, but the only served SDK vendor prefix is `/vendor/@spatialwalk/avatarkit/dist/`. Legacy `/vendor/livekit-client/...` and `/vendor/@spatialwalk/avatarkit-rtc/...` stay 404 on the default path. Allowed SDK JavaScript/MJS assets must be served as `text/javascript`, and allowed SDK `.wasm` assets must be served as `application/wasm`. Package-root reads under `/vendor/` must stay rejected.

Archive/runtime note: `git archive HEAD` does not include `apps/web/node_modules`, so remote verification that exercises allowed vendor assets must either run `npm --prefix apps/web ci` in the synced checkout or use a runtime tree where those dependencies are already installed. Missing package files should be reported as a vendor install/runtime packaging blocker, not as proof that LiveKit RTC is required.

## SpatialReal non-LiveKit spike evidence

Current docs/infra outcome: `sdk_mode_deferred`. The worker checkout declares `@spatialwalk/avatarkit` but lacks installed package files, so SDK Mode Web exports/method names and audio-feed lifecycle were not locally verifiable. Future SDK Mode verification must prove package/API availability and a muted PCM16 mono audio feed without LiveKit before changing avatar status from disabled/deferred. Valid outcomes are `sdk_mode_verified`, `sdk_mode_not_supported_current_version`, `sdk_mode_blocked_by_audio_feed`, or `sdk_mode_deferred`.

## Interviewer voice and avatar provider contract

- Non-Realtime LLM/TTS provider fallback must stay removed from env, compose, supported docs, and default runtime services.
- `SPATIALREAL_BROWSER_AUDIO_BRIDGE_ENABLED=false` is the stable default. If explicitly enabled, it exposes API-owned metadata only and still requires kiostation browser evidence before any avatar lip-sync claim.
- SpatialReal/avatar provider credentials and legacy RTC egress variables are not part of the default runtime env. Reintroducing them requires a separate compatibility-gated change and must not make LiveKit or avatar egress a Realtime/MMM prerequisite.
- Public ingress must not expose direct `/tts/*`, `/avatar/*`, `/ai/tts/*`, `/ai/avatar/*`, or broad `/ai/*` provider routes. Legacy TTS/avatar broker routes are disabled/deferred unless explicitly verified as API-owned compatibility surfaces; default Realtime/MMM must not depend on ai-engine.

Remote verification command shape from a synced checkout on `kiostation` (default rebuild/restart scope: `api web analysis-engine caddy`):

```bash
ssh hoddukzoa@kiostation 'cd /home/hoddukzoa/GilJob_v2 && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -v'
```


## Default Realtime/MMM and optional local media room

- The default OpenAI Realtime + MMM path must not require LiveKit config or a LiveKit join. LiveKit is a direct browser media room only when the optional/legacy media overlay is enabled, not a frontend-backend API proxy.
- API/container address must use `LIVEKIT_INTERNAL_URL` (for example `ws://livekit:7880`).
- Browser address must use `LIVEKIT_PUBLIC_URL` (for example `ws://127.0.0.1:7880`) and is returned as both `livekit.publicUrl` and backward-compatible `livekit.url`.
- Direct local media ports to verify: `7880/tcp`, `7881/tcp`, `50000-50100/udp`, plus coturn `3478`/`5349` when relay is used. Same-host browser smoke uses `LIVEKIT_NODE_IP=127.0.0.1`; external browser smoke must set it to the reachable host address.
- `./scripts/smoke.sh config` must pass base config, prove media config fails without `LIVEKIT_PUBLIC_URL`, and pass media config with explicit local values.
- `./scripts/smoke.sh media-up` must start `postgres`, `api`, `web`, `livekit`, and `coturn`; verify API/web health; verify `/sessions` returns an issued LiveKit token; and verify LiveKit `7880` responds.

- `./scripts/smoke.sh browser-join` should pass on kiostation when Chrome is available; it proves the browser UI creates a session, connects to LiveKit, leaves the room, and does not expose raw tokens in visible text.
- `./scripts/smoke.sh realtime-ready` should pass before claiming Realtime branch readiness; with `REQUIRE_REALTIME_LIVE=1`, provider/network failures are runtime blockers with redacted evidence, not a reason to expose direct provider secrets.
