#!/usr/bin/env python3
"""GilJob v2 front-end dev preview server.

Serves the full 5-page flow (index / new / lobby / room / report) with
production-style routing + stub API responses so the UI is previewable
without starting the full backend stack.

Usage
-----
    python scripts/dev-server.py             # http://127.0.0.1:7070
    PORT=8080 python scripts/dev-server.py

Shutdown
--------
    Ctrl+C  — graceful (waits for in-flight requests then exits cleanly)
    GET /dev/shutdown  — same, triggered from browser / curl
"""
from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

# Windows 터미널이 cp949일 경우 UTF-8 강제 출력
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).resolve().parents[1]
STATIC_ROOT = (REPO_ROOT / "apps" / "web" / "static").resolve()
NODE_MODULES = (REPO_ROOT / "apps" / "web" / "node_modules").resolve()
LIVEKIT_DIST = NODE_MODULES / "livekit-client" / "dist"

PORT = int(os.getenv("PORT", "7070"))
HOST = os.getenv("HOST", "127.0.0.1")

# ── routing ───────────────────────────────────────────────────────────────────
INTERVIEW_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
VENDOR_LK       = "vendor/livekit-client/dist/"
VENDOR_SW_PREFIXES = (
    "vendor/@spatialwalk/avatarkit/dist/",
    "vendor/@spatialwalk/avatarkit-rtc/dist/",
)

CONTENT_TYPES = {
    ".css":  "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js":   "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map":  "application/json; charset=utf-8",
    ".mjs":  "text/javascript; charset=utf-8",
    ".wasm": "application/wasm",
    ".svg":  "image/svg+xml",
    ".ico":  "image/x-icon",
    ".png":  "image/png",
}

# ── log helpers ───────────────────────────────────────────────────────────────
_LOG_LOCK = threading.Lock()

def _ts() -> str:
    return time.strftime("%H:%M:%S")

def log(tag: str, msg: str) -> None:
    with _LOG_LOCK:
        print(f"[{_ts()}] {tag:8s} {msg}", flush=True)

def log_req(method: str, path: str, status: int, ms: float, client: str) -> None:
    status_str = f"{status}"
    tag = "OK" if status < 400 else ("WARN" if status < 500 else "ERR")
    with _LOG_LOCK:
        print(
            f"[{_ts()}] {tag:8s} {method:6s} {path:<50s}  {status_str}  {ms:5.1f}ms  {client}",
            flush=True,
        )

# ── static routing ────────────────────────────────────────────────────────────
def _route_alias(path: str) -> str | None:
    if path in ("/", "/index.html"):
        return "index.html"
    if path == "/interviews/new":
        return "interview-new.html"
    if path == "/interview-room.html":
        return "interview-room.html"
    parts = [p for p in path.split("/") if p]
    if len(parts) == 3 and parts[0] == "interviews" and INTERVIEW_ID_RE.fullmatch(parts[1]):
        return {
            "lobby":  "interview-lobby.html",
            "room":   "interview-room.html",
            "report": "interview-report.html",
        }.get(parts[2])
    return None

def _safe_file(root: Path, rel: str) -> Path | None:
    try:
        candidate = (root / rel).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    return candidate if candidate.is_file() else None

def _resolve_static(request_path: str) -> Path | None:
    alias = _route_alias(request_path)
    if alias:
        return _safe_file(STATIC_ROOT, alias)
    rel = request_path.lstrip("/")
    if not rel:
        return None
    f = _safe_file(STATIC_ROOT, rel)
    if f:
        return f
    if rel.startswith(VENDOR_LK):
        return _safe_file(LIVEKIT_DIST, rel.removeprefix(VENDOR_LK))
    for pfx in VENDOR_SW_PREFIXES:
        if rel.startswith(pfx):
            return _safe_file(NODE_MODULES, rel.removeprefix("vendor/"))
    return None

# ── stub API data ─────────────────────────────────────────────────────────────
_STUB_QUESTIONS = [
    "간단한 자기소개와 지원 동기를 말씀해 주세요.",
    "최근 해결한 가장 어려운 기술 문제는 무엇이었나요?",
    "의견이 다른 동료와 협업한 경험을 말씀해 주세요.",
    "실패했던 프로젝트와 거기서 배운 점을 말씀해 주세요.",
    "마지막으로 입사 후 포부를 말씀해 주세요.",
]

def _stub_turn(n: int, q: str, a: str) -> dict:
    return {
        "turnId": n,
        "question": q,
        "answer": a,
        "feedback": {
            "keyObservations": ["논리 구조가 명확합니다.", "구체적 사례를 제시했습니다."],
            "critique": ["다음 턴에서는 더 간결하게 핵심을 먼저 전달해 보세요."],
        },
        "metrics": {
            "vocal": {"speechRateSylPerSec": 5.5 + n * 0.1, "pitchMeanHz": 240, "pauseCount": n % 3},
            "visual": {"smileMean": 0.22, "gazeOffMean": 0.28, "blinkCount": n},
            "coverage": {"visualMeasurable": True},
        },
    }

def _stub_report(interview_id: str) -> dict:
    turns = [
        _stub_turn(1, _STUB_QUESTIONS[0], "4년 차 백엔드 엔지니어입니다. 결제 정합성 문제를 다루며 지원했습니다."),
        _stub_turn(2, _STUB_QUESTIONS[1], "멱등 키와 상태 머신으로 중복 지급 문제를 해결했습니다."),
        _stub_turn(3, _STUB_QUESTIONS[2], "트레이드오프 표를 작성해 팀원과 절충안을 도출했습니다."),
        _stub_turn(4, _STUB_QUESTIONS[3], "캐시 전략 실패를 회고하고 무효화 정책을 재설계했습니다."),
        _stub_turn(5, _STUB_QUESTIONS[4], "관측 가능성과 자동화로 장애 대응 시간을 줄이겠습니다."),
    ]
    return {
        "interviewId": interview_id,
        "generatedAt": "2026-06-13T09:00:00+00:00",
        "turnCount": len(turns),
        "complete": True,
        "turns": turns,
        "rawMediaExposed": False,
        "rawSecretsExposed": False,
    }

def _stub_signals() -> dict:
    return {
        "sessionId": "dev-session",
        "records": [
            {
                "type": "window",
                "seq": 1,
                "transcript": "[DEV] 답변 텍스트가 여기에 표시됩니다.",
                "ts": time.time(),
            },
            {
                "type": "eval",
                "seq": 2,
                "evaluation": {
                    "gaze_off_ratio": 0.18,
                    "speech_rate": 5.4,
                    "pause_count": 1,
                    "expression_label": "neutral",
                    "posture_wobble": 0.05,
                    "critique": "[DEV stub] 시선이 안정적입니다.",
                },
                "ts": time.time(),
            },
        ],
    }

# ── API stub router ───────────────────────────────────────────────────────────
_INTERVIEW_RE   = re.compile(r"^/api/interviews/([^/]+)$")
_REPORT_RE      = re.compile(r"^/api/interviews/([^/]+)/report/?$")
_QUESTION_RE    = re.compile(r"^/api/interviews/([^/]+)/turns/(\d+)/question/?$")
_TURN_RE        = re.compile(r"^/api/interviews/([^/]+)/turns/(\d+)/answer/?$")
_AVATAR_RE      = re.compile(r"^/api/interviews/([^/]+)/avatar/session/?$")
_TTS_RE         = re.compile(r"^/api/interviews/([^/]+)/turns/(\d+)/tts/?$")
_SIGNALS_RE     = re.compile(r"^/analysis/signals/?$")

def _handle_api(method: str, path: str, body: bytes) -> tuple[int, dict] | None:
    """Return (status, payload) for stub API paths, or None to fall through."""
    # POST /api/interviews  — create session
    if method == "POST" and path == "/api/interviews":
        return 201, {
            "interviewId": "local-demo",
            "sessionId":   "dev-session-001",
            "candidateToken": "[dev-token-hidden]",
            "publicUrl": f"ws://{HOST}:7777",
            "rawMediaExposed": False,
        }

    # GET /api/interviews/:id
    m = _INTERVIEW_RE.fullmatch(path)
    if method == "GET" and m:
        return 200, {"interviewId": m.group(1), "status": "active", "turnCount": 0}

    # GET /api/interviews/:id/report
    m = _REPORT_RE.fullmatch(path)
    if method == "GET" and m:
        return 200, _stub_report(m.group(1))

    # POST /api/interviews/:id/turns/:n/question
    m = _QUESTION_RE.fullmatch(path)
    if method == "POST" and m:
        turn_idx = int(m.group(2))
        q_text = _STUB_QUESTIONS[min(turn_idx - 1, len(_STUB_QUESTIONS) - 1)]
        return 200, {
            "question":   q_text,
            "turnIndex":  turn_idx,
            "provider":   "stub",
            "ttsReady":   False,
        }

    # POST /api/interviews/:id/turns/:n/answer (turn answer record)
    m = _TURN_RE.fullmatch(path)
    if method == "POST" and m:
        return 202, {"stored": True, "turnId": int(m.group(2))}

    # POST /api/interviews/:id/avatar/session
    m = _AVATAR_RE.fullmatch(path)
    if method == "POST" and m:
        return 200, {"avatarSessionId": "dev-avatar-stub", "clientToken": "[hidden]"}

    # GET /api/interviews/:id/turns/:n/tts
    m = _TTS_RE.fullmatch(path)
    if method == "GET" and m:
        return 200, {"ttsReady": False, "reason": "stub — no TTS in dev mode"}

    # GET /analysis/signals
    if method == "GET" and _SIGNALS_RE.fullmatch(path):
        return 200, _stub_signals()

    return None

# ── shutdown coordination ─────────────────────────────────────────────────────
_shutdown_event = threading.Event()
_server_ref: ThreadingHTTPServer | None = None

def _do_shutdown(reason: str) -> None:
    if _shutdown_event.is_set():
        return
    _shutdown_event.set()
    log("SHUTDOWN", f"requested ({reason}) -- draining in-flight requests...")
    if _server_ref is not None:
        threading.Thread(target=_server_ref.shutdown, daemon=True).start()

def _signal_handler(signum: int, _frame: object) -> None:
    _do_shutdown(f"signal {signum}")

# ── handler ───────────────────────────────────────────────────────────────────
class DevHandler(BaseHTTPRequestHandler):
    server_version = "GilJobDevServer/1.0"

    # silence BaseHTTP's own logger — we write our own
    def log_message(self, fmt: str, *args: object) -> None:
        pass

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body)

    def _handle(self, method: str) -> None:
        t0 = time.monotonic()
        raw_path = unquote(urlsplit(self.path).path)
        client   = self.address_string()

        try:
            status = self._dispatch(method, raw_path)
        except (BrokenPipeError, ConnectionResetError):
            return  # client disconnected — normal for browser pre-fetch
        except Exception as exc:
            log("ERR", f"내부 오류 {raw_path}: {exc}")
            self._json(500, {"error": "internal_error", "detail": str(exc)})
            status = 500

        ms = (time.monotonic() - t0) * 1000
        log_req(method, raw_path, status, ms, client)

    def _dispatch(self, method: str, path: str) -> int:
        # ── 안전 종료 엔드포인트 ──────────────────────────────────────────
        if path == "/dev/shutdown":
            self._json(200, {"message": "Shutting down dev server."})
            _do_shutdown("GET /dev/shutdown")
            return 200

        # ── 상태 확인 ─────────────────────────────────────────────────────
        if path in ("/healthz", "/dev/status"):
            self._json(200, {
                "status":    "ok",
                "pid":       os.getpid(),
                "host":      HOST,
                "port":      PORT,
                "static":    str(STATIC_ROOT),
                "vendor_lk": LIVEKIT_DIST.exists(),
                "vendor_sw": (NODE_MODULES / "@spatialwalk").exists(),
            })
            return 200

        # ── OPTIONS preflight ─────────────────────────────────────────────
        if method == "OPTIONS":
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()
            return 204

        # ── stub API ──────────────────────────────────────────────────────
        body = b""
        if method == "POST":
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len:
                body = self.rfile.read(content_len)

        api_result = _handle_api(method, path, body)
        if api_result is not None:
            status, payload = api_result
            self._json(status, payload)
            return status

        # ── static files ──────────────────────────────────────────────────
        if method in ("GET", "HEAD"):
            file_path = _resolve_static(path)
            if file_path is not None:
                content_type = (
                    CONTENT_TYPES.get(file_path.suffix)
                    or mimetypes.guess_type(str(file_path))[0]
                    or "application/octet-stream"
                )
                file_body = file_path.read_bytes() if method == "GET" else b""
                self._send(200, content_type, file_body)
                return 200

        self._json(404, {"error": "not_found", "path": path})
        return 404

    def do_GET(self):    self._handle("GET")     # noqa: E704
    def do_POST(self):   self._handle("POST")    # noqa: E704
    def do_HEAD(self):   self._handle("HEAD")    # noqa: E704
    def do_OPTIONS(self):self._handle("OPTIONS") # noqa: E704

# ── entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    global _server_ref

    # ── signal 등록 ───────────────────────────────────────────────────────
    signal.signal(signal.SIGINT, _signal_handler)
    try:
        signal.signal(signal.SIGTERM, _signal_handler)
    except (OSError, AttributeError):
        pass  # SIGTERM not available on some Windows configurations

    server = ThreadingHTTPServer((HOST, PORT), DevHandler)
    _server_ref = server

    # ── 시작 배너 ─────────────────────────────────────────────────────────
    print("", flush=True)
    lk_ok  = LIVEKIT_DIST.exists()
    sw_ok  = (NODE_MODULES / "@spatialwalk").exists()
    print("=" * 60, flush=True)
    print("  GilJob v2  front-end dev server", flush=True)
    print(f"  http://{HOST}:{PORT}", flush=True)
    print(f"  static : {STATIC_ROOT}", flush=True)
    print(f"  vendor/livekit      : {'ok' if lk_ok  else 'missing (HTML preview still works)'}", flush=True)
    print(f"  vendor/@spatialwalk : {'ok' if sw_ok  else 'missing'}", flush=True)
    print("", flush=True)
    print("  Pages:", flush=True)
    print(f"    landing  http://{HOST}:{PORT}/", flush=True)
    print(f"    new      http://{HOST}:{PORT}/interviews/new", flush=True)
    print(f"    lobby    http://{HOST}:{PORT}/interviews/local-demo/lobby", flush=True)
    print(f"    room     http://{HOST}:{PORT}/interviews/local-demo/room", flush=True)
    print(f"    report   http://{HOST}:{PORT}/interviews/local-demo/report", flush=True)
    print("", flush=True)
    print("  Stop server:", flush=True)
    print(f"    Ctrl+C   or   curl http://127.0.0.1:{PORT}/dev/shutdown", flush=True)
    print(f"    Status check: curl http://127.0.0.1:{PORT}/dev/status", flush=True)
    print("=" * 60, flush=True)
    print("", flush=True)
    log("START", f"http://{HOST}:{PORT}  PID={os.getpid()}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass  # SIGINT already sets _shutdown_event via signal handler

    # ── 종료 처리 ─────────────────────────────────────────────────────────
    log("SHUTDOWN", "closing server socket...")
    try:
        server.server_close()
    except Exception:
        pass
    log("SHUTDOWN", "done. Safe to unplug USB.")
    print("", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
