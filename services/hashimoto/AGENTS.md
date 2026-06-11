# services/hashimoto Agent Contract

This module owns the bounded hashimoto strategy engine as an internal service. Follow the root `AGENTS.md` plus these local rules. This service runs inside the single-server, multi-container Docker Compose deployment and is reachable only on the internal network.

## Current responsibilities
- Consume per-turn final transcript text only, keyed by `session_id` and `turn_id` (the `stt.final` payload `text`).
- Maintain one in-memory hashimoto engine per `session_id` (a session registry); never share interview state across sessions.
- Asynchronously update a per-session interviewer **strategy package** in the background using `GEMINI_API_KEY` from environment configuration; never commit or print its value.
- Expose a pull endpoint so the question generator can read the latest strategy package on demand without blocking.
- Deduplicate by `(session_id, turn_id)`; a repeated `turn_id` is ignored so an at-least-once delivery never advances engine state twice.
- Provide health/readiness endpoints for the container.

## Hard boundaries
- This service **does not generate questions**. It only produces a reference strategy package; the AI engine (Agent2) owns the actual interview question, tone, avatar, and UI output.
- Do not write any field of the AI engine output (no `speak_text`, `avatar`, `ui`, or `rubric`). Slot fulfillment scores are internal state only and are not exposed as evaluation.
- This service is **internal only**; it is not routed through Caddy and must not be publicly exposed.
- Do not ingest raw media or audio. Input is transcript text only.
- Multimodal anxiety/confidence input is accepted for API compatibility but is unused in this slice and defaults to neutral values.

## Job-description (JD) focus keywords
- Optional. `POST /session` accepts `job_url`; the posting is fetched once at engine
  creation and analyzed into session `focus_keywords` that ride along as metadata in
  the strategy package (`current_context.focus_keywords`). No engine logic uses them.
- `job_url` is validated at the request boundary (http(s) only; loopback/private/
  link-local/reserved hosts rejected) because this internal service makes the fetch.
  Fetch/analysis failure degrades gracefully to an empty keyword list.

## Not implemented here yet
- Redis event-stream subscription; the v1 boundary is HTTP `POST /submit_turn`, and the event-bus form is a later slice.
- Multi-process or multi-worker scaling; one asyncio event loop hosts one worker per session.

## Tests
Run the hashimoto contract test after changes:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.contract.test_hashimoto_contract -v
```
