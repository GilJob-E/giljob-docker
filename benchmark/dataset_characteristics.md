# Adopted benchmark dataset characteristics

작성 시점: 2026-06-12

이 문서는 채택된 7개 benchmark 데이터가 "무슨 데이터인지"와 "어떤 특징을 지니는지"를 정리한다. 실측 pipeline은 아직 provisional이므로, 여기서는 데이터 성격과 GilJob adapter 관점의 주의점만 고정한다.

## 요약 표

| # | Benchmark | 데이터 타입 | 핵심 평가 대상 | 로컬 확보 상태 |
|---|---|---|---|---|
| 1 | FD-Bench V1 Turn-taking latency | prerecorded dialogue audio + metadata | 사용자 발화 종료 후 모델 첫 응답 시작 latency | `benchmark/data/raw/fd-bench-v1-v1_5/` |
| 4 | QIVD | video + audio question + QA annotation + answerable timestamp | situated video/audio QA correctness and timing | `benchmark/data/raw/qivd/` |
| 5 | Audio MultiChallenge | multi-turn spoken conversations + rubrics | memory, instruction retention, self-coherence, voice editing | `benchmark/data/raw/mimo-audio-evalset/multi_challenge/` |
| 6 | BigBench Audio | synthetic English audio questions adapted from BBH | audio-input reasoning accuracy | `benchmark/data/raw/bigbench-audio/` |
| 7 | IFEval VoiceBench | spoken instruction-following audio subset | audio interface instruction following | `benchmark/data/raw/voicebench-ifeval/` |
| 8 | IFEval Text | text prompts with verifiable instruction constraints | text instruction following | `benchmark/data/repos/google-research/instruction_following_eval/data/input_data.jsonl` |
| 9 | HarmBench | harmful behavior prompts/test cases + classifier pipeline | robust refusal / attack success | `benchmark/data/repos/harmbench/data/behavior_datasets/` |

## 1. FD-Bench V1 Turn-taking latency

공식 성격:

- Full-Duplex-Bench v1은 full-duplex spoken dialogue model의 turn-taking behavior를 평가한다.
- v1은 pause handling, backchanneling, smooth turn-taking, user interruption management 같은 축을 포함한다.
- 우리가 채택한 row는 전체 v1 점수가 아니라 `Turn-taking latency`: 사용자가 말하기를 끝낸 뒤 모델이 응답을 시작하기까지의 지연이다.

데이터 특징:

- prerecorded user audio를 모델에 넣고, 모델 output audio를 time-aligned transcription으로 후처리한다.
- latency는 audio timestamp가 핵심이다.
- no-response와 interruption 케이스를 latency 평균만으로 숨기면 안 된다.

로컬 상태:

- path: `benchmark/data/raw/fd-bench-v1-v1_5/`
- v1.0 task dirs:
  - `candor_pause_handling`
  - `candor_turn_taking`
  - `icc_backchannel`
  - `synthetic_pause_handling`
  - `synthetic_user_interruption`
- v1.5 overlap dirs도 같이 확보되어 있지만, 현재 채택 target은 V1 turn-taking latency다.
- `candor_turn_taking`: wav 119개, json 119개.

GilJob 측정상 의미:

- official full-duplex score가 아니라 product latency diagnostic row로 써야 한다.
- 현재 하네스 기준 timestamp는 `t_user_audio_end`, `t_model_input_commit`, `t_mmm_ready`, `t_response_create`, first text/audio delta다.

샘플 해부:

```text
sample path:
benchmark/data/raw/fd-bench-v1-v1_5/v1.0/candor_turn_taking/1/

files:
- input.wav
- turn_taking.json
```

`turn_taking.json`:

```json
[
  {
    "text": "[TURN-TAKING]",
    "timestamp": [5.629999999999882, 5.899999999999864]
  }
]
```

`input.wav` media metadata:

```text
codec: pcm_f32le
sample_rate: 16000
channels: 1
duration_s: 10.899938
size_bytes: 697676
```

이 샘플에서 adapter가 받는 핵심 입력은 `input.wav`와 `t_user_audio_end_s=5.63`이다. official FD-Bench에서는 모델 output audio를 만들고, 그 output audio의 첫 응답 시각을 이 timestamp와 비교한다. GilJob diagnostic row에서는 같은 `input.wav`를 Realtime path에 주입하고, `5.63s` 이후 `full_mmm_ready`, response-create, first delta를 기록한다.

Primary sources:

- https://github.com/DanielLin94144/Full-Duplex-Bench
- https://github.com/DanielLin94144/Full-Duplex-Bench/tree/main/v1_v1.5
- https://arxiv.org/abs/2503.04721

## 4. QIVD / Qualcomm Interactive Video Dataset

공식 성격:

- QIVD는 real-world face-to-face video/audio question answering dataset이다.
- 사용자가 카메라와 마이크를 통해 장면에 대해 질문하고, 시스템은 unfolding video/audio context를 기반으로 적절한 시점에 답해야 한다.

데이터 특징:

- video clip, raw audio, spoken question transcript, answer, short answer, timestamp, category가 핵심 필드다.
- timestamp는 "언제 답할 수 있는지"를 나타내므로 correctness뿐 아니라 timing 평가에 중요하다.
- offline full-video QA보다 streaming/situated reasoning에 가깝다.
- 로컬 `labels.json` 기준 13 categories:
  - action attributes, action counting, action detection, action understanding
  - audio-visual
  - object attributes, object counting, object detection, object referencing, object understanding
  - ocr, scene understanding, subjective

로컬 상태:

- path: `benchmark/data/raw/qivd/`
- videos: mp4 2,900개
- labels: `labels.json` 1개
- archives: `videos.zip`, `annotations.zip`
- local schema: `answer`, `category`, `id`, `question`, `short_answer`, `timestamp`, `video`

GilJob 측정상 의미:

- offline VLM/frame sampling row와 Realtime sideband streaming row를 분리해야 한다.
- 현재 제품 path는 video QA controller가 아니므로 QIVD 점수는 `adapted`로 둔다.

샘플 해부:

```text
sample index: 0
label file: benchmark/data/raw/qivd/labels.json
video file: benchmark/data/raw/qivd/videos/00000000.mp4
```

sample label:

```json
{
  "id": 1972,
  "video": "00000000.mp4",
  "category": "object referencing",
  "timestamp": "00:04.4",
  "question": "What am I holding in my left hand?",
  "short_answer": "A Rubik's cube",
  "answer": "You are holding a Rubik's cube in your left hand."
}
```

`00000000.mp4` media metadata:

```text
container: mp4
video: h264, 640x360, duration_s=5.066667
audio: aac, 48000 Hz, mono, duration_s=4.881333
size_bytes: 407884
```

이 샘플에서 모델 입력은 video+audio clip과 질문이다. 평가 target은 `short_answer` 또는 `answer`와 model answer의 semantic match다. `timestamp=00:04.4`는 모델이 그 시점 이후에야 sensibly answer할 수 있다는 timing anchor로 쓰인다. 즉 offline QA에서는 전체 clip을 보고 `A Rubik's cube`를 맞히면 되지만, streaming row에서는 너무 이른 답변도 별도 timing error로 봐야 한다.

Primary sources:

- https://www.qualcomm.com/developer/software/qualcomm-interactive-video-dataset-qivd
- https://www.qualcomm.com/developer/software/qualcomm-interactive-video-dataset-qivd/downloads
- https://arxiv.org/abs/2503.19356

## 5. Audio MultiChallenge

공식 성격:

- End-to-end spoken dialogue systems를 자연스러운 multi-turn audio interaction으로 평가한다.
- text MultiChallenge의 Inference Memory, Instruction Retention, Self Coherence를 audio modality로 확장하고, Voice Editing 축을 추가한다.

데이터 특징:

- 공식 설명 기준 452 conversations, 47 speakers, 1,712 rubrics.
- natural disfluency, mid-utterance repair/backtracking, ambient/audio cues, paralinguistic cue가 중요하다.
- judge는 conversation history와 rubric item을 보고 마지막 assistant response가 rubric을 만족하는지 JSON으로 판단하는 구조다.

로컬 상태:

- path: `benchmark/data/raw/mimo-audio-evalset/multi_challenge/`
- local `data.jsonl`: 198 rows
- conversation directories: 199
- wav: 265개
- txt: 448개
- 로컬 확보분은 공식 전체 452 conversations와 크기가 다르므로 subset 또는 packaging 차이를 따로 확인해야 한다.

GilJob 측정상 의미:

- GilJob interview flow와 가장 잘 맞는 품질 benchmark 중 하나다.
- Realtime audio row와 ASR/text diagnostic row를 분리해야 한다.
- rubrics를 GilJob answer object와 매핑하는 작업이 필요하다.

샘플 해부:

```text
sample row: data.jsonl line 1
QUESTION_ID: 674552683acc22154b07a598
axis: INFERENCE_MEMORY
conversation path:
benchmark/data/raw/mimo-audio-evalset/multi_challenge/674552683acc22154b07a598/
```

sample fields:

```text
QUESTION_ID: 674552683acc22154b07a598
AXIS: INFERENCE_MEMORY
TARGET_QUESTION: Are the restaurants chosen within a 5-minute walk from the UN headquarters?
PASS_CRITERIA: YES
CONVERSATION length: 3 turns
speech_dialogue length: 3 turns
user_voice_id: english_prompt_147
assistant_voice_id: english_prompt_008
```

conversation turn shape:

```text
CONV[0] role=user, chars=289
  user states that they work at the UN headquarters, dislike taxis/public transportation in New York,
  and prefer venues within a 5-minute walk from UN headquarters.

CONV[1] role=assistant, chars=1166
  assistant suggests nearby options and should preserve the user's walking-distance constraint.

CONV[2] role=user, chars=275
  user asks for an upscale lunch place for a German diplomat on Friday.
```

speech files referenced by the sample:

```text
./674552683acc22154b07a598/0_wav.mp3
./674552683acc22154b07a598/1_assistant_wav.mp3
./674552683acc22154b07a598/2_wav.mp3
```

first user audio metadata:

```text
file: 0_wav.mp3
codec: mp3
sample_rate: 32000
channels: 1
duration_s: 15.840000
size_bytes: 255156
```

이 샘플의 평가 포인트는 "마지막 답변에서 추천한 식당들이 UN headquarters에서 5분 도보 이내인가"다. 즉 단순 음성 인식 문제가 아니라, 첫 turn의 제약을 마지막 turn까지 기억하는지 보는 memory/rubric 평가다. GilJob adapter는 conversation audio를 순서대로 넣고, 마지막 assistant response를 `TARGET_QUESTION`과 `PASS_CRITERIA`에 대해 judge해야 한다.

Primary sources:

- https://arxiv.org/abs/2512.14865
- https://huggingface.co/datasets/ScaleAI/audiomc
- https://labs.scale.com/leaderboard/audiomc

## 6. BigBench Audio

공식 성격:

- Big Bench Hard subset을 audio question form으로 바꾼 audio reasoning dataset이다.
- audio-capable model이 spoken question을 듣고 reasoning answer를 맞히는지 본다.

데이터 특징:

- Hugging Face dataset card 기준 1,000 audio recordings.
- 4 BBH categories, 각 250문항:
  - Formal Fallacies
  - Navigate
  - Object Counting
  - Web of Lies
- English synthetic audio, 23 voices.
- instance fields: `category`, `official_answer`, `file_name`, `id`

로컬 상태:

- path: `benchmark/data/raw/bigbench-audio/`
- mp3: 1,000개
- `metadata.jsonl`: 1,000 rows

GilJob 측정상 의미:

- audio-input reasoning accuracy로 쓸 수 있다.
- official runner transparency는 다른 benchmark보다 낮으므로 `internal-adapted` 성격을 명시해야 한다.
- Realtime audio adapter와 ASR/text diagnostic adapter를 반드시 분리한다.

샘플 해부:

```text
sample row: metadata.jsonl line 1
audio file: benchmark/data/raw/bigbench-audio/data/question_0.mp3
```

sample metadata:

```json
{
  "category": "formal_fallacies",
  "official_answer": "invalid",
  "file_name": "data/question_0.mp3",
  "id": 0
}
```

`question_0.mp3` media metadata:

```text
codec: mp3
sample_rate: 22050
channels: 1
duration_s: 23.562449
size_bytes: 471816
```

이 샘플에서 모델 입력은 audio question 하나뿐이다. metadata에는 prompt text가 없고 `official_answer=invalid`만 있다. 따라서 audio-native row는 MP3를 그대로 모델에 넣어 답을 받아야 하고, ASR/text diagnostic row를 만들려면 별도 transcription step을 명시해야 한다. category가 `formal_fallacies`라서 output extraction은 free-form 답변에서 `valid/invalid`류 label을 안정적으로 뽑는 정책이 필요하다.

Primary sources:

- https://huggingface.co/datasets/ArtificialAnalysis/big_bench_audio
- https://artificialanalysis.ai/methodology/speech-to-speech-benchmarking

## 7. IFEval VoiceBench

공식 성격:

- VoiceBench는 LLM-based voice assistant를 real/synthetic spoken instructions로 평가하는 benchmark다.
- 우리가 채택한 것은 VoiceBench의 `ifeval` subset이다.

데이터 특징:

- VoiceBench 전체는 open-ended QA, multiple-choice QA, multi-turn QA, reasoning, safety 등 여러 subset을 포함한다.
- `ifeval` subset은 Google TTS 기반 spoken instruction-following data다.
- official repo 기준 `ifeval`: 345 samples, task type은 Instruction Following.

로컬 상태:

- path: `benchmark/data/raw/voicebench-ifeval/test-00000-of-00001.parquet`
- rows: 345
- columns include audio bytes/path, prompt, key, and IFEval constraint kwargs.

GilJob 측정상 의미:

- text IFEval과 같은 instruction constraints를 audio interface로 통과시키는지 본다.
- audio recognition 실패와 response instruction-following 실패를 분리해야 한다.

샘플 해부:

```text
sample index: 0
file: benchmark/data/raw/voicebench-ifeval/test-00000-of-00001.parquet
```

sample fields:

```text
top-level keys:
- audio
- key
- prompt
- instruction_id_list
- kwargs

key: 1001
prompt:
I am planning a trip to Japan and I would like thee to write an itinerary for my journey in a Shakespearean style. You are not allowed to use any commas in your response.

instruction_id_list:
- punctuation:no_comma

kwargs:
- all constraint-specific kwargs are null for this instruction
```

embedded audio metadata:

```text
audio.bytes length: 322604
format: wav
codec: pcm_s16le
sample_rate: 16000
channels: 1
duration_s: 10.08
sample_width_bytes: 2
```

이 샘플은 text IFEval의 `punctuation:no_comma` constraint를 spoken prompt로 바꾼 형태다. audio row에서는 모델이 음성을 제대로 이해해야 하고, response에서는 comma를 쓰지 않아야 한다. 실패 원인은 크게 `ASR/음성 이해 실패`, `Shakespearean style 불충분`, `comma 사용`으로 나뉠 수 있으므로 artifact에 transcript와 final response를 분리해 남기는 것이 좋다.

Primary sources:

- https://arxiv.org/abs/2410.17196
- https://github.com/MatthewCYM/VoiceBench
- https://huggingface.co/datasets/lmms-lab/voicebench

## 8. IFEval Text

공식 성격:

- LLM instruction-following을 rule-based로 평가하는 text benchmark다.
- 사람이 judge하지 않고, 검증 가능한 지시만 모아 자동 평가한다.

데이터 특징:

- 약 500 prompts.
- 25 types of verifiable instructions.
- prompt마다 하나 이상의 instruction id와 kwargs가 붙는다.
- 대표 constraint 예시는 length, keyword frequency, forbidden words, output format, punctuation, case, repeat prompt 등이다.

로컬 상태:

- path: `benchmark/data/repos/google-research/instruction_following_eval/data/input_data.jsonl`
- rows: 541
- reference GPT-4 response file도 541 rows 확보.

GilJob 측정상 의미:

- 7개 중 가장 먼저 stable baseline을 만들기 좋다.
- GilJob text boundary, Gemini fallback, report writer 등 text-only adapter에 바로 연결 가능하다.

샘플 해부:

```text
sample line: input_data.jsonl line 1
key: 1000
```

sample prompt:

```text
Write a 300+ word summary of the wikipedia page "https://en.wikipedia.org/wiki/Raymond_III,_Count_of_Tripoli". Do not use any commas and highlight at least 3 sections that has titles in markdown format, for example *highlighted section part 1*, *highlighted section part 2*, *highlighted section part 3*.
```

sample evaluation metadata:

```json
{
  "instruction_id_list": [
    "punctuation:no_comma",
    "detectable_format:number_highlighted_sections",
    "length_constraints:number_words"
  ],
  "kwargs": [
    {},
    {"num_highlights": 3},
    {"relation": "at least", "num_words": 300}
  ]
}
```

이 샘플은 한 prompt 안에 3개 검증 조건이 들어 있다. evaluator는 response가 comma를 쓰지 않았는지, markdown-highlighted section이 최소 3개인지, 단어 수가 300개 이상인지 각각 검사한다. prompt-level accuracy는 3개가 모두 통과해야 pass이고, instruction-level accuracy는 개별 조건 단위로 계산한다.

Primary sources:

- https://arxiv.org/abs/2311.07911
- https://github.com/google-research/google-research/tree/master/instruction_following_eval
- https://huggingface.co/datasets/google/IFEval

## 9. HarmBench

공식 성격:

- Automated red teaming과 robust refusal 평가용 standardized framework다.
- harmful behaviors와 evaluation pipeline, classifier model을 제공한다.

데이터 특징:

- text behaviors와 multimodal behaviors를 포함한다.
- functional categories:
  - standard
  - contextual
  - copyright
- semantic categories include cybercrime, copyright, misinformation/disinformation, illegal, chemical/biological, harassment/bullying, harmful.
- official pipeline은 test case generation, model completion generation, classifier evaluation으로 나뉜다.

로컬 상태:

- path: `benchmark/data/repos/harmbench/data/behavior_datasets/`
- text all: 400 behaviors
- text test: 320 behaviors
- text val: 80 behaviors
- multimodal all: 431 behaviors
- repo includes generation/evaluation scripts and classifier config references.

GilJob 측정상 의미:

- GilJob text safety boundary에 바로 연결할 수 있다.
- refusal rate만 보면 안 되고 over-refusal/benign set도 같이 봐야 한다.
- token/report/session/Realtime secret/SDP/raw media 노출 유도 prompt를 GilJob-specific safety set으로 별도 추가하는 것이 맞다.

샘플 해부:

HarmBench 샘플은 harmful behavior 자체가 평가 입력이므로, 이 문서에는 원문을 재출력하지 않는다. 대신 schema와 safe metadata만 기록한다.

```text
sample file:
benchmark/data/repos/harmbench/data/behavior_datasets/harmbench_behaviors_text_test.csv

sample row: first data row
fields:
- Behavior
- FunctionalCategory
- SemanticCategory
- Tags
- ContextString
- BehaviorID
```

sanitized sample metadata:

```text
BehaviorID: korean_war_north_defensive
FunctionalCategory: standard
SemanticCategory: misinformation_disinformation
Tags: empty
Behavior length: 140 chars
Behavior sha256 prefix: 394b5e866aa5
ContextString length: 0 chars
ContextString sha256 prefix: e3b0c44298fc
```

이 샘플에서 adapter 입력은 `Behavior` 원문이다. 모델 output은 HarmBench classifier가 해당 harmful behavior를 실제로 충족했는지 판단한다. GilJob용으로는 refusal/safe answer를 기대하지만, refusal rate만 높으면 benign 질문까지 거절하는지 알 수 없으므로 over-refusal set을 반드시 별도로 붙여야 한다.

Primary sources:

- https://arxiv.org/abs/2402.04249
- https://github.com/centerforaisafety/HarmBench
- https://www.harmbench.org/
