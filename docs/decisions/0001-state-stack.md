# ADR 0001 — State/Event Stack for GilJob v2 MVP

- Status: Accepted for scaffold; revisit after fake 3-turn loop if evidence contradicts assumptions
- Date: 2026-05-30
- Gate: A — Postgres/Redis state stack
- Source: `docs/planning/prd-giljob-v2-execution-prep-20260530T050637Z.md`, `docs/planning/test-spec-giljob-v2-execution-prep-20260530T050637Z.md`

## Context

GilJob v2 must preserve the v0.3.1 token/security/state contract while keeping the first implementation pass small enough for a graduation-demo MVP. The preserved constraints are:

- session token TTL: `SESSION_TOKEN_TTL_SECONDS=7200`
- report token TTL: `REPORT_TOKEN_TTL_SECONDS=2592000`
- separate session/report signing and hash paths
- raw bearer tokens are never persisted
- state transitions are validated against allowed transitions and guarded by `state_version` CAS semantics or an equivalent tested guarantee
- DB/event infrastructure is not publicly exposed

The reopened question is whether Phase 0 must include full Postgres + Redis or can defer part of the stack.

## Options considered

### Option A — Postgres + Redis from Phase 0

Pros:
- Closest to v0.3.1 docs.
- State, token hash, event stream, and backpressure contracts are all represented early.
- Reduces migration work later.

Cons:
- More services before first visible demo loop.
- Redis stream/backpressure work may slow fake-loop progress.

### Option B — Postgres from Phase 0, Redis deferred behind an event-bus adapter

Pros:
- Keeps token hash persistence and CAS state correctness concrete from the start.
- Lets the fake 3-turn loop use an in-process/event-log adapter with the same envelope shape.
- Preserves migration path to Redis without requiring Redis semantics before they are needed.

Cons:
- Adapter equivalence must be explicit or it becomes hand-wavy.
- Backpressure/drop/DLQ behavior is not fully tested until Redis is enabled.

### Option C — Fully simplified local/in-memory state first

Pros:
- Fastest fake-loop path.

Cons:
- Weakens token and CAS contract tests.
- High risk of rewriting state/session code later.
- Conflicts with the consensus principle “contracts before code.”

## Decision

Choose **Option B: Postgres from Phase 0, Redis deferred behind an event-bus adapter until after the fake 3-turn loop passes**.

Postgres is required from the skeleton phase because token hash persistence, report token persistence, session state, and CAS tests are part of the preserved contract. Redis may be deferred for the earliest fake loop only if the code uses an `EventBus` boundary whose envelope matches the eventual Redis stream envelope.

## EventBus equivalence requirements while Redis is deferred

The temporary adapter must define and test:

- event envelope fields: `event_id`, `session_id`, `turn_id`, `type`, `payload`, `created_at`, `idempotency_key`, `schema_version`
- ordering: per-session append order only; global ordering is not guaranteed
- idempotency/dedupe: `idempotency_key` or `event_id` rejects duplicate handling
- durability limit: acceptable for dev/fake-loop process lifetime only; not accepted for final demo hardening
- deferred Redis behavior: maxlen, TTL, retry, DLQ, and backpressure policies are documented but not enforced by the temporary adapter
- migration trigger: Redis must be enabled before real STT/Agent1/Agent2 concurrent adapters are considered demo-ready

## Consequences

- `services/api` must have Postgres access in Phase 0/M1.
- State transition and token tests can be written before LiveKit/AI integrations.
- Early fake-loop code must depend on an event-bus interface, not Redis directly.
- Redis configuration remains in the final target architecture and can be introduced when concurrency/backpressure becomes meaningful.

## Verification

- Token hash tests prove session/report hash paths and TTLs.
- CAS tests prove valid transition, stale version rejection, invalid transition rejection, and idempotent replay behavior.
- Event adapter tests prove envelope shape, per-session ordering, duplicate handling, and explicit lack of durability/backpressure guarantees.
- Final Redis migration tests must prove equivalent envelope consumption plus Redis maxlen/TTL/retry/DLQ policy before real adapter demo hardening.

## Follow-ups

- Add `EventBus` interface to implementation plan.
- Add Redis migration checkpoint before real adapters.
- Keep Redis in Compose as optional/profiled service or add it no later than the real-adapter milestone.
