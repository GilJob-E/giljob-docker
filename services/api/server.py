#!/usr/bin/env python3
"""Minimal GilJob v2 API scaffold.

Security contracts kept in scaffold:
- internal API paths are not exposed;
- raw session/report tokens are returned only in the create-session response;
- server-side records keep purpose-separated token hashes only.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from app.token_contract import issue_session

SERVICE_NAME = os.getenv("SERVICE_NAME", "api")
PORT = int(os.getenv("SERVICE_PORT", "8000"))
MAX_JSON_BODY_BYTES = int(os.getenv("MAX_JSON_BODY_BYTES", "65536"))

# In-process scaffold store for G006. The persistence contract is represented by
# services/api/db/schema.sql; a later M2 slice will wire this to Postgres.
SESSION_HASH_STORE: dict[str, dict[str, object]] = {}


class Handler(BaseHTTPRequestHandler):
    server_version = "GilJobV2API/0.2"

    def _json(self, status: int, payload: dict[str, object], *, write_body: bool = True) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if write_body:
            self.wfile.write(body)

    def _is_internal_path(self) -> bool:
        return self.path.startswith("/api/internal") or self.path.startswith("/internal")

    def _reject_internal_path(self, *, write_body: bool = True) -> bool:
        if self._is_internal_path():
            self._json(404, {"error": "not_found"}, write_body=write_body)
            return True
        return False

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            return {}
        if content_length > MAX_JSON_BODY_BYTES:
            raise ValueError("request body too large")
        raw_body = self.rfile.read(content_length)
        if not raw_body:
            return {}
        parsed = json.loads(raw_body.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("JSON body must be an object")
        return parsed

    def _handle_create_session(self) -> None:
        try:
            body = self._read_json_body()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self._json(400, {"error": "invalid_json", "message": str(exc)})
            return

        requested_role = str(body.get("role") or "candidate")
        requested_session_id = body.get("sessionId") or body.get("interviewId")
        try:
            issued = issue_session(requested_role=requested_role, requested_session_id=requested_session_id)
        except ValueError as exc:
            self._json(400, {"error": "invalid_session_id", "message": str(exc)})
            return
        stored = issued["stored"]
        public = issued["public"]
        SESSION_HASH_STORE[str(stored["sessionId"])] = stored
        self._json(201, public)

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if self._reject_internal_path():
            return
        if self.path == "/healthz":
            self._json(200, {"service": SERVICE_NAME, "status": "ok"})
            return
        if self.path == "/readyz":
            self._json(200, {"service": SERVICE_NAME, "status": "ok"})
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib callback name
        if self._reject_internal_path(write_body=False):
            return
        if self.path in {"/healthz", "/readyz"}:
            self._json(200, {"service": SERVICE_NAME, "status": "ok"}, write_body=False)
            return
        self._json(404, {"error": "not_found", "path": self.path}, write_body=False)

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib callback name
        if self._reject_internal_path():
            return
        self.send_response(204)
        self.send_header("Allow", "GET, HEAD, OPTIONS, POST, PUT, PATCH, DELETE")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        if self._reject_internal_path():
            return
        if self.path in {"/sessions", "/api/sessions"}:
            self._handle_create_session()
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def do_PUT(self) -> None:  # noqa: N802 - stdlib callback name
        if self._reject_internal_path():
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def do_PATCH(self) -> None:  # noqa: N802 - stdlib callback name
        if self._reject_internal_path():
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib callback name
        if self._reject_internal_path():
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
