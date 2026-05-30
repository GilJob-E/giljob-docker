# Deep Interview Spec — GilJob v2 Execution-Ready Specification

## Metadata

- Profile: standard
- Context type: brownfield/docs-first
- Final ambiguity: 0.16
- Threshold: 0.20
- Context snapshot: `.omx/context/giljob-v2-docs-interview-20260530T045141Z.md`
- Transcript: `.omx/interviews/giljob-v2-execution-spec-<timestamp>.md`
- Primary docs:
  - `docs/giljob-v0.3.1-final-spec.md`
  - `docs/giljob-v0.3.1-high3-validation.md`
- Remote target: `hoddukzoa@kiostation:/home/hoddukzoa/GilJob_v2`

## Intent

Create an execution-ready specification for **GilJob v2** from the local v0.3.1 docs. The output should make the next planning/execution step possible without repeating requirements discovery.

The target is not to code immediately inside deep-interview. The target is a handoff-quality implementation brief that converts the large Single-Server Docker spec into milestones, acceptance checks, stack decision gates, and initial scaffold boundaries for `~/GilJob_v2`.

## Desired outcome

A downstream `$ralplan`, `$team`, or implementation lane can read this spec and proceed with:

1. a concrete milestone/task order for `GilJob_v2`,
2. explicit stack decision gates for the reopened areas,
3. testable acceptance criteria,
4. a safe initial folder/file scaffold contract,
5. preserved v0.3.1 security/token/state invariants.

## In scope

- Convert docs into an implementation-prep plan.
- Define milestone order and task boundaries for `~/GilJob_v2`.
- Define scaffold contract for the new v2 folder.
- Define test/verification matrix:
  - health/smoke,
  - token/security,
  - state transition/CAS,
  - 3-turn demo flow,
  - LiveKit/browser join evidence,
  - Agent1/Agent2/fallback evidence.
- Include stack-reopen gates for:
  - Postgres/Redis state/event stack,
  - Caddy/reverse-proxy ingress.
- Keep Single-Server Docker Compose as the deployment envelope.

## Out of scope / non-goals

- Do not modify or overwrite existing `~/GilJob`.
- Do not directly copy existing `~/GilJob` into v2 without an explicit later decision.
- Do not implement the full system in this deep-interview mode.
- Do not force every AI capability to be local; STT/TTS/LLM/SpatialReal external APIs remain allowed where useful.
- Do not include production SaaS features such as multi-tenancy, autoscaling, billing, or large-scale operations.

## Decision boundaries

OMX may decide without confirmation:

- milestone/task ordering,
- phase decomposition,
- unspecified implementation libraries/packages,
- wording and organization of the execution-ready spec,
- scaffold shape that does not violate the boundaries below.

OMX must not change without confirmation:

- v0.3.1 security/token contract,
- internal API public-blocking requirement,
- token TTL/hash separation contract,
- StateCoordinator/CAS transition invariant,
- Single-Server Docker Compose deployment envelope.

## Stack gates

### Fixed envelope

- One server.
- Docker Compose.
- Service boundaries remain separate enough to preserve debugability and future split potential.
- Existing `~/GilJob` remains untouched.

### Baseline retained unless a concrete blocker appears

- LiveKit/coturn as the RTC/TURN baseline.
- AI service boundary direction from docs: frontend/API/AI Engine/Agent1/Agent2 responsibilities remain conceptually separated.

### Reopened before implementation

#### Gate A — Postgres/Redis state stack

Question: Is full Postgres + Redis required from Phase 0, or can MVP start with a simpler state/event arrangement while preserving the documented token/security/state contracts?

Decision criteria:

- Must preserve session/report token hashing and TTL contract.
- Must preserve state transition CAS semantics or provide an equivalent correctness guarantee.
- Must support enough event flow for 3-turn demo and report generation.
- Must not expose DB/event bus publicly.
- Must have a clear migration path to the documented Postgres/Redis version if simplified.

Allowed outcomes:

1. Keep Postgres + Redis from Phase 0.
2. Keep Postgres, defer Redis with in-process/event-log substitute for early fake loop.
3. Use a simplified local persistence path only if CAS/token/report requirements remain testable.

#### Gate B — Caddy/reverse-proxy ingress

Question: Is Caddy the right default for MVP ingress, or should Caddy/Nginx/direct LiveKit exposure be selected based on server/network constraints?

Decision criteria:

- Public health endpoints must remain `/healthz` and `/readyz` only.
- `/api/internal/*` must be blocked at public ingress and protected at API middleware.
- Browser must access frontend/API/WSS over public HTTPS/WSS.
- LiveKit and TURN networking must be testable from a different network before demo.
- The selected proxy/ingress must map cleanly into Docker Compose and runbook smoke checks.

Allowed outcomes:

1. Keep Caddy as docs baseline.
2. Use Nginx if operational familiarity/certbot setup is safer.
3. Expose LiveKit separately while keeping API/frontend behind reverse proxy, if that reduces WebRTC risk.

## Constraints from docs to preserve

- Public health smoke route: `/healthz` and `/readyz`.
- Internal service ports (Postgres, Redis, AI Engine, Agent1 internal) are not public.
- API-prefixed health smoke path is not a canonical endpoint.
- Session token TTL: 2h / `SESSION_TOKEN_TTL_SECONDS=7200`.
- Report token TTL: 30d / `REPORT_TOKEN_TTL_SECONDS=2592000`.
- Separate session/report signing/hash paths.
- State transitions via allowed transition table + CAS transaction.
- Docker smoke must separate public route checks and container-internal checks.

## Acceptance criteria for this spec

This spec is complete when all of the following are true:

- [x] Work breakdown target is explicit.
- [x] Stack reopen gates are included for Postgres/Redis and ingress.
- [x] Test categories are defined.
- [x] Scaffold contract is defined.
- [x] Handoff is possible without another requirements interview.

## Acceptance criteria for the next implementation-prep artifact

The next planning artifact should contain:

- [ ] Milestones mapped to `~/GilJob_v2` deliverables.
- [ ] Decision record for Gate A: Postgres/Redis state stack.
- [ ] Decision record for Gate B: Caddy/reverse-proxy ingress.
- [ ] Initial scaffold tree with ownership of `apps/`, `services/`, `infra/`, `docs/`, `scripts/`, and tests.
- [ ] Docker smoke commands using public `/healthz`/`/readyz` plus `docker compose exec` internal checks.
- [ ] Token/security tests covering session/report TTL/hash separation and internal API blocking.
- [ ] State transition/CAS tests or equivalent proof if state stack is simplified.
- [ ] E2E demo script for 3-turn interview and report display.

## Proposed milestone order

### M0 — Decision/scaffold gate

- Copy or create docs inside `~/GilJob_v2/docs` as controlled source material.
- Decide Gate A and Gate B.
- Create root scaffold only after those gates are recorded.

### M1 — Docker skeleton and health

- Compose envelope.
- Frontend placeholder.
- API `/healthz` and `/readyz`.
- AI Engine and Agent1 placeholder health endpoints.
- DB/event stack per Gate A.
- Ingress per Gate B.

### M2 — Session/token/LiveKit minimal path

- `POST /api/sessions`.
- Session/report token hash contract.
- LiveKit token issue.
- Browser device check and room join.
- Engine participant join/track subscribe.

### M3 — Fake 3-turn loop

- Fake STT.
- Fake Agent1.
- Fake Agent2.
- State machine/event flow.
- Text/avatar fallback response.
- Fake report.

### M4 — Real adapters

- STT provider adapter.
- Agent2 LLM adapter.
- Agent1/Multi_Modal_Module integration path.
- Fallbacks and schema validation.

### M5 — Avatar/report/demo hardening

- SpatialReal/TTS path or text fallback.
- Report generator.
- Runbook.
- Failure injection and demo rehearsals.

## Scaffold contract for `~/GilJob_v2`

Recommended initial tree:

```txt
GilJob_v2/
  docs/
    giljob-v0.3.1-final-spec.md
    giljob-v0.3.1-high3-validation.md
    decisions/
      0001-state-stack.md
      0002-ingress-stack.md
    implementation-plan.md
  infra/
    docker-compose.yml
    caddy/Caddyfile
    livekit/livekit.yaml
    coturn/turnserver.conf
  apps/
    web/
  services/
    api/
    ai-engine/
    agent1/
  packages/
    shared/
  scripts/
    smoke.sh
    demo-e2e.md
  tests/
    contract/
    integration/
```

Scaffold rule: create only files needed to preserve decisions, contracts, and smokeability first. Avoid copying legacy app code until a later explicit migration/greenfield decision.

## Verification matrix

- Docs/source verification:
  - compare copied docs to local source checksums,
  - ensure decision files exist for Gate A and Gate B.
- Health/smoke:
  - public `https://${PUBLIC_DOMAIN}/healthz`, `/readyz`,
  - container-internal `api`, `ai-engine`, `agent1`, DB/event stack checks.
- Security/token:
  - `/api/internal/*` public 404/403 behavior,
  - internal token/HMAC middleware,
  - session token 2h and report token 30d,
  - separate hash/signing secrets.
- State:
  - allowed transition seed,
  - invalid transition rejection,
  - CAS version conflict handling,
  - idempotent event handling.
- RTC/demo:
  - browser mic/camera join,
  - engine track subscribe,
  - 3-turn fake loop,
  - report generation.

## Assumptions exposed and resolutions

- Assumption: docs stack is fixed.
  - Resolution: not fully fixed. Docker Compose is fixed, but Postgres/Redis and ingress are reopened decision gates.
- Assumption: implementation can start immediately.
  - Resolution: not inside deep-interview; output is implementation-prep specification.
- Assumption: all AI must be local.
  - Resolution: false; external STT/TTS/LLM/SpatialReal may remain.

## Recommended handoff

Recommended next lane: `$ralplan` using this spec as source of truth.

Why: requirements are clear enough to stop interviewing, but the reopened Postgres/Redis and ingress decisions need architecture/test-shape review before execution.

Suggested command shape:

```txt
$ralplan .omx/specs/deep-interview-giljob-v2-execution-spec.md
```

Alternative:

- `$team` after the plan is approved, if parallel scaffold/API/infra/docs lanes are desired.
- `$autopilot` only after Gate A and Gate B are decided.
- `$ultragoal` can be used after the plan to track durable completion checkpoints.
