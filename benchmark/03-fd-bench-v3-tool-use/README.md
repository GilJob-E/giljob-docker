# FD-bench V3 Tool Use

## 이것이 무엇인가

Full-Duplex-Bench v3, 또는 FDB-v3는 자연스러운 사람 음성의 disfluency와 multi-step tool use를 함께 평가하는 voice agent benchmark다. 사용자는 실제 사람이 녹음한 음성으로 요청하고, agent는 여러 mock API를 올바른 순서와 인자로 호출한 뒤 자연스럽게 답해야 한다.

Thinking Machines 표에서는 `FD-bench V3 Response Quality (%) / Pass@1 (%)`로 등장한다.

## 출처

- Paper: https://arxiv.org/abs/2604.04847
- Repo: https://github.com/DanielLin94144/Full-Duplex-Bench/tree/main/v3
- Thinking Machines benchmark table: https://thinkingmachines.ai/blog/interaction-models/

## 데이터

공식 repo 기준 데이터는 다음 구조다.

- 100 examples
- 79 unique scenarios
- 12 speakers
- 각 example은 `input.wav`와 `metadata.json`으로 구성
- 4개 domain: `ecommerce_support`, `finance_billing`, `housing_location`, `travel_identity`
- 3개 difficulty: easy는 1 tool, medium은 2 tools, hard는 3 tools
- 12개 mock API tools

disfluency는 hesitation, false start, self-correction, filler, repair 같은 실제 음성 현상을 포함한다. 예를 들어 사용자가 목적지를 말했다가 중간에 정정하면, agent는 이전 값을 버리고 최종 정정값을 tool argument에 반영해야 한다.

## 공식 측정 방식

repo는 세 단계 평가를 제공한다.

1. Tool accuracy
2. Pass rate
3. Latency analysis

주요 지표는 다음이다.

```text
tool_selection_precision = expected tool 중 실제 호출된 비율의 precision
tool_selection_recall = expected tool 중 실제 호출된 비율의 recall
tool_selection_f1 = precision/recall harmonic mean
argument_accuracy = tool argument가 의미적으로 맞는지
response_accuracy = spoken response가 expected task completion을 충족하는지
pass@1 = 모든 expected tools와 arguments가 맞고 missing/extra call이 없으면 1, 아니면 0
first_response_latency = user speech end -> agent first word
tool_call_latency = user speech end -> first tool invocation
task_completion_latency = user speech end -> key information sentence
```

semantic argument matching과 response quality는 `--use-llm` 옵션에서 GPT-4o judge를 사용하고, 아니면 exact string matching 중심으로 평가한다.

## GilJob에서 측정 가능한가

라벨: `adapted`

현재 GilJob에는 범용 tool-calling controller가 없다. 그러므로 product 그대로는 FDB-v3 Pass@1을 의미 있게 찍기 어렵다. 하지만 benchmark harness로는 가능하다.

GilJob row는 다음처럼 만든다.

```text
FDB input.wav
  -> OpenAI Realtime audio/tool adapter or ASR/text diagnostic adapter
  -> FDB-v3 mock API execution
  -> response text/audio
  -> FDB-v3 evaluator
```

행 이름은 기본적으로 `GilJob v2 Realtime/tool adapter`로 둔다. ASR -> text LLM으로 우회하는 경우에는 `GilJob v2 ASR/text diagnostic`으로 따로 표시한다.

## GilJob용 리포트 필드

- `tool_selection_f1`
- `argument_accuracy`
- `response_accuracy`
- `pass_at_1`
- `first_response_latency_ms`
- `tool_call_latency_ms`
- `task_completion_latency_ms`
- `turn_take_rate`
- `disfluency_breakdown`
- `difficulty_breakdown`
- `domain_breakdown`

## 다음 준비 작업

1. FDB-v3 repo와 released data를 별도 benchmark workspace에 받는다.
2. mock API schema를 GilJob adapter prompt에 고정한다.
3. Realtime audio/tool path와 ASR/text diagnostic fallback을 분리해 두 행을 만든다.
4. 먼저 10 samples smoke를 돌리고, 그 다음 100 samples full run으로 확장한다.

## 주의점

FDB-v3는 GilJob 면접 제품의 기본 task와 다르다. 하지만 "disfluent speech를 이해하고 여러 step을 정확히 수행하는가"는 Realtime 기반 orchestration 품질을 보기 좋은 proxy다.
