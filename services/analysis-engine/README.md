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

Not yet implemented in this slice:

- Production LiveKit room subscription loop.
- Delivery of GilJobE records to `services/ai-engine`.
- Real candidate media analysis in the Docker stack.

## Environment contract

| Variable | Purpose | Secret |
|---|---|---|
| `ANALYSIS_ENGINE_ENABLE_SUBSCRIBER` | Explicitly enable the future LiveKit subscriber loop. Defaults to `false`. | no |
| `LIVEKIT_URL` | Internal/container LiveKit URL, for example `ws://livekit:7880`. | no |
| `LIVEKIT_TOKEN` | Optional pre-issued hidden analyzer participant token. | yes |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | Optional fallback for GilJobE self-minting hidden subscriber token. | yes |
| `LIVEKIT_SESSION_ID` | Session id used by GilJobE room naming (`giljob-session-{id}`). | no |
| `GILJOBE_GIT_REF` | Pinned GilJobE source reference included in the image. | no |

`/healthz` is intentionally non-secret and redacted. `/readyz` only reports readiness; it never prints token values.
