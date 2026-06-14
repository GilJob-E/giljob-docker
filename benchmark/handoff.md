# Benchmark handoff

작성 시점: 2026-06-12

## 현재 목표

채택 benchmark 7개는 다음이다.

1. `01-fd-bench-v1-turn-taking-latency`
2. `04-qivd`
3. `05-audio-multichallenge`
4. `06-bigbench-audio`
5. `07-ifeval-voicebench`
6. `08-ifeval-text`
7. `09-harmbench`

현재 benchmark 작업의 핵심 원칙은 다음이다.

> 핵심은 "full-duplex 여부"가 아니라 동일 데이터, 동일 judge, 동일 latency 기준으로 GilJob 행을 만든다.

PR #15 이후 GilJob v2는 LiveKit 중심 측정이 아니라 API-mediated OpenAI Realtime WebRTC 경로를 기준으로 본다. 제품 latency row는 `/realtime/session`, `/realtime/call`, `full_mmm_ready`, Realtime response create, first text/audio delta를 같은 monotonic clock 기준으로 기록한다.

## 반영된 구조

- `benchmark/README.md`
  - GilJob row 이름을 `GilJob v2 Realtime adapter` 중심으로 정리했다.
  - Gemini next-question/TTS 또는 ASR/text 경로는 fallback/diagnostic row로 분리하도록 명시했다.
- `benchmark/harness/README.md`
  - `evaluator-smoke`, `component`, `product-path`, `full-service-e2e` measurement level을 추가했다.
  - FD-Bench V1용 product-path/direct browser collector 사용법을 추가했다.
  - inline analysis fixture 또는 benchmark probe bridge를 쓰는 run은 product-path complete로 집계하지 않도록 설명했다.
- `benchmark/harness/targets.json`
  - 선택된 7개 benchmark의 runner/adapter/evaluator 상태를 추적한다.
  - FD-Bench V1의 target을 `product-path` / `realtime-product-path`로 둔다.
- `benchmark/harness/run_fdbench_v1_latency.py`
  - Realtime timestamp aliases를 지원한다.
  - `t_mmm_ready_s`, `t_response_create_s`, first text/audio delta, response done을 latency artifact로 계산한다.
  - `analysis_inline_fixture_used` 또는 `response_command_forwarded_by_probe`가 true인 row는 `product_path_complete`에서 제외한다.
- `benchmark/harness/probe_realtime_product_path.py`
  - API sideband component probe다.
  - `/realtime/session`, turn events, vision events, `/mmm-ready`를 호출한다.
  - browser WebRTC SDP attach와 first delta는 포함하지 않는다.
- `benchmark/harness/collect_realtime_direct_fdbench.mjs`
  - Playwright/Chrome fake audio로 FD-Bench audio를 Realtime path에 넣는다.
  - API-mediated `/realtime/session`과 `/realtime/call` broker를 사용한다.
  - standard provider key, raw client secret, SDP body, raw media를 artifact에 쓰지 않는다.
  - `--analysis-inline-fixture`는 live analysis-engine result가 없을 때 response-create plumbing만 여는 진단 옵션이다.
  - `--forward-api-command-on-browser-channel`은 API가 반환한 command를 benchmark probe가 browser data channel로 전달해 first delta만 확인하는 진단 옵션이다.
- `benchmark/harness/collect_realtime_browser_fdbench.mjs`
  - 실제 room UI를 통한 browser collector다.
  - 현재 UI 경로 smoke에서는 `/realtime/call` upstream failure가 있었고, direct collector 쪽을 우선 보강했다.

## 확인한 실행 결과

### Component MMM gate smoke

Run:

```text
benchmark/runs/01-fd-bench-v1-turn-taking-latency/pr15-realtime-mmm-gate-smoke-2
```

관측:

- `realtime_session_contract_observed=true`
- `full_mmm_ready=true`
- route statuses:
  - realtime session: `200`
  - turn events: `202`
  - vision event: `202`
  - mmm-ready: `200`
- browser WebRTC와 first model delta는 포함하지 않는 `component` level run이다.

### Direct browser product-path smoke

Run:

```text
benchmark/runs/01-fd-bench-v1-turn-taking-latency/pr15-direct-browser-product-path-smoke-3
```

관측:

- API call broker observed: true
- browser WebRTC observed: true
- `full_mmm_ready=true`
- response-create 단계에서 `409 analysis_result_unavailable`

해석:

- WebRTC attach와 MMM gate까지는 연결됐다.
- live analysis-engine result가 준비되지 않아 API response-create가 막혔다.

### Inline analysis fixture smoke

Run:

```text
benchmark/runs/01-fd-bench-v1-turn-taking-latency/pr15-direct-browser-product-path-smoke-6-inline-analysis
```

관측:

- API call broker observed: true
- API response create observed: true
- browser WebRTC observed: true
- `full_mmm_ready=true`
- first audio/text delta observed
- `analysis_inline_fixture_used=true`
- `product_path_complete_rate=0.0`

해석:

- Realtime plumbing 자체는 first delta까지 열릴 수 있다.
- 그러나 live analysis-engine result 대신 inline fixture를 썼으므로 official/product-path complete로 집계하지 않는다.

### Inline fixture + probe command bridge smoke

Run:

```text
benchmark/runs/01-fd-bench-v1-turn-taking-latency/pr15-direct-browser-product-path-smoke-8-inline-analysis-command-bridge
```

관측:

- first response latency: `1094.8ms`
- `technical_realtime_first_delta_observed=true`
- `response_command_forwarded_by_probe=true`
- `product_path_complete_rate=0.0`

해석:

- API가 반환한 command를 benchmark probe가 browser data channel로 전달하면 first delta가 관측된다.
- 이 bridge는 제품 소유 sideband 송신이 아니므로 product-path complete로 집계하지 않는다.

## 현재 gap

1. Live analysis-engine result가 response-create endpoint까지 안정적으로 전달돼야 한다.
2. API가 생성한 response-create command가 실제 Realtime sideband/data channel로 제품 경로에서 송신돼야 한다.
3. 위 두 조건이 만족되면 `--analysis-inline-fixture`와 `--forward-api-command-on-browser-channel` 없이 FD-Bench V1 product-path run을 다시 돌려야 한다.
4. `full-service-e2e`는 아직 target이 아니다. SpatialReal avatar RTC/egress, public TURN/external media path, final report generation은 제외했다.

## 검증

통과한 검증:

```bash
node --check benchmark/harness/collect_realtime_direct_fdbench.mjs benchmark/harness/collect_realtime_browser_fdbench.mjs apps/web/static/app.js
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile benchmark/harness/probe_realtime_product_path.py benchmark/harness/run_fdbench_v1_latency.py benchmark/harness/run_qivd_offline.py
python3 -m json.tool benchmark/harness/targets.json
git diff --check
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -v
```

계약 테스트 결과:

```text
Ran 78 tests in 27.706s
OK
```

## Git 상태 메모

benchmark 관련 변경 외에 다음 untracked 항목은 기존/외부 작업물로 보이며 이 작업에서는 건드리지 않았다.

```text
.ppt/
apps/web/design.md
```

benchmark run artifact는 `benchmark/runs/` 아래에 남지만 git ignore 대상이다. raw secrets, SDP body, raw media는 출력/저장하지 않는 방침을 유지한다.
