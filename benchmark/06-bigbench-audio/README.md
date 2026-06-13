# BigBench Audio

## 이것이 무엇인가

Thinking Machines 표에는 `BigBench Audio Accuracy (%)`라는 audio benchmark 행이 있다. 이 행은 audio input을 받아 정답을 맞히는 accuracy benchmark로 사용되며, Thinking Machines는 baseline metrics가 Artificial Analysis에서 reported되었다고 주석을 달았다.

공개 검색 기준으로 `BigBench Audio`의 독립적인 공식 paper/repo/spec는 다른 항목들보다 명확하지 않다. 따라서 이 문서는 재현 가능성을 낮게 보고, 공개 출처가 확정되기 전까지는 adapted benchmark 후보로만 둔다.

## 출처

- Thinking Machines benchmark table and Artificial Analysis note: https://thinkingmachines.ai/blog/interaction-models/
- MiMo-Audio paper, Big Bench Audio를 spoken dialogue/audio benchmark 중 하나로 언급: https://arxiv.org/abs/2512.23808

## 데이터

공개적으로 확인된 최소 정보는 다음이다.

- input modality: audio
- output: answer text 또는 spoken/text answer
- metric: accuracy
- Thinking Machines 표에서는 Artificial Analysis reported metrics를 baseline으로 사용

공식 dataset card, task list, runner, judge prompt가 확인되기 전까지는 다음을 문서상 가정으로 둔다.

```text
audio question/task input
  -> model response
  -> exact match or judge-based correctness
  -> accuracy
```

## 공식 측정 방식

공개 spec가 부족하므로 공식 측정식은 확정하지 않는다. 현재 문서에서는 다음 generic metric만 기록한다.

```text
accuracy = correct_examples / total_examples
```

정답 추출 방식이 multiple-choice인지, free-form judge인지, transcript 기반인지가 확인되어야 official-compatible 여부를 판단할 수 있다.

## GilJob에서 측정 가능한가

라벨: `adapted`, 공개 재현성 낮음

GilJob row는 다음처럼 만들 수 있다.

```text
BigBench Audio input
  -> OpenAI Realtime audio adapter or ASR/text diagnostic adapter
  -> GilJob/Gemini answer
  -> official or fixed correctness judge
```

하지만 official dataset과 judge가 고정되지 않으면 비교표에 넣지 않는다. 내부 실험에서는 `audio_qa_accuracy_adapted` 정도의 이름을 쓴다.

## GilJob용 리포트 필드

- `accuracy`
- `transcript_error_rate`
- `answer_extraction_policy`
- `judge_model`
- `dataset_source`
- `reproducibility_status`

## 다음 준비 작업

1. Artificial Analysis의 BigBench Audio methodology 공개 여부를 확인한다.
2. 확보된 `ArtificialAnalysis/big_bench_audio` data subset과 MiMo evaluator 기준으로 provisional runner를 유지한다.
3. Realtime audio adapter와 ASR/text diagnostic adapter를 분리해 재현성 낮음을 명확히 표시한다.

## 주의점

이 항목은 9개 중 가장 source transparency가 낮다. 지금 단계에서 GilJob 성능 주장에 쓰면 안 되고, "조사 필요" 상태로 둔다.
