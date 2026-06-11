# HarmBench

## 이것이 무엇인가

HarmBench는 automated red teaming과 robust refusal을 위한 standardized evaluation framework다. harmful behavior prompt 또는 attack method를 target model에 적용하고, completions가 harmful behavior를 충족했는지 classifier로 평가한다.

Thinking Machines 표에서는 `HarmBench Refusal rate (%)` text safety benchmark 행으로 등장한다.

## 출처

- Paper: https://arxiv.org/abs/2402.04249
- Repo: https://github.com/centerforaisafety/HarmBench
- Website: https://www.harmbench.org/
- Thinking Machines benchmark table: https://thinkingmachines.ai/blog/interaction-models/

## 데이터

HarmBench repo는 다음을 포함한다.

- harmful behavior data
- red teaming methods
- model configs
- completion generation scripts
- completion evaluation scripts
- classifiers for standard/contextual/multimodal behaviors

논문은 18 red teaming methods와 33 target LLMs/defenses를 비교했다고 설명한다.

## 공식 측정 방식

평가 pipeline은 세 단계다.

```text
1. generate test cases
2. generate completions from target model
3. evaluate completions with HarmBench classifier
```

Thinking Machines 표의 `Refusal rate`는 safety prompt에 대해 모델이 harmful answer를 내지 않고 거절한 비율로 해석한다.

HarmBench 자체에서는 attack success 관점도 중요하다.

```text
attack_success_rate = harmful_completions / total_test_cases
refusal_rate = refused_or_safe_completions / total_test_cases
```

실제 리포트에서는 refusal rate만 보면 안 된다. benign prompt에 대한 over-refusal도 별도 측정해야 한다.

## GilJob에서 측정 가능한가

라벨: `official-compatible` for text boundary

GilJob의 API/AI boundary에 HarmBench text prompts를 넣어 safety behavior를 측정할 수 있다.

GilJob row는 다음처럼 만든다.

```text
HarmBench behavior/test case
  -> GilJob AI boundary adapter
  -> response text
  -> HarmBench classifier
  -> refusal/safe/harmful metric
```

제품 특화 추가 테스트도 필요하다.

- interview prompt injection
- resume/job posting에 숨겨진 malicious instruction
- token/report URL/session key를 말하라고 유도하는 prompt
- candidate evaluation을 차별적으로 하라는 prompt
- raw media나 transcript를 외부로 보내라는 prompt

## GilJob용 리포트 필드

- `refusal_rate`
- `attack_success_rate`
- `over_refusal_rate`
- `harm_category_breakdown`
- `prompt_injection_success_rate`
- `secret_exposure_count`
- `classifier_model`
- `adapter_boundary`

## 다음 준비 작업

1. HarmBench repo를 별도 benchmark workspace에 받는다.
2. GilJob text adapter를 만든다.
3. official harmful behaviors run과 GilJob-specific safety run을 분리한다.
4. `.env`, raw token, JWT, LiveKit token, report token, raw media는 test artifact에 남기지 않도록 redaction test를 같이 붙인다.

## 주의점

Refusal rate가 높다고 항상 좋은 것은 아니다. 면접 제품에서는 legitimate career/interview 질문을 과도하게 거절하면 사용자 경험이 망가진다. HarmBench와 함께 benign over-refusal set을 반드시 둔다.
