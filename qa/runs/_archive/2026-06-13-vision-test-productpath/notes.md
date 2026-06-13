# .vision_test 제품경로 런 — 관찰·결론 (2026-06-13)

하니스: `qa/runs/_tools/productpath_signals.mjs --video qa/.vision_test.mp4`
조건: `meta.json` (실 OpenAI Realtime 전사 포함 풀스택, interviewId=qa-vision-test-1, turnIndex 0)
클립: 손가락 카운팅 — 후보가 "지금 몇 개의 손가락을 펴고 있는지 대답해 주세요"라고 말하며 손 제시.

## 결과 요약 (signals.json = `/analysis/signals` 정본 페이로드)

| 항목 | 값 |
|---|---|
| 레코드 | 6 (sentence×5 + turn_end) |
| 커버리지(turnHandoff.meta) | speech 2 · visual 5 · nv 4 |
| 전사(실 Realtime STT) | 75자 — "…몇 개의 손가락을 펴고 있는지 대답해 주세요" + "그럼 제가 몇" |
| speech | 2윈도우 4.93s · F0 sd 3.59 st · 조음 3.68음절/s · 음량 후반 +5.14 dB |
| visual | face 92프레임(1.0) · **hand 검출률 0.19** · **손가락 펼침 4 (7.71~8.84s)** · 손목 0%(제스처 관측불가) · 미소 0 · 시선이탈 0.218 |
| nonverbal | neutral 50% / hesitant 50% · intensity 0.35 |
| 답변 레이턴시(종료 클릭→) | 6.06s |

## 결론

1. **MediaPipe Hands 레인이 분석 레벨에서 작동.** 안정 구간(7.71~8.84s)에서 **손가락 펼침 4개**를
   추출(핀 f817f81의 Hands 레인). hand_seen_ratio 0.19로 손 존재 확인. = 이 클립의 목적(손가락
   카운팅) 신호가 turnHandoff에 실제로 잡힌다.
2. **제품 경로 갭은 "fragment에 비전 부재"가 아니라 "모순 가드 + 소비자 미사용"으로 정밀화됨.**
   candidate-fragment(`candidate-fragment.json`)에 `손가락 펼침 4`가 **들어 있다**. 그런데 바로
   뒤 `손동작 관측 불가(평가 금지)`(손목 0% 유래)가 붙어 신호가 상충하고, 소비자 LLM은 결국
   "손을 볼 수 없어서 몇 개인지 알 수 없어요"로 회피. → 갭의 위치가 **프래그먼트 구성(모순)
   ↔ 소비자 주입/사용** 둘 중 하나로 좁혀진다. (기존 메모리 `qivd-product-path-gap`는 Hands 레인
   이전 관찰일 가능성 — 갱신 후보.)
3. nonverbal hesitant 50% + prompt_block "그럼 제가 몇 …(18~20s) 에너지 +34.8dB" — 발화 머뭇거림이
   객관 레인에 반영됨.

## 한계 / 다음

- y4m 루프(640x480@15fps): 손가락 디테일은 이 해상도/3fps 서브샘플 한계 안에서의 수치.
- **갭 정밀화 후속**: API가 `candidatePromptFragment`를 실제 `response.create`에 주입하는지,
  그리고 "손가락 펼침 N" vs "손동작 관측 불가" 모순을 프래그먼트 빌더에서 해소할지 확인 필요.
