# Benchmark data acquisition

이 디렉토리는 채택된 benchmark 데이터 확보 상태를 추적한다. 실제 데이터, clone한 외부 repo, cache, download artifact는 git에 넣지 않는다.

채택된 벤치:

| # | Benchmark | Data source | Local target | Status |
|---|---|---|---|---|
| 1 | FD-bench V1 Turn-taking latency | `DanielLin94144/Full-Duplex-Bench` repo plus Google Drive dataset | `benchmark/data/raw/fd-bench-v1-v1_5` | acquired |
| 4 | QIVD / Qualcomm IVD | Official Qualcomm Developer download page, files `videos.zip` and `annotations.zip` | `benchmark/data/raw/qivd` | acquired |
| 5 | Audio MultiChallenge | Paper claims open-source benchmark; MiMo-Audio-Eval supports `MultiChallenge Audio` via `XiaomiMiMo/MiMo-Audio-Evalset` | `benchmark/data/raw/mimo-audio-evalset/multi_challenge` | acquired |
| 6 | BigBench Audio | Hugging Face dataset `ArtificialAnalysis/big_bench_audio` plus MiMo evaluator support | `benchmark/data/raw/bigbench-audio` | acquired |
| 7 | IFEval VoiceBench | Hugging Face dataset `hlt-lab/voicebench`, subset `ifeval` | `benchmark/data/raw/voicebench-ifeval` | acquired |
| 8 | IFEval Text | `google-research/google-research/instruction_following_eval` | `benchmark/data/repos/google-research` | acquired |
| 9 | HarmBench | `centerforaisafety/HarmBench` repo, `data/` | `benchmark/data/repos/harmbench` | acquired |

## Policy

- Do not commit downloaded audio/video/model outputs.
- Do not store `.env`, API keys, raw session tokens, JWTs, LiveKit tokens, report tokens, or raw GilJob media in this tree.
- Keep source URLs, commit revisions, dataset subsets, and local paths in `sources.json`.
- If a dataset requires manual access, record `blocked` with the required action instead of fabricating a substitute.
