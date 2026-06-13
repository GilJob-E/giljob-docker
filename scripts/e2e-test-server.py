#!/usr/bin/env python3
"""Run a local GilJob v2 end-to-end test stack without Docker.

This branch-only harness starts the real API and ai-engine modules, the
analysis-engine dummy scenario, a small hashimoto-compatible dummy service, and
a same-origin gateway that serves the web UI while proxying API calls.

No .env file is created or modified. All configuration is passed only to child
processes through process-local environment variables.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_STATIC_ROOT = (REPO_ROOT / "apps" / "web" / "static").resolve()
WEB_NODE_MODULES = (REPO_ROOT / "apps" / "web" / "node_modules").resolve()
LIVEKIT_DIST = WEB_NODE_MODULES / "livekit-client" / "dist"

INTERVIEW_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
VENDOR_LIVEKIT_PREFIX = "vendor/livekit-client/dist/"
VENDOR_NODE_PREFIXES = (
    "vendor/@spatialwalk/avatarkit/dist/",
    "vendor/@spatialwalk/avatarkit-rtc/dist/",
)

CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".wasm": "application/wasm",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
}

LIVEKIT_STUB_MODULE = b"""
export const RoomEvent = {
  ConnectionStateChanged: "connectionStateChanged",
  Connected: "connected",
  Disconnected: "disconnected",
  Reconnecting: "reconnecting",
  Reconnected: "reconnected",
  ParticipantConnected: "participantConnected",
  ParticipantDisconnected: "participantDisconnected"
};

export function setLogLevel() {}

export class Room {
  constructor() {
    this.localParticipant = {
      async setMicrophoneEnabled() {},
      async setCameraEnabled() {}
    };
  }
  on() {
    return this;
  }
  async connect() {
    throw new Error("LiveKit is disabled in the local E2E test server. Use ?e2eNoLiveKit=1.");
  }
  disconnect() {}
}
""".strip()


def log(message: str) -> None:
    print(f"[e2e] {message}", flush=True)


def route_alias(path: str) -> str | None:
    if path in {"/", "/index.html"}:
        return "index.html"
    if path == "/interviews/new":
        return "interview-new.html"
    if path == "/interview-room.html":
        return "interview-room.html"
    parts = [part for part in path.split("/") if part]
    if len(parts) == 3 and parts[0] == "interviews" and INTERVIEW_ID_RE.fullmatch(parts[1]):
        return {
            "lobby": "interview-lobby.html",
            "room": "interview-room.html",
            "report": "interview-report.html",
        }.get(parts[2])
    return None


def safe_file(root: Path, relative_path: str) -> Path | None:
    try:
        candidate = (root / relative_path).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    return candidate if candidate.is_file() else None


def resolve_static(path: str) -> Path | None:
    alias = route_alias(path)
    if alias:
        return safe_file(WEB_STATIC_ROOT, alias)
    relative = path.lstrip("/")
    if not relative:
        return None
    static_file = safe_file(WEB_STATIC_ROOT, relative)
    if static_file:
        return static_file
    if relative.startswith(VENDOR_LIVEKIT_PREFIX):
        return safe_file(LIVEKIT_DIST, relative.removeprefix(VENDOR_LIVEKIT_PREFIX))
    for prefix in VENDOR_NODE_PREFIXES:
        if relative.startswith(prefix):
            return safe_file(WEB_NODE_MODULES, relative.removeprefix("vendor/"))
    return None


class DummyHashimoto:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, dict[str, Any]] = {}

    def open_session(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        session_id = safe_session_id(body.get("session_id") or "local-demo")
        with self._lock:
            session = self._sessions.setdefault(
                session_id,
                {
                    "session_id": session_id,
                    "turns": {},
                    "topic": "motivation",
                    "as_of_turn_id": None,
                    "complete": False,
                },
            )
        log(
            "hashimoto.session_opened "
            + json.dumps(
                {
                    "step": "ai-engine bootstrapped strategy session",
                    "sessionId": session_id,
                    "resumeChars": len(str(body.get("resume_text") or "")),
                    "jobUrlProvided": bool(body.get("job_url")),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 201, {"session_id": session_id, "current_topic": session["topic"], "topics": ["motivation", "problem-solving", "collaboration"]}

    def submit_turn(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        session_id = safe_session_id(body.get("session_id") or "local-demo")
        turn_id = str(body.get("turn_id") or "turn_0001")
        text = str(body.get("text") or "").strip()
        with self._lock:
            session = self._sessions.setdefault(
                session_id,
                {"session_id": session_id, "turns": {}, "topic": "motivation", "as_of_turn_id": None, "complete": False},
            )
            if turn_id in session["turns"]:
                return 200, {"accepted": False, "reason": "duplicate_turn", "session_id": session_id, "turn_id": turn_id}
            session["turns"][turn_id] = text
            session["as_of_turn_id"] = turn_id
            session["topic"] = topic_for_text(text, len(session["turns"]))
            topic = session["topic"]
        log(
            "hashimoto.turn_submitted "
            + json.dumps(
                {
                    "step": "ai-engine forwarded completed answer transcript to hashimoto",
                    "sessionId": session_id,
                    "turnId": turn_id,
                    "answerChars": len(text),
                    "topic": topic,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 202, {"accepted": True, "session_id": session_id, "turn_id": turn_id}

    def strategy(self, session_id: str) -> tuple[int, dict[str, Any]]:
        session_id = safe_session_id(session_id)
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return 200, {"ready": False, "session_id": session_id, "as_of_turn_id": None, "interaction_strategy": None}
            topic = session["topic"]
            as_of_turn_id = session.get("as_of_turn_id")
        log(
            "hashimoto.strategy_pulled "
            + json.dumps(
                {
                    "step": "ai-engine pulled latest strategy package for next-question metadata",
                    "sessionId": session_id,
                    "asOfTurnId": as_of_turn_id,
                    "topic": topic,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 200, {
            "ready": True,
            "session_id": session_id,
            "as_of_turn_id": as_of_turn_id,
            "session_complete": False,
            "interaction_strategy": {
                "logic_goal": f"Probe evidence around {topic}.",
                "logical_gap_to_bridge": "Ask for one concrete decision, tradeoff, and outcome.",
                "interviewer_persona_guidance": {
                    "intent": "follow-up",
                    "emotion_direction": "calm",
                    "focus_point": f"Keep the next question anchored to {topic}.",
                },
                "current_context": {
                    "topic": topic,
                    "depth_level": 2 if as_of_turn_id else 1,
                    "topic_changed": bool(as_of_turn_id),
                    "transition_hint": None,
                    "multimodal_feedback_requirement": None,
                    "resolved_history": [],
                    "focus_keywords": [],
                },
            },
        }

    def end_session(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        session_id = safe_session_id(body.get("session_id") or "local-demo")
        with self._lock:
            session = self._sessions.setdefault(
                session_id,
                {"session_id": session_id, "turns": {}, "topic": "motivation", "as_of_turn_id": None, "complete": False},
            )
            session["complete"] = True
        log(
            "hashimoto.session_ended "
            + json.dumps(
                {
                    "step": "finalize told hashimoto to close the strategy session",
                    "sessionId": session_id,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 200, {"session_id": session_id, "closed": True}


def safe_session_id(value: object) -> str:
    session_id = str(value or "").strip()
    if not INTERVIEW_ID_RE.fullmatch(session_id):
        raise ValueError("invalid session id")
    return session_id


def topic_for_text(text: str, count: int) -> str:
    lowered = text.lower()
    if any(keyword in lowered for keyword in ("collaboration", "schema", "team", "conflict", "trade-off", "tradeoff")):
        return "collaboration"
    if any(keyword in lowered for keyword in ("payment", "idempot", "failure", "debug", "log", "root", "incident")):
        return "problem-solving"
    return ("motivation", "problem-solving", "collaboration")[(count - 1) % 3]


HASHIMOTO = DummyHashimoto()


class HashimotoHandler(BaseHTTPRequestHandler):
    server_version = "GilJobDummyHashimoto/0.1"

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in {"/healthz", "/readyz"}:
            self._json(200, {"service": "dummy-hashimoto", "status": "ok"})
            return
        if parsed.path == "/strategy":
            params = urllib.parse.parse_qs(parsed.query)
            try:
                status, payload = HASHIMOTO.strategy((params.get("session_id") or ["local-demo"])[0])
            except ValueError as exc:
                self._json(400, {"error": "invalid_session_id", "message": str(exc)})
                return
            self._json(status, payload)
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def do_POST(self) -> None:  # noqa: N802
        try:
            body = self._read_json()
            if self.path == "/session":
                status, payload = HASHIMOTO.open_session(body)
            elif self.path == "/submit_turn":
                status, payload = HASHIMOTO.submit_turn(body)
            elif self.path == "/session/end":
                status, payload = HASHIMOTO.end_session(body)
            else:
                status, payload = 404, {"error": "not_found", "path": self.path}
        except (ValueError, json.JSONDecodeError) as exc:
            status, payload = 400, {"error": "invalid_request", "message": str(exc)}
        self._json(status, payload)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class ManagedProcess:
    def __init__(self, name: str, command: list[str], cwd: Path, env: dict[str, str]) -> None:
        self.name = name
        self.command = command
        self.cwd = cwd
        self.env = env
        self.process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        child_env = os.environ.copy()
        child_env.update(self.env)
        self.process = subprocess.Popen(
            self.command,
            cwd=str(self.cwd),
            env=child_env,
        )
        log(f"started {self.name} pid={self.process.pid}")

    def stop(self) -> None:
        if not self.process or self.process.poll() is not None:
            return
        log(f"stopping {self.name}")
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "GilJobE2EGateway/0.1"
    api_base = ""
    analysis_base = ""

    def _send_bytes(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        self._send_bytes(status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _proxy(self, target_base: str, path: str) -> None:
        method = self.command
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else None
        target = target_base.rstrip("/") + path
        log(
            "gateway.proxy "
            + json.dumps(
                {
                    "step": "browser same-origin request forwarded to internal test service",
                    "method": method,
                    "path": path,
                    "targetBase": target_base,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        headers = {"Content-Type": self.headers.get("Content-Type", "application/json")}
        request = urllib.request.Request(target, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
                content_type = response.headers.get("Content-Type", "application/octet-stream")
                self._send_bytes(response.status, content_type, payload)
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            content_type = exc.headers.get("Content-Type", "application/json; charset=utf-8")
            self._send_bytes(exc.code, content_type, payload)
        except Exception as exc:  # noqa: BLE001
            self._json(502, {"error": "proxy_failed", "message": exc.__class__.__name__})

    def _dispatch(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = f"?{parsed.query}" if parsed.query else ""
        if path == "/dev/status":
            self._json(200, {"status": "ok", "api": self.api_base, "analysis": self.analysis_base})
            return
        if path == "/dev/shutdown":
            self._json(200, {"status": "shutting_down"})
            threading.Thread(target=request_shutdown, daemon=True).start()
            return
        if path == "/sessions" or path.startswith("/api/") or path.startswith("/debug/e2e/"):
            self._proxy(self.api_base, path + query)
            return
        if path.startswith("/analysis/"):
            stripped = path.removeprefix("/analysis") or "/"
            self._proxy(self.analysis_base, stripped + query)
            return
        if self.command in {"GET", "HEAD"}:
            static_file = resolve_static(path)
            if static_file:
                content_type = CONTENT_TYPES.get(static_file.suffix) or mimetypes.guess_type(str(static_file))[0] or "application/octet-stream"
                body = static_file.read_bytes() if self.command == "GET" else b""
                self._send_bytes(200, content_type, body)
                return
            if path == "/vendor/livekit-client/dist/livekit-client.esm.mjs":
                body = LIVEKIT_STUB_MODULE if self.command == "GET" else b""
                self._send_bytes(200, "text/javascript; charset=utf-8", body)
                return
        if self.command == "OPTIONS":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._json(404, {"error": "not_found", "path": path})

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch()

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch()

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._dispatch()

    def log_message(self, fmt: str, *args: object) -> None:
        log(f"{self.command} {self.path} - {fmt % args}")


_shutdown_event = threading.Event()
_gateway: ThreadingHTTPServer | None = None


def request_shutdown() -> None:
    _shutdown_event.set()
    if _gateway is not None:
        _gateway.shutdown()


def wait_http(url: str, name: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not ready"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                if response.status < 500:
                    return
        except Exception as exc:  # noqa: BLE001
            last_error = exc.__class__.__name__
        time.sleep(0.25)
    raise RuntimeError(f"{name} did not become ready: {last_error}")


def start_hashimoto_server(host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), HashimotoHandler)
    thread = threading.Thread(target=server.serve_forever, name="dummy-hashimoto", daemon=True)
    thread.start()
    log(f"started dummy-hashimoto http://{host}:{port}")
    return server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the branch-local GilJob E2E test stack.")
    parser.add_argument("--host", default=os.getenv("GILJOB_TEST_HOST", "127.0.0.1"))
    parser.add_argument("--web-port", type=int, default=int(os.getenv("GILJOB_TEST_WEB_PORT", "7070")))
    parser.add_argument("--api-port", type=int, default=int(os.getenv("GILJOB_TEST_API_PORT", "8000")))
    parser.add_argument("--ai-port", type=int, default=int(os.getenv("GILJOB_TEST_AI_PORT", "8100")))
    parser.add_argument("--analysis-port", type=int, default=int(os.getenv("GILJOB_TEST_ANALYSIS_PORT", "8200")))
    parser.add_argument("--hashimoto-port", type=int, default=int(os.getenv("GILJOB_TEST_HASHIMOTO_PORT", "8300")))
    return parser.parse_args()


def main() -> int:
    global _gateway
    args = parse_args()
    python = sys.executable

    hashimoto_server = start_hashimoto_server(args.host, args.hashimoto_port)
    processes = [
        ManagedProcess(
            "ai-engine",
            [python, "server.py"],
            REPO_ROOT / "services" / "ai-engine",
            {
                "SERVICE_NAME": "ai-engine",
                "SERVICE_PORT": str(args.ai_port),
                "LLM_PROVIDER": "fake",
                "VOICE_PROVIDER": "fake",
                "AVATAR_PROVIDER": "disabled",
                "HASHIMOTO_BASE_URL": f"http://{args.host}:{args.hashimoto_port}",
            },
        ),
        ManagedProcess(
            "analysis-engine",
            [python, "server.py"],
            REPO_ROOT / "services" / "analysis-engine",
            {
                "SERVICE_NAME": "analysis-engine",
                "SERVICE_PORT": str(args.analysis_port),
                "ANALYSIS_ENGINE_DUMMY_SCENARIO": "hashimoto-report-ui",
                "ANALYSIS_ENGINE_ENABLE_SUBSCRIBER": "false",
                "LIVEKIT_SESSION_ID": "local-demo",
            },
        ),
        ManagedProcess(
            "api",
            [python, "server.py"],
            REPO_ROOT / "services" / "api",
            {
                "SERVICE_NAME": "api",
                "SERVICE_PORT": str(args.api_port),
                "PYTHONUNBUFFERED": "1",
                "GILJOB_E2E_TRACE": "1",
                "GILJOB_ENV": "development",
                "API_DB_BACKEND": "memory",
                "LIVEKIT_REQUIRED": "false",
                "AI_ENGINE_INTERNAL_URL": f"http://{args.host}:{args.ai_port}",
                "ANALYSIS_ENGINE_INTERNAL_URL": f"http://{args.host}:{args.analysis_port}",
            },
        ),
    ]

    for process in processes:
        process.start()

    try:
        wait_http(f"http://{args.host}:{args.ai_port}/healthz", "ai-engine")
        wait_http(f"http://{args.host}:{args.analysis_port}/readyz", "analysis-engine")
        wait_http(f"http://{args.host}:{args.api_port}/healthz", "api")

        GatewayHandler.api_base = f"http://{args.host}:{args.api_port}"
        GatewayHandler.analysis_base = f"http://{args.host}:{args.analysis_port}"
        _gateway = ThreadingHTTPServer((args.host, args.web_port), GatewayHandler)

        def handle_signal(signum: int, _frame: object) -> None:
            log(f"received signal {signum}; shutting down")
            request_shutdown()

        signal.signal(signal.SIGINT, handle_signal)
        try:
            signal.signal(signal.SIGTERM, handle_signal)
        except (OSError, AttributeError):
            pass

        log("")
        log(f"gateway   http://{args.host}:{args.web_port}")
        log(f"room      http://{args.host}:{args.web_port}/interviews/local-demo/room?e2eNoLiveKit=1")
        log(f"report    http://{args.host}:{args.web_port}/interviews/local-demo/report")
        log(f"debug db  http://{args.host}:{args.web_port}/debug/e2e/turn-store?sessionId=local-demo")
        log(f"api       http://{args.host}:{args.api_port}")
        log(f"ai        http://{args.host}:{args.ai_port}")
        log(f"analysis  http://{args.host}:{args.analysis_port} dummy=hashimoto-report-ui")
        log(f"hashimoto http://{args.host}:{args.hashimoto_port} dummy")
        log("stop with Ctrl+C or GET /dev/shutdown")
        _gateway.serve_forever()
    finally:
        request_shutdown()
        if _gateway is not None:
            _gateway.server_close()
        hashimoto_server.shutdown()
        hashimoto_server.server_close()
        for process in reversed(processes):
            process.stop()
        log("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
