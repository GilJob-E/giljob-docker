# services/api Agent Contract

This module owns the session/token API scaffold. Follow the root `AGENTS.md` plus these local rules.

## Current responsibilities
- Issue session and report public tokens once in the session-create response.
- Store purpose-separated HMAC hashes only. This is a hash-only contract; raw token persistence is forbidden.
- Block internal API routes such as `/api/internal/*` from public ingress behavior.
- Issue LiveKit candidate join tokens when LiveKit is configured.
- Preserve the `LIVEKIT_INTERNAL_URL` and `LIVEKIT_PUBLIC_URL` split.
- Fail closed for production secret requirements and required LiveKit configuration.
- Broker browser-facing interview question, TTS, and avatar-session routes to internal `ai-engine` routes; never expose provider keys, raw session tokens, or internal upstream error bodies.
- Keep direct `/ai/*`, `/tts/*`, and `/avatar/*` provider paths blocked at ingress; browser code should use `/api/interviews/...` routes.

## Forbidden changes
- Do not store raw token values in records, fixtures, logs, test output, or docs.
- Do not log JWTs, LiveKit tokens, session tokens, report tokens, or secret env values.
- Do not weaken token TTL, purpose separation, or hash comparison behavior without an ADR and tests.

## Tests
Run API/token contracts after changes:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.contract.test_api_token_contract tests.contract.test_api_http_contract -v
```
