# RALPLAN-DR — GilJob v2 Execution Preparation

## Principles

1. Demo reproducibility before breadth.
2. Contracts before code.
3. Decisions before scaffold freeze.
4. Reference, do not mutate legacy.
5. Fallbacks are acceptable MVP product behavior when explicit.

## Decision drivers

1. Risk isolation around state/ingress.
2. Verification clarity for each milestone.
3. Graduation-demo schedule pressure.

## Viable options

1. Gate-first scaffold, then implementation — chosen.
2. Scaffold docs baseline immediately — rejected due stack-gate rework risk.
3. Minimal fake app first — rejected due contract/testing deferral risk.

## Deliberate-mode note

Security/token/state contracts and public ingress make this high-risk enough to include expanded test planning in the test spec. Pre-mortem is captured below.

## Pre-mortem

1. WebRTC demo fails on the day because TURN/UDP was not tested externally.
   - Mitigation: require hotspot/external network smoke before demo.
2. Token/internal route contract regresses during scaffold shortcuts.
   - Mitigation: contract tests before real adapters.
3. Redis/Postgres simplification hides state correctness bugs.
   - Mitigation: ADR must preserve CAS-equivalent tests or choose Postgres from Phase 0.
