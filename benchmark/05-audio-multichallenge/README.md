# Audio MultiChallenge

## 이것이 무엇인가

Audio MultiChallenge는 end-to-end spoken dialogue system의 자연스러운 multi-turn interaction 능력을 평가하는 benchmark다. text 기반 MultiChallenge의 축을 audio modality로 확장하고, 자연 발화의 disfluency와 mid-utterance repair를 포함한다.

Thinking Machines 표에서는 `Audio MultiChallenge APR (%)`로 등장한다. APR은 average pass rate로 이해하면 된다.

## 출처

- Paper: https://arxiv.org/abs/2512.14865
- Text MultiChallenge paper: https://arxiv.org/abs/2501.17399
- Thinking Machines benchmark table: https://thinkingmachines.ai/blog/interaction-models/

## 데이터

논문 abstract 기준 데이터는 다음이다.

- 452 conversations
- 47 speakers
- 1,712 instance-specific rubrics
- 자연 발화의 disfluency 유지
- hybrid audio-native agentic plus human-in-the-loop pipeline으로 curated

평가 축은 다음이다.

- Inference Memory: 앞서 들은 정보, 주변 소리, paralinguistic cue를 기억하는가
- Instruction Retention: multi-turn 중 이전 지시를 유지하는가
- Self Coherence: 긴 대화에서 스스로 한 말과 충돌하지 않는가
- Voice Editing: 사용자가 중간에 말을 고치거나 되돌릴 때 최신 의도를 반영하는가

## 공식 측정 방식

각 conversation에는 instance-specific rubric이 붙고, 모델 응답이 rubric을 통과하는지 평가한다.

```text
pass_rate_per_conversation = passed_rubrics / total_rubrics
APR = average(pass_rate_per_conversation across conversations)
```

구체 judge는 benchmark release를 따라야 한다. Thinking Machines 표에서는 baseline metrics를 Scale AI가 reported했다고 주석 처리한다.

## GilJob에서 측정 가능한가

라벨: `adapted`

이 벤치마크는 GilJob에 실용성이 높다. 면접 제품에서 중요한 능력인 "이전 답변을 기억하고, 제약을 유지하고, 자연스러운 follow-up을 하는가"와 잘 맞는다.

다만 official Audio MultiChallenge는 general voice assistant용이다. GilJob 행은 다음처럼 두 층으로 나눈다.

### Official audio adapted

```text
Audio MultiChallenge conversation audio
  -> GilJobE transcript or direct STT adapter
  -> GilJob Main LLM / Gemini adapter response
  -> rubric judge
```

### GilJob interview multichallenge

```text
resume/job posting/persona seed
  -> 3 to 5 turn interview script
  -> candidate audio answers
  -> follow-up generation
  -> rubric judge
```

두 번째는 official benchmark가 아니지만, 제품 품질에는 더 직접적이다.

## GilJob용 리포트 필드

- `average_pass_rate`
- `inference_memory_pass_rate`
- `instruction_retention_pass_rate`
- `self_coherence_pass_rate`
- `voice_editing_pass_rate`
- `transcript_error_rate`
- `turn_count`
- `judge_model`

## 다음 준비 작업

1. 공식 Audio MultiChallenge data/repo release 상태를 확인한다.
2. rubric schema를 분석해 GilJob answer object와 매핑한다.
3. GilJob interview-specific 20 conversation mini set을 먼저 만든다.
4. judge prompt와 rubric pass/fail 기준을 repo에 고정한다.

## 주의점

Audio-native model과 GilJob cascaded adapter를 같은 표에 놓을 수는 있다. 단, `cascaded/turn-based` 라벨을 붙이고, transcript error와 answer generation error를 분리해서 보고해야 한다.
