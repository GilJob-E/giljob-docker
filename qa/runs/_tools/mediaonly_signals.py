#!/usr/bin/env python3
"""미디어-온리 라이브 하니스 — 임의 클립을 fakecam-browser 경로로 룸에 퍼블리시해
객관 그라운딩 레인(vision/prosody/nonverbal)의 signals.json을 절대값으로 측정한다.

fakecam_live_harness.py(giljobe/.dev)의 검증된 퍼블리시 경로를 그대로 쓰되, 사이드밴드
전사 주입을 제거한다 — 새 클립은 정본 전사가 없으므로 speech/sentence 레인은 의도적으로
공란이고, 미디어 시각으로 도는 nv(3s)·eval(16s) 윈도우만 잰다. windower의 _next_nv_end/
_next_eval_end가 전사와 무관하게 미디어 도착 시각으로 due 윈도우를 제출하므로 전사 없이도
객관 레인이 채워진다(근거: giljobe src/giljobe/pipeline/windowing.py).

사용: python3 mediaonly_signals.py <clip.mp4> <run_label> [publish_s]
출력: giljob-docker/qa/runs/<run_label>/{signals,meta}.json
  (publish_s 미지정 시 클립 길이 + 1.5s — 마지막 윈도우 트레일링 flush 여유)

미디어 변환: Chrome fake device는 y4m/wav만 받음 → ffmpeg로 960x540@15fps y4m + 48k mono wav.
LIVEKIT_API_KEY/SECRET는 셸 env 또는 giljob-docker/.env에서 읽고 출력하지 않는다(토큰은
livekit-cli 컨테이너로 발급).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DOCKER_REPO = Path("/home/kio/workspace/giljob-docker")
QA = DOCKER_REPO / "qa"
BASE = "http://127.0.0.1:8081/analysis"   # QA caddy → analysis-engine:8200
LIVEKIT_WS = "ws://127.0.0.1:17880"
HTTP_PORT = 8099
ENGINE_CONTAINER = "giljob-qa-analysis-engine-1"
WORK = Path("/tmp/qa-mediatest")

# QA 스택 엔진 토글(in-repo compose 기본값, realtime 핀 f817f81 — 컨테이너 .env 오버라이드 없음 전제)
ENGINE_TOGGLES = {
    "GILJOBE_GIT_REF": "f817f81",
    "GILJOBE_TRANSCRIPT_SOURCE": "external",
    "GILJOBE_VISION": "auto",
    "GILJOBE_PROSODY": "auto",
    "GILJOBE_EVAL_GRID": "off",
    "GILJOBE_FRAME_FPS": "3",
    "GILJOBE_NV_FRAME_CAP": "24",
}

PAGE = """<!doctype html><meta charset=utf-8><title>mediaonly</title>
<script src="https://cdn.jsdelivr.net/npm/livekit-client@2/dist/livekit-client.umd.min.js"></script>
<script>
(async () => {
  const cfg = await (await fetch('/token')).json();
  const room = new LivekitClient.Room();
  await room.connect(cfg.url, cfg.token);
  const tracks = await LivekitClient.createLocalTracks({
    audio: {echoCancellation: false, noiseSuppression: false, autoGainControl: false},
    video: {resolution: {width: cfg.width, height: cfg.height, frameRate: 15}},
  });
  for (const t of tracks) await room.localParticipant.publishTrack(t);
  await fetch('/published', {method: 'POST'});
})().catch(e => fetch('/errlog', {method: 'POST', body: String((e && e.stack) || e)}));
</script>"""


def _livekit_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    env_file = (DOCKER_REPO / ".env").read_text().splitlines()
    for k in ("LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        v = os.environ.get(k) or next(
            (ln.split("=", 1)[1].strip() for ln in env_file if ln.startswith(k + "=")), None)
        if not v:
            raise SystemExit(f"{k} 미설정 (셸 env / giljob-docker/.env)")
        keys[k] = v
    return keys


def _mint_token(keys: dict[str, str], room: str, identity: str = "qa-candidate") -> str:
    out = subprocess.run(
        ["docker", "run", "--rm",
         "-e", f"LIVEKIT_API_KEY={keys['LIVEKIT_API_KEY']}",
         "-e", f"LIVEKIT_API_SECRET={keys['LIVEKIT_API_SECRET']}",
         "livekit/livekit-cli", "token", "create", "--join",
         "--room", room, "--identity", identity, "--valid-for", "2h"],
        capture_output=True, text=True, check=True, timeout=60).stdout
    m = re.search(r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}", out)
    if not m:
        raise SystemExit("토큰 파싱 실패 (lk token create 출력 형식 변경?)")
    return m.group(0)


def _post(path: str, payload: dict) -> dict:
    import urllib.request
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def _signals(session_id: str) -> dict:
    import urllib.request
    with urllib.request.urlopen(f"{BASE}/signals?sessionId={session_id}", timeout=15) as r:
        return json.loads(r.read().decode())


class _Hub:
    def __init__(self, token: str, width: int, height: int):
        self.token_payload = json.dumps(
            {"url": LIVEKIT_WS, "token": token, "width": width, "height": height}).encode()
        self.published = threading.Event()
        self.page_error: str | None = None


def _make_handler(hub: _Hub):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # access 로그 침묵
            pass

        def _send(self, code: int, body: bytes = b"", ctype: str = "text/plain"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            elif self.path == "/token":
                self._send(200, hub.token_payload, "application/json")
            else:
                self._send(404)

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if self.path == "/published":
                hub.published.set()
                self._send(204)
            elif self.path == "/errlog":
                hub.page_error = "(page error)"
                self._send(204)
            else:
                self._send(404)

    return Handler


def _chrome(y4m: str, wav: str, profile: str) -> subprocess.Popen:
    return subprocess.Popen(
        ["google-chrome", "--headless=new", "--no-first-run", "--disable-gpu",
         f"--user-data-dir={profile}",
         "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
         f"--use-file-for-fake-video-capture={y4m}",
         f"--use-file-for-fake-audio-capture={wav}",
         "--autoplay-policy=no-user-gesture-required",
         f"http://127.0.0.1:{HTTP_PORT}/"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _convert(clip: Path) -> tuple[str, str, int, int, float]:
    WORK.mkdir(parents=True, exist_ok=True)
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(clip)],
        capture_output=True, text=True, check=True).stdout.strip())
    w, h = 960, 540
    y4m = str(WORK / f"{clip.stem}-{w}x{h}.y4m")
    wav = str(WORK / f"{clip.stem}-48k.wav")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(clip),
         "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps=15",
         "-pix_fmt", "yuv420p", y4m], check=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(clip),
         "-vn", "-ar", "48000", "-ac", "1", wav], check=True)
    return y4m, wav, w, h, dur


def _engine_image() -> str:
    try:
        return subprocess.run(
            ["docker", "inspect", ENGINE_CONTAINER, "--format", "{{.Config.Image}}"],
            capture_output=True, text=True, check=True, timeout=20).stdout.strip()
    except Exception:  # noqa: BLE001
        return "(inspect unavailable)"


def run(clip_path: str, run_label: str, publish_s: float | None) -> None:
    clip = Path(clip_path)
    if not clip.exists():
        raise SystemExit(f"클립 없음: {clip}")
    y4m, wav, w, h, dur = _convert(clip)
    if publish_s is None:
        publish_s = dur + 1.5

    session_id = f"qa-mediatest-{run_label}"
    run_dir = QA / "runs" / run_label
    run_dir.mkdir(parents=True, exist_ok=True)

    keys = _livekit_keys()
    token = _mint_token(keys, f"giljob-session-{session_id}")
    hub = _Hub(token, w, h)
    httpd = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), _make_handler(hub))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    start_resp = _post("/subscriber/start", {"sessionId": session_id, "criticMode": "window"})
    print("subscriber/start:", json.dumps(start_resp, ensure_ascii=False))
    profile = tempfile.mkdtemp(prefix="mediaonly-chrome-")
    chrome = _chrome(y4m, wav, profile)
    t0 = None
    try:
        if not hub.published.wait(timeout=40):
            raise SystemExit(f"publish beacon 타임아웃 — page_error={hub.page_error!r}")
        t0 = time.time()
        print(f"published (Chrome→LiveKit) t0 고정; publish_s={publish_s:.1f}s (clip={dur:.1f}s)")
        time.sleep(max(0.0, t0 + publish_s - time.time()))
    finally:
        chrome.terminate()
        try:
            chrome.wait(timeout=10)
        except Exception:  # noqa: BLE001
            chrome.kill()
        shutil.rmtree(profile, ignore_errors=True)
        httpd.shutdown()

    time.sleep(2.0)
    stop_t0 = time.time()
    stop_resp = _post("/subscriber/stop", {})
    stop_dur = round(time.time() - stop_t0, 2)
    print("subscriber/stop:", json.dumps(stop_resp, ensure_ascii=False))

    final = _signals(session_id)
    (run_dir / "signals.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2) + "\n")

    chrome_ver = subprocess.run(
        ["google-chrome", "--version"], capture_output=True, text=True).stdout.strip()
    meta = {
        "date": time.strftime("%Y-%m-%d"),
        "purpose": f"{clip.name} 객관 그라운딩 레인(vision/prosody/nonverbal) 커버리지 — "
                   "전사 없이 미디어-온리 퍼블리시로 측정",
        "engine": {"container": ENGINE_CONTAINER, "image": _engine_image(),
                   "toggles_from_compose": ENGINE_TOGGLES},
        "media": f"{clip} ({dur:.1f}s, 원본 1920x1080) → {y4m} ({w}x{h}@15fps) + {wav} (48k mono)",
        "publish_path": "fakecam-browser",
        "publisher": f"{chrome_ver} --headless=new --use-file-for-fake-{{video,audio}}-capture, "
                     "livekit-client@2 (CDN), 오디오 처리 OFF(AEC/NS/AGC)",
        "transcript_feed": "none (media-only — speech/sentence 레인은 의도적 공란, "
                           "객관 vocal/visual/nonverbal 레인만 측정)",
        "publish_s": round(publish_s, 1),
        "stop_to_stop_resp_s": stop_dur,
        "stack": "giljob-qa",
        "harness": "qa/runs/_tools/mediaonly_signals.py (fakecam_live_harness 퍼블리시 경로 재사용)",
        "caveat": "y4m은 캡처 시작부터 루프 — publish_s>clip이면 마지막 ~1.5s는 선두 재생(꼬리 윈도우 "
                  "경미 오염). FRAME_FPS=3이라 vision은 3fps로 서브샘플.",
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    print(f"→ {run_dir}  recordCount={final.get('recordCount')}  "
          f"rawMediaExposed={final.get('rawMediaExposed')} rawSecretsExposed={final.get('rawSecretsExposed')}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("usage: mediaonly_signals.py <clip.mp4> <run_label> [publish_s]")
    run(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else None)
