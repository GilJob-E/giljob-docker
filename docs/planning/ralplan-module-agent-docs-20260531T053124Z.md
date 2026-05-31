# Ralplan: Module Agent Documentation

## Task
Write English `AGENTS.md` and `CLAUDE.md` guidance files per module for the current GilJob v2 repository. This ralplan produces the plan only; implementation happens after ralplan closure.

## Context Snapshot
- `.omx/context/module-agent-docs-20260531T053124Z.md`

## RALPLAN-DR Summary

### Principles
1. Scoped hierarchy: root guidance defines global invariants; module guidance defines local ownership.
2. Security first: token, secret, LiveKit, and LLM key boundaries must be explicit.
3. Low duplication: link to README, DESIGN, ADRs, and tests instead of copying them wholesale.
4. Module-local override: deeper `AGENTS.md` files refine the root contract for their subtree.
5. Testable docs: add contract tests for the presence and critical semantics of agent docs.

### Decision Drivers
1. Agents need reliable local instructions before editing code or docs.
2. Current GilJob v2 security and media boundaries must not regress.
3. Placeholder modules must not be documented as implemented product features.

### Viable Options

#### Option A: Root-only `AGENTS.md` / `CLAUDE.md`
- Pros: minimal maintenance burden.
- Cons: too generic for web/API/infra/AI/security boundaries; agents would still infer too much.
- Verdict: rejected.

#### Option B: Root + module `AGENTS.md`, thin `CLAUDE.md` files
- Pros: actionable local guidance, low duplication, clear override hierarchy, Claude compatibility.
- Cons: more files to maintain.
- Verdict: chosen.

#### Option C: Module-only docs
- Pros: local by default.
- Cons: misses global no-touch, security, and deployment invariants.
- Verdict: rejected.

## Approved Plan

### 1. Documentation hierarchy
- Root `AGENTS.md` is the canonical English repo contract for all agents. It covers product intent, no-touch legacy GilJob boundary, single-server multi-container architecture, source-of-truth links, global security invariants, env/secrets rules, module map, global verification commands, and reporting expectations.
- Root `CLAUDE.md` is a thin Claude Code entrypoint: read root AGENTS first, respect deeper AGENTS files, use Korean user-facing conversation when appropriate, keep AGENTS/CLAUDE prose English, never print secrets, and run relevant tests.
- Module `AGENTS.md` files contain local ownership, allowed/forbidden edits, module-specific invariants, and local tests.
- Module `CLAUDE.md` files are intentionally short: read local AGENTS first, Claude-specific reminders, common commands only. They must not duplicate full contracts.

### 2. Files to create
- `AGENTS.md`, `CLAUDE.md`
- `apps/web/{AGENTS.md,CLAUDE.md}`
- `services/api/{AGENTS.md,CLAUDE.md}`
- `services/ai-engine/{AGENTS.md,CLAUDE.md}`
- `services/agent1/{AGENTS.md,CLAUDE.md}`
- `infra/{AGENTS.md,CLAUDE.md}`
- `tests/{AGENTS.md,CLAUDE.md}` covering `tests/contract` and `tests/integration`
- `docs/{AGENTS.md,CLAUDE.md}`
- `packages/shared/{AGENTS.md,CLAUDE.md}`
- `scripts/{AGENTS.md,CLAUDE.md}`

### 3. Module content boundaries
- `apps/web`: `DESIGN.md` adherence, production routes, no prejoin in room, light non-scrolling meeting room, right sidebar context panel, manual button answer flow, LiveKit browser client only, visible/log redaction, no raw token/JWT UI/logs, web static contract tests.
- `services/api`: session/report token contract, purpose-separated HMAC hash-only storage, no raw token persistence/logging, `/api/internal/*` blocked, LiveKit candidate token issuance, `LIVEKIT_INTERNAL_URL`/`LIVEKIT_PUBLIC_URL` split, production fail-closed rules, API/token tests.
- `services/ai-engine`: Gemini-backed next-question provider boundary only; `GEMINI_API_KEY` env; no key/prompt leakage; fail closed when `LLM_PROVIDER=gemini` and `GEMINI_API_KEY` is missing; do not claim full STT/avatar/final-report implementation.
- `services/agent1`: future multimodal placeholder only; raw AV may be observed only inside a future boundary; outward interface should be structured signal only; no raw media/token exposure; no premature implementation promises.
- `infra`: Docker Compose/Caddy/LiveKit/coturn/Postgres boundaries; Caddy blocks internal APIs; current `/ai/*` ingress tension must be documented because Caddy currently exposes an AI route while ADR 0002 treats AI Engine/Agent1 as internal; direct media ports; TURN notes; single-server multi-container deployment; `LIVEKIT_INTERNAL_URL`/`LIVEKIT_PUBLIC_URL`; no secret commits.
- `tests`: contract tests are behavior/security gates; add tests for new invariants; cover integration directory; avoid network-dependent tests unless explicitly requested.
- `docs`: ADR/runbook/planning conventions; architecture NOML/SVG sync; source docs vs generated artifacts; English for AGENTS/CLAUDE, Korean product docs allowed.
- `packages/shared`: shared contracts/schemas only; avoid premature abstractions.
- `scripts`: smoke/browser scripts, token redaction, fail-closed validation, no secret printing.

### 4. Generated/vendor/secrets ignore scope
- Do not read-print, commit, or quote `.env` values.
- Skip/ignore `__pycache__/`, `node_modules/`, `.tmp-gemini-default-marker`, generated build/cache artifacts, and vendor residue unless explicitly cleaning them.
- Generated SVG/assets may be referenced, but source of truth for architecture edits remains `docs/architecture.noml`.

### 5. Documentation contract test
Add `tests/contract/test_agent_docs_contract.py` that checks:
- Expected `AGENTS.md` and `CLAUDE.md` files exist.
- Every `CLAUDE.md` says to read the nearest/local `AGENTS.md` first.
- Semantic requirements are path-specific, not global:
  - `services/ai-engine/AGENTS.md` includes `GEMINI_API_KEY` and the bounded next-question provider scope.
  - `services/agent1/AGENTS.md` includes `structured signal` and future multimodal placeholder wording.
  - `services/api/AGENTS.md` includes `hash-only`, `raw token`, and LiveKit URL split terms.
  - `apps/web/AGENTS.md` includes manual answer flow, right sidebar, and redaction terms.
  - `infra/AGENTS.md` includes Caddy, LiveKit, coturn, direct media ports, and `/ai/*` ingress tension.
- Secret/JWT scans are scoped to the new `AGENTS.md` / `CLAUDE.md` files only, with intentional placeholder wording allowed.
- Docs do not claim full Main LLM loop, STT, SpatialReal/ElevenLabs avatar, multimodal analysis, or final report is already implemented.
- Do not require all docs to be exclusively English if quoting Korean UI labels; requirement is that AGENTS/CLAUDE prose is English.

### 6. Risks and mitigations
- Drift risk: mitigate with source-of-truth links and short module docs instead of duplicating README/ADR content.
- False implementation claims: mitigate with explicit current vs future boundary wording, especially in `ai-engine`, `agent1`, and `packages/shared`.
- Secret leakage: mitigate with no `.env` printing, no raw token/JWT examples, and path-scoped contract tests.
- Agent overreach: mitigate with module-local forbidden edits and no-touch legacy GilJob reminder.
- Over-documentation: mitigate by keeping `CLAUDE.md` thin and using module `AGENTS.md` only for actionable local constraints.

### 7. Verification commands
Run in the current git checkout:

```bash
node --check apps/web/static/app.js
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -v
git diff --check
```

Use a small Python whitespace/static doc sanity script only if extra checks are useful.

### 8. Handoff
- After ralplan closure/state cleanup, solo execution is sufficient because this is doc + contract-test work with low conflict risk.
- `$team` is optional only if parallelizing module drafting.
- `$ultragoal` is only needed if durable ledger tracking is desired for the documentation rollout.
- `$ralph` remains an explicit fallback only if persistent single-owner verification pressure is requested.

## Acceptance Criteria
- All planned agent docs exist and are English prose except quoted UI labels.
- Module docs are scoped and do not duplicate full README/ADR content.
- `CLAUDE.md` files point to nearest/local `AGENTS.md` first.
- Contract tests verify path-specific invariants.
- Existing contract tests remain green.
- No secrets, raw JWTs, raw tokens, or fake implementation claims are introduced.

## Consensus Gate
- Architect review: APPROVE after re-review.
- Critic review: APPROVE after Architect re-review.
- Consensus order: Architect -> Critic.
