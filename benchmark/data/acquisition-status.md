# Acquisition status

Updated: 2026-06-11

| # | Benchmark | Status | Local data |
|---|---|---|---|
| 1 | FD-bench V1 Turn-taking latency | acquired | `benchmark/data/raw/fd-bench-v1-v1_5/` |
| 4 | QIVD / Qualcomm IVD | acquired | `benchmark/data/raw/qivd/` |
| 5 | Audio MultiChallenge | acquired | `benchmark/data/raw/mimo-audio-evalset/multi_challenge/` |
| 6 | BigBench Audio | acquired | `benchmark/data/raw/bigbench-audio/` |
| 7 | IFEval VoiceBench | acquired | `benchmark/data/raw/voicebench-ifeval/test-00000-of-00001.parquet` |
| 8 | IFEval Text | acquired | `benchmark/data/repos/google-research/instruction_following_eval/` |
| 9 | HarmBench | acquired | `benchmark/data/repos/harmbench/data/` |

## Verification

```text
FD-bench V1: ok, v1_0_files=3743, v1_5_files=3496, size_mib=2051.8
QIVD: ok, labels=2900, mp4_files=2900, size_mib=1681.9
Audio MultiChallenge: ok, examples=198, media_files=1931, size_mib=1574.2
BigBench Audio: ok, examples=1000, mp3_files=1000, size_mib=304.6
VoiceBench IFEval: ok, files=1, size_mib=112.4
IFEval Text: ok, prompts=541, files=12
HarmBench: ok, text_behaviors_all_lines=1530, files=227, size_mib=350.8
```

Run verification with:

```bash
python3 benchmark/data/verify_acquisition.py
```

## QIVD

QIVD was acquired from the official Qualcomm Developer download page: https://www.qualcomm.com/developer/software/qualcomm-interactive-video-dataset-qivd/downloads. Local files include `annotations.zip`, `videos.zip`, extracted `labels.json`, and extracted `videos/*.mp4` under `benchmark/data/raw/qivd/`.
