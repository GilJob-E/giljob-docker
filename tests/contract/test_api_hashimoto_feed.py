"""Contract test for the Realtime API -> hashimoto feed.

The API receives completed answer transcripts on the turn-events endpoint and
best-effort forwards them to hashimoto via POST /session + POST /submit_turn.
The public API response must expose only feed metadata, never the transcript.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

import server as api_server  # noqa: E402
from server import Handler, SESSION_HASH_STORE  # noqa: E402


class _FakeHashimotoHandler(BaseHTTPRequestHandler):
    received: list[tuple[str, dict[str, object]]] = []

    def log_message(self, *args: object) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        type(self).received.append((self.path, body))
        if self.path == "/session":
            self._json(201, {"session_id": body.get("session_id"), "current_topic": "backend"})
        elif self.path == "/submit_turn":
            self._json(202, {"accepted": True, "turn_id": body.get("turn_id")})
        else:
            self._json(404, {"error": "not_found"})

    def _json(self, status: int, obj: dict[str, object]) -> None:
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ApiHashimotoFeedTest(unittest.TestCase):
    def setUp(self) -> None:
        SESSION_HASH_STORE.clear()
        api_server.REALTIME_TURN_STATE.clear()
        api_server.HASHIMOTO_SESSION_SEEDS.clear()
        api_server.HASHIMOTO_BOOTSTRAPPED_SESSIONS.clear()
        self._old_base = os.environ.get("HASHIMOTO_BASE_URL")
        _FakeHashimotoHandler.received = []

        self.hashimoto = ThreadingHTTPServer(("127.0.0.1", 0), _FakeHashimotoHandler)
        self.hashimoto_thread = threading.Thread(target=self.hashimoto.serve_forever, daemon=True)
        self.hashimoto_thread.start()
        host, port = self.hashimoto.server_address
        os.environ["HASHIMOTO_BASE_URL"] = f"http://{host}:{port}"

        self.api = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.api_thread = threading.Thread(target=self.api.serve_forever, daemon=True)
        self.api_thread.start()
        self.api_base = f"http://{self.api.server_address[0]}:{self.api.server_address[1]}"

    def tearDown(self) -> None:
        self.api.shutdown()
        self.api.server_close()
        self.api_thread.join(timeout=2)
        self.hashimoto.shutdown()
        self.hashimoto.server_close()
        self.hashimoto_thread.join(timeout=2)
        SESSION_HASH_STORE.clear()
        api_server.REALTIME_TURN_STATE.clear()
        api_server.HASHIMOTO_SESSION_SEEDS.clear()
        api_server.HASHIMOTO_BOOTSTRAPPED_SESSIONS.clear()
        if self._old_base is None:
            os.environ.pop("HASHIMOTO_BASE_URL", None)
        else:
            os.environ["HASHIMOTO_BASE_URL"] = self._old_base

    def _post(self, path: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
        req = urllib.request.Request(
            self.api_base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.status, json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _body_for(self, path: str) -> dict[str, object]:
        return next(body for received_path, body in _FakeHashimotoHandler.received if received_path == path)

    def test_completed_transcript_is_forwarded_without_echoing_text(self) -> None:
        status, _ = self._post(
            "/api/sessions",
            {
                "role": "candidate",
                "interviewId": "local-demo",
                "candidateProfile": "backend engineer with three years of API experience",
                "job": "https://jobs.example.com/42",
            },
        )
        self.assertEqual(status, 201)

        status, body = self._post(
            "/api/interviews/local-demo/turns/1/events",
            {
                "type": "transcript.completed",
                "detail": {
                    "transcript": "I built FastAPI services and operated them in production.",
                    "itemId": "item-1",
                },
            },
        )

        self.assertEqual(status, 202)
        self.assertEqual(body["hashimoto"]["attempted"], True)
        self.assertEqual(body["hashimoto"]["status"], 202)
        self.assertNotIn("I built FastAPI", json.dumps(body))

        self.assertEqual([path for path, _ in _FakeHashimotoHandler.received], ["/session", "/submit_turn"])
        session = self._body_for("/session")
        self.assertEqual(session["session_id"], "local-demo")
        self.assertEqual(session["resume_text"], "backend engineer with three years of API experience")
        self.assertEqual(session["job_url"], "https://jobs.example.com/42")
        turn = self._body_for("/submit_turn")
        self.assertEqual(turn["session_id"], "local-demo")
        self.assertEqual(turn["turn_id"], "turn_0001")
        self.assertEqual(turn["text"], "I built FastAPI services and operated them in production.")

    def test_feed_is_noop_when_base_url_unset(self) -> None:
        os.environ.pop("HASHIMOTO_BASE_URL", None)
        self._post(
            "/api/sessions",
            {
                "role": "candidate",
                "interviewId": "local-disabled",
                "candidateProfile": "backend engineer",
            },
        )

        status, body = self._post(
            "/api/interviews/local-disabled/turns/1/events",
            {"type": "transcript.completed", "transcript": "answer text"},
        )

        self.assertEqual(status, 202)
        self.assertEqual(body["hashimoto"], {"attempted": False, "reason": "disabled"})
        self.assertEqual(_FakeHashimotoHandler.received, [])

    def test_feed_requires_session_seed(self) -> None:
        status, body = self._post(
            "/api/interviews/unseeded/turns/1/events",
            {"type": "transcript.completed", "transcript": "answer text"},
        )

        self.assertEqual(status, 202)
        self.assertEqual(body["hashimoto"], {"attempted": False, "reason": "missing_session_seed"})
        self.assertEqual(_FakeHashimotoHandler.received, [])


if __name__ == "__main__":
    unittest.main()
