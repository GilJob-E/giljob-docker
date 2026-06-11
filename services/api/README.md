# GilJob v2 API scaffold

Current slice: session/token API plus brokered interview-provider routes.

## Implemented now

- `GET /healthz` and `GET /readyz`.
- `POST /sessions` for direct API calls and `POST /api/sessions` through Caddy.
- Separate raw `sessionToken` and `reportToken` returned once in the create-session response.
- Purpose-separated HMAC hashes in the current server-side runtime record; raw tokens are not stored in those records.
- Compose requires `SESSION_TOKEN_HASH_SECRET` and `REPORT_TOKEN_HASH_SECRET`; direct production runs fail closed when `GILJOB_ENV=production` and either secret is missing.
- Postgres schema contract at `db/schema.sql` for a later persistence slice, including token-hash lookup indexes.
- LiveKit candidate join token issue when the split LiveKit env is configured:
  - `LIVEKIT_INTERNAL_URL` for API/container-side LiveKit calls, e.g. `ws://livekit:7880`.
  - `LIVEKIT_PUBLIC_URL` returned to browsers, e.g. `ws://127.0.0.1:7880` or a public `wss://...` endpoint.
  - `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` for token signing.
  - `LIVEKIT_URL` remains only a legacy fallback for older one-URL scaffold runs.
- SpatialReal AvatarKit RTC viewer token metadata is issued separately from the candidate participant token.
- Browser-facing broker routes for interview question generation, room TTS, and avatar session metadata:
  - `/api/interviews/{interviewId}/turns/{turnIndex}/question`
  - `/api/interviews/{interviewId}/turns/{turnIndex}/tts`
  - `/api/interviews/{interviewId}/avatar/session`
- Provider calls stay internal to `services/ai-engine`; public responses are redacted and do not expose raw provider keys, LiveKit tokens, SpatialReal session-token logs, or upstream error bodies.

## Important current limitations

- Runtime persistence is still in process memory, not Postgres. `db/schema.sql` is a contract for the next persistence slice.
- `POST /api/sessions` currently accepts caller-selected `sessionId`/`interviewId` values for local/demo flows. Production should generate ids server-side or reject duplicate/client-chosen ids.
- The create-session response currently includes both session and report tokens. A production flow should minimize report-token issuance and bind it to authorization.
- Question/TTS/avatar broker routes are browser-facing and redacted, but do not yet enforce a GilJob session bearer token, rate limit, or turn state machine.
- Analysis-engine control/polling is not brokered by this service yet; the web app currently reaches `/analysis/*` through Caddy as a development boundary.

## Deferred intentionally

- Real Postgres insert/query wiring.
- Explicit LiveKit RoomService `CreateRoom` calls, if later required beyond join-time room creation.
- Authenticated analysis broker routes for subscriber start/stop/signals.
- Full browser media QA and production session/user authorization.

## Follow

- Root `README.md` for current system state.
- `docs/reviews/main-branch-readiness-20260611.md` for the latest known issues.
- `tests/contract/` for token, HTTP, and redaction contracts.
