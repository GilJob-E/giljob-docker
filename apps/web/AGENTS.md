# apps/web Agent Contract

This module owns the browser-facing GilJob v2 web shell. Follow the root `AGENTS.md` plus these local rules.

## Current responsibilities
- Serve production-style routes: `/interviews/new`, `/interviews/:id/lobby`, `/interviews/:id/room`, and `/interviews/:id/report`.
- Keep the room route as the actual meeting room, not a prejoin/setup page.
- Follow `DESIGN.md`: light UI, Cal-style hierarchy, non-scrolling room surface, and restrained product chrome.
- Preserve the light, non-scrolling interview room with candidate/interviewer tiles.
- Keep interview context as a right sidebar, not an overlay that covers the interviewer screen.
- Preserve the manual button answer flow: interviewer question ends, the manual answer button enables, the candidate starts speaking, and the candidate presses again to end/finalize the answer; STT output belongs to the future GilJobE analysis-engine boundary, not a browser-owned transcription path.
- Use LiveKit only as the browser media/signaling client. Do not move token issuing into the browser.

## Security and privacy
- Keep visible text and logs token-safe with redaction.
- Never display or log raw token values, JWTs, LiveKit candidate tokens, session tokens, or report tokens.
- Do not persist sensitive data in `localStorage`.

## Tests
Run web/static contract tests after UI behavior changes:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.contract.test_web_static_contract -v
node --check apps/web/static/app.js
```
