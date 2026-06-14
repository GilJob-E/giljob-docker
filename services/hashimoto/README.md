# services/hashimoto

Interviewer **strategy engine** for GilJob v2. It consumes per-turn final transcripts and maintains a per-session strategy package that the AI engine (Agent2) consults when generating the next question. It does not generate questions itself.

Follow:
- docs/implementation-plan.md
- docs/decisions/0001-state-stack.md
- the local `AGENTS.md`

## Role and boundary
- Input: final transcript text per turn (`stt.final` payload `text`), keyed by `session_id` + `turn_id`.
- Output: a reference strategy package (logic goal, focus point, persona guidance, resolved-question history for re-ask avoidance, topic/depth context), pulled on demand.
- The AI engine (Agent2) owns the actual question, tone, avatar, UI, and rubric. hashimoto never writes those.
- Internal only (not routed through Caddy). Multimodal anxiety/confidence input is accepted but unused in this slice.

## Env contract
```env
GEMINI_API_KEY=your-google-ai-studio-key
HASHIMOTO_ANALYSIS_MODEL=gemini-3.1-flash-lite
```
The analysis LLM uses `GEMINI_API_KEY`. Do not commit `.env` or real API keys.

## HTTP contract (internal)
| Method | Path | Purpose |
|---|---|---|
| POST | `/session` | Create a per-session engine from a resume (or topics). One call per interview, before the turn loop. |
| POST | `/submit_turn` | Submit a turn's final transcript; returns immediately (non-blocking). Deduplicated by `(session_id, turn_id)`. |
| GET | `/strategy?session_id=` | Pull the latest strategy package plus `ready` and `as_of_turn_id`. Non-blocking. |
| POST | `/session/end` | Tear down the session engine. |
| GET | `/healthz`, `/readyz` | Liveness/readiness. |

### POST /session
```json
{ "session_id": "sess_01J...", "resume_text": "...", "topic_count": 3, "job_url": "https://..." }
```
→ `201 { "session_id": "...", "current_topic": "...", "topics": ["...", "..."] }`

`job_url` is optional (JD focus keywords, see below). It is validated at the boundary
(http(s) only; loopback/private/link-local/reserved hosts rejected) and a `422` is
returned for a disallowed URL.

### POST /submit_turn
```json
{ "session_id": "sess_01J...", "turn_id": "turn_0003", "text": "저는 FastAPI 기반 백엔드를..." }
```
→ `202 { "accepted": true, "session_id": "...", "turn_id": "turn_0003" }`
(duplicate turn → `200 { "accepted": false, "reason": "duplicate_turn" }`)

### GET /strategy?session_id=
```json
{
  "ready": true,
  "session_id": "sess_01J...",
  "as_of_turn_id": "turn_0003",
  "session_complete": false,
  "interaction_strategy": {
    "logic_goal": "...",
    "logical_gap_to_bridge": "...",
    "interviewer_persona_guidance": { "intent": "...", "emotion_direction": "...", "focus_point": "..." },
    "current_context": {
      "topic": "...", "depth_level": 2, "topic_changed": false,
      "transition_hint": null, "multimodal_feedback_requirement": null,
      "resolved_history": [ { "proposition": "...", "status": "검증됨" } ]
    }
  }
}
```
Before the first analysis completes: `200 { "ready": false, "as_of_turn_id": null, "interaction_strategy": null }`.

## Consumption (Realtime API side)
The Realtime API pulls `/strategy` while preparing `/api/interviews/{interviewId}/turns/{turnIndex}/realtime/response` and merges the package into the server-authored `response.create` instructions as guidance only. If hashimoto is cold (`ready=false`), stale (`as_of_turn_id` does not match the prior answer turn), or unreachable, the API generates from the analysis-engine result alone. hashimoto must never block question generation.

**Wiring:** the API consumes hashimoto only when `HASHIMOTO_BASE_URL` is set. In `infra/docker-compose.yml` the `api` service defaults it to `http://hashimoto:8200`; hashimoto remains internal-only. The pull is non-blocking and best-effort (`HASHIMOTO_STRATEGY_TIMEOUT_SECONDS`, default `0.5`); on any cold/slow/error state the API falls back to analysis-engine guidance. Set `HASHIMOTO_BASE_URL=` (empty) to disable consumption entirely.

> `as_of_turn_id` reports the turn whose analysis the returned package was actually computed from (set when the background worker completes), **not** merely the last submitted turn. A turn that was submitted but not yet analyzed is never reported here, so `as_of_turn_id` always matches the package contents.

## Feed (Realtime API producer side)
The API is the producer in the realtime runtime: it receives each completed answer
transcript on `/api/interviews/{interviewId}/turns/{turnIndex}/events`, seeds
hashimoto with `POST /session` once (from `/api/sessions` fields such as
`candidateProfile`, `resumeText`, and URL-valued `job`), then forwards the completed
answer with `POST /submit_turn`. The feed is best-effort, gated on
`HASHIMOTO_BASE_URL`, and exposes only metadata such as `attempted`, `status`, and
`reason` in the public API response; raw transcript text is never echoed back.
`session_id` is the interview/session id and `turn_id` is `turn_{turnIndex:04d}`, so
hashimoto's `(session_id, turn_id)` dedup absorbs retries.

## JD (job-description) focus keywords
Optional. Pass `job_url` to `POST /session`; the posting is fetched once at engine
creation and analyzed into session focus keywords carried as metadata in the strategy
package (`current_context.focus_keywords`). No engine logic consumes them — they are a
hint for the question LLM. The fetch is an outbound call, so `job_url` is validated at
the request boundary and the whole step degrades gracefully (empty list) on failure.

## Not implemented yet
- Redis event-stream (`stt.final`) subscription; v1 uses HTTP `POST /submit_turn`.
