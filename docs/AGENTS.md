# docs Agent Contract

This module owns planning, architecture, ADR, runbook, and source documentation. Follow the root `AGENTS.md` plus these local rules.

## Source-of-truth rules
- Keep architecture edits in `docs/architecture.noml`; rendered SVG assets are generated outputs.
- Keep ADRs in `docs/decisions/` concise and decision-oriented.
- Keep runbooks in `docs/runbooks/` operational and command-focused.
- Planning/review artifacts may record workflow history, but should not replace current README, DESIGN, ADR, or test contracts.

## Language
`AGENTS.md` and `CLAUDE.md` prose must be English. Korean product docs and quoted Korean UI labels are allowed when they reflect the product surface.

## Generated/vendor scope
Do not treat `node_modules/`, generated assets, caches, or vendor residue as source material unless the task explicitly asks for cleanup. Do not quote `.env` values.
