# nv 강화 + eval off 라이브 검증 (2026-06-12)

변경 3개를 한 런으로 기능 검증 (fakecam, kor, 비교 기준 = `../2026-06-12-evalab-a,b/`):
① nv에 프로소디 측정치 주입(vision과 동일한 inject) ② JPEG 버퍼 3fps + nv 캡 24
(`GILJOBE_FRAME_FPS=3`, `GILJOBE_NV_FRAME_CAP=24` — 핫패치는 기본값 플립) ③ `GILJOBE_EVAL_GRID=off`
(발화중 풀 평가 + eot compact tail 모두 끔).

## 결과

| 지표 | evalab-a/b (eval on, 1fps) | 이 런 (eval off, 3fps) |
|---|---|---|
| **stop→turn_end** | 1.24 / 1.35s | **0.03s** (tail 대기 소멸) |
| eval 레코드 | 2 + tail | **0** (turn_end.eval=None — 의도) |
| nv 레이턴시(문장 배치 꼬리) | 0.88~2.9s | 0.92~2.52s — **3fps 비용 사실상 0** |
| 레인 충족 | visual 8/8, nv 7~8/8 | visual 8/8, **nv 8/8**, speech 6/8(초단문 한계) |
| nv note 품질 | 시각 인용만 | **음성 인용 추가**: "발화 속도가 느림", "음량 추세가 후반에 감소함" |

- 3fps가 공짜인 이유(추정): nv 지연이 프레임 prefill보다 출력 생성+큐 대기에 지배됨. eval off로
  gemma 경합이 줄어든 효과와 섞여 있음 — 순수 fps 비용 분리가 필요하면 eval off+1fps 런 1회 추가.
- 주의 1건: 마지막 0.9s 문장 nv note "뚜렷한 제스처 3회" — y4m 루프 꼬리(클립 선두 재생) 구간이라
  실제 모션일 수 있으나, 초단문에서의 제스처 카운트 주장은 grounding 검증 후보.

## 결정 반영 (2026-06-12 사용자)

- **eval은 제거 방향 확정** — 내용 판단은 소비자 LLM(Gemini) 위임. 이 런이 GilJobE 쪽 절반
  (`eval_grid=off`)의 검증. 나머지 절반 = turn_handoff 편입(A안: signals_payload `turnHandoff`)
  + API 중계 + ai-engine `build_question_prompt` 주입 — 다음 작업 단위.
- 모델 호칭 정정: vLLM 모델은 **gemma4 e4b** (3n 아님).

## 상태

QA 컨테이너는 런 후 기본값 코드(wall/1fps/캡12 — 기존 동작)로 원복. 실험 구성 재현은
b2-patch 방식(기본값 sed 플립) 또는 컴포즈 env 배선 후 `GILJOBE_EVAL_GRID=off GILJOBE_FRAME_FPS=3
GILJOBE_NV_FRAME_CAP=24`.
