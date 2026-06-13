# Claude Notes for qa/ — product-path verification runbook

Read `qa/README.md` first (run-folder conventions + `meta.json` schema + the
`lk-file` vs `fakecam` publish-path caveat). This file is the **Claude-specific
map** for verifying the realtime product path end-to-end without re-deriving the
structure every session. Prose in English (repo rule); run notes stay where
`qa/README.md` says.

## What "verification" means here

Drive the **real interview room UI** as if a human candidate were answering, then
read the analysis the stack produced. The verification harness is:

    qa/runs/_tools/productpath_signals.mjs   (Node + Playwright)

Run (QA stack must be up; spends OpenAI Realtime tokens):

    node qa/runs/_tools/productpath_signals.mjs \
      --video <clip.mp4> --out-dir qa/runs/<YYYY-MM-DD>-<label> \
      --label <label> --interview-id <id> [--headed] [--wait-s 90] [--pad-ms 3000]

Outputs into `--out-dir`: `signals.json` (canonical), `candidate-fragment.json`
(what the consumer sees), `run.json` (summary), `meta.json` (auto-written).

### Is it equivalent to a real browser session? — Yes, below the page boundary.

It loads the actual room page (`page.goto(.../interviews/<id>/room)`) and clicks
the real DOM buttons (`#toggle-camera`, `#toggle-mic` = 답변 시작/종료), reading the
interviewer reply from the page's own `#current-question-body`. The page, JS,
WebRTC, API broker, analysis-engine, OpenAI Realtime, and LiveKit are all **real**.
Only the inputs are synthetic:

| | real browser | harness |
|---|---|---|
| camera | webcam | `--use-file-for-fake-video-capture` (y4m loop) |
| mic | microphone | `getUserMedia` override injects clip audio via WebAudio |
| operator | human clicks | Playwright clicks the same buttons (headless) |

The avatar bundle (`@spatialwalk`) is blocked (headless GL distortion only). So
findings here hold for the real browser — e.g. the whisper VAD-coverage gap is an
upstream OpenAI server-VAD limit, reproduced identically because injected audio
still rides a real WebRTC track through the same VAD.

## Where `signals.json` actually comes from (the #1 time-sink)

`signals.json` is the **`GET /analysis/signals` payload** (`records` +
`turnHandoff`), i.e. the giljobe-wrapped analysis. It is **NOT** the thin
`/realtime/turn-results` fragment. The objective lanes live in
`turnHandoff.{speech,visual,nonverbal}` + `turnHandoff.prompt_block`.

`candidate-fragment.json` is the `/realtime/turn-results` result: a candidate-safe
**880-char single-line projection** (`render_prompt_fragment`, giljobe
`src/giljobe/emit/handoff.py`) — what the consumer LLM is actually fed. It is a
lossy summary of `prompt_block`, not the raw handoff.

## Lane read-out architecture (so you don't re-trace it)

- `turnHandoff` = **aggregate of per-sentence records** (`build_turn_handoff`,
  giljobe `emit/handoff.py`; `visual_in = [r.visual for r in sents] or [evals]`).
  Any time not covered by some sentence span is never read out.
- **Turn boundary** = 답변 시작/종료 buttons. **Sentence segmentation inside the
  turn** = OpenAI server-VAD events (`speech_started/stopped` + `transcript.completed`)
  via `RealtimeTurnTracker` (`pipeline/sentences.py`). **Both** shape `turnHandoff`:
  if VAD never fires for a region, no sentence covers it → it's absent from the handoff.
- Per-sentence windows (`_do_sentence`, `pipeline/windowing.py`):
  - vision / nonverbal = `[prev_sentence_end, this_end]` (end-to-end, **includes
    inter-sentence silence** so silent gestures e.g. finger counts are captured)
  - prosody = `[speech_onset, this_end]` (speech-bounded, so silence doesn't dilute
    articulation rate / energy)
- `GILJOBE_EVAL_GRID=off` is the deploy default (`infra/docker-compose.yml`) → there
  is **no transcript-independent vision read**. Media-only publishing therefore yields
  an essentially empty `signals.json`; you must use the product path (real transcript).

## RNAS is dormant under pin f7307fc

RNAS = Realtime-Native Analysis Session (`_EventOnlyRealtimeTurns` /`_RnasSession`
in `services/analysis-engine/server.py`) — assembles `transcriptSignals` /
`prosodySignals` / `visionSignals` from forwarded sideband events. **But under pin
f7307fc GilJobE owns `POST /realtime/turn-events`** (the wrapper's `_route_registered`
guard skips its own handler), so RNAS sessions never fill → `/realtime/turn-results`
falls back to the turnHandoff-fragment branch (`schemaVersion:
2026-06-12.turn-handoff-fragment.v2` in our artifacts is the proof). Don't chase
`visionSignals`/`prosodySignals` in turn-results expecting rich lanes; the rich data
is in `turnHandoff` via `/analysis/signals`.

## Consumer LLM does NOT get the raw turnHandoff

API fetches the fragment (`services/api/server.py` `_fetch_analysis_result` →
`/realtime/turn-results`) and wraps it as *"Use this candidate-safe guidance from
the previous answer to ask the next Korean interview question … Guidance: {fragment}"*
(`create_realtime_response`). So the consumer is an **interviewer asking the next
question**, not answering — it will not echo measurements (e.g. finger counts)
verbatim, and its use of the fragment is non-deterministic. Analysis correctness is
judged from `signals.json`/`candidate-fragment.json`, not from the spoken reply.

## Hot-patch deploy (cross-repo) — giljobe lives in a separate repo

The analysis-engine **bakes** giljobe at build time into
`/usr/local/lib/python3.12/site-packages/giljobe` (no source mount). The source is
the separate repo `/home/kio/workspace/giljobe`, branch `feat/grounding-hands-whisper`
@ `f7307fc` (the container's `GILJOBE_GIT_REF`).

To test a giljobe code change without a rebuild:

    docker cp <file> giljob-qa-analysis-engine-1:/usr/local/lib/python3.12/site-packages/giljobe/<path>
    docker restart giljob-qa-analysis-engine-1
    # wait for ready:
    curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8081/analysis/readyz   # → 200

When you hot-patch, a container rebuild/replace **loses it** unless you commit
giljobe + bump the pin (`GILJOBE_GIT_REF` in `infra/docker-compose.yml`,
`.env.example`, `Dockerfile`, `requirements.txt`, and `PINNED_GILJOBE_REF` in
`tests/contract/test_analysis_engine_contract.py` — the contract test enforces
consistency + a superseded-ref guard).

### giljobe analysis fixes committed in pin f7307fc (2026-06-13)

Committed on `feat/grounding-hands-whisper` (f7307fc, supersedes a26045d → f817f81);
the QA engine runs this code. All validated by `pytest tests/` (177 passed,
4 vLLM-skipped), regression tests included:

1. `analysis/grounding.py` + `emit/handoff.py` — removed the wrist-not-visible
   "관측 불가(평가 금지)" guard that was contradicting finger-count numbers.
2. `pipeline/sentences.py` — sentence window = prev-end → this-end (stop skipping
   inter-sentence silence); added `speech_start_s` for prosody bounding.
3. `pipeline/windowing.py` `_do_sentence` — vision/nv end-to-end, prosody
   speech-bounded.
4. `emit/handoff.py` + `analysis/prosody.py` — whisper (voiced_ratio<0.15) takes
   priority over sparse-voicing F0, so a low-confidence F0 doesn't mask "속삭임형".
5. `emit/handoff.py` `render_prompt_fragment` — face guard now checks
   `face_seen_ratio>0` (not just `face_frames`); a no-face cam (empty room) emits
   "얼굴 미검출", not "미소 평균 None", so the consumer can't claim it sees a face.
   `.dev/grounding/noface_trace.py` reproduces the empty-cam → fragment path.

## Current up-to-date signals (regenerate after any engine change)

- vision: `qa/runs/2026-06-13-vision-test-productpath-final/` — finger seq `[4,2,5]`
- audio:  `qa/runs/2026-06-13-audio-test-productpath-final/` — whisper + slow surfaced

Older 2026-06-13 runs (pre-fix stages, groundtruth) are in `qa/runs/_archive/`.

## Environment / deps (all present on this host)

- analysis-engine via QA caddy: `http://127.0.0.1:8081/analysis` (`/healthz`,
  `/readyz`, `/signals`, `/realtime/turn-results`). LiveKit: `ws://127.0.0.1:17880`.
- `google-chrome`, Playwright (`benchmark/data/cache/browser-tools/node_modules`),
  and the `livekit/livekit-cli` image are installed.
- LiveKit keys come from shell env or `.env` (never print them); tokens are minted
  via the `livekit-cli` container.
