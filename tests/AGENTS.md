# tests Agent Contract

This module owns behavior and security verification. Follow the root `AGENTS.md` plus these local rules.

## Scope
- `tests/contract/` contains fast behavior/security contracts and should stay deterministic.
- `tests/integration/` is reserved for broader integration checks and may need explicit runtime services.

## Rules
- Add or update contract tests when changing security, token, LiveKit, Gemini, route, or agent-doc invariants.
- Avoid network-dependent tests unless the task explicitly asks for live integration.
- Keep tests from printing raw token values, JWTs, `.env` values, Gemini keys, or raw media.
- Prefer path-specific semantic assertions over broad keyword scans.

## Commands
```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -v
```
