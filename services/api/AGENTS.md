# services/api Agent Contract

This module owns the session/token API scaffold. Follow the root `AGENTS.md` plus these local rules.

## Current responsibilities
- Issue session and report public tokens once in the session-create response.
- Store purpose-separated HMAC hashes only in the current runtime record. This is a hash-only contract; raw token persistence is forbidden.
- Keep in mind that runtime persistence is still process-local; `db/schema.sql` is the Postgres contract for a later slice.
- Block internal API routes such as `/api/internal/*` from public ingress behavior.
- Issue LiveKit candidate join tokens and avatar-viewer tokens when LiveKit is configured.
- Preserve the `LIVEKIT_INTERNAL_URL` and `LIVEKIT_PUBLIC_URL` split.
- Fail closed for production secret requirements and required LiveKit configuration.
- Broker browser-facing interview question, TTS, and avatar-session routes to internal `ai-engine` routes; never expose provider keys, raw session tokens, or internal upstream error bodies.
- Keep direct `/ai/*`, `/tts/*`, and `/avatar/*` provider paths blocked at ingress; browser code should use `/api/interviews/...` routes.

## Known hardening debt
- `POST /api/sessions` currently supports caller-selected ids for local/demo flows. Production should generate ids server-side or reject duplicates/client-chosen ids.
- Browser-facing question/TTS/avatar broker routes are not yet protected by GilJob session bearer validation, rate limiting, or a turn state machine.
- Analysis-engine start/stop/signals are not yet brokered by this service; they are currently reached through public `/analysis/*` development ingress.
- Do not add new public broker routes without closing or explicitly documenting the same auth/authorization boundary.

## Forbidden changes
- Do not store raw token values in records, fixtures, logs, test output, or docs.
- Do not log JWTs, LiveKit tokens, session tokens, report tokens, provider keys, or secret env values.
- Do not weaken token TTL, purpose separation, or hash comparison behavior without an ADR and tests.

## Tests
Run API/token contracts after changes:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.contract.test_api_token_contract tests.contract.test_api_http_contract -v
```
