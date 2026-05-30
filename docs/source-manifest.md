# Source Manifest — GilJob_v2

- Generated UTC: 2026-05-30T05:19:01Z
- Target host: `hoddukzoa@kiostation`
- Target root: `/home/hoddukzoa/GilJob_v2`
- Provenance: copied from local reviewed docs/planning artifacts in `/Users/hoddukzoa/Desktop/학교/giljob`; not copied from remote legacy `/home/hoddukzoa/GilJob`.
- Legacy rule: `/home/hoddukzoa/GilJob` is reference-only and must remain untouched.

## Files

| sha256 | size | target path |
|---|---:|---|
| `164f0705edb4abbc2254c88656a7a090acc6c605b65431ca41bc8fae742164aa` | 10316 | `docs/planning/deep-interview-giljob-v2-execution-spec.md` |
| `7904351e015a38351345abace33768d5a4f2d89db498ed66638f1bef811190e1` | 11489 | `docs/planning/prd-giljob-v2-execution-prep-20260530T050637Z.md` |
| `c47f68a80929fc4516e8fd2f825b6790a45631e74daf79826017f3fe010d1632` | 1264 | `docs/planning/ralplan-dr-giljob-v2-execution-prep-20260530T050637Z.md` |
| `5df1e4a5416e2c5c8b2b886ddf7e881ca9694b0724fba9930712e07fc2fb90a3` | 1657 | `docs/planning/ralplan-giljob-v2-execution-prep-20260530T051157Z.json` |
| `d235c575c36ffd3a898f0b2c84367acfa89a52c74dd53c7755cad8a2eaeb0d0e` | 6478 | `docs/planning/test-spec-giljob-v2-execution-prep-20260530T050637Z.md` |
| `b08a169a84883b89ada58c1e01f43a5937ec8d0490ec6e530adc209a87a9313e` | 896 | `docs/reviews/architect-giljob-v2-execution-prep-20260530T050637Z.md` |
| `d7a5636166ce0ae9a77950213e0a4e5a79578cf2d42b4801134aaa9146aacb9f` | 2140 | `docs/reviews/critic-giljob-v2-execution-prep-20260530T050637Z.md` |
| `29fc7e626dcff46fe4395a5580ae796220c4a30ee1fd7b5701ca3416db8c3635` | 76988 | `docs/source/giljob-v0.3.1-final-spec.md` |
| `0b949a85e8dcbd3a3de5e5399abc731c41356553093ad7b70d4c2570940bfcf4` | 2720 | `docs/source/giljob-v0.3.1-high3-validation.md` |

## Required next evidence

- Verify remote SHA256 against this manifest.
- Record `stat /home/hoddukzoa/GilJob` before/after v2 writes as untouched evidence.
- Continue with ADRs: `docs/decisions/0001-state-stack.md`, `docs/decisions/0002-ingress-stack.md`.

## Implementation amendments

- 2026-05-30: `docs/planning/test-spec-giljob-v2-execution-prep-20260530T050637Z.md` was amended in-place to reflect the hardened ingress contract: public `/readyz` returns 404, while container-internal API `/readyz` returns success.
- 2026-05-30: `docs/source/giljob-v0.3.1-final-spec.md` smoke block was amended to match the active v2 scaffold commands and hardened readiness contract.
