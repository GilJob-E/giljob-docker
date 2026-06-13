# .audio_test 제품경로 — 최신 엔진 정본 (2026-06-13)

interviewId=qa-audio-test-final-1 · turnIndex 0 · 하니스 `productpath_signals.mjs`
**엔진(누적 패치 3개, vision-test-final과 동일 상태)**:
1. `sentences.py` — 분석 단위 = 직전 문장 끝→이번 끝(묵음 포함), 발화 온셋 별도 보유.
2. `windowing.py` — 비전/nv = end-to-end, 프로소디 = 발화-바운드.
3. `grounding.py`/`handoff.py` — 손목 가드 제거.

이 런이 `.audio_test`의 **up-to-date signal**(이전 `../2026-06-13-audio-test-productpath`는 패치 전
엔진이라 stale).

## 결과 요약 (signals.json = `/analysis/signals` 정본 페이로드)

| 항목 | 값 |
|---|---|
| 레코드 | 2 (sentence×1 + turn_end) |
| 커버리지 | speech 1 · visual 1 · nv 1 |
| 전사(실 Realtime STT) | 9자 (14s 중 전반 일부) |
| sentence 윈도우 | [0, 5.37] (end-to-end) — 프로소디는 발화-바운드 dur=3.4s |
| speech | F0 sd 1.47st(단조) · 조음 1.07음절/s · 음량 후반 +7.39dB |
| visual | face 82프레임(검출 1.0) · 미소 0.03 · 시선이탈 0.165 · 손 검출 0 |
| nonverbal | neutral 100% |
| 답변 레이턴시 | 6.06s |

> 클립 특성: **느리게 속삭이는** 음성. 검증 관심사 = 속삭임(무성 우세)·느린 발화가 잡히는가.

## 관찰

1. **속삭임 포착 + 표면화(B 수정)**: raw `voiced_ratio 0.028`(2.8% — 무성 우세=속삭임 서명).
   prompt_block·fragment 둘 다 "무성 우세 발성 — 속삭임형 신호"로 명시, 저신뢰 F0(sd 1.59st,
   2.8% 유성에서 나온 값)는 "신뢰 낮음"으로 강등. 수정 전엔 `F0 변동 1.59st`만 정상 억양처럼
   나가 속삭임이 가려졌었다(render_prompt_fragment·describe_vocal의 sd 우선 → 속삭임 우선으로 교정).
2. **느린 발화 포착**: 조음 0.7음절/s(보통 5.8~6.9). 그대로 유지.
3. **프로소디 발화-바운드 동작**: sentence 윈도우 [0,5.x](end-to-end)에서 프로소디만 dur=3.42s
   (선행 묵음 제외). end-to-end 비전(81프레임)과 분리 — 음량/조음이 묵음에 안 희석됨.
4. 손 검출 0 — 오디오 클립이라 정상(vision-test는 0.33).

## 한계 (잡았지만 남는 약점)

- **커버리지: 14s 중 ~3.4s만 분석.** OpenAI server-VAD가 속삭임(저에너지)을 대부분 미검출 →
  speech_started/stopped가 한 구간만 떠 문장 1개 → 나머지 ~10s가 turnHandoff에 안 실림. 이건
  상류 STT/VAD 한계(우리 레인 아님). "느린 속삭임일수록 제품경로가 더 많이 놓침"의 실증.
- 엔진은 hot-patch(미커밋) 상태 — 영속하려면 giljobe 커밋+핀 갱신 필요.
