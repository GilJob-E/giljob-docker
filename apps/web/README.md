# apps/web

Browser-facing GilJob v2 web shell for the local self-hosted LiveKit interview-room scaffold.

## Current scope

- Serves production-shaped routes:
  - `/interviews/new`
  - `/interviews/:id/lobby`
  - `/interviews/:id/room`
  - `/interviews/:id/report`
- Serves static browser assets, including the vendored `livekit-client` bundle and SpatialReal AvatarKit RTC bundle path used by contract tests.
- Calls `/api/sessions` through Caddy to create a candidate session and receive `livekit.publicUrl`, `livekit.candidateToken`, and avatar-viewer token metadata.
- Joins the returned LiveKit room automatically from the room route; room UI is the meeting surface, not a prejoin form.
- Implements the manual push-to-talk answer loop: interviewer question/TTS ends, candidate starts an answer, candidate ends the answer, then the browser asks for the next question.
- Plays interviewer TTS audio returned through the API broker.
- Renders a SpatialReal AvatarKit RTC shell when avatar session metadata is available.
- In the current development boundary, directly calls `/analysis/subscriber/start`, `/analysis/subscriber/stop`, and `/analysis/signals` through Caddy to control/poll the GilJobE analysis-engine turn.
- Keeps raw session/report/LiveKit/avatar tokens out of visible UI and event logs.

## Known gaps

- `/analysis/*` is currently browser-accessible through Caddy. Production should move this behind authenticated API broker routes that validate the GilJob session token and turn id.
- `local-demo` is a local demo id only. Production session ids should be server-generated and collision-resistant.
- Browser autoplay can still fail for TTS; the room should distinguish successful audio playback from fallback text-only confirmation before opening the answer turn.
- Final report UI is still a placeholder.

## Local dependency note

Some contract tests expect browser vendor files to exist under `apps/web/node_modules`. From the repository root, run:

```bash
cd apps/web
npm ci --omit=dev --ignore-scripts
npm run check:js
cd ../..
```

## Follow

- Root `README.md` for current run instructions and known blockers.
- `DESIGN.md` for room layout constraints.
- `docs/runbooks/tts-avatar-contract.md` for TTS/avatar provider boundaries.
- `docs/runbooks/local-livekit-media.md` for LiveKit media smoke notes.
- `docs/reviews/main-branch-readiness-20260611.md` for the current readiness audit.
