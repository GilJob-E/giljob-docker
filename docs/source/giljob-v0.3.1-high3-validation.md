# GilJob v0.3.1 High Closure Validation

## Verdict
HIGH_CLOSED

## H-01
CLOSED

Evidence lines:
- Lines 763-767 define separate `SESSION_SIGNING_SECRET` and `REPORT_SIGNING_SECRET`, and set `.env` TTLs to `SESSION_TOKEN_TTL_SECONDS=7200` and `REPORT_TOKEN_TTL_SECONDS=2592000`.
- Lines 1081-1085 token table matches session `기본 2h / SESSION_TOKEN_TTL_SECONDS=7200` and report `기본 30d / REPORT_TOKEN_TTL_SECONDS=2592000`.
- Lines 1091-1092 restate canonical TTL source as session `7200 # 2h` and report `2592000 # 30d`.
- Lines 1100-1104 define session token hash with `SESSION_SIGNING_SECRET`, report token hash with `REPORT_SIGNING_SECRET`, and explicitly require the secrets/verification paths to be separate.

## H-02
CLOSED

Evidence lines:
- Lines 662-663 Caddy routes only `@health path /healthz /readyz` to the API.
- Lines 998-1000 API endpoint list exposes `GET /healthz` and `GET /readyz`.
- Lines 2607-2608 runbook status checks curl only `/healthz` and `/readyz`.
- Lines 2715-2722 Docker smoke uses public `https://${PUBLIC_DOMAIN}/healthz` and `/readyz`, plus container-internal `/healthz` checks; no `/api/healthz` smoke path is present.
- Content search for `/api/healthz` returned 0 matches in the spec.

## H-03
CLOSED

Evidence lines:
- Lines 1035-1058 show `POST /api/sessions` response with `"state": "WAITING_FRONTEND"`.
- Lines 1063-1074 state successful `POST /api/sessions` always returns `WAITING_FRONTEND`, inserts/uses `CREATED` only inside the transaction, audits `CREATED → WAITING_FRONTEND` before commit/response, and clients must never rely on observing `CREATED` from a successful POST.
- Lines 1245-1246 mark `CREATED` as transaction-local/transient and `WAITING_FRONTEND` as the canonical successful response state.
- Lines 1264-1274 restate the session creation algorithm: DB insert `CREATED`, hash persist, audit transition `CREATED → WAITING_FRONTEND`, response `state=WAITING_FRONTEND`, and frontend/engine do not implement `CREATED` polling.
- Lines 1292-1301 include the previously omitted documented transitions: `AVATAR_SPEAKING → READY`, `DECIDING_NEXT → CANDIDATE_ANSWERING`, active-to-`REPORT_GENERATING`, active-to-`FAILED_*`, and `FAILED_* → ENDED` with DB-seed expansion notes.
- Lines 1569-1570 require concrete seed rows and no wildcard insertions.
- Lines 1579-1585 seed `AVATAR_SPEAKING → READY`, `DECIDING_NEXT → CANDIDATE_ANSWERING`, and `REPORT_GENERATING → ENDED` in base transitions.
- Lines 1588-1605 define concrete active states and concrete failure states.
- Lines 1607-1623 expand active-to-`REPORT_GENERATING`, active-to-concrete-failure, and concrete-failure-to-`ENDED` into `allowed_state_transitions`.

## Residual notes
None.
