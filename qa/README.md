# QA 폴더 구조 (2026-06-12 정리)

> 이 폴더 전체는 gitignore 대상(raw 미디어·전사 포함 산출물). 정리 이전 문서들이
> `qa/<파일>.json` 평면 경로를 참조하면 `qa/archive/<파일>.json`에서 찾을 것.

```
qa/
  media/      # 원본 테스트 미디어 (kor.mp4, vid_0001.mp4, vid_0033.mp4)
  archive/    # 2026-06-11까지의 산출물 JSON (pre-체계화 — 런 조건은 핸드오프/커밋 메시지 참조)
  runs/       # 2026-06-12부터의 체계 실험 — 런마다 폴더
  *.md        # 정본 문서 (nv-lane-investigation, handoff-schema-notes) — 경로 참조 유지를 위해 루트 고정
```

## 런 관례 (`runs/<YYYY-MM-DD>-<실험명>/`)

런 폴더마다 **meta.json 필수** — "이 결과 어떤 조건에서 나온 거지?"의 재발 방지가 목적.

```jsonc
// meta.json 필수 필드
{
  "date": "2026-06-12",
  "purpose": "한 줄 가설/목적",
  "giljobe_pin": "<커밋 sha>",          // analysis-engine 컨테이너의 GilJobE 핀
  "image": "analysis-engine:<tag>",     // 핫패치 여부 명기
  "env": { "GILJOBE_TRANSCRIPT_SOURCE": "external", "GILJOBE_VISION": "auto" },
  "media": "qa/media/kor.mp4",
  "publish_path": "lk-file | fakecam-browser | webcam",  // ★ 영상 딜리버리 특성 좌우
  "transcript_feed": "harness-sideband | openai-realtime",
  "stack": "giljob-qa"
}
```

결과물은 `signals.json` / `latency.json` / `notes.md`(관찰·결론) 이름으로 통일.

## publish_path 주의

`lk-file`(livekit-cli 파일 퍼블리시)은 영상이 ~5s GOP 버스트로 늦게 도착하는 병리가 있어
**영상 의존 수치(visual/nv 커버리지)는 하한으로만 유효** — 정본 설명은
`nv-lane-investigation.md`. 영상 판단은 `fakecam-browser`(Chrome fake device, 실 WebRTC
페이싱) 이상에서만 절대값으로 읽는다. 오디오·전사·레이턴시 수치는 lk-file에서도 유효.
실증: `runs/2026-06-12-fakecam-coverage/notes.md` (같은 미디어에서 visual 4/8→8/8).

fakecam 하니스: `giljobe/.dev/llm_handoff/fakecam_live_harness.py <clip>` — y4m/wav 변환본은
`/tmp/qa-media/`(소실 시 스크립트 docstring의 ffmpeg 레시피로 재생성).
