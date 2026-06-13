# services/analysis-engine

GilJobE-backed analysis boundary for GilJob v2.

This service is the planned hidden LiveKit analyzer participant:

```text
Candidate browser -> LiveKit room -> services/analysis-engine (GilJobE)
  -> transcript_full + multimodal signals -> ai-engine / interview controller
```

## Current slice

Implemented now:

- Docker/service scaffold under `services/analysis-engine`.
- Pinned GilJobE dependency in `requirements.txt`.
- Token-safe HTTP health/contract surface.
- Compose wiring with standby default.
- Temporary dummy scenario mode for this branch, gated by
  `ANALYSIS_ENGINE_DUMMY_SCENARIO`, which emits the same `/signals` input/output
  shape without LiveKit, GilJobE/MMM, Docker media, or a local model runtime.

Not yet implemented in this slice:

- Production LiveKit room subscription loop.
- Delivery of GilJobE records to `services/ai-engine`.
- Real candidate media analysis in the Docker stack.

## Environment contract

| Variable | Purpose | Secret |
|---|---|---|
| `ANALYSIS_ENGINE_ENABLE_SUBSCRIBER` | Explicitly enable the future LiveKit subscriber loop. Defaults to `false`. | no |
| `ANALYSIS_ENGINE_DUMMY_SCENARIO` | Optional local test stand-in. Set to `hashimoto-report-ui` to make `/subscriber/start`, `/subscriber/stop`, and `/signals` emit deterministic dummy records. | no |
| `LIVEKIT_URL` | Internal/container LiveKit URL, for example `ws://livekit:7880`. | no |
| `LIVEKIT_TOKEN` | Optional pre-issued hidden analyzer participant token. | yes |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | Optional fallback for GilJobE self-minting hidden subscriber token. | yes |
| `LIVEKIT_SESSION_ID` | Session id used by GilJobE room naming (`giljob-session-{id}`). | no |
| `GILJOBE_GIT_REF` | Pinned GilJobE source reference included in the image. | no |

`/healthz` is intentionally non-secret and redacted. `/readyz` only reports readiness; it never prints token values.

## Temporary dummy scenario

For hashimoto/report UI verification on machines that cannot run Docker media or
the local model runtime:

```powershell
$env:ANALYSIS_ENGINE_DUMMY_SCENARIO='hashimoto-report-ui'
$env:SERVICE_PORT='8200'
py services/analysis-engine/server.py
```

The dummy mode is process-local and deterministic. `POST /subscriber/start`
stages one transcript/eval window, `POST /subscriber/stop` closes it with a
`turn_end`, and `GET /signals?sessionId=local-demo` returns `window`, `eval`,
and `turn_end` records in the shape consumed by `services/api`.
