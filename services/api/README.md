# GilJob v2 API scaffold

Current slice: session/token API plus brokered interview-provider routes.

Implemented now:

- `GET /healthz` and `GET /readyz`.
- `POST /sessions` for direct API calls and `POST /api/sessions` through Caddy.
- Separate raw `sessionToken` and `reportToken` returned once in the create-session response.
- Purpose-separated HMAC hashes in server-side records; raw tokens are not stored in those records.
- Compose requires `SESSION_TOKEN_HASH_SECRET` and `REPORT_TOKEN_HASH_SECRET`; direct production runs fail closed when `GILJOB_ENV=production` and either secret is missing.
- Postgres schema contract at `db/schema.sql` for the later persistence slice, including unique lookup indexes for both token hash paths.
- LiveKit candidate join token issue when `LIVEKIT_INTERNAL_URL`/`LIVEKIT_PUBLIC_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` are configured; base scaffold returns `tokenStatus: not_configured` otherwise.
- Browser-facing broker routes for interview question generation, room TTS, and avatar session metadata: `/api/interviews/{interviewId}/turns/{turnIndex}/question`, `/api/interviews/{interviewId}/turns/{turnIndex}/tts`, and `/api/interviews/{interviewId}/avatar/session`.
- OpenAI Realtime broker/readiness routes: `/api/interviews/{interviewId}/realtime/session`, `/api/interviews/{interviewId}/realtime/call`, `/api/interviews/{interviewId}/turns/{turnIndex}/events`, `/api/interviews/{interviewId}/turns/{turnIndex}/vision-events`, and `/api/interviews/{interviewId}/turns/{turnIndex}/mmm-ready`.
- Provider calls stay internal to `services/ai-engine`; public responses are redacted and do not expose raw provider keys, LiveKit tokens, SpatialReal session-token logs, or upstream error bodies.
- Standard OpenAI provider keys stay server-only; browser responses expose only ephemeral Realtime client-secret shape, route metadata, and redacted readiness status.

Deferred intentionally:

- Real Postgres insert/query wiring.
- Explicit LiveKit RoomService `CreateRoom` calls, if later required beyond join-time room creation.
- Full browser media QA and AI engine media track subscribe.
- Production-grade interview state machine and final report generation.
