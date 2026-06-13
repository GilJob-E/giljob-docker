# giljob-docker realtime 기준 hashimoto 탑재/인터페이스 context

현재 default 작업 기준은 `main`이 아니라 `realtime`이다. 과거 `ai-engine` 중심 구조는 제거되었고, `services/ai-engine`은 default runtime에 존재하지 않는다. 따라서 hashimoto 소비/연동 작업은 API realtime response-create 흐름 기준으로 봐야 한다.

## 현재 탑재 형상

- hashimoto는 `services/hashimoto` internal sidecar 서비스다.
- Docker Compose에는 `hashimoto` 서비스가 internal-only로 추가되어 있고 public Caddy route는 없다.
- API 서비스는 `HASHIMOTO_BASE_URL`로 hashimoto에 접근한다.
- Compose 기본값:
  - API: `HASHIMOTO_BASE_URL=http://hashimoto:8200`
  - hashimoto: `HASHIMOTO_ANALYSIS_MODEL=gemini-3.1-flash-lite`
- `.env.example`에도 `HASHIMOTO_BASE_URL=http://hashimoto:8200`가 있다.
- hashimoto LLM credential은 `GEMINI_API_KEY`이며 hashimoto container env로 주입된다.

## 현재 연결된 방향: API -> hashimoto feed

PR10은 예전 `ai-engine` feed 구현을 realtime 구조에 맞춰 API로 포팅한 상태다.

API는 `/api/sessions` 요청에서 resume seed를 메모리에 저장한다. Seed 추출 필드는 `resume_text`, `resumeText`, `candidateProfile`, `job_url`, `jobUrl`, URL-valued `job`이다.

이후 candidate 답변 transcript 완료 이벤트가 API에 들어오면 API가 hashimoto에 입력을 보낸다.

- 입력 endpoint: `POST /api/interviews/{interviewId}/turns/{turnIndex}/events`
- event kind: `transcript.completed` 또는 `analysis.transcript.completed`
- transcript 위치: `detail.transcript`, `detail.text`, top-level `transcript`, top-level `text`

API 내부 동작:

1. `HASHIMOTO_BASE_URL`이 비어 있으면 no-op.
2. transcript가 비어 있으면 no-op.
3. 해당 session/interview seed가 있으면 hashimoto `POST /session`을 1회 bootstrap.
4. hashimoto `POST /submit_turn` 호출.
5. `submit_turn`이 404이면 bootstrap memo를 지우고 `/session` 1회 재시도 후 `/submit_turn` 재시도.

ID 규칙:

- `session_id = interviewId/sessionId`
- `turn_id = turn_{turnIndex:04d}`
- 예: `turnIndex=1` -> `turn_0001`

공개 API 응답에는 transcript 원문을 싣지 않는다. 대신 `hashimoto` 메타데이터만 노출한다.

```json
{
  "hashimoto": {
    "attempted": true,
    "status": 202,
    "endpoint": "/submit_turn"
  }
}
```

비활성/누락 예:

```json
{ "attempted": false, "reason": "disabled" }
{ "attempted": false, "reason": "empty_transcript" }
{ "attempted": false, "reason": "missing_session_seed" }
```

## hashimoto internal HTTP contract

### POST /session

세션별 hashimoto engine 생성. 같은 `session_id`로 다시 호출하면 idempotent하게 기존 session을 반환한다.

```json
{
  "session_id": "local-demo",
  "resume_text": "...",
  "topic_count": 3,
  "job_url": "https://..."
}
```

### POST /submit_turn

최종 답변 transcript 제출. 비동기 분석 큐에 넣고 즉시 반환한다. `(session_id, turn_id)` 기준 dedup.

```json
{
  "session_id": "local-demo",
  "turn_id": "turn_0001",
  "text": "candidate final answer transcript"
}
```

### GET /strategy?session_id=

hashimoto output 소비 endpoint. Non-blocking이다.

분석 전:

```json
{
  "ready": false,
  "session_id": "local-demo",
  "as_of_turn_id": null,
  "session_complete": false,
  "interaction_strategy": null
}
```

분석 완료 후:

```json
{
  "ready": true,
  "session_id": "local-demo",
  "as_of_turn_id": "turn_0001",
  "session_complete": false,
  "interaction_strategy": {
    "logic_goal": "...",
    "logical_gap_to_bridge": "...",
    "interviewer_persona_guidance": {
      "intent": "...",
      "emotion_direction": "...",
      "focus_point": "..."
    },
    "current_context": {
      "topic": "...",
      "depth_level": 2,
      "topic_changed": false,
      "transition_hint": null,
      "multimodal_feedback_requirement": null,
      "resolved_history": []
    }
  }
}
```

중요: `as_of_turn_id`는 제출된 turn이 아니라 분석 완료되어 package에 실제 반영된 turn이다. 소비자는 반드시 `as_of_turn_id`와 필요한 turn id를 비교해야 한다.

### POST /session/end

세션 engine teardown.

```json
{ "session_id": "local-demo" }
```

## 현재 hashimoto output 소비자는 아직 붙어 있지 않음

현재 realtime 질문 생성 파이프라인은 `services/api/server.py`의 `create_realtime_response()`가 소유한다.

현 흐름:

1. turn 1은 bootstrap opening question을 바로 만든다.
2. turn N > 1은 prior answer인 `turnIndex - 1`의 MMM/readiness 및 `analysis-engine` 결과를 요구한다.
3. API가 `analysis-engine`의 `/realtime/turn-results?interviewId=&turnIndex=` 결과에서 `candidateSafePromptFragment`를 뽑아 OpenAI Realtime `response.create` instructions에 넣는다.
4. 브라우저는 API가 만든 sideband `response.create` command를 relay한다.

즉 현재 질문 생성에 실제 반영되는 소비자는 hashimoto가 아니라 `analysis-engine` 결과다. hashimoto는 transcript feed를 받아 내부 strategy를 만들 수 있지만, `/strategy`를 pull해서 `response.create` instructions에 merge하는 작업은 아직 필요하다.

## hashimoto output 소비를 붙일 후보 지점

추천 지점은 `services/api/server.py`의 `create_realtime_response()` 내부, `analysis-engine` 결과가 검증되고 `fragment`가 만들어진 뒤 `instructions`를 구성하는 부분이다.

현재 instructions 형태:

```python
instructions = (
    "Use this candidate-safe guidance from the previous answer to ask the next Korean interview question. "
    "Do not mention internal infrastructure, private gating, or analysis labels. "
    f"Guidance: {fragment}"
)
```

여기에 hashimoto `/strategy?session_id={interview_id}`를 best-effort pull해서 다음 조건을 만족할 때만 candidate-safe guidance로 병합하는 방식이 자연스럽다.

권장 조건:

- `HASHIMOTO_BASE_URL`이 설정되어 있어야 함.
- `/strategy` 호출 timeout은 짧게. 예: 0.3s~0.5s.
- hashimoto 실패/timeout/404/`ready=false`는 질문 생성을 막지 않음.
- `ready=true`일 때만 사용.
- `as_of_turn_id`가 현재 분석 대상 turn과 일치해야 함.
  - `analysis_turn_index = turn_index - 1`
  - 기대 turn id: `turn_{analysis_turn_index:04d}`
- `interaction_strategy` 중 candidate-safe한 필드만 prompt에 요약 병합.
- raw transcript나 내부 상태 debug를 candidate-facing instructions에 직접 넣지 않음.
- `topic_changed`, `transition_hint`, `session_complete`는 단순 guidance로 쓸지 세션 제어 신호로 격상할지 별도 계약 필요.

## 세션 종료 관련 주의점

hashimoto `/strategy` 응답에는 `session_complete`가 있다. 하지만 giljob realtime 시스템은 현재 이 값을 시스템적으로 강제하지 않는다. 따라서 hashimoto 내부 정책상 종료 타이밍이 되더라도 API/OpenAI Realtime 쪽에서 이를 읽고 처리하지 않으면 실제 면접은 종료되지 않는다.

세션 종료를 강제하려면 별도 계약이 필요하다.

권장 방향:

- API가 `/strategy` pull 결과에서 `session_complete=true`를 감지.
- 일반 다음 질문 instructions 대신 마무리 발화 instructions 또는 finalize flag를 반환.
- aiengine/frontend 쪽은 이 flag를 보고 finalize API call 또는 session end workflow를 호출.

## 주의할 문서 잔상

`services/hashimoto/README.md`에는 아직 “Consumption (AI engine side)”처럼 예전 ai-engine 기준 표현이 일부 남아 있다. 현재 `realtime` 기준 실제 소비자는 `ai-engine`이 아니며, 소비 작업은 API realtime response-create 흐름에 붙여야 한다.

## 검증 기준

PR10 merge 시 확인된 테스트:

- `tests/contract/test_api_hashimoto_feed.py`
- 전체 contract suite: 116 tests OK, 12 skipped
- `node --check apps/web/static/app.js`
- `git diff --check`
- `docker compose -f infra/docker-compose.yml config --quiet`

hashimoto output 소비를 붙이면 별도 contract test를 추가해서 다음을 검증해야 한다.

- hashimoto unavailable이면 기존 analysis-engine 기반 질문 생성이 유지된다.
- `ready=false`이면 질문 생성이 막히지 않는다.
- `as_of_turn_id`가 현재 prior turn과 다르면 무시한다.
- `ready=true` + exact turn match일 때만 strategy guidance가 instructions에 병합된다.
- 공개 응답과 logs에 raw transcript/secrets가 노출되지 않는다.
