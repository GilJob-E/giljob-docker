#!/usr/bin/env python3
"""Minimal static web server for smoke testing — mimics Caddy's interview route mapping.

Routes:
  /                              → index.html
  /interviews/new                → interview-new.html
  /interviews/:id/lobby          → interview-lobby.html
  /interviews/:id/room           → interview-room.html
  /interviews/:id/report         → interview-report.html
  /app.js, /styles.css, etc.     → served directly from static/
"""
from __future__ import annotations

import os
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT = int(os.getenv("SMOKE_WEB_PORT", "8101"))
STATIC_DIR = Path(__file__).resolve().parents[1] / "apps" / "web" / "static"

CONTENT_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
}

INTERVIEW_ROUTE = re.compile(r"^/interviews/([^/]+)/(lobby|room|report)$")
NEW_ROUTE = re.compile(r"^/interviews/new$")


def _resolve(path: str) -> Path | None:
    if path in ("/", ""):
        return STATIC_DIR / "index.html"
    m = INTERVIEW_ROUTE.match(path)
    if m:
        page = m.group(2)
        return STATIC_DIR / f"interview-{page}.html"
    if NEW_ROUTE.match(path):
        return STATIC_DIR / "interview-new.html"
    candidate = STATIC_DIR / path.lstrip("/")
    return candidate if candidate.is_file() else None


class Handler(BaseHTTPRequestHandler):
    server_version = "SmokeWebServer/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[smoke-web] {fmt % args}")

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        file = _resolve(path)
        if file is None or not file.exists():
            self.send_response(404)
            self.end_headers()
            return
        body = file.read_bytes()
        ct = CONTENT_TYPES.get(file.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[smoke-web] serving {STATIC_DIR} on :{PORT}")
    server.serve_forever()
