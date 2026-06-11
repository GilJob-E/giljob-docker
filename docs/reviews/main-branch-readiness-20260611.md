# Main Branch Readiness and Documentation Consistency Review — 2026-06-11

Review target:

- Repository: `https://github.com/GilJob-E/giljob-docker.git`
- Branch: `main`
- Reviewed commit: `34403b7c60cc43b2615e11351cc5d7cf37f84ca2`
- Review type: whole-repository release/readiness audit plus documentation-consistency audit.

This document records the current problems found on `main`. It is intentionally documentation-only: it does **not** fix runtime code, Dockerfiles, ingress rules, tests, or configuration defaults.

## Executive verdict

`main` is a useful v2 scaffold with good contract-test coverage around token redaction, LiveKit URL splitting, provider brokering, and static browser behavior. It is **not yet a production-ready or fully compose-buildable single-server stack**.

The highest-risk gaps are:

1. `services/analysis-engine` Docker build currently fails because the image lacks native build tooling required by `praat-parselmouth` through `giljobe[vision,prosody]`.
2. Caddy publicly exposes `/analysis/*`, including transcript/signal polling and subscriber start/stop controls.
3. `POST /api/sessions` accepts caller-selected `sessionId`/`interviewId` and returns raw session/report/LiveKit tokens without an application-auth gate.
4. Browser-facing provider broker routes can invoke Gemini/TTS/SpatialReal paths without session-token validation or rate limiting.
5. Several README, runbook, and agent-contract files described older behavior: SpatialReal as future-only, LiveKit client `2.19.1`, Postgres persistence as implemented, and verification commands that do not pass from a clean clone.

## Verification evidence from the audit

Passing checks observed at the reviewed commit:

- Clean clone and `git status` were clean at `34403b7c60cc43b2615e11351cc5d7cf37f84ca2`.
- Python syntax checks passed for API, AI engine, web, and agent1 entrypoints.
- `node --check apps/web/static/app.js` passed.
- `node --check scripts/browser-join-smoke.mjs` passed.
- `cd apps/web && npm ci --omit=dev --ignore-scripts` succeeded.
- `cd apps/web && npm run check:js` passed.
- `cd apps/web && npm audit --omit=dev --audit-level=high` reported no high-or-higher production vulnerability.
- After `apps/web/node_modules` exists, `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -p 'test_*_contract.py' -v` passed with 78 tests.
- Docker builds passed for `services/api`, `services/ai-engine`, `services/agent1`, and `apps/web`.
- Local Markdown link checking found no broken local links.

Known failing or misleading checks:

- Contract tests from a clean clone fail before `apps/web/npm ci` because the web server cannot serve vendored SpatialReal/LiveKit browser assets from missing `node_modules`.
- `docker build services/analysis-engine` fails at `pip install -r /app/requirements.txt` while building `praat-parselmouth`.
- `npx --yes pyright` reports type errors in contract-test helper code.
- `docs/planning/package-lock.json` pulls an obsolete npm `gh` package tree with critical/high audit findings. This does not appear to be production runtime input, but it is stale dependency residue in the repo.

## P0 blockers / critical issues

### B1 — `analysis-engine` Docker build failure

Evidence:

- `services/analysis-engine/requirements.txt` installs `giljobe[vision,prosody] @ git+https://github.com/GilJob-E/GilJobE.git@e0671f5`.
- That dependency path pulls `praat-parselmouth`.
- `services/analysis-engine/Dockerfile` installs `git ffmpeg ca-certificates curl libegl1 libgles2`, but not `build-essential`, `cmake`, or `ninja-build`.
- Build failure includes missing Ninja/make/compiler messages from CMake.

Impact:

- A full compose build that includes `analysis-engine` is not reliable.
- Any README/runbook command that treats `docker build services/analysis-engine` as a passing gate is currently inaccurate.

Recommended code follow-up:

- Add a native build-toolchain layer or split the prosody extra into an optional image/profile.
- Prefer a multi-stage build if native build dependencies should not remain in the runtime image.
- Add `analysis-engine` build to CI once fixed.

### B2 — Public `/analysis/*` ingress exposes sensitive/control endpoints

Evidence:

- `infra/caddy/Caddyfile` has `handle_path /analysis/* { reverse_proxy analysis-engine:8200 }`.
- `services/analysis-engine` exposes `/subscriber/start`, `/subscriber/stop`, and `/signals?sessionId=`.
- `apps/web/static/app.js` calls those endpoints directly from the browser.

Impact:

- A client that knows or guesses a session id can poll transcripts/signals.
- A client can start/stop the hidden subscriber for a session turn.
- Transcript and non-verbal signal data are sensitive candidate data.

Recommended code follow-up:

- Remove public Caddy exposure for `/analysis/*`.
- Add authenticated API broker routes for analysis start/stop/signals.
- Validate the GilJob session token and bind start/stop/polling to the session and turn id.

### B3 — Public session creation allows caller-selected ids and raw token issuance

Evidence:

- `POST /api/sessions` accepts `sessionId`/`interviewId` from the request body.
- Static routes and fallback code use `local-demo` as a shared id.
- The create-session response includes `sessionToken`, `reportToken`, and LiveKit candidate/avatar token material.

Impact:

- Multiple users can collide in the same LiveKit room/session id.
- Raw report tokens are returned at session creation time.
- Production user/session authorization cannot be enforced by route id alone.

Recommended code follow-up:

- Generate production session ids server-side.
- Make caller-selected ids dev-only or reject duplicates with `409 Conflict`.
- Issue report tokens only when needed and behind the correct authorization check.

### B4 — Provider broker routes lack session-token validation/rate limiting

Evidence:

- Browser-facing routes under `/api/interviews/{interviewId}/...` proxy to `services/ai-engine` question, TTS, and avatar paths.
- The current broker boundary redacts provider secrets, but it does not yet validate an application session bearer token per request.

Impact:

- Public clients can potentially consume Gemini, Gemini TTS, ElevenLabs, or SpatialReal quota.
- Turn order/state is not enforced server-side.

Recommended code follow-up:

- Require session bearer validation on question/TTS/avatar broker calls.
- Add turn monotonicity/idempotency checks, request body limits, provider response size caps, and rate limiting.

## High-priority implementation/documentation gaps

- `local-demo` remains in production-shaped route examples and fallback behavior. Treat it as a local demo id only.
- Postgres exists as a service and schema contract, but API runtime token state is still in process memory.
- `services/api/db/schema.sql` uses UUID session ids, while current demo/browser paths allow non-UUID ids such as `local-demo`.
- `.env.example` sets `LLM_PROVIDER=gemini` with a placeholder key even though keyless local smoke is safer with `LLM_PROVIDER=fake`.
- Production startup does not yet reject known placeholder secret values such as `change-me`, `replace-me`, or `local-only`.
- The LiveKit overlay starts coturn, but LiveKit config has `turn.enabled: false`; coturn is not automatically advertised to LiveKit clients.
- `ai-engine` request parsing should catch invalid UTF-8 and return a controlled `400 invalid_json`-style response.
- Public-facing token/provider responses should add cache/security headers and response-size caps.
- LLM question generation should treat candidate/job text as untrusted context and validate provider output shape/length.

## Documentation drift corrected or called out by this PR

- Root `README.md` now calls the repository a scaffold and points to this known-issues review instead of implying fully green compose readiness.
- Root architecture text distinguishes current in-memory token hash storage from deferred Postgres persistence.
- Root architecture text records the current development `/analysis/*` browser-to-service path and the intended production broker direction.
- `apps/web/README.md` now describes the current production-shaped routes, TTS playback, AvatarKit shell, and direct `/analysis` development boundary.
- `services/api/README.md` now documents `LIVEKIT_INTERNAL_URL` / `LIVEKIT_PUBLIC_URL`, the in-memory runtime store, and the current auth hardening gaps.
- `services/ai-engine/AGENTS.md` now includes Gemini TTS and SpatialReal RTC egress attempt responsibilities.
- `docs/runbooks/tts-avatar-contract.md` now reflects the implemented SpatialReal session/RTC shell and current `livekit-client@2.16.1` compatibility pin.
- `docs/runbooks/local-livekit-media.md` now notes that `/analysis/*` is currently proxied publicly and that coturn is not wired into LiveKit TURN advertisement.
- `docs/runbooks/verification.md` now separates currently passing checks from known failing gates.
- `docs/implementation-plan.md` is labeled as a historical planning artifact where its older fake-STT/Postgres-persistence wording conflicts with current code.
- `tests/contract/README.md` and `tests/integration/README.md` now describe the real test state instead of placeholder text.

## Suggested follow-up PR sequence

1. Fix `analysis-engine` Docker build and add it to CI.
2. Move `/analysis/*` behind authenticated API broker routes.
3. Harden session creation and provider broker auth/rate limits.
4. Wire real Postgres persistence or explicitly keep the runtime in-memory until a later milestone.
5. Clean `.env.example` local provider defaults and production placeholder-secret checks.
6. Decide the TURN strategy and update LiveKit/coturn wiring accordingly.
7. Fix pyright errors or remove `pyright` from documented gates until it is intended to pass.
