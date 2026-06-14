# .audio_test 제품경로 런 — 관찰·결론 (2026-06-13)

하니스: `qa/runs/_tools/productpath_signals.mjs --video qa/.audio_test.mp4`
조건: `meta.json` (실 OpenAI Realtime 전사 포함 풀스택, interviewId=qa-audio-test-1, turnIndex 0)

## 결과 요약 (signals.json = `/analysis/signals` 정본 페이로드)

| 항목 | 값 |
|---|---|
| 레코드 | 2 (sentence×1 + turn_end) |
| 커버리지(turnHandoff.meta) | speech 1 · visual 1 · nv 1 (전 레인 충족) |
| 전사(실 Realtime STT) | "지금 목소리 크기나" — **10자** (14s 중 전반 일부만 전사됨) |
| speech | 1윈도우 3.42s · F0 sd **1.6 st**(단조) · 조음 0.71음절/s · 음량 후반 **+7.67 dB** |
| visual | face 51프레임(검출 1.0) · 미소 0.047 · 시선이탈 0.163 · **손 검출 0** |
| nonverbal | neutral 100% · intensity 0.30 |
| 답변 레이턴시(종료 클릭→) | 6.46s |

## 결론

1. **오디오/프로소디 레인이 소비자까지 종단 작동.** 면접관 후속 발화가 실측 음량을 그대로
   인용: "후반부가 초반보다 7.7데시벨 정도 크게…" = turnHandoff `energy_delta_db 7.67`.
   prompt_block의 음성 실측치가 소비자 LLM 응답을 실제로 구동했다.
2. **전사가 14s 중 10자뿐.** 실 Realtime STT가 클립 전반의 짧은 구간만 전사 → speech 1윈도우.
   조음 0.71음절/s(비정상적으로 느림)는 발화량 부족의 산물로 해석(클립이 대부분 비발화/낮은
   음성일 가능성). 객관 수치는 그 1윈도우 한정 유효.
3. 손 검출 0 — 오디오 테스트 클립이라 정상(비교용: vision 런은 0.19).

## 한계

- y4m 루프(640x480@15fps) + 주입 mic — 실 WebRTC 페이싱이나 카메라 영상은 테스트 클립의 영상
  그대로(오디오 테스트라 영상은 부차).
- 전사 짧음은 클립 특성/STT 컷 — 더 긴 발화 커버리지가 필요하면 발화 밀도 높은 클립 권장.
