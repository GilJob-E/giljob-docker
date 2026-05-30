# PRD — GilJob v2 Execution Preparation Plan

## Metadata

- Source spec: `.omx/specs/deep-interview-giljob-v2-execution-spec.md`
- Source docs:
  - `docs/giljob-v0.3.1-final-spec.md`
  - `docs/giljob-v0.3.1-high3-validation.md`
- Remote target: `hoddukzoa@kiostation:/home/hoddukzoa/GilJob_v2`
- Planning mode: `$ralplan` consensus
- Execution status: planning only; no implementation yet

## Goal

Prepare GilJob v2 for implementation by turning the v0.3.1 Single-Server Docker specification into a bounded, testable, handoff-ready plan for the empty remote `~/GilJob_v2` folder.

## Problem

The local docs are detailed enough to describe the target MVP, but too broad to execute safely as a single implementation task. Two architecture axes were intentionally reopened during deep-interview:

1. Postgres/Redis state stack.
2. Caddy/reverse-proxy ingress.

Implementation should not begin until those gates have explicit decision records, because they affect scaffold shape, smoke tests, runtime contracts, and state/security tests.

## Non-goals

- Do not modify existing `~/GilJob`.
- Do not copy existing `~/GilJob` into v2 without a later explicit decision.
- Do not implement the whole MVP as part of planning.
- Do not force all AI to run locally; external STT/TTS/LLM/SpatialReal APIs remain allowed.
- Do not include production SaaS features: multi-tenancy, autoscaling, billing, large-scale operations.

## Preserved invariants

- Single server, Docker Compose envelope.
- Service boundaries remain visible even if early implementations are placeholders.
- Public health endpoints are `/healthz` and `/readyz` only.
- `/api/internal/*` must be blocked at public ingress and protected by API middleware.
- Session token TTL: `SESSION_TOKEN_TTL_SECONDS=7200`.
- Report token TTL: `REPORT_TOKEN_TTL_SECONDS=2592000`.
- Session/report token hash/signing paths are separate.
- State transitions use allowed-transition validation plus CAS/state-version semantics, or an explicitly equivalent testable guarantee if a temporary simplified state store is chosen.
- Docker smoke tests separate public route checks from container-internal `docker compose exec` checks.

## RALPLAN-DR summary

### Principles

1. **Demo reproducibility before breadth**: every milestone must improve the chance of a repeatable 3-turn demo.
2. **Contracts before code**: token/security/state/health contracts must be testable before real AI integrations.
3. **Decisions before scaffold freeze**: the two reopened stack axes need ADRs before files hard-code assumptions.
4. **Reference, do not mutate legacy**: existing `~/GilJob` is evidence only, not a write target.
5. **Fallbacks are product features for MVP**: fake/text/external-provider fallbacks are acceptable if contracts and evidence remain clear.

### Decision drivers

1. **Risk isolation**: reduce WebRTC/ingress/state complexity before coding broad slices.
2. **Verification clarity**: make each milestone prove something observable.
3. **Graduation-demo schedule**: prefer phases that produce early smokeable artifacts.

### Viable options

#### Option A — Gate-first scaffold, then implementation (chosen)

- Create/copy source docs and ADR stubs in `~/GilJob_v2`.
- Decide state and ingress gates before composing runtime skeleton.
- Then scaffold Compose/health/session loop.

Pros:
- Avoids hard-coding reopened decisions.
- Keeps planning and implementation bounded.
- Gives Architect/Critic concrete gates to validate.

Cons:
- Slower than immediately scaffolding placeholders.
- Requires one extra decision artifact step before visible app progress.

#### Option B — Scaffold docs baseline immediately, decide gates later

Pros:
- Fast visible folder progress.
- Matches v0.3.1 docs closely.

Cons:
- May require rework if Redis/Postgres or ingress decisions change.
- Risks conflating docs baseline with chosen implementation.

#### Option C — Minimal fake app first, retrofit infra later

Pros:
- Fastest route to demo-looking UI loop.
- Reduces initial infra burden.

Cons:
- Violates contract-first intent.
- Security/token/state acceptance could be postponed until too late.
- Harder to prove architecture during review.

### Chosen option

Option A: **Gate-first scaffold, then implementation**.

## Product / implementation milestones

### M0 — Planning intake and remote-safe source setup

Deliverables:

- `~/GilJob_v2/docs/` contains controlled copies of the local source docs.
- `~/GilJob_v2/docs/implementation-plan.md` contains the approved milestone plan.
- `~/GilJob_v2/docs/decisions/0001-state-stack.md` exists.
- `~/GilJob_v2/docs/decisions/0002-ingress-stack.md` exists.
- Legacy `~/GilJob` is untouched.

Acceptance:

- Source doc checksums are recorded.
- `find ~/GilJob_v2 -maxdepth 3` shows only planned scaffold/docs files.
- Git initialization is allowed only in `~/GilJob_v2`, not `~/GilJob`.

### M1 — Gate A: State/event stack ADR

Decision question:

Should Phase 0 use full Postgres + Redis from the start, or a simplified early state/event store while preserving security/state contracts?

Recommended planning stance:

- Prefer **Postgres from Phase 0** for token hash storage and state CAS.
- Permit **Redis deferral only for the fake 3-turn loop** if event behavior is captured by an in-process adapter with the same envelope and later migration contract.
- Do not remove the Redis contract from the final MVP unless another explicit decision occurs.

Acceptance:

- ADR names selected state/event option.
- Token hash storage is testable.
- State-version CAS is testable.
- Event envelope path for fake loop and later Redis path is documented.
- Migration boundary is explicit if Redis is deferred.

### M2 — Gate B: Ingress ADR

Decision question:

Should MVP use Caddy as docs baseline, Nginx, or split LiveKit direct exposure while keeping API/frontend behind reverse proxy?

Recommended planning stance:

- Keep **Caddy for frontend/API health/internal route blocking** unless server TLS constraints prove otherwise.
- Allow **LiveKit subdomain/direct exposure** if path-proxying WSS/media becomes a risk.
- TURN/coturn remains baseline; network smoke must be from at least one external network before demo.

Acceptance:

- ADR names selected ingress shape.
- `/healthz` and `/readyz` public routes are defined.
- `/api/internal/*` public block is represented in proxy config and API middleware tests.
- LiveKit/TURN smoke plan is explicit.

### M3 — Scaffold skeleton and contract tests

Deliverables:

```txt
GilJob_v2/
  docs/
  infra/
  apps/web/
  services/api/
  services/ai-engine/
  services/agent1/
  packages/shared/
  scripts/
  tests/contract/
  tests/integration/
```

Acceptance:

- `docker compose config` succeeds.
- API, AI Engine, Agent1 expose local health endpoints.
- Public `/healthz` and `/readyz` smoke shape exists.
- Contract tests exist for token TTL/hash separation and internal route block.

### M4 — Session/token/LiveKit minimal runtime

Deliverables:

- `POST /api/sessions` issues session/report contract pieces and LiveKit candidate token.
- Frontend can perform device check and join LiveKit room.
- Engine participant can join and subscribe/log candidate tracks.

Acceptance:

- Browser publishes mic/camera.
- Engine logs track subscription.
- Token TTL/hash tests pass.
- Invalid internal access is rejected.

### M5 — Fake 3-turn interview loop

Deliverables:

- Fake STT final.
- Fake Agent1 nonverbal signal.
- Fake Agent2 follow-up.
- Text/avatar placeholder response.
- Fake report generation.

Acceptance:

- 3-turn loop completes.
- State transitions are recorded/validated.
- Report is displayed.
- Docker logs provide evidence for each turn.

### M6 — Real adapters and demo hardening

Deliverables:

- STT provider adapter.
- Agent2 LLM adapter.
- Agent1/Multi_Modal_Module integration path.
- SpatialReal/TTS or text fallback path.
- Demo runbook and failure injection.

Acceptance:

- Follow-up reflects candidate answer.
- Agent1 signal can influence Agent2 context or fallback is clearly shown.
- 5–10 minute demo runbook passes.

### Architect follow-up conditions carried forward

These conditions are binding for the next execution handoff:

- **Redis-deferral equivalence must be concrete**: if Redis is deferred, the ADR must define event envelope shape, ordering guarantees, idempotency/dedupe handling, durability limits, and which Redis backpressure/drop/DLQ rules are intentionally deferred.
- **External-network RTC evidence is required**: Gate B smoke evidence must include hotspot/non-local browser join and TURN allocation/log evidence, not only local container logs.
- **AI boundary remains explicit**: Agent1 owns signal/evaluation; Agent2 owns interviewer decision/question generation; any fallback must be declared in logs/UI/ADR rather than silently bypassing multimodal flow.
- **Source provenance is mandatory**: v2 docs must be copied from reviewed local source docs with checksums; do not source files from remote legacy `~/GilJob`.

## Available agent-types roster

- `planner`: milestone and artifact sequencing.
- `architect`: stack gates, service boundaries, security/state invariants.
- `critic`: quality gate, alternative fairness, acceptance criteria adequacy.
- `executor`: implementation/scaffold patches after planning approval.
- `test-engineer`: contract/integration/e2e test matrix and smoke scripts.
- `verifier`: final evidence review.
- `dependency-expert`: optional if Gate A/B need package/platform comparison.
- `researcher`: optional for official LiveKit/Caddy/Nginx/coturn docs if implementation choices require current reference checks.
- `writer`: ADR/runbook/docs polishing.

## Staffing guidance

Recommended after approval:

- Use `$ultragoal` as the durable goal ledger for sequential milestones.
- Use `$team` for coordinated implementation after M0/M1/M2 are approved:
  - Infra lane: Docker Compose, ingress, LiveKit/coturn.
  - API/state lane: sessions, tokens, CAS state, internal auth.
  - Frontend/LiveKit lane: device check, room join, UI flow.
  - Test lane: smoke, contract, fake 3-turn e2e.
- Keep `$ralph` only as an explicit fallback for single-owner verification/fix pressure.

## Verification path

1. Planning verification: Architect review then Critic review approve this plan.
2. Scaffold verification: doc checksums, ADRs, tree shape, no legacy writes.
3. Contract verification: token/security/state tests.
4. Runtime verification: Docker smoke and health checks.
5. Demo verification: browser join, engine subscribe, 3-turn loop, report.

## ADR

### Decision

Adopt a gate-first implementation-prep plan for GilJob v2: preserve Single-Server Docker Compose, reopen only Postgres/Redis and ingress decisions, then scaffold and implement in contract-first milestones.

### Drivers

- Avoid rework from unresolved stack gates.
- Preserve v0.3.1 security/state contracts.
- Maximize reproducible graduation demo readiness.

### Alternatives considered

- Scaffold docs baseline immediately: rejected because reopened stack decisions could invalidate early files.
- Minimal fake app first: rejected because it postpones security/state contracts and weakens reviewability.

### Consequences

- Slightly slower visible app progress.
- Much clearer implementation boundary and test plan.
- Requires ADR completion before full scaffold freeze.

### Follow-ups

- Fill Gate A and Gate B ADRs.
- Then launch implementation via `$ultragoal` + optional `$team`.
