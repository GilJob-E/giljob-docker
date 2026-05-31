# packages/shared Agent Contract

This module is reserved for shared contracts and schemas. Follow the root `AGENTS.md` plus these local rules.

## Current responsibilities
- Hold shared schema/contract utilities only when multiple modules actually need them.
- Avoid premature abstractions and dependencies.
- Keep shared code small, typed or schema-backed when possible, and covered by tests.

## Forbidden changes
Do not move web/API/AI-specific behavior here just to make it look reusable. Do not add runtime dependencies without a concrete cross-module need.
