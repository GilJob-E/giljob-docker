# QIVD / Qualcomm Interactive Video Dataset

## 이것이 무엇인가

QIVD는 Thinking Machines 표에서 사용한 이름이고, 원 논문 이름은 Qualcomm Interactive Video Dataset, IVD다. 비디오와 오디오가 함께 들어오는 face-to-face question answering benchmark다.

사용자는 카메라 앞 장면을 보여주면서 음성 질문을 하고, 모델은 video/audio를 함께 보고 답한다. 중요한 점은 질문이 끝나는 시각과 답할 수 있는 시각이 다를 수 있다는 것이다. 예를 들어 사용자가 어떤 동작을 한 뒤 개수를 묻는 경우, 모델은 동작이 끝난 뒤에야 정답을 낼 수 있다.

## 출처

- Paper: https://arxiv.org/abs/2503.19356
- Thinking Machines benchmark table and QIVD note: https://thinkingmachines.ai/blog/interaction-models/

## 데이터

논문은 real-world camera/microphone setting에서 사용자가 질문하고 시스템이 장면과 음성 입력을 기반으로 실시간 답변하는 QA setup을 제안한다.

문서화할 데이터 필드는 다음을 기준으로 둔다.

- video clip
- raw audio
- question transcript
- reference answer
- short answer
- answer timestamp 또는 답변 가능 시점
- category label

Thinking Machines는 원 QIVD를 streaming setting으로 바꿔 raw clip을 처음부터 보내고, 모델 transcript를 GPT-4o-mini grader로 채점했다고 설명한다.

## 공식 측정 방식

대표 지표는 answer correctness다.

```text
accuracy = correct_answers / total_examples
```

채점은 reference answer와 model answer를 비교한다. 원 논문 setup은 offline/streaming 조건을 구분할 수 있고, streaming 조건에서는 언제 답해야 하는지도 중요하다.

Streaming-adapted 측정에는 다음 보조 지표를 넣는 것이 맞다.

```text
answer_correct = judge(predicted_answer, reference_answer)
answer_timing_error = abs(t_model_answer_start - t_reference_answer_timestamp)
first_response_latency = t_model_answer_start - t_question_or_answerable_end
```

## GilJob에서 측정 가능한가

라벨: `adapted`

GilJob은 LiveKit video path와 analysis-engine signal boundary를 갖고 있지만, 현재 제품은 QIVD용 video QA controller가 아니다. 따라서 두 버전으로 나눠야 한다.

### QIVD offline adapted

```text
video clip
  -> frame sampling
  -> audio transcript
  -> Gemini/VLM answer
  -> GPT-4o-mini or fixed judge
```

이 버전은 가장 먼저 시도할 수 있다. 단, streaming timing 능력은 보지 못한다.

### QIVD streaming adapted

```text
raw video/audio clip
  -> LiveKit publish
  -> GilJob visual/audio adapter
  -> answer generation
  -> transcript grading and timing evaluation
```

이 버전은 LiveKit media path와 answer timestamp를 함께 측정해야 한다.

## GilJob용 리포트 필드

- `accuracy`
- `category_accuracy`
- `answer_timing_mae_ms`
- `first_response_latency_ms`
- `video_frame_sampling_policy`
- `judge_model`
- `adapter_type`: `offline-adapted` 또는 `streaming-adapted`

## 다음 준비 작업

1. QIVD 데이터 접근 경로를 확인한다.
2. offline-adapted runner부터 만든다.
3. video frame sampling interval과 max frames를 고정한다.
4. streaming runner는 LiveKit browser smoke가 안정화된 뒤 진행한다.

## 주의점

QIVD 점수는 VLM 성능 영향을 크게 받는다. GilJobE의 visual signal boundary만으로 QIVD QA를 직접 수행한다고 해석하면 안 된다.
