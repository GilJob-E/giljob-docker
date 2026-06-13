# GilJob v2 benchmark research

이 디렉토리는 Thinking Machines의 "Interaction Models" 글에 등장한 9개 벤치마크를 GilJob v2 기준으로 해석한 조사 노트다.
https://thinkingmachines.ai/blog/interaction-models/

핵심 원칙은 다음 한 문장이다.

> 핵심은 "full-duplex 여부"가 아니라 동일 데이터, 동일 judge, 동일 latency 기준으로 GilJob 행을 만든다.

PR #15 기준 GilJob v2의 primary interviewer audio path는 API가 OpenAI Realtime ephemeral client secret을 발급하고 브라우저가 `/v1/realtime/calls`에 SDP attach하는 Realtime WebRTC 흐름이다. ordinary next Realtime response는 이전 turn의 transcript/prosody/vision sideband가 `full_mmm_ready`를 만족한 뒤에만 허용된다. 그래서 이 문서의 목표는 "GilJob이 원 논문/리더보드와 같은 시스템이다"라고 주장하는 것이 아니라, 같은 입력 데이터와 같은 평가자, 같은 latency timestamp 규칙을 고정해 `GilJob v2 Realtime adapter`라는 비교 행을 만드는 것이다. Gemini next-question/TTS와 ASR/text 경로는 fallback 또는 diagnostic row로만 분리한다.

## 적용 라벨

각 벤치마크에는 다음 라벨을 붙인다.

| 라벨 | 의미 |
|---|---|
| `official-compatible` | 공식 데이터와 공식 runner/judge를 거의 그대로 쓸 수 있다. |
| `adapted` | 공식 데이터나 judge는 쓸 수 있지만 GilJob용 adapter가 필요하다. |
| `diagnostic-only` | 제품 구조가 달라 공식 비교 점수로 보기 어렵고, 내부 병목 진단용으로만 쓴다. |
| `not-ready` | 현재 GilJob boundary만으로는 의미 있는 측정이 어렵다. |

## 9개 벤치마크 요약

| # | 벤치마크 | Thinking Machines 표의 행 | 핵심 입력 | 공식/대표 지표 | GilJob 적용 |
|---|---|---|---|---|---|
| 1 | [FD-bench V1 Turn-taking latency](./01-fd-bench-v1-turn-taking-latency/README.md) | `FD-bench V1 Turn-taking latency (s)` | Audio | user turn end to model response start latency | `diagnostic-only`: `answer audio end -> Realtime response.create gate -> first text/audio delta`로 제품 latency 행 생성 |
| 2 | [FD-bench V1.5 Average](./02-fd-bench-v1-5-average/README.md) | `FD-bench V1.5 Average` | Audio overlap | average quality across interruption/backchannel/side conversation/background speech | `not-ready` 또는 `diagnostic-only`: overlap controller/evaluation schema가 아직 제품 계약으로 고정되지 않음 |
| 3 | [FD-bench V3 Tool Use](./03-fd-bench-v3-tool-use/README.md) | `FD-bench V3 Response Quality / Pass@1` | Audio + tools | response quality, strict pass@1, tool F1, latency | `adapted`: FDB-v3 mock APIs와 Realtime/tool adapter 필요 |
| 4 | [QIVD](./04-qivd/README.md) | `QIVD Accuracy` | Video + audio | answer correctness, streaming transcript grading | `adapted`: Realtime sideband/video QA adapter 또는 offline VLM adapter 필요 |
| 5 | [Audio MultiChallenge](./05-audio-multichallenge/README.md) | `Audio MultiChallenge APR` | Multi-turn audio | average pass rate over rubric checks | `adapted`: interview memory/follow-up 품질 측정에 가장 유용 |
| 6 | [BigBench Audio](./06-bigbench-audio/README.md) | `BigBench Audio Accuracy` | Audio | accuracy | `adapted`, but public reproducibility unclear |
| 7 | [IFEval VoiceBench](./07-ifeval-voicebench/README.md) | `IFEval (VoiceBench) Accuracy` | Spoken instructions | VoiceBench `ifeval` subset accuracy | `adapted`: Realtime audio adapter 또는 ASR/text diagnostic으로 가능 |
| 8 | [IFEval Text](./08-ifeval-text/README.md) | `IFEval Accuracy` | Text | prompt-level/instruction-level strict accuracy | `official-compatible`: GilJob/Gemini text boundary instruction-following check |
| 9 | [HarmBench](./09-harmbench/README.md) | `HarmBench Refusal rate` | Text safety prompts | refusal / attack success classifier result | `official-compatible` for text boundary safety checks |

## GilJob row 생성 규칙

GilJob 행의 이름은 기본적으로 `GilJob v2 Realtime adapter`로 둔다. 제품 그대로 측정하면 `GilJob v2 Realtime product path`를 별도 행으로 둔다. Gemini next-question/TTS fallback 또는 transcript -> text LLM 경로를 따로 재면 `GilJob v2 Gemini fallback diagnostic`이나 `GilJob v2 ASR/text diagnostic`처럼 명시한다.

공통 timestamp는 다음처럼 통일한다.

| timestamp | 의미 |
|---|---|
| `t_input_start` | benchmark input audio/video/text를 시스템에 넣기 시작한 시각 |
| `t_user_audio_end` | 사용자의 음성 입력이 끝난 시각 |
| `t_realtime_session_ready` | optional: `/api/interviews/:id/realtime/session`이 browser-safe Realtime session contract를 반환한 시각 |
| `t_model_input_commit` | harness가 Realtime 또는 동등 adapter에 input/end-of-turn을 commit한 시각 |
| `t_mmm_ready` | optional: `/api/interviews/:id/turns/:turnIndex/mmm-ready`가 `full_mmm_ready: true`를 반환한 시각 |
| `t_response_create` | optional: Realtime response create가 accepted/observed된 시각 |
| `t_transcript_ready` | optional: ASR/text diagnostic row에서 final transcript를 사용할 수 있게 된 시각 |
| `t_model_first_text_delta` | Realtime 또는 adapter의 첫 text delta가 관측된 시각 |
| `t_model_first_audio_delta` | Realtime 또는 adapter의 첫 audio delta가 관측된 시각 |
| `t_model_response_done` | agent response 오디오 또는 텍스트 완료 |

대표 latency는 다음처럼 계산한다.

```text
input_commit_overhead = t_model_input_commit - t_user_audio_end
mmm_ready_latency = t_mmm_ready - t_user_audio_end
response_create_overhead = t_response_create - t_mmm_ready
transcript_flush_latency = t_transcript_ready - t_user_audio_end  # ASR/text diagnostic row only
first_text_latency = t_model_first_text_delta - t_user_audio_end
first_audio_latency = t_model_first_audio_delta - t_user_audio_end
first_response_latency = min(t_model_first_text_delta, t_model_first_audio_delta) - t_user_audio_end
end_to_end_latency = t_model_response_done - t_user_audio_end
```

full-duplex 벤치마크를 Realtime 기반 GilJob 행에 얹을 때는 사람의 클릭 지연을 제외한다. 자동 harness가 benchmark audio 종료 직후 input commit/end-of-turn 또는 이에 해당하는 adapter event를 발생시키고, `full_mmm_ready` gate, Realtime response create, 첫 text/audio delta, response done을 monotonic clock으로 기록해야 한다.

## Judge 고정 원칙

1. 공식 runner가 있으면 공식 runner를 우선 사용한다.
2. 공식 runner가 없거나 private이면, Thinking Machines가 명시한 judge를 따른다.
3. judge가 공개되지 않았으면 `gpt-4o-mini` 또는 동일 judge model을 명시하고, judge prompt와 version을 repo에 고정한다.
4. GilJob 내부 로그, UI, docs, test output에는 raw session token, report token, JWT, Realtime client secret, SDP body, provider key, raw media를 남기지 않는다.

## 추천 우선순위

1. `IFEval Text`: 데이터가 작고 text-only라 가장 빨리 baseline을 찍을 수 있다.
2. `HarmBench`: 제품 safety boundary와 token/secret non-exposure contract를 같이 검증할 수 있다.
3. `Audio MultiChallenge adapted`: GilJob 면접 흐름의 memory, instruction retention, self coherence를 직접 겨냥한다.
4. `FD-bench V1 latency adapted`: Realtime gate 이후 첫 응답 delta latency를 수치화한다.
5. `FDB-v3 adapted`: Realtime/tool-calling adapter를 만든 뒤 측정한다.
6. `QIVD adapted`: offline VLM adapter 또는 Realtime sideband/video QA harness가 필요하다.

## 주요 출처

- Thinking Machines, "Interaction Models: A Scalable Approach to Human-AI Collaboration" (2026-05-11): https://thinkingmachines.ai/blog/interaction-models/
- Full-Duplex-Bench v1 paper: https://arxiv.org/abs/2503.04721
- Full-Duplex-Bench v1/v1.5 repo: https://github.com/DanielLin94144/Full-Duplex-Bench/tree/main/v1_v1.5
- Full-Duplex-Bench v1.5 paper: https://arxiv.org/abs/2507.23159
- Full-Duplex-Bench v3 paper: https://arxiv.org/abs/2604.04847
- Full-Duplex-Bench v3 repo: https://github.com/DanielLin94144/Full-Duplex-Bench/tree/main/v3
- Qualcomm Interactive Video Dataset paper: https://arxiv.org/abs/2503.19356
- Audio MultiChallenge paper: https://arxiv.org/abs/2512.14865
- VoiceBench paper: https://arxiv.org/abs/2410.17196
- VoiceBench repo: https://github.com/MatthewCYM/VoiceBench
- IFEval paper: https://arxiv.org/abs/2311.07911
- IFEval repo: https://github.com/google-research/google-research/tree/master/instruction_following_eval
- HarmBench paper: https://arxiv.org/abs/2402.04249
- HarmBench repo: https://github.com/centerforaisafety/HarmBench
