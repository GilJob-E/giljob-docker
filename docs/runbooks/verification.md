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
- With LiveKit env configured on the API service, `POST /api/sessions` must return `livekit.tokenStatus=issued`, `livekit.url`, and a JWT-shaped `livekit.candidateToken` while server-side session records remain hash-only.

## Remote-only final checks

Run final verification from the leader-approved checkout on `kiostation`; do not run these checks from a worker Mac/worktree when the lane is marked remote-only. Minimum final command set:

```bash
ssh hoddukzoa@kiostation 'cd /home/hoddukzoa/GilJob_v2 && node --check apps/web/static/app.js'
ssh hoddukzoa@kiostation 'cd /home/hoddukzoa/GilJob_v2 && PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile services/api/server.py services/ai-engine/server.py services/analysis-engine/server.py'
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

## Interviewer voice and avatar provider contract

- `VOICE_PROVIDER=fake` must remain the keyless smoke path.
- Non-Realtime LLM/TTS provider fallback must stay removed from env, compose, supported docs, and active AI-engine code.
- `VOICE_PROVIDER=elevenlabs` must require server-side `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID`; raw keys and upstream error bodies must never be returned.
- `TTS_PROVIDER_FAILURE_FALLBACK=fake` is allowed only as an explicit local-demo fail-open setting.
- `AVATAR_PROVIDER=disabled` must return a safe disabled response without a provider `sessionToken`.
- `AVATAR_PROVIDER=spatialreal` must require server-side `SPATIALREAL_API_KEY`, `SPATIALREAL_APP_ID`, and `SPATIALREAL_AVATAR_ID`; browser responses may include only short-lived client session metadata.
- `AVATAR_PROVIDER_FAILURE_FALLBACK=disabled` is allowed only as an explicit local-demo fail-open setting.
- `SPATIALREAL_RTC_EGRESS_ENABLED=false` is the default; enabling it requires a public LiveKit URL reachable from SpatialReal cloud, not a loopback or Docker-only URL. Passing this egress check does not prove OpenAI Realtime audio lip-sync; that requires separate bridge evidence.
- Public ingress must not expose direct `/tts/*`, `/avatar/*`, `/ai/tts/*`, `/ai/avatar/*`, or broad `/ai/*` provider routes. Browser traffic must use the `/api/interviews/.../tts` and `/api/interviews/.../avatar/session` broker routes.

Remote verification command shape from a synced checkout on `kiostation`:

```bash
ssh hoddukzoa@kiostation 'cd /home/hoddukzoa/GilJob_v2 && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.contract.test_ai_engine_contract -v'
```


## Local self-hosted media room

- LiveKit is a direct browser media room, not a frontend-backend API proxy.
- API/container address must use `LIVEKIT_INTERNAL_URL` (for example `ws://livekit:7880`).
- Browser address must use `LIVEKIT_PUBLIC_URL` (for example `ws://127.0.0.1:7880`) and is returned as both `livekit.publicUrl` and backward-compatible `livekit.url`.
- Direct local media ports to verify: `7880/tcp`, `7881/tcp`, `50000-50100/udp`, plus coturn `3478`/`5349` when relay is used. Same-host browser smoke uses `LIVEKIT_NODE_IP=127.0.0.1`; external browser smoke must set it to the reachable host address.
- `./scripts/smoke.sh config` must pass base config, prove media config fails without `LIVEKIT_PUBLIC_URL`, and pass media config with explicit local values.
- `./scripts/smoke.sh media-up` must start `postgres`, `api`, `web`, `livekit`, and `coturn`; verify API/web health; verify `/sessions` returns an issued LiveKit token; and verify LiveKit `7880` responds.

- `./scripts/smoke.sh browser-join` should pass on kiostation when Chrome is available; it proves the browser UI creates a session, connects to LiveKit, leaves the room, and does not expose raw tokens in visible text.
- `./scripts/smoke.sh realtime-ready` should pass before claiming Realtime branch readiness; with `REQUIRE_REALTIME_LIVE=1`, provider/network failures are runtime blockers with redacted evidence, not a reason to expose direct provider secrets.
