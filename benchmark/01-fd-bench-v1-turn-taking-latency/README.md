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

GilJob v2는 full-duplex listener/speaker가 아니다. 현재 제품 흐름은 사용자가 답변을 시작하고 끝내는 turn-based interview room이다. 따라서 FD-bench V1 official score처럼 말할 수는 없다.

대신 GilJob 행은 다음 product latency로 만들 수 있다.

```text
t_user_audio_end = benchmark answer audio 종료
t_stop_sent = harness가 /subscriber/stop 또는 동등 event를 보낸 시각
t_transcript_ready = GilJobE final transcript 확보
t_next_question_ready = Gemini next-question text 생성 완료
t_tts_first_audio = next question TTS 첫 오디오 송출 가능

giljob_first_response_latency = t_tts_first_audio - t_user_audio_end
```

사람의 "답변 종료" 클릭 지연은 제외한다. benchmark harness가 audio 종료 직후 stop event를 보내야 한다.

## GilJob용 리포트 필드

- `latency_mean_ms`
- `latency_median_ms`
- `latency_p95_ms`
- `no_response_rate`
- `transcript_flush_latency_ms`
- `next_question_llm_latency_ms`
- `tts_first_audio_latency_ms`
- `measurement_label`: `GilJob v2 cascaded/turn-based adapter`

## 다음 준비 작업

1. FD-bench V1 데이터를 받을 수 있는지 확인한다.
2. audio sample을 LiveKit room 또는 analysis-engine adapter로 주입하는 harness를 만든다.
3. `/subscriber/stop` 자동 호출 시각과 TTS first audio 시각을 monotonic clock으로 기록한다.
4. 같은 sample set으로 20개 smoke run을 먼저 돌려 timestamp 안정성을 확인한다.

## 주의점

이 점수는 "GilJob이 full-duplex turn-taking을 한다"는 증거가 아니다. GilJob의 turn-based interview latency를 FD-bench식 기준선에 맞춰 기록하는 진단 행이다.
