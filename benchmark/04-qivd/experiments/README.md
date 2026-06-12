# QIVD 실험 — MMM 보완 + 소비자 LLM end-to-end (2026-06-12)

이 디렉토리는 QIVD에 대한 GilJob v2 측정 3종의 코드와 결과를 보존한다.
상위 벤치 설명은 [`../README.md`](../README.md), 측정 프레임은
[`../../mmm-enhancement-plan.md`](../../mmm-enhancement-plan.md) 참조.

핵심 프레임: **벤치 점수의 측정 종착은 소비자 LLM 응답**이다. 비전 레인 정확도는 MMM이
fragment로 운반할 "재료 품질"(component)이고, 공식 행은 소비자 LLM(`gpt-realtime-2`)이 답한 것이다.

## 결과 요약

| 측정 | 모델 | 입력 | 표본 | Accuracy |
|---|---|---|---|---|
| **공식 행 (제품 소비자 LLM)** | **gpt-realtime-2** (OpenAI Realtime) | video frames + audio(질문 음성) | 50 (1.7%) | **64.0%** (32/50) · judge보정 ~70% |
| 참고 (분석 스택 모델) | gemma-4-E4B-it | video frames + audio | 29 (1%) | 41.4% (12/29) |
| component (비전 레인) | MediaPipe hands 레인 | video only (손가락) | 95 (손가락 subset) | 76.9% exact / 87.9% ±1 |

- 공식 행 95% CI(Wilson, n=50): **50%~76%**. 29/21 분할 65.5%/61.9%로 안정적.
- gpt-realtime-2가 객체 인식·동작 이해 전반에서 gemma를 압도(+24%p): Rubik's cube, shuffling,
  lighter, scissors, boat 등 정확.

### 카테고리별 (gpt-realtime-2, 50)

object attributes 7/7 · object detection 1/1 · action detection 10/13 · object referencing 13/21 ·
action attributes 1/3 · object/action counting 0/3 · scene understanding 0/1 · action understanding 0/1

## 방법

- **소비자 LLM 경로**: GilJob 서비스가 쓰는 소비자 LLM은 OpenAI Realtime `gpt-realtime-2`
  (`.env` `OPENAI_REALTIME_MODEL`). 같은 모델·키로 WebSocket 직접 연결(서비스 api 컨테이너의
  면접 instructions·MMM 게이트는 미경유 — 그것들은 "질문 생성"용이라 QIVD QA와 태스크 불일치).
- **입력**: 비디오 균등 3프레임(448px) + 질문 음성(answer-timestamp 무관, 전체 오디오 24k PCM16
  buffer). 질문 텍스트 미제공 = 순수 video+audio.
- **채점**: 정규화 substring + gemma judge 폴백(semantic match). 문항마다 새 세션(오염 방지).
- **표본**: 전체 2,900 중 seed 42로 29 + seed 43으로 비중복 21 = 50.

### 비전 레인 component (손가락)

QIVD `object_counting` "How many fingers" 95문항으로 hands 레인 단독 정확도 측정. 임계는
정답 라벨 기준 그리드 스윕으로 최적화(radial 1.25→1.15, thumb 0.75→0.68; GilJobE
`feat/grounding-hands-whisper`). 자세한 갭/한계는 GilJobE `.dev/grounding/hands-lane-findings.md`.

## 한계 (정직)

1. **n=50(1.7%)** — CI 50~76%. 점추정. 전체 2,900 풀런 필요 시 약 1시간.
2. **judge 형식 버그로 ~6%p 손실** — "Three pens"↔정답 `3`(숫자/단어 미연결), "no plants
   visible"↔`No`(첫 단어 아님) 등 명백한 정답을 정규화가 놓침. 보정 시 35/50=70%.
   표준화하려면 judge를 gpt-4o-mini로 고정하거나 norm_match에 숫자-단어 매핑 추가.
3. **좌/우 관점 모호성** — QIVD 화자 관점("on my left") vs 모델 카메라 관점. action attributes
   1/3의 주원인. QIVD 알려진 난점.

## 재현

```bash
# 사전: QA 스택 gemma vLLM(8001) 가동, .env에 OPENAI_API_KEY(유효), websockets 설치
GVENV=/home/kio/workspace/giljobe/.venv/bin/python

# 1) 샘플 추출은 harness 내장(seed 42/43). 공식 행(gpt-realtime-2):
$GVENV harness/qivd_e2e_realtime.py        # sample_29 → e2e_realtime_29.json
# 21개 추가분은 sample 경로/출력만 바꿔 재실행(README 본문 sed 참고)

# 2) 참고(gemma 분석 모델):
$GVENV harness/qivd_e2e_gemma.py           # → e2e_gemma_29.json

# 3) component(비전 레인 손가락):
GILJOBE_VISION_MODELS_DIR=<models> $GVENV harness/qivd_finger_eval.py   # → finger_eval_95.json
$GVENV harness/qivd_finger_sweep.py        # 임계 그리드 스윕
```

## 파일

- `harness/qivd_e2e_realtime.py` — 공식 행(gpt-realtime-2 video+audio)
- `harness/qivd_e2e_gemma.py` — 참고(gemma-4-E4B video+audio)
- `harness/qivd_finger_eval.py` — 비전 레인 손가락 정확도
- `harness/qivd_finger_sweep.py` — 손가락 임계 그리드 스윕
- `runs/e2e_realtime_29.json`·`runs/e2e_realtime_21.json` — 공식 행 결과(합산 50)
- `runs/e2e_gemma_29.json` — gemma 참고 결과
- `runs/finger_eval_95.json` — 비전 레인 손가락 결과
- `runs/sample_29_seed42.json`·`runs/sample_21_seed43.json` — 샘플 목록(재현용)
