# IFEval (VoiceBench)

## 이것이 무엇인가

VoiceBench는 LLM-based voice assistant를 평가하기 위한 benchmark다. real/synthetic spoken instructions를 사용하고, speaker characteristics, environment, content variation 같은 실제 음성 조건을 포함한다.

Thinking Machines 표의 `IFEval (VoiceBench) Accuracy (%)`는 VoiceBench의 `ifeval` subset을 이용해 spoken instruction-following accuracy를 본 행으로 해석한다.

## 출처

- VoiceBench paper: https://arxiv.org/abs/2410.17196
- VoiceBench repo: https://github.com/MatthewCYM/VoiceBench
- Thinking Machines benchmark table: https://thinkingmachines.ai/blog/interaction-models/

## 데이터

VoiceBench repo는 Hugging Face dataset `hlt-lab/voicebench`를 사용한다. 공개 README 기준 subset은 다음을 포함한다.

- `alpacaeval`
- `commoneval`
- `wildvoice`
- `openbookqa`
- `mmsu`
- `sd-qa`
- `mtbench`
- `ifeval`
- `bbh`
- `advbench`

이 중 `ifeval` subset은 345 samples, audio source는 Google TTS, task type은 instruction following으로 문서화되어 있다.

## 공식 측정 방식

VoiceBench runner 흐름은 다음이다.

```text
spoken instruction audio
  -> voice assistant response
  -> dataset-specific evaluator
  -> final score
```

`ifeval` subset은 VoiceBench evaluation script에서 evaluator type `ifeval`을 사용한다. open-ended QA 계열은 GPT-4o-mini judge를 쓰지만, `ifeval`은 rule-based instruction-following evaluator로 처리한다.

대표 지표는 accuracy다.

```text
accuracy = passed_examples / total_examples
```

## GilJob에서 측정 가능한가

라벨: `adapted`

GilJob은 범용 voice assistant가 아니라 interview product이므로, product 그대로는 VoiceBench의 모든 subset에 맞지 않는다. 그러나 `ifeval` spoken instruction-following은 다음 방식으로 측정 가능하다.

```text
VoiceBench ifeval audio
  -> OpenAI Realtime audio adapter or ASR/text diagnostic adapter
  -> GilJob/Gemini response
  -> VoiceBench ifeval evaluator
```

이때 두 행을 분리하는 것이 좋다.

- `GilJob v2 Realtime audio adapter`: audio를 직접 product media path에 넣은 경우
- `GilJob v2 ASR/text diagnostic`: audio를 transcript로 바꾼 뒤 text LLM 평가

## GilJob용 리포트 필드

- `accuracy`
- `prompt_level_accuracy`
- `instruction_level_accuracy`
- `transcript_error_rate`
- `failed_instruction_types`
- `audio_source`
- `adapter_type`

## 다음 준비 작업

1. VoiceBench `ifeval` subset은 `benchmark/data/raw/voicebench-ifeval/`에 확보되어 있다.
2. Realtime audio path를 연결하고, ASR/text diagnostic row에서는 transcript와 reference transcript를 비교해 ASR 영향을 분리한다.
3. text-only IFEval baseline을 먼저 찍고, 그 다음 VoiceBench audio path로 확장한다.

## 주의점

VoiceBench `ifeval`은 audio interface를 거친 instruction following이다. GilJob의 면접 질문 품질이나 후보자 평가 품질과는 별개로, "음성 지시를 놓치지 않고 구조적 제약을 지키는가"를 보는 지표다.
