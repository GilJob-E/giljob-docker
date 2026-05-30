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


## Local self-hosted media room

- LiveKit is a direct browser media room, not a frontend-backend API proxy.
- API/container address must use `LIVEKIT_INTERNAL_URL` (for example `ws://livekit:7880`).
- Browser address must use `LIVEKIT_PUBLIC_URL` (for example `ws://127.0.0.1:7880`) and is returned as both `livekit.publicUrl` and backward-compatible `livekit.url`.
- Direct local media ports to verify: `7880/tcp`, `7881/tcp`, `50000-50100/udp`, plus coturn `3478`/`5349` when relay is used. Same-host browser smoke uses `LIVEKIT_NODE_IP=127.0.0.1`; external browser smoke must set it to the reachable host address.
- `./scripts/smoke.sh config` must pass base config, prove media config fails without `LIVEKIT_PUBLIC_URL`, and pass media config with explicit local values.
- `./scripts/smoke.sh media-up` must start `postgres`, `api`, `web`, `livekit`, and `coturn`; verify API/web health; verify `/sessions` returns an issued LiveKit token; and verify LiveKit `7880` responds.

- `./scripts/smoke.sh browser-join` should pass on kiostation when Chrome is available; it proves the browser UI creates a session, connects to LiveKit, leaves the room, and does not expose raw tokens in visible text.
