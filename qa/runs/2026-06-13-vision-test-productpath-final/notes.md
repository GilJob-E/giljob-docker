# .vision_test 제품경로 — 최종(프로소디 발화-바운드) (2026-06-13)

interviewId=qa-vision-test-final-1 · turnIndex 0 · 하니스 `productpath_signals.mjs`
**엔진 패치(누적, docker cp + restart)**:
1. `sentences.py` — 분석 단위 = 직전 문장 끝→이번 끝(묵음 포함). 발화 온셋(speech_start_s)은
   별도 보유.
2. `windowing.py _do_sentence` — 비전/nv = [start_s,end_s](end-to-end), 프로소디 = [speech_start_s,
   end_s](발화-바운드).  ← 이번 수정(사용자 선택).
3. `grounding.py`/`handoff.py` — 손목 가드 제거(유지).

## 검증

| 항목 | endtoend(프로소디 미바운드) | **final(프로소디 바운드)** |
|---|---|---|
| finger_sequence | [4,2,5] | **[4,2,5]** ✓ 유지 |
| hand_seen | 0.32 | 0.33 |
| sentence [8.x,19.x] fingers | [2,5] | [2,5] ✓ |
| fragment 손가락 펼침 | 4→2→5 | 4→2→5 ✓ |
| speech.duration_s | 22.42 | **13.85** (묵음 제외) |

- **손가락 시퀀스 보존 확정** — 프로소디만 발화-바운드로 바꿔도 비전/nv end-to-end는 그대로라
  4→2→5가 유지된다.
- **프로소디 윈도우 단축**(22.42→13.85s) = 발화-바운드가 묵음을 빼고 있음을 확인.
- 단, 두 런은 **서로 다른 라이브 take**(Realtime STT 분절이 달라짐)라 조음/속도 *절대값*은
  직접 비교 불가(이 클립은 발화가 희소해 rate가 본래 낮음). 바운딩 배선은 단위테스트로 결정적
  확인: `test_silent_gap_attaches_to_next_sentence` → `speech_start_s==9.0`, 프로소디는 거기서 슬라이스.

## 테스트

giljobe 오프라인 174 passed, 4 skipped(vLLM 게이트). 추가/수정: test_sentences(+1 회귀),
test_grounding(가드 제거 반영).

## 주의

- 소비자 응답은 여전히 변동적(이 런 answer_text는 페이지 상태 라인 — 정상 응답 미렌더). 분석
  (signals)은 정상. 제품경로 소비자 게이트는 별개 과제.
- **남은 지시**: eval grid 코드 제거("그냥 지워버려") — 런타임 eval-off라 동작 중립, 6파일 정리는
  별도 패스 예정(전체 계약 테스트 동반).
