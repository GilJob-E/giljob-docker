# Benchmark harness

이 디렉토리는 채택된 benchmark를 실제 측정으로 연결하기 위한 provisional harness다. GilJob의 최종 evaluation pipeline이 아직 확정되지 않았으므로, 여기서는 제품 경로를 강하게 고정하지 않고 다음 세 가지만 고정한다.

1. 동일 데이터 subset을 명시한다.
2. response 생성 adapter를 명시한다.
3. judge/evaluator와 latency artifact를 같은 run 디렉토리에 남긴다.

## Run artifact contract

모든 run은 기본적으로 다음 위치에 생성한다.

```text
benchmark/runs/<benchmark_id>/<run_id>/
```

각 run 디렉토리는 다음 파일을 가진다.

| 파일 | 의미 |
|---|---|
| `manifest.json` | benchmark id, dataset source, adapter, run status, artifact 경로 |
| `inputs.jsonl` | 이번 run에 실제로 사용한 입력 예제 |
| `responses.jsonl` | adapter가 생성한 응답. evaluator 입력으로도 사용 가능해야 한다. |
| `latency.jsonl` | example 단위 wall-clock latency와 stage latency |
| `metrics.json` | evaluator 결과를 요약한 기계 판독용 지표 |
| `errors.jsonl` | example 단위 실패. 성공 run에서는 빈 파일이다. |
| `evaluation/` | official 또는 fixed evaluator의 raw output |

`benchmark/runs/`는 git ignore 대상이다. 모델 응답, judge 결과, raw timing, 실패 로그는 재현을 위해 로컬에는 남기되 commit하지 않는다.

## Adapter contract

현재 adapter contract는 의도적으로 작게 둔다.

```text
prompt/input artifact
  -> adapter
  -> response text or structured response
  -> official/fixed evaluator
```

Text benchmark에서는 adapter가 `prompt`를 받아 `response`를 만든다. Audio/video benchmark에서는 이후 다음 stage를 추가한다.

```text
media input
  -> transcript/frame/audio feature adapter
  -> response adapter
  -> evaluator
```

GilJob product path, direct model API, oracle transcript, offline VLM, LiveKit streaming path는 모두 adapter 이름으로 분리한다. 같은 benchmark 표에 섞더라도 `adapter_type`과 timestamp 기준을 manifest에 반드시 남긴다.

## Secret and media policy

- `.env` 값, API key, session token, report token, JWT, LiveKit token은 artifact에 저장하지 않는다.
- raw GilJob media는 run artifact에 저장하지 않는다. benchmark 원본 media는 `benchmark/data/raw/` 아래의 ignored data로만 둔다.
- command adapter를 사용할 때 stdout은 response로 저장된다. adapter command는 stdout에 응답 외 로그나 secret을 쓰지 않아야 한다.
- runner는 obvious API key/JWT 패턴을 저장 전에 `[REDACTED]` 처리하고 `secret_exposure_count`로 카운트한다. 이 카운트는 정밀 secret scanner가 아니라 안전장치다.

## IFEval Text smoke

선택된 7개 benchmark의 현재 runner 준비 상태는 `targets.json`에 둔다. 이 파일은 최종 pipeline 선언이 아니라, 어떤 데이터와 adapter/evaluator를 먼저 연결할지 추적하는 작업용 matrix다.

의존성은 official IFEval requirements를 기준으로 하되, `absl`의 pip 패키지명은 `absl-py`를 사용한다. `nltk` tokenizer data도 cache 아래에 둔다.

```bash
benchmark/data/cache/data-tools/bin/pip install absl-py langdetect nltk immutabledict
benchmark/data/cache/data-tools/bin/python -m nltk.downloader -d benchmark/data/cache/nltk_data punkt punkt_tab
```

evaluator 연결만 확인하려면 reference response로 20개 subset을 돌린다.

```bash
PYTHONDONTWRITEBYTECODE=1 benchmark/data/cache/data-tools/bin/python benchmark/harness/run_ifeval_text.py \
  --limit 20 \
  --adapter reference-jsonl
```

외부 pipeline이 만든 response JSONL을 평가하려면 다음 형식을 사용한다.

```json
{"prompt": "...", "response": "..."}
```

```bash
PYTHONDONTWRITEBYTECODE=1 benchmark/data/cache/data-tools/bin/python benchmark/harness/run_ifeval_text.py \
  --adapter existing-jsonl \
  --responses-jsonl path/to/responses.jsonl
```

명령형 adapter는 prompt를 stdin으로 받고 stdout을 response로 저장한다.

```bash
PYTHONDONTWRITEBYTECODE=1 benchmark/data/cache/data-tools/bin/python benchmark/harness/run_ifeval_text.py \
  --limit 20 \
  --adapter command \
  --command "python3 scripts/my_text_adapter.py"
```

## HarmBench Text Smoke

HarmBench text runner는 기본적으로 `harmbench_behaviors_text_test.csv`를 사용한다. 이 runner의 내장 evaluator는 lightweight refusal detector이므로 공식 HarmBench classifier 점수가 아니다. 대신 `harmbench_completions.json`을 함께 생성해서 나중에 공식 `evaluate_completions.py` 또는 별도 judge로 다시 평가할 수 있게 한다.

안전 거절 baseline으로 20개 smoke를 돌린다.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 benchmark/harness/run_harmbench_text.py \
  --limit 20 \
  --adapter safe-refusal
```

외부 pipeline이 만든 response JSONL을 평가하려면 `behavior_id` 또는 `prompt`와 `response`를 포함한다.

```json
{"behavior_id": "example_behavior_id", "response": "..."}
```

```bash
PYTHONDONTWRITEBYTECODE=1 python3 benchmark/harness/run_harmbench_text.py \
  --adapter existing-jsonl \
  --responses-jsonl path/to/responses.jsonl
```

명령형 adapter는 IFEval과 동일하게 prompt를 stdin으로 받고 stdout을 response로 저장한다.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 benchmark/harness/run_harmbench_text.py \
  --limit 20 \
  --adapter command \
  --command "python3 scripts/my_safety_adapter.py"
```

## VoiceBench IFEval Smoke

VoiceBench IFEval runner는 parquet 안의 `audio.bytes`를 raw artifact로 저장하지 않는다. 대신 audio byte count와 SHA-256만 `inputs.jsonl`에 남긴다. 첫 runner는 `prompt` 필드를 oracle transcript로 사용해 IFEval evaluator 연결을 확인한다. 실제 ASR/GilJobE 경로는 별도 adapter로 추가한다.

parquet reader가 필요하다.

```bash
benchmark/data/cache/data-tools/bin/pip install pyarrow
```

oracle transcript 기반 placeholder smoke:

```bash
PYTHONDONTWRITEBYTECODE=1 benchmark/data/cache/data-tools/bin/python benchmark/harness/run_voicebench_ifeval.py \
  --limit 20 \
  --adapter placeholder-empty
```

외부 pipeline response를 평가하려면 `example_id` 또는 `prompt`와 `response`를 포함한다.

```bash
PYTHONDONTWRITEBYTECODE=1 benchmark/data/cache/data-tools/bin/python benchmark/harness/run_voicebench_ifeval.py \
  --adapter existing-jsonl \
  --responses-jsonl path/to/responses.jsonl
```

## BigBench Audio Smoke

BigBench Audio runner는 공개 official runner가 고정되지 않은 상태이므로 `internal-adapted`로만 기록한다. Adapter에는 raw audio bytes가 아니라 로컬 audio path와 category metadata를 넘긴다.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 benchmark/harness/run_bigbench_audio.py \
  --limit 20 \
  --adapter constant-answer \
  --constant-answer No
```

외부 pipeline response는 `example_id` 또는 `audio_path`와 `response`를 포함한다.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 benchmark/harness/run_bigbench_audio.py \
  --adapter existing-jsonl \
  --responses-jsonl path/to/responses.jsonl
```

## Audio MultiChallenge Smoke

Audio MultiChallenge runner는 첫 단계에서 `TARGET_QUESTION`에 대한 `YES/NO` 답을 평가하는 binary rubric 형태로 둔다. 이는 full multi-turn audio-agent simulation이 아니라, rubric/evaluator artifact를 먼저 고정하기 위한 provisional runner다.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 benchmark/harness/run_audio_multichallenge.py \
  --limit 20 \
  --adapter constant-answer \
  --constant-answer YES
```

외부 pipeline response는 `question_id` 또는 `target_question`과 `response`를 포함한다.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 benchmark/harness/run_audio_multichallenge.py \
  --adapter existing-jsonl \
  --responses-jsonl path/to/responses.jsonl
```

## FD-Bench V1 Latency Smoke

FD-Bench V1 latency runner는 official full-duplex score가 아니라 GilJob turn-based latency diagnostic row다. Adapter는 `t_user_audio_end_s` 기준으로 `model_response_start_s` 또는 `t_tts_first_audio_s`를 반환해야 한다.

artifact plumbing만 확인하려면 simulated latency를 사용한다.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 benchmark/harness/run_fdbench_v1_latency.py \
  --limit 20 \
  --adapter simulated-latency \
  --simulated-latency-ms 750
```

외부 timestamp JSONL은 `example_id`와 timestamp field를 포함한다.

```json
{"example_id": "1", "t_user_audio_end_s": 5.63, "model_response_start_s": 6.38}
```

```bash
PYTHONDONTWRITEBYTECODE=1 python3 benchmark/harness/run_fdbench_v1_latency.py \
  --adapter existing-jsonl \
  --timestamps-jsonl path/to/timestamps.jsonl
```

## QIVD Offline Smoke

QIVD runner는 첫 단계에서 offline video-QA 형태로만 동작한다. Adapter에는 video path, question, category, reference timestamp를 넘긴다. LiveKit streaming timing은 별도 runner로 추가한다.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 benchmark/harness/run_qivd_offline.py \
  --limit 20 \
  --adapter short-answer-oracle
```

외부 response는 `example_id` 또는 `video`와 `response`를 포함한다. `answer_start_s`를 같이 넣으면 `answer_timing_mae_ms`도 계산한다.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 benchmark/harness/run_qivd_offline.py \
  --adapter existing-jsonl \
  --responses-jsonl path/to/responses.jsonl
```
