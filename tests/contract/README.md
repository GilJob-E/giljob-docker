# tests/contract

Contract tests for the GilJob v2 scaffold. These are not placeholders; they currently cover API token behavior, API HTTP behavior, AI-engine provider boundaries, web static behavior, ingress/security expectations, and redaction checks.

## Clean-clone prerequisite

Some web static tests verify vendored browser assets that are materialized by the web package lock. From a clean clone, run this first:

```bash
(cd apps/web && npm ci --omit=dev --ignore-scripts)
```

## Run all contract tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -p 'test_*_contract.py' -v
```

At reviewed main commit `34403b7c60cc43b2615e11351cc5d7cf37f84ca2`, the full contract suite passed after the web dependency install.

## Scope notes

- These tests do not prove production auth is complete. Known gaps such as public `/analysis/*` and unauthenticated provider broker calls are documented in `docs/reviews/main-branch-readiness-20260611.md`.
- These tests do not prove `services/analysis-engine` Docker build is green; that build is a separate known failing gate.

Follow:
- `docs/runbooks/verification.md`
- `docs/reviews/main-branch-readiness-20260611.md`
- `docs/decisions/0001-state-stack.md`
- `docs/decisions/0002-ingress-stack.md`
