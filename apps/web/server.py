#!/usr/bin/env python3
"""Minimal GilJob v2 web service.

Serves a small static browser UI that creates an interview session through the
API and joins the returned self-hosted LiveKit room. The web layer intentionally
keeps interview intelligence, avatar/TTS, CV parsing, multimodal analysis, and
final reports as placeholders for later slices.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

SERVICE_NAME = os.getenv("SERVICE_NAME", "web")
PORT = int(os.getenv("SERVICE_PORT", "3000"))
STATIC_ROOT = Path(os.getenv("STATIC_ROOT", Path(__file__).with_name("static"))).resolve()
LIVEKIT_CLIENT_DIST = Path(
    os.getenv("LIVEKIT_CLIENT_DIST", Path(__file__).with_name("node_modules") / "livekit-client" / "dist")
).resolve()
VENDOR_PREFIX = "vendor/livekit-client/dist/"
INTERVIEW_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")

CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".wasm": "application/wasm",
}


def _route_alias(request_path: str) -> str | None:
    """Map production-style app routes to static shell templates.

    The static server stays deliberately simple for this scaffold, but the
    public URLs should already look like the future production app:
    /interviews/new -> setup page
    /interviews/{id}/lobby -> pre-join lobby
    /interviews/{id}/room -> LiveKit room
    /interviews/{id}/report -> report placeholder
    """
    if request_path == "/interview-room.html":
        return "interview-room.html"
    if request_path == "/interviews/new":
        return "interview-new.html"

    parts = [part for part in request_path.split("/") if part]
    if len(parts) != 3 or parts[0] != "interviews":
        return None
    interview_id = parts[1]
    screen = parts[2]
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        return None
    if screen == "lobby":
        return "interview-lobby.html"
    if screen == "room":
        return "interview-room.html"
    if screen == "report":
        return "interview-report.html"
    return None


def _safe_file(root: Path, relative_path: str) -> Path | None:
    """Resolve a static file path without allowing traversal outside root."""
    try:
        candidate = (root / relative_path).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    if not candidate.is_file():
        return None
    return candidate


class Handler(BaseHTTPRequestHandler):
    server_version = "GilJobV2Web/0.2"

    def _send(self, status: int, content_type: str, body: bytes, *, write_body: bool = True) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if write_body:
            self.wfile.write(body)

    def _json(self, status: int, payload: dict[str, object], *, write_body: bool = True) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body, write_body=write_body)

    def _static_file(self) -> Path | None:
        request_path = unquote(urlsplit(self.path).path)
        if request_path == "/":
            request_path = "/index.html"
        alias = _route_alias(request_path)
        if alias is not None:
            return _safe_file(STATIC_ROOT, alias)
        relative_path = request_path.lstrip("/")
        if not relative_path:
            return None

        static_file = _safe_file(STATIC_ROOT, relative_path)
        if static_file is not None:
            return static_file

        if relative_path.startswith(VENDOR_PREFIX):
            vendor_relative = relative_path.removeprefix(VENDOR_PREFIX)
            return _safe_file(LIVEKIT_CLIENT_DIST, vendor_relative)
        return None

    def _send_static(self, file_path: Path, *, write_body: bool = True) -> None:
        content_type = CONTENT_TYPES.get(file_path.suffix)
        if content_type is None:
            content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        body = file_path.read_bytes() if write_body else b""
        self._send(200, content_type, body, write_body=write_body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path in {"/healthz", "/readyz"}:
            self._json(200, {"service": SERVICE_NAME, "status": "ok"})
            return
        static_file = self._static_file()
        if static_file is not None:
            self._send_static(static_file)
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path in {"/healthz", "/readyz"}:
            self._json(200, {"service": SERVICE_NAME, "status": "ok"}, write_body=False)
            return
        static_file = self._static_file()
        if static_file is not None:
            self._send_static(static_file, write_body=False)
            return
        self._json(404, {"error": "not_found", "path": self.path}, write_body=False)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
