# ADR 0004 — LiveKit-free Realtime/MMM default and SpatialReal SDK Mode spike

- Status: Accepted for the next implementation slice
- Date: 2026-06-12
- Gate: LiveKit removal from the main Realtime/MMM path
- Source: approved RALPLAN handoff `livekit-free-realtime-mmm-spatialreal-sdk-20260612T153126Z`, SpatialReal autoresearch report, `.env.example`, `apps/web/package.json`

## Context

GilJob's product-critical interview loop is **candidate answer → analysis-engine MMM result → Hashimoto strategy adapter → API-owned `response.create` → OpenAI Realtime output**. OpenAI Realtime WebRTC does not need LiveKit. The prior room/avatar scaffold still contains LiveKit media-room and AvatarKit RTC wiring, which made `LIVEKIT_PUBLIC_URL` and SpatialReal RTC reachability look like prerequisites for the main interview path.

SpatialReal itself is not inherently LiveKit-only. Official integration docs distinguish SDK Mode, RTC Mode, and Host Mode. The retired GilJob implementation was LiveKit-bound when it used AvatarKit RTC/UI concepts (`@spatialwalk/avatarkit-rtc`, `LiveKitProvider`, `AvatarPlayer.publishAudio(track)`). The current default target is SDK Mode Web through `@spatialwalk/avatarkit`, not because Realtime/MMM requires LiveKit.

## Decision

Adopt a **LiveKit-free default Realtime/MMM path**:

- OpenAI Realtime remains the only live interviewer voice/STT path.
- The API owns Realtime session/call brokering and authors/approves `response.create`.
- Turn 1 may bootstrap without a prior MMM result.
- Ordinary follow-up turns require exact prior-turn full MMM readiness and a candidate-safe analysis result.
- LiveKit remains optional/legacy for media-room compatibility and AvatarKit RTC experiments only; it is not required for default `/api/sessions`, Realtime broker, MMM sideband ingress, or the success claim.

SpatialReal avatar work moves to a separate non-default spike:

1. Try SDK Mode Web first because it is the simplest official non-LiveKit path.
2. Treat Host Mode as the fallback if SDK Mode cannot safely consume the audio source.
3. Keep avatar UI disabled/deferred unless a feature-flagged proof is verified.
4. Do not claim production lip-sync until kiostation browser evidence proves the audio-to-avatar path without raw SDP, provider secrets, tokens, transcripts, or raw media logs.

## SDK Mode implementation contract for this lane

Outcome before kiostation credentialed QA: `sdk_mode_deferred` or a safe blocked reason.

Evidence available in this checkout:

- `apps/web/package.json` declares `@spatialwalk/avatarkit` `1.0.0-beta.104` only for the default SDK path; `livekit-client` and `@spatialwalk/avatarkit-rtc` are not default dependencies.
- The web image vendors `/vendor/@spatialwalk/avatarkit/dist/*` and serves JavaScript plus WASM with safe MIME types.
- The browser initializes SDK Mode only after API-owned ready metadata, mutes SDK playback, and feeds a PCM16 copy of OpenAI Realtime output to `AvatarController.send(pcm, false)`.

Until kiostation browser QA proves avatar render, connected state, and lip movement without double audio, the product must report `sdk_mode_deferred` or a concrete blocked reason such as `sdk_mode_blocked_missing_provider_token`, `sdk_mode_blocked_dynamic_import`, `sdk_mode_blocked_pcm_send_failed`, or `sdk_mode_blocked_double_audio_or_mute`.

## Consequences

- Docs and env examples must not imply `LIVEKIT_PUBLIC_URL` is required for Realtime/MMM.
- AvatarKit RTC and SpatialReal-to-LiveKit egress are legacy compatibility paths, not default production claims.
- Reintroducing LiveKit into the default path requires a new ADR and tests proving why Realtime/MMM cannot remain LiveKit-free.
- Remote rebuild/restart and browser smoke remain kiostation-only integration steps after implementation is synchronized by the leader.

## Verification

Minimum local/static verification for this decision surface:

- `node --check apps/web/static/app.js`
- `npm --prefix apps/web run check:js`
- `PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile services/api/server.py services/analysis-engine/server.py`
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -v`
- `./scripts/kiostation-verify-archive.sh`

Kiostation Docker rebuild/restart and browser Realtime/MMM smoke are final integration evidence only and must not print `.env`, raw SDP, tokens, provider keys, transcripts, or raw media.
