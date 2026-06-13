# scripts Agent Contract

This module owns local smoke and verification scripts. Follow the root `AGENTS.md` plus these local rules.

## Responsibilities
- Keep smoke scripts deterministic and explicit about prerequisites.
- Preserve fail-closed validation for config and LiveKit media setup.
- Preserve browser smoke token redaction and avoid asserting or printing raw token payloads.
- Do not print `.env` values, provider keys, LiveKit secrets, raw tokens, JWTs, or raw media.

## Tests
When editing scripts, run the relevant script in its safest mode and the contract tests that inspect script behavior.
