# IFEval Text

## 이것이 무엇인가

IFEval은 LLM의 instruction-following 능력을 rule-based로 평가하는 text benchmark다. 사람 평가나 LLM judge에 의존하지 않고, 검증 가능한 지시를 사용한다.

예시는 다음 유형이다.

- 특정 단어를 최소 N번 포함
- 특정 길이 이상 작성
- 특정 형식으로 출력
- 금지 단어를 사용하지 않음

Thinking Machines 표에서는 `IFEval Accuracy (%)` text benchmark 행으로 등장한다.

## 출처

- Paper: https://arxiv.org/abs/2311.07911
- Repo: https://github.com/google-research/google-research/tree/master/instruction_following_eval
- Thinking Machines benchmark table: https://thinkingmachines.ai/blog/interaction-models/

## 데이터

원 논문 기준:

- 약 500 prompts
- 25 types of verifiable instructions
- 각 prompt는 하나 이상의 verifiable instruction 포함

repo는 `input_data.jsonl`와 model response jsonl을 받아 evaluation script로 채점한다.

## 공식 측정 방식

runner는 prompt와 response를 입력으로 받아 instruction check를 수행한다.

```text
prompt_level_accuracy = prompts where all instructions pass / total_prompts
instruction_level_accuracy = passed_instructions / total_instructions
```

대표 실행 흐름은 다음이다.

```text
input_data.jsonl
model responses jsonl
  -> instruction_following_eval.evaluation_main
  -> prompt-level and instruction-level metrics
```

## GilJob에서 측정 가능한가

라벨: `official-compatible`

이 9개 중 가장 먼저 측정하기 좋다. audio/video path와 무관하게 Gemini question provider, future Main LLM, report generation boundary의 text instruction-following을 볼 수 있다.

GilJob row는 다음처럼 만든다.

```text
IFEval prompt
  -> GilJob Main LLM adapter or Gemini provider adapter
  -> response text
  -> official IFEval evaluator
```

면접 제품 맥락에 맞춘 추가 row도 만들 수 있다.

```text
IFEval prompt + interview system prompt
  -> next-question provider
  -> response
  -> official evaluator
```

## GilJob용 리포트 필드

- `prompt_level_accuracy`
- `instruction_level_accuracy`
- `failed_instruction_types`
- `model`
- `system_prompt_variant`
- `temperature`
- `max_output_tokens`

## 다음 준비 작업

1. google-research IFEval code/data를 별도 benchmark workspace에 받는다.
2. GilJob provider adapter가 prompt/response jsonl을 생성하도록 만든다.
3. 먼저 20 prompt smoke를 돌려 response extraction을 검증한다.
4. full 500 prompt run을 실행한다.

## 주의점

IFEval은 면접 질문 품질을 직접 평가하지 않는다. 하지만 system prompt를 정확히 따르는지, 금지된 출력 형식을 피하는지, report/token 노출 금지 같은 contract를 model prompt 수준에서 검증하기 좋다.
