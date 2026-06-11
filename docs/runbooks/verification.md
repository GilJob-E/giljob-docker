# Verification Runbook

## Source/provenance

- Check `docs/source-manifest.md`.
- Do not use `/home/hoddukzoa/GilJob` as a source for v2 unless explicitly approved.
- For the 2026-06-11 readiness audit, the reviewed main commit was `34403b7c60cc43b2615e11351cc5d7cf37f84ca2`; see `docs/reviews/main-branch-readiness-20260611.md`.

## Current baseline checks

From a clean clone, install the web dependency lock before running contract tests because vendor asset tests depend on `apps/web/node_modules`.

```bash
python3 -m py_compile   services/api/server.py   services/api/app/livekit_tokens.py   services/api/app/token_contract.py   services/ai-engine/server.py   apps/web/server.py   services/agent1/server.py
node --check apps/web/static/app.js
node --check scripts/browser-join-smoke.mjs
(cd apps/web && npm ci --omit=dev --ignore-scripts)
(cd apps/web && npm run check:js)
(cd apps/web && npm audit --omit=dev --audit-level=high)
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -p 'test_*_contract.py' -v
./scripts/smoke.sh config
```

## Known failing gates at reviewed main

Keep these gates visible; do not claim the stack is fully green until follow-up implementation PRs close them.

```bash
# Fails at reviewed main because praat-parselmouth/native build tooling is missing.
docker build -q services/analysis-engine >/tmp/giljob-analysis-engine-image.txt

# Reports type issues in contract-test helper code at reviewed main.
npx --yes pyright
```

A clean clone can also fail the web static contract before `apps/web/npm ci`; that is a verification-order issue, not necessarily a product runtime bug.

## State/security contracts

Current implemented contracts:

- Test session token TTL = 7200 seconds.
- Test report token TTL = 2592000 seconds.
- Test raw tokens are not persisted in the current runtime records.
- Test browser-visible UI/log redaction for raw tokens and JWTs.
- Public `/api/internal/*` must be blocked at ingress.
- Public `/healthz` must pass.
- Public `/readyz` must return 404; container-internal API `/readyz` must pass.
- Direct public `/ai/*`, `/tts/*`, and `/avatar/*` provider routes must be blocked.

Current known gaps to verify as failing/unfinished until code changes land:

- `/analysis/*` is publicly proxied by Caddy for development; production should move it behind API auth.
- Browser-facing question/TTS/avatar broker routes do not yet validate a GilJob session bearer token per request.
- `POST /api/sessions` allows caller-selected demo ids and returns session/report tokens in one response.
- API runtime persistence is in process memory, not Postgres.
- Placeholder secret values are documented as unsafe but are not comprehensively rejected at production startup.

## Local self-hosted media room

- LiveKit is a direct browser media room, not a frontend-backend API proxy.
- API/container address must use `LIVEKIT_INTERNAL_URL` (for example `ws://livekit:7880`).
- Browser address must use `LIVEKIT_PUBLIC_URL` (for example `ws://127.0.0.1:7880`) and is returned as both `livekit.publicUrl` and backward-compatible `livekit.url`.
- Direct local media ports to verify: `7880/tcp`, `7881/tcp`, `50000-50100/udp`, plus coturn `3478`/`5349` when relay is used. Same-host browser smoke uses `LIVEKIT_NODE_IP=127.0.0.1`; external browser smoke must set it to the reachable host address.
- `./scripts/smoke.sh config` must pass base config, prove media config fails without `LIVEKIT_PUBLIC_URL`, and pass media config with explicit local values.
- `./scripts/smoke.sh media-up` starts `postgres`, `api`, `web`, `livekit`, and `coturn`; verify API/web health; verify `/sessions` returns an issued LiveKit token; and verify LiveKit `7880` responds. Remember that `analysis-engine` build is a known blocker until fixed.
- `./scripts/smoke.sh browser-join` should pass on a machine with Chrome; it proves the browser UI creates a session, connects to LiveKit, leaves the room, and does not expose raw tokens in visible text.

## Documentation-only PR checks

For documentation-only changes, at minimum run:

```bash
git diff --check
git diff --name-only origin/main...HEAD
```

Confirm the diff contains only Markdown/documentation assets. If docs mention executable verification, either run the command or clearly mark it as a known failing/future gate.
