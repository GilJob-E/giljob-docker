# Test Spec — GilJob v2 Execution Preparation

## Scope

This test spec validates the planning and next implementation path for `~/GilJob_v2`. It is not yet a full code test suite; it defines required checks for the next implementation artifacts.

## Test principles

1. Every milestone must have observable evidence.
2. Security/token/state contracts are tested before real AI integrations.
3. Public route tests and container-internal tests stay separate.
4. Existing `~/GilJob` must remain untouched.

## M0 planning/scaffold tests

### T0.1 Source docs copied and checksummed

- Given local docs exist:
  - `docs/giljob-v0.3.1-final-spec.md`
  - `docs/giljob-v0.3.1-high3-validation.md`
- When they are copied to `~/GilJob_v2/docs/`
- Then checksums are recorded in `docs/source-manifest.md`.

### T0.2 Legacy folder untouched

- Given `/home/hoddukzoa/GilJob` exists
- When v2 scaffold tasks run
- Then no files under `/home/hoddukzoa/GilJob` are modified.

### T0.3 Decision gates exist

- `docs/decisions/0001-state-stack.md` exists and has status.
- `docs/decisions/0002-ingress-stack.md` exists and has status.

## Gate A — state/event stack tests

### T1.1 Token hash persistence

- Session token hash is stored using session secret path.
- Report token hash is stored using report secret path.
- Raw access tokens are not persisted.

### T1.2 TTL contract

- Session token TTL is `7200` seconds.
- Report token TTL is `2592000` seconds.

### T1.3 CAS transition semantics

- Valid transition with current `state_version` succeeds and increments version.
- Same transition replay is idempotent or safely rejected per ADR.
- Stale `state_version` update fails.
- Invalid transition fails.

### T1.4 Redis deferral equivalence, if chosen

- If Redis is deferred, in-process/event-log adapter emits the same envelope shape.
- Later Redis migration boundary is documented.
- Fake 3-turn loop remains testable without public exposure.

### T1.5 Redis-deferral equivalence detail, if chosen

If Redis is deferred, the ADR and tests must specify:

- event envelope fields,
- ordering guarantee or explicit lack thereof,
- idempotency/dedupe key,
- durability limit and acceptable data loss for MVP fake loop,
- which Redis maxlen/TTL/retry/DLQ/backpressure rules are deferred,
- migration trigger for replacing the adapter with Redis.


## Gate B — ingress tests

### T2.1 Public health routes

- `GET /healthz` returns success through public ingress.
- `GET /readyz` returns `404` through public ingress; API `/readyz` succeeds only on container-internal path.
- `/api/healthz` is not treated as canonical smoke endpoint.

### T2.2 Internal route block

- Public `GET /api/internal/*` is blocked by ingress.
- Direct API internal route without `X-GilJob-Internal-Token` or HMAC is rejected.
- Valid internal auth succeeds only on internal network path.

### T2.3 LiveKit/TURN smoke plan

- Browser can join from primary network.
- Browser can join from phone hotspot or external network.
- LiveKit logs show join/publish/subscription.
- coturn logs show allocation when TURN fallback is exercised.

### T2.4 External-network evidence

Gate B is not accepted with local logs alone. Before demo readiness, collect:

- browser join from normal Wi-Fi/network,
- browser join from phone hotspot or another external network,
- LiveKit stats/log evidence for publish/subscribe,
- coturn allocation evidence when relay fallback is exercised.


## Docker smoke tests

Required script shape:

```bash
POSTGRES_PASSWORD=... docker compose -f infra/docker-compose.yml up -d --build
POSTGRES_PASSWORD=... docker compose -f infra/docker-compose.yml ps
curl -fsS https://${PUBLIC_DOMAIN}/healthz
test "$(curl -sS -o /dev/null -w "%{http_code}" https://${PUBLIC_DOMAIN}/readyz)" = "404"
POSTGRES_PASSWORD=... docker compose -f infra/docker-compose.yml exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=2).read()"
POSTGRES_PASSWORD=... docker compose -f infra/docker-compose.yml exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz', timeout=2).read()"
POSTGRES_PASSWORD=... docker compose -f infra/docker-compose.yml exec -T ai-engine python -c "import urllib.request; urllib.request.urlopen('http://localhost:8100/healthz', timeout=2).read()"
POSTGRES_PASSWORD=... docker compose -f infra/docker-compose.yml exec -T agent1 python -c "import urllib.request; urllib.request.urlopen('http://localhost:8010/healthz', timeout=2).read()"
# DB/event stack checks depend on Gate A
POSTGRES_PASSWORD=... LIVEKIT_API_KEY=... LIVEKIT_API_SECRET=... TURN_DOMAIN=... TURN_REALM=... TURN_STATIC_AUTH_SECRET=... docker compose -f infra/docker-compose.yml -f infra/docker-compose.media.yml config
POSTGRES_PASSWORD=... LIVEKIT_API_KEY=... LIVEKIT_API_SECRET=... TURN_DOMAIN=... TURN_REALM=... TURN_STATIC_AUTH_SECRET=... docker compose -f infra/docker-compose.yml -f infra/docker-compose.media.yml logs --tail=100 livekit
POSTGRES_PASSWORD=... LIVEKIT_API_KEY=... LIVEKIT_API_SECRET=... TURN_DOMAIN=... TURN_REALM=... TURN_STATIC_AUTH_SECRET=... docker compose -f infra/docker-compose.yml -f infra/docker-compose.media.yml logs --tail=100 coturn
```

## E2E demo acceptance

### T4.1 Fake 3-turn loop

- Frontend starts session.
- Browser mic/camera permission succeeds.
- LiveKit room join succeeds.
- Engine subscribes to candidate track.
- Fake STT final event appears.
- Fake Agent1 signal appears.
- Fake Agent2 follow-up appears.
- Candidate completes 3 answers.
- Report page displays.
- Logs show each step.

### T4.2 Real adapter progression

After fake loop passes:

- STT provider adapter replaces fake STT.
- Agent2 LLM adapter replaces fake Agent2.
- Agent1/Multi_Modal_Module path can add a nonverbal signal or explicit fallback.

## AI boundary/fallback tests

- Agent1 emits signal/evaluation or an explicit `agent1_fallback` event.
- Agent2 consumes transcript plus Agent1 signal/fallback marker.
- UI/logs distinguish real multimodal signal from fallback.
- No path silently skips Agent1 while pretending multimodal context was used.


## Observability evidence

Each milestone must produce:

- command used,
- pass/fail result,
- relevant logs,
- known gaps,
- next action.

## Exit criteria for implementation handoff

- PRD and test spec exist.
- Architect review approves.
- Critic review approves.
- Durable handoff record marks `ralplan_consensus_gate.complete: true`.
