# MMM 보완 설계 — 7개 벤치마크 매핑

작성: 2026-06-12. 입력: `dataset_characteristics.md` + 7개 벤치 README + 소넷 조사 7건.
기준: MMM(analysis-engine/GilJobE 분석 경로) 관점에서 각 벤치가 요구하는 능력과 현 갭.

## 측정의 종착은 항상 소비자 LLM 응답이다

모든 벤치 점수는 "진짜 답변" — 즉 **소비자 LLM(OpenAI Realtime)의 응답** — 을 채점한다.
MMM(분석 레인)은 그 응답 자체를 만들지 않는다. MMM이 LLM 응답에 거는 레버는 둘뿐이다:

1. **언제 응답할지 — 게이트 타이밍** (`full_mmm_ready`). FD-Bench V1 latency.
2. **무엇을 재료로 줄지 — fragment** (turn_handoff → response.create instructions).
   IFEval(형식·지시준수)·HarmBench(안전)·Audio MC(기억/일관)·QIVD(비전 측정값).

⚠️ 따라서 "분석 레인 내부 지표"(게이트 단계 타임스탬프, fragment 형식 self-check)는 **component
진단**이지 벤치 점수가 아니다. **MMM 보완의 효과는 반드시 LLM 응답을 측정해 검증한다**
(end-to-end). 게이트를 빨리 열어도 LLM 첫 토큰이 늦으면 체감은 그대로고, fragment 형식이
깨끗해도 LLM이 지시를 어기면 IFEval은 실패다.

분석 레인 철칙(설계 제약): **LLM 호출 0**(turn_handoff는 순수 파이썬), **실시간성 ★1순위**.

## 매핑 표 (측정 = LLM 응답, MMM 레버 = 언제/무엇)

| # | 벤치 | 벤치 점수(LLM 응답 측정) | MMM 레버 | component 보조지표 |
|---|---|---|---|---|
| 1 | FD-Bench V1 | first_response_latency = LLM 첫 델타−발화종료 (end-to-end) | 게이트 타이밍 | mmm_ready_latency 단계 분해 |
| 4 | QIVD | 답변 정확도+timing (LLM이 비전 측정값으로 답 구성) | fragment(비전 측정값) | 손가락/제스처 레인 정확도(95문항 0.77) |
| 5 | Audio MC | 마지막 LLM 응답의 rubric pass(기억·일관) | fragment(누적 사실/제약) | 추출 슬롯 충실도 |
| 6 | BigBench Audio | LLM reasoning 정확도 | (MMM 무관) | 전사 충실도만 |
| 7 | IFEval VoiceBench | LLM 응답의 spoken-지시 준수 | fragment(주입 영향) | 오디오이해/위반 분리 |
| 8 | IFEval Text | LLM 응답의 지시 준수(strict acc) | fragment(주입 on/off) | fragment 형식 self-check |
| 9 | HarmBench | LLM 응답의 거부/안전(classifier) | fragment(위험 전파 차단) | redaction 계약 |

## 우선순위 (MMM 보완 → LLM 응답으로 검증)

1. **FD-Bench V1 end-to-end latency 하니스** — 벤치 점수 = LLM 첫 델타까지. 게이트 단계 계측은
   그 안의 MMM 몫 분해(보조). 제품 경로(Realtime 응답) 포함 필수 — 현재 `409
   analysis_result_unavailable`로 first delta까지 못 가는 게 병목(PR #19 RNAS 게이트와 얽힘).
   보완: ① 게이트 단계 타임스탬프 노출 ② live analysis result가 response-create까지 도달 →
   first-delta latency 측정 가능. 효과 = end-to-end latency 감소로 증명.
2. **fragment 주입 A/B → LLM 응답 채점** — IFEval(형식·지시준수)+HarmBench(안전) 동시.
   fragment 형식 self-check(개행 0·≤880자·금칙어·전사 사이드채널)는 전제(쓰레기 입력 차단).
   진짜 측정 = fragment on/off로 같은 IFEval 프롬프트를 LLM에 넣어 strict acc 차이, HarmBench로
   위험 발화가 fragment 경유 다음 질문에 전파되는지 LLM 응답 채점.
3. **QIVD 비전 fragment 운반·검증** — 손가락/제스처 레인 측정값(95문항 0.77, 임계 최적화 완료)을
   fragment로 LLM에 줘서 답변 정확도 측정. 손가락 카운트 정확도는 레인 단독 검증 가능(완료).
4. **Audio MC 사실/제약 추출 슬롯** — 턴 명시 수치를 순수 규칙으로 추출 운반, 마지막 LLM 응답을
   rubric 채점. 누적·모순 판단은 소비자 LLM.
5. **BigBench/VoiceBench** — MMM 무관(순수 reasoning·ASR). 전사 충실도·무응답 분리만 기여.

## QIVD 비전 subset 실측 결과 (완료, 이번 워크스트림 1단계)

`labels.json` 2,900개 중 hands/pose 레인이 LLM 0으로 측정 가능한 후보:
- 손가락 카운팅 95개 · 손 제스처 47개 · 자세/방향 일부.
- 임계 스윕 최적화 완료: 레인답변가능 91문항 0.714→0.769(GilJobE feat/grounding-hands-whisper).
- 나머지 ~80%(객체 인식·OCR·장면)는 VLM 모델 영역(이 워크스트림 밖).
