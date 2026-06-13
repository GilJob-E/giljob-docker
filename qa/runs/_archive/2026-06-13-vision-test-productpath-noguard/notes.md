# .vision_test 제품경로 — 손목 가드 제거 후 재측정 (2026-06-13)

하니스: `qa/runs/_tools/productpath_signals.mjs --video qa/.vision_test.mp4`
조건: `meta.json` (실 OpenAI Realtime, interviewId=qa-vision-test-noguard-1, turnIndex 0)
**엔진 핫패치**: `grounding.py`/`handoff.py`의 손목 미가시 "관측 불가(평가 금지)" 가드 라인 제거
→ docker cp + restart (giljob-qa-analysis-engine-1).

## 변경 동기

직전 런(`../2026-06-13-vision-test-productpath`)에서 MediaPipe Hands는 손가락 4개를 잡았고
candidate-fragment에도 `손가락 펼침 4`가 실렸지만, 바로 뒤 `손동작 관측 불가(평가 금지)`
(손목 0% 유래)가 신호를 상충시켜 소비자 LLM이 "손을 볼 수 없다"고 회피했다. 가드가 갭의 원인인지
검증하려 그 라인만 제거하고 동일 클립 재실행.

## 결과 — 소비자 응답 역전 (★ 갭 원인 확정)

| | 가드 있음 (직전) | **가드 제거 (이번)** |
|---|---|---|
| candidate-fragment 시각 | `손가락 펼침 4 · 손동작 관측 불가(평가 금지)` | `손가락 펼침 4` (가드 없음) |
| **소비자 LLM 답변** | "실제로 손을 볼 수 없어서 몇 개인지 알 수 없어요" | **"엄지부터 차례대로 네 개가 펴져 있는 걸로 보여요"** |
| 답변 레이턴시 | 6.06s | **4.04s** |
| visual 커버리지 | 5 windows · hand 0.19 | 4 windows · hand 0.28 |
| 손가락 펼침(prompt_block) | 4 (7.71~8.84s) | 4 (7.63~8.9s) |

## 결론

1. **제품경로 비전 갭의 원인 = 모순 가드.** 손가락 수치는 이미 fragment에 있었고, "관측 불가·평가
   금지" 한 줄을 빼자 소비자 LLM이 곧바로 **손가락 4개를 정확히 사용**해 답했다. 분석 레인 부재가
   아니라 **프래그먼트의 자기모순(N개 펼침 + 평가 금지)** 이 소비자 회피를 유발했음이 실측으로 확정.
2. **기존 메모리 `qivd-product-path-gap`("fragment에 의미 비전 부재") 갱신 필요** — Hands 레인(f817f81)
   이후 fragment에 비전은 있었고, 진짜 병목은 가드 라인이었다.
3. 부수효과: 레이턴시 -2s(회피 서사 생성 대신 짧은 사실 답변). 단조/속도 등 음성 실측은 양 런 일관.

## 주의 / 후속

- 손목 미가시 시 가드를 *전면 삭제*하면, **손이 정말 안 보이는** 일반 답변에서 소비자가 손동작을
  환각할 위험이 생긴다(이 클립은 손가락이 검출됐기에 안전). 더 안전한 설계: **손가락이 검출됐을
  때만**(finger_sequence 존재) 가드를 생략하고, 손가락도 없으면 가드 유지 — 후속 검토 권장.
- giljobe 코드 변경은 워킹트리(feat/grounding-hands-whisper @ f817f81)에 **미커밋**. 유지하려면
  커밋+핀 갱신, 되돌리려면 `git checkout -- src/giljobe/analysis/grounding.py src/giljobe/emit/handoff.py`
  후 엔진 재빌드/재시작(현재 컨테이너는 패치본 실행 중).
