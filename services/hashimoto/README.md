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
{ "session_id": "sess_01J...", "resume_text": "...", "topic_count": 3 }
```
→ `201 { "session_id": "...", "current_topic": "...", "topics": ["...", "..."] }`

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

## Consumption (AI engine side)
The AI engine pulls `/strategy` with a short timeout and merges the package into its question prompt as guidance only. If hashimoto is cold (`ready=false`) or unreachable, the AI engine generates from the transcript alone. hashimoto must never block question generation.

## Not implemented yet
- Redis event-stream (`stt.final`) subscription; v1 uses HTTP `POST /submit_turn`.
- JD (job-description) analysis.
