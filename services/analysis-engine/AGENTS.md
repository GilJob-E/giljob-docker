# services/analysis-engine Agent Contract

This module owns the GilJobE-backed analysis boundary. Follow the root `AGENTS.md` plus these local rules.

## Current responsibilities
- Treat `GilJobE` as the STT and multimodal input-analysis source of truth.
- Run as the future hidden LiveKit analyzer participant boundary under `services/analysis-engine`.
- Keep startup safe in standby mode unless `ANALYSIS_ENGINE_ENABLE_SUBSCRIBER=true` is explicitly set.
- Report dependency/config readiness without exposing raw LiveKit tokens, JWTs, API secrets, media, or transcript payloads in logs.

## Not implemented here yet
- Do not claim production LiveKit subscription, real candidate media analysis, or AI Engine event delivery unless code and tests implement it.
- Do not reintroduce alternate STT paths in this service.
- Do not mint browser/candidate tokens here; API owns token contracts.

## Tests
Run analysis-engine contract tests after changes:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -p 'test_analysis_engine_contract.py' -v
python3 -m py_compile services/analysis-engine/server.py
```
