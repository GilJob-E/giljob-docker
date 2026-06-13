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
- Legacy browser-facing question and room TTS routes are deprecated and return `deprecated_ai_engine_removed` with `reason=realtime_only`; avatar session metadata is API-owned and disabled/deferred unless separately verified.
- Session and avatar-session responses include safe sibling metadata for the experimental Realtime-audio browser bridge probe: `/api/sessions` returns `realtimeAvatarBridge`, and `/api/interviews/{interviewId}/avatar/session` returns `bridge`. `browserAudioBridgeEnabled` is controlled by `SPATIALREAL_BROWSER_AUDIO_BRIDGE_ENABLED` and stays outside token-bearing `client` metadata.
- Primary OpenAI Realtime broker/readiness/command routes: `/api/interviews/{interviewId}/realtime/session`, `/api/interviews/{interviewId}/realtime/call`, `/api/interviews/{interviewId}/turns/{turnIndex}/events`, `/api/interviews/{interviewId}/turns/{turnIndex}/vision-events`, `/api/interviews/{interviewId}/turns/{turnIndex}/mmm-ready`, and `/api/interviews/{interviewId}/turns/{turnIndex}/realtime/response`. The ordinary follow-up chain is answer → analysis-engine MMM/RNAS exact-turn result → API-authored `response.create` → browser relay to OpenAI Realtime.
- Live interviewer provider calls stay on the OpenAI Realtime broker path. Public responses are redacted and do not expose raw provider keys, LiveKit tokens, SpatialReal session-token logs, or upstream error bodies.
- Standard OpenAI provider keys stay server-only; browser responses expose only ephemeral Realtime client-secret shape, route metadata, redacted readiness status, and API-approved sideband commands. `OPENAI_REALTIME_PRIMARY=true` is the documented Realtime-only interviewer voice mode; Gemini fallback is not supported. Legacy fake/ElevenLabs route fallbacks are removed from the default runtime; SpatialReal/Avatar metadata remains disabled/deferred outside the priority-1 RNAS→Realtime response path.
- `SPATIALREAL_BROWSER_AUDIO_BRIDGE_ENABLED=false` is the stable default. If explicitly enabled, the browser may use `realtimeAvatarBridge`/`bridge.browserAudioBridgeEnabled` to attempt the `AvatarPlayer.publishAudio(track)` probe, but success remains experimental until kiostation browser evidence records `bridge_verified`; API responses must remain metadata-only and redacted.

Deferred intentionally:

- Real Postgres insert/query wiring.
- Explicit LiveKit RoomService `CreateRoom` calls, if later required beyond join-time room creation.
- Full browser media QA and AI engine media track subscribe.
- Production-grade interview state machine and final report generation.
