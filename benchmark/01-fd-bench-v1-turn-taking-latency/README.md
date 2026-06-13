# FD-bench V1 Turn-taking latency

## 이것이 무엇인가

FD-bench V1은 full-duplex spoken dialogue model의 turn-taking capability를 평가하는 벤치마크다. 논문은 pause handling, backchanneling, turn-taking, interruption management 같은 실시간 대화 행동을 자동 지표로 평가한다.

Thinking Machines 표에서는 이 중 `FD-bench V1 Turn-taking latency (s)`를 responsiveness 지표로 사용한다. 즉 사용자가 말하기를 마친 뒤 모델이 실제 응답을 시작하기까지 걸리는 시간을 초 단위로 본다.

## 출처

- Paper: https://arxiv.org/abs/2503.04721
- Repo: https://github.com/DanielLin94144/Full-Duplex-Bench/tree/main/v1_v1.5
- Thinking Machines benchmark table: https://thinkingmachines.ai/blog/interaction-models/

## 데이터

공식 벤치마크는 prerecorded audio를 모델에 입력하고, 모델이 생성한 output audio를 time-aligned transcript로 후처리해 평가한다. 공식 repo는 model inference 후 generated audio에 timestamp를 붙이고, task별 evaluation script를 실행하는 구조다.

Thinking Machines의 `simple turn-taking latency` 행은 full FD-bench V1 전체가 아니라, turn end 이후 첫 응답까지의 지연을 대표 responsiveness 지표로 뽑은 것이다.

## 공식 측정 방식

핵심 timestamp는 다음이다.

```text
t_user_end = user speech가 끝난 시각
t_model_start = model의 실질 응답 음성이 시작된 시각
turn_taking_latency = t_model_start - t_user_end
```

해석:

- 낮을수록 좋다.
- 모델이 응답하지 않은 케이스는 latency 평균에서만 보면 안 되고, no-response/turn-take 계열 지표와 같이 봐야 한다.
- full-duplex 모델은 사용자가 끝나기 전에 끼어들 수 있으므로, 일부 setup에서는 음수 latency나 interruption 관련 지표가 별도로 필요하다.

## GilJob에서 측정 가능한가

라벨: `diagnostic-only`

실측 레벨: `product-path`

이 레벨은 PR #15의 Realtime product path를 겨냥한다. MMM 분석 모듈만의 단독 성능이 아니며, SpatialReal avatar/public TURN/final report까지 포함하는 full-service E2E도 아니다.

PR #15 기준 GilJob v2의 primary interviewer audio path는 API-mediated OpenAI Realtime WebRTC 흐름이다. 그래도 FD-bench V1 official score처럼 말하려면 공식 streaming 조건과 동일한 judge/timestamp 규칙이 필요하므로, 지금은 제품 latency를 같은 기준으로 맞춘 diagnostic row로 둔다.

대신 GilJob 행은 다음 product latency로 만들 수 있다.

```text
t_user_audio_end = benchmark answer audio 종료
t_model_input_commit = harness가 Realtime input/end-of-turn을 commit한 시각
t_mmm_ready = API가 full_mmm_ready: true를 반환한 시각
t_response_create = API 또는 adapter가 Realtime response create를 accepted/observed한 시각
t_model_first_text_delta = Realtime 첫 text delta 관측 시각
t_model_first_audio_delta = Realtime 첫 audio delta 관측 시각
t_model_response_done = Realtime response 완료 시각

giljob_first_response_latency = min(t_model_first_text_delta, t_model_first_audio_delta) - t_user_audio_end
```

사람의 "답변 종료" 클릭 지연은 제외한다. benchmark harness가 audio 종료 직후 input commit/end-of-turn event를 보내고, 같은 monotonic clock으로 `full_mmm_ready`, Realtime response create, 첫 delta와 response done을 기록해야 한다.

## GilJob용 리포트 필드

- `latency_mean_ms`
- `latency_median_ms`
- `latency_p95_ms`
- `no_response_rate`
- `input_commit_overhead_ms`
- `mmm_ready_latency_ms`
- `response_create_overhead_ms`
- `first_text_delta_latency_ms`
- `first_audio_delta_latency_ms`
- `end_to_end_latency_ms`
- `transcript_flush_latency_ms` when measuring an ASR/text diagnostic row
- `measurement_label`: `GilJob v2 Realtime adapter`

## 다음 준비 작업

1. FD-bench V1 데이터는 `benchmark/data/raw/fd-bench-v1-v1_5/`에 확보되어 있다.
2. audio sample을 Realtime product path 또는 동등 command adapter로 주입하는 harness를 연결한다.
3. input commit, `full_mmm_ready`, Realtime response create, first text/audio delta, response done 시각을 monotonic clock으로 기록한다.
4. 같은 sample set으로 20개 smoke run을 먼저 돌려 timestamp 안정성을 확인한다.

## 주의점

이 점수는 "GilJob이 official FD-bench full-duplex 조건을 통과했다"는 증거가 아니다. GilJob의 Realtime gate와 첫 응답 latency를 FD-bench식 기준선에 맞춰 기록하는 진단 행이다.
