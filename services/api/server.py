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
import re
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from app.token_contract import issue_session

SERVICE_NAME = os.getenv("SERVICE_NAME", "api")
PORT = int(os.getenv("SERVICE_PORT", "8000"))
MAX_JSON_BODY_BYTES = int(os.getenv("MAX_JSON_BODY_BYTES", "65536"))
AI_ENGINE_INTERNAL_URL = os.getenv("AI_ENGINE_INTERNAL_URL", "http://ai-engine:8100").rstrip("/")
INTERVIEW_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
TTS_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/turns/([0-9]{1,4})/tts/?$")
AVATAR_SESSION_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/avatar/session/?$")
NEXT_QUESTION_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/turns/([0-9]{1,4})/question/?$")
MAX_TTS_TEXT_CHARS = 1_200

# In-process scaffold store for G006. The persistence contract is represented by
# services/api/db/schema.sql; a later M2 slice will wire this to Postgres.
SESSION_HASH_STORE: dict[str, dict[str, object]] = {}



def _safe_str(value: object, max_len: int = 4_000) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def _redact_provider_error(text: str) -> str:
    for name in ("ELEVENLABS_API_KEY", "SPATIALREAL_API_KEY", "LIVEKIT_API_SECRET"):
        value = os.getenv(name, "").strip()
        if value:
            text = text.replace(value, "<redacted>")
    return text[:500]


def _provider_failure_payload(error: str, provider: object = "api-mediated", *, ready: bool | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "error": error,
        "provider": _safe_str(provider or "api-mediated", 80),
        "message": "provider request failed",
    }
    if ready is not None:
        payload["ready"] = ready
    return payload


def _sanitize_upstream_provider_failure(upstream: dict[str, object], upstream_status: int, default_error: str, *, ready: bool | None = None) -> dict[str, object] | None:
    if upstream_status < 500:
        return None
    upstream_error = _safe_str(upstream.get("error") or default_error, 120)
    if upstream_error.endswith("_failed") or upstream_error in {"llm_provider_failed", "tts_provider_failed", "avatar_provider_failed"}:
        return _provider_failure_payload(upstream_error, upstream.get("provider") or "api-mediated", ready=ready)
    return None


def request_next_question(interview_id: str, turn_index: int, payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        return 400, {"error": "invalid_interview_id"}
    if turn_index < 1:
        return 400, {"error": "invalid_turn_index"}
    request_payload = json.dumps({
        "interviewId": interview_id,
        "turnIndex": turn_index,
        "persona": _safe_str(payload.get("persona") or "차분하고 명확한 한국어 면접관", 500),
        "candidateProfile": _safe_str(payload.get("candidateProfile") or "not provided in this slice", 2_000),
        "job": _safe_str(payload.get("job") or "not provided in this slice", 2_000),
        "lastAnswer": _safe_str(payload.get("lastAnswer") or "아직 이전 답변 전사가 없습니다.", 2_000),
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{AI_ENGINE_INTERNAL_URL}/interview/next-question",
        data=request_payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            upstream_status = response.status
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        upstream_status = error.code
    except urllib.error.URLError as error:
        return 502, {
            "error": "llm_provider_failed",
            "provider": "api-mediated",
            "message": _redact_provider_error(str(error.reason)),
        }
    try:
        upstream = json.loads(body)
    except json.JSONDecodeError:
        return 502, {"error": "llm_provider_failed", "provider": "api-mediated", "message": "invalid upstream response"}
    if not isinstance(upstream, dict):
        return 502, {"error": "llm_provider_failed", "provider": "api-mediated", "message": "invalid upstream payload"}
    public_failure = _sanitize_upstream_provider_failure(upstream, upstream_status, "llm_provider_failed")
    if public_failure is not None:
        public_failure["interviewId"] = interview_id
        public_failure["turnIndex"] = turn_index
        public_failure["delivery"] = {
            "mode": "api-mediated-question",
            "source": "ai-engine",
            "publicDirectAiRoutes": "blocked",
        }
        return upstream_status, public_failure
    upstream["interviewId"] = interview_id
    upstream["turnIndex"] = turn_index
    upstream["delivery"] = {
        "mode": "api-mediated-question",
        "source": "ai-engine",
        "publicDirectAiRoutes": "blocked",
    }
    return upstream_status, upstream


def create_avatar_session(interview_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        return 400, {"error": "invalid_interview_id"}
    request_payload = json.dumps({
        "interviewId": interview_id,
        "reason": _safe_str(payload.get("reason") or "room-join", 120),
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{AI_ENGINE_INTERNAL_URL}/avatar/session",
        data=request_payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            upstream_status = response.status
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        upstream_status = error.code
    except urllib.error.URLError as error:
        return 502, {
            "error": "avatar_provider_failed",
            "provider": "api-mediated",
            "message": _redact_provider_error(str(error.reason)),
        }
    try:
        upstream = json.loads(body)
    except json.JSONDecodeError:
        return 502, {"error": "avatar_provider_failed", "provider": "api-mediated", "message": "invalid upstream response"}
    if not isinstance(upstream, dict):
        return 502, {"error": "avatar_provider_failed", "provider": "api-mediated", "message": "invalid upstream payload"}
    public_failure = _sanitize_upstream_provider_failure(upstream, upstream_status, "avatar_provider_failed", ready=False)
    if public_failure is not None:
        public_failure["interviewId"] = interview_id
        public_failure["delivery"] = {
            "mode": "api-mediated-spatialreal-session",
            "source": "ai-engine",
            "publicDirectAvatarRoutes": "blocked",
        }
        return upstream_status, public_failure
    upstream["interviewId"] = interview_id
    upstream["delivery"] = {
        "mode": "api-mediated-spatialreal-session",
        "source": "ai-engine",
        "publicDirectAvatarRoutes": "blocked",
    }
    return upstream_status, upstream


def synthesize_room_tts(interview_id: str, turn_index: int, payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    text = _safe_str(payload.get("text") or payload.get("question") or "", MAX_TTS_TEXT_CHARS)
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        return 400, {"error": "invalid_interview_id"}
    if turn_index < 1:
        return 400, {"error": "invalid_turn_index"}
    if not text:
        return 400, {"error": "missing_text"}

    request_payload = json.dumps({
        "sessionId": interview_id,
        "turnId": f"q_{interview_id}_{turn_index:04d}",
        "text": text,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{AI_ENGINE_INTERNAL_URL}/tts/synthesize",
        data=request_payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            upstream_status = response.status
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        upstream_status = error.code
    except urllib.error.URLError as error:
        return 502, {
            "error": "tts_provider_failed",
            "provider": "api-mediated",
            "message": _redact_provider_error(str(error.reason)),
        }
    try:
        upstream = json.loads(body)
    except json.JSONDecodeError:
        return 502, {"error": "tts_provider_failed", "provider": "api-mediated", "message": "invalid upstream response"}
    if not isinstance(upstream, dict):
        return 502, {"error": "tts_provider_failed", "provider": "api-mediated", "message": "invalid upstream payload"}

    upstream.pop("sessionId", None)
    upstream.pop("turnId", None)
    public_failure = _sanitize_upstream_provider_failure(upstream, upstream_status, "tts_provider_failed")
    if public_failure is not None:
        public_failure["interviewId"] = interview_id
        public_failure["turnIndex"] = turn_index
        public_failure["delivery"] = {
            "mode": "api-mediated-base64",
            "source": "ai-engine",
            "publicDirectTtsRoutes": "blocked",
        }
        return upstream_status, public_failure
    upstream["interviewId"] = interview_id
    upstream["turnIndex"] = turn_index
    upstream["delivery"] = {
        "mode": "api-mediated-base64",
        "source": "ai-engine",
        "publicDirectTtsRoutes": "blocked",
    }
    return upstream_status, upstream

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
        question_match = NEXT_QUESTION_ROUTE_PATTERN.fullmatch(self.path)
        if question_match:
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self._json(400, {"error": "invalid_json", "message": str(exc)})
                return
            status, payload = request_next_question(question_match.group(1), int(question_match.group(2)), body)
            self._json(status, payload)
            return
        avatar_match = AVATAR_SESSION_ROUTE_PATTERN.fullmatch(self.path)
        if avatar_match:
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self._json(400, {"error": "invalid_json", "message": str(exc)})
                return
            status, payload = create_avatar_session(avatar_match.group(1), body)
            self._json(status, payload)
            return
        tts_match = TTS_ROUTE_PATTERN.fullmatch(self.path)
        if tts_match:
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self._json(400, {"error": "invalid_json", "message": str(exc)})
                return
            interview_id = tts_match.group(1)
            turn_index = int(tts_match.group(2))
            status, payload = synthesize_room_tts(interview_id, turn_index, body)
            self._json(status, payload)
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
