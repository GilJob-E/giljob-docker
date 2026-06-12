# Local self-hosted LiveKit media room runbook

This slice uses LiveKit as a self-hosted realtime media room, not as a normal
frontend-to-backend API proxy. The browser connects directly to the LiveKit
WebSocket/ICE endpoints returned by the API, while Caddy continues to proxy only
GilJob web/API HTTP traffic.

Official references used for this contract:

- LiveKit browser clients connect with a `Room` plus `wsUrl` and participant token: <https://docs.livekit.io/home/client/connect/>
- LiveKit local self-hosting can run on `ws://localhost:7880` during development: <https://docs.livekit.io/transport/self-hosting/local/>
- LiveKit self-hosted networking requires direct media ports such as API/WebSocket `7880`, ICE/TCP `7881`, and an ICE/UDP range: <https://docs.livekit.io/home/self-hosting/ports-firewall/>

## Current bounded scope

In scope now:

1. `POST /api/sessions` issues a candidate session and, when LiveKit env is configured,
   returns `livekit.publicUrl`, `livekit.roomName`, `livekit.participantIdentity`, and
   a `livekit.candidateToken`.
2. The browser UI at `/` calls `/api/sessions`, then joins/leaves the returned room with
   `livekit-client`.
3. The Docker media overlay starts local `livekit` and `coturn` services on the same host.

Out of scope for this slice:

- CV/job parsing.
- Real Main LLM turn loop.
- SpatialReal/ElevenLabs avatar or TTS.
- Multimodal analysis.
- Final report generation.
- Production domain/TLS hardening.

## Addressing contract

Use two URLs because containers and browsers do not reach LiveKit through the same hostname.

| Env var | Consumer | Example | Notes |
|---|---|---|---|
| `LIVEKIT_INTERNAL_URL` | API/container-side code | `ws://livekit:7880` | Docker service DNS. Not returned to browser. |
| `LIVEKIT_PUBLIC_URL` | Browser LiveKit client | `ws://127.0.0.1:7880` or `ws://kiostation:7880` | Returned as `livekit.publicUrl` and backward-compatible `livekit.url`. |
| `LIVEKIT_URL` | Legacy fallback | empty | Only for old one-URL scaffold development runs; ignored in required/prod media mode. |
| `LIVEKIT_NODE_IP` | LiveKit ICE candidate address | `127.0.0.1` for same-host local smoke | For external browser tests, set this to the host IP/DNS reachable by that browser. |

Media-enabled compose is fail-closed: `infra/docker-compose.media.yml` refuses to render
without explicit `LIVEKIT_PUBLIC_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `TURN_DOMAIN`,
`TURN_REALM`, and `TURN_STATIC_AUTH_SECRET`.

## Direct ports

For the current single-server local overlay, the host must allow:

- `80/tcp` and `443/tcp` for Caddy web/API ingress when Caddy is included.
- `7880/tcp` for LiveKit API/WebSocket signaling.
- `7881/tcp` for LiveKit ICE/TCP fallback.
- `50000-50100/udp` for LiveKit WebRTC ICE/UDP media in this scaffold.
- `3478/udp+tcp` and `5349/tcp` for coturn when relay is used.

The scaffold narrows LiveKit UDP to `50000-50100` for local smoke; production sizing should
be revisited before real users. Local smoke sets `LIVEKIT_NODE_IP=127.0.0.1` so a browser
running on the same host can complete ICE. For another laptop or public network, set
`LIVEKIT_PUBLIC_URL` and `LIVEKIT_NODE_IP` to the server address reachable by that browser
and open the listed ports. SpatialReal RTC egress has a stricter reachability requirement:
`SPATIALREAL_RTC_LIVEKIT_URL` must be reachable from SpatialReal cloud, so loopback values
such as `ws://127.0.0.1:7880` are not valid for cloud-side avatar publishing even when they
work for same-host browser smoke.

## Local media smoke

From `/home/hoddukzoa/GilJob_v2`:

```bash
./scripts/smoke.sh config
./scripts/smoke.sh media-up
./scripts/smoke.sh browser-join
```

When this runbook is executed from an OMX worker lane with remote-only verification, run the
same commands through SSH from the leader-approved checkout instead of the local Mac worktree,
for example:

```bash
ssh hoddukzoa@kiostation 'cd /home/hoddukzoa/GilJob_v2 && ./scripts/smoke.sh config'
ssh hoddukzoa@kiostation 'cd /home/hoddukzoa/GilJob_v2 && ./scripts/smoke.sh media-up'
ssh hoddukzoa@kiostation 'cd /home/hoddukzoa/GilJob_v2 && ./scripts/smoke.sh browser-join'
```

`media-up` starts `postgres`, `api`, `web`, `livekit`, and `coturn`, verifies API/web health,
checks that `/sessions` returns `livekit.tokenStatus=issued` and `livekit.publicUrl`, verifies
LiveKit port `7880` responds, and then tears the stack down unless `KEEP_STACK=1` is set.
`browser-join` also starts Caddy and runs a headless Chrome/Playwright join-and-leave smoke
against the real browser UI.

For a manual browser check through Caddy, run the media stack with Caddy too:

```bash
KEEP_STACK=1 ./scripts/smoke.sh media-up
cd infra
POSTGRES_PASSWORD=giljob-dev-password \
SESSION_TOKEN_HASH_SECRET=giljob-dev-session-secret \
REPORT_TOKEN_HASH_SECRET=giljob-dev-report-secret \
LIVEKIT_PUBLIC_URL=ws://127.0.0.1:7880 \
LIVEKIT_INTERNAL_URL=ws://livekit:7880 \
LIVEKIT_NODE_IP=127.0.0.1 \
LIVEKIT_API_KEY=devkey \
LIVEKIT_API_SECRET=devsecret-with-at-least-32-bytes \
TURN_DOMAIN=turn.localhost \
TURN_REALM=localhost \
TURN_STATIC_AUTH_SECRET=turn-secret-with-at-least-32-bytes \
docker compose -f docker-compose.yml -f docker-compose.media.yml up -d caddy
```

Then open `http://<server>/`, create a session, and join the room. For same-origin API calls,
use the default endpoint `/api/sessions`.

## Secret placeholders

`.env.example` values containing `change-me` or `replace-me-local-only` are local smoke placeholders only. Replace them before any shared, external, or non-local deployment.
