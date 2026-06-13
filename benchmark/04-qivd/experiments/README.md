# QIVD 실험 — MMM 보완 + 소비자 LLM end-to-end (2026-06-12)

이 디렉토리는 QIVD에 대한 GilJob v2 측정 3종의 코드와 결과를 보존한다.
상위 벤치 설명은 [`../README.md`](../README.md), 측정 프레임은
[`../../mmm-enhancement-plan.md`](../../mmm-enhancement-plan.md) 참조.

핵심 프레임: **벤치 점수의 측정 종착은 소비자 LLM 응답**이다. 비전 레인 정확도는 MMM이
fragment로 운반할 "재료 품질"(component)이고, 공식 행은 소비자 LLM(`gpt-realtime-2`)이 답한 것이다.

## 결과 요약

| 측정 | 모델 | 입력 | 표본 | Accuracy |
|---|---|---|---|---|
| **공식 행 (제품 소비자 LLM)** | **gpt-realtime-2** (OpenAI Realtime) | video frames + audio(질문 음성) | 100 (3.4%) | **66.0%** (66/100) · judge보정 ~70% |
| 참고 (분석 스택 모델) | gemma-4-E4B-it | video frames + audio | 29 (1%) | 41.4% (12/29) |
| component (비전 레인) | MediaPipe hands 레인 | video only (손가락) | 95 (손가락 subset) | 76.9% exact / 87.9% ±1 |

- 공식 행 95% CI(Wilson, n=100): **56%~75%**. 배치별 32/50=64.0%(seed 42+43, 2026-06-12) ·
  34/50=68.0%(seed 44, 2026-06-13)로 안정적.
- gpt-realtime-2가 객체 인식·동작 이해 전반에서 gemma를 압도(+24%p): Rubik's cube, shuffling,
  lighter, scissors, boat 등 정확.

### 카테고리별 (gpt-realtime-2, 100 합산)

object attributes 15/16 · object detection 5/5 · object referencing 25/33 · action detection 14/22 ·
object counting 3/7 · action counting 1/6 · action understanding 1/4 · action attributes 1/3 ·
subjective 0/2 · scene understanding 0/1 · ocr 1/1

## 방법

- **소비자 LLM 경로**: GilJob 서비스가 쓰는 소비자 LLM은 OpenAI Realtime `gpt-realtime-2`
  (`.env` `OPENAI_REALTIME_MODEL`). 같은 모델·키로 WebSocket 직접 연결(서비스 api 컨테이너의
  면접 instructions·MMM 게이트는 미경유 — 그것들은 "질문 생성"용이라 QIVD QA와 태스크 불일치).
- **입력**: 비디오 균등 3프레임(448px) + 질문 음성(answer-timestamp 무관, 전체 오디오 24k PCM16
  buffer). 질문 텍스트 미제공 = 순수 video+audio.
- **채점**: 정규화 substring + gemma judge 폴백(semantic match). 문항마다 새 세션(오염 방지).
- **표본**: 전체 2,900 중 seed 42로 29 + seed 43으로 비중복 21 = 50(2026-06-12),
  seed 44로 기존 50과 비중복 50 추가 = 누적 100(2026-06-13).

### 비전 레인 component (손가락)

QIVD `object_counting` "How many fingers" 95문항으로 hands 레인 단독 정확도 측정. 임계는
정답 라벨 기준 그리드 스윕으로 최적화(radial 1.25→1.15, thumb 0.75→0.68; GilJobE
`feat/grounding-hands-whisper`). 자세한 갭/한계는 GilJobE `.dev/grounding/hands-lane-findings.md`.

## 한계 (정직)

1. **n=100(3.4%)** — CI 56~75%. 점추정. 전체 2,900 풀런 필요 시 약 1시간.
2. **judge 형식 버그 — 거짓음성**: "Three pens"↔정답 `3`(숫자/단어 미연결), "no plants
   visible"↔`No`(첫 단어 아님), em-dash 융합("No—you're"→정규화 시 "noyoure"라 yes/no 첫
   토큰 검사 실패; seed 44 배치 #16·#48), "It's a bow"↔`Bowing`(#42) 등 명백한 정답을 놓침.
3. **norm_match 토큰 부분일치 — 거짓양성**: 다단어 정답의 일부 토큰만 겹쳐도 통과
   ("Jack of Hearts"↔`King of Hearts` #29, "right hand"↔`Left hand` #38). 거짓음성과
   거짓양성을 모두 보정하면 seed 44 배치 35/50, 누적 ~70/100=**70%**(1차 배치는 거짓음성만
   감사함). 표준화하려면 judge를 gpt-4o-mini로 고정하거나 norm_match에 숫자-단어 매핑 추가
   + 다단어 정답 전체일치 요구.
4. **좌/우 관점 모호성** — QIVD 화자 관점("on my left") vs 모델 카메라 관점. action attributes
   1/3의 주원인. QIVD 알려진 난점.
5. **subjective 카테고리(ref=`NA`) 2문항은 구조적으로 채점 불가** — substring/judge 어느 쪽도
   `NA`와 매칭될 수 없어 무조건 X. 카테고리 제외 여부는 풀런 때 결정.

## 재현

```bash
# 사전: QA 스택 gemma vLLM(8001) 가동, .env에 OPENAI_API_KEY(유효), websockets 설치
GVENV=/home/kio/workspace/giljobe/.venv/bin/python

# 1) 샘플 추출은 harness 내장(seed 42/43). 공식 행(gpt-realtime-2):
$GVENV harness/qivd_e2e_realtime.py        # sample_29 → e2e_realtime_29.json
# 추가 배치(seed 43 21개, seed 44 50개)는 runs/sample_*.json을 /tmp/qivd_run/sample.json에
# 놓고 출력 경로만 sed로 바꿔 재실행 (seed 44 = 기존 ID 제외 후 random.Random(44).sample)

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
- `runs/e2e_realtime_29.json`·`runs/e2e_realtime_21.json`·`runs/e2e_realtime_50_seed44.json`
  — 공식 행 결과(합산 100)
- `runs/e2e_gemma_29.json` — gemma 참고 결과
- `runs/finger_eval_95.json` — 비전 레인 손가락 결과
- `runs/sample_29_seed42.json`·`runs/sample_21_seed43.json`·`runs/sample_50_seed44.json`
  — 샘플 목록(재현용, 상호 비중복)
