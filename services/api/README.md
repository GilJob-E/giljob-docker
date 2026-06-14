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
- Legacy browser-facing question and room TTS routes are deprecated and return `deprecated_ai_engine_removed` with `reason=realtime_only`; avatar session metadata is API-owned and disabled/deferred unless SDK Mode Web is explicitly configured.
- Session responses include safe sibling `avatarSdkMode` metadata. `/api/interviews/{interviewId}/avatar/session` returns token-bearing `client.spatialrealSdk` only after `SPATIALREAL_SDK_MODE_WEB_ENABLED=true` and required SpatialReal config are present. `SPATIALREAL_API_KEY` stays server-only; the API mints short-lived SpatialReal session tokens and never returns provider keys or upstream error bodies.
- Primary OpenAI Realtime broker/readiness/command routes: `/api/interviews/{interviewId}/realtime/session`, `/api/interviews/{interviewId}/realtime/call`, `/api/interviews/{interviewId}/turns/{turnIndex}/events`, `/api/interviews/{interviewId}/turns/{turnIndex}/vision-events`, `/api/interviews/{interviewId}/turns/{turnIndex}/mmm-ready`, and `/api/interviews/{interviewId}/turns/{turnIndex}/realtime/response`. The ordinary follow-up chain is answer → analysis-engine exact-turn MMM result → Hashimoto strategy adapter → API-authored `response.create` → browser relay to OpenAI Realtime.
- Hashimoto is consumed on the same Realtime response path: after the analysis-engine exact-turn result is accepted, the API best-effort pulls hashimoto `/strategy`, requires `as_of_turn_id` to match the prior answer turn, and adds only candidate-safe strategy guidance to the server-authored `response.create` instructions.
- Live interviewer provider calls stay on the OpenAI Realtime broker path. Public responses are redacted and do not expose raw provider keys, LiveKit tokens, SpatialReal session-token logs, or upstream error bodies.
- Standard OpenAI provider keys stay server-only; browser responses expose only ephemeral Realtime client-secret shape, route metadata, redacted readiness status, and API-approved sideband commands. `OPENAI_REALTIME_PRIMARY=true` is the documented Realtime-only interviewer voice mode; Gemini fallback is not supported. Legacy fake/ElevenLabs route fallbacks are removed from the default runtime; SpatialReal/Avatar SDK output remains separate from the priority-1 analysis-engine/Hashimoto → Realtime response gate and cannot bypass `full_mmm_ready`.
- Legacy Realtime-audio browser bridge probes are removed from the default API contract. Keep LiveKit/AvatarKit RTC out of the SDK Mode Web path unless a later ADR reintroduces it explicitly.

Deferred intentionally:

- Real Postgres insert/query wiring.
- Explicit LiveKit RoomService `CreateRoom` calls, if later required beyond join-time room creation.
- Full browser media QA and AI engine media track subscribe.
- Production-grade interview state machine and final report generation.
