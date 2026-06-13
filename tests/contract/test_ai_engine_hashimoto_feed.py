"""Contract test for the ai-engine -> hashimoto feed (write side).

Spins a tiny in-process fake hashimoto HTTP server and asserts that the ai-engine
forwards answer transcripts to it via POST /session + POST /submit_turn, with freely
synthesized session_id/turn_id. Network stays on loopback; no Gemini/API key needed.
The whole feed is gated on HASHIMOTO_BASE_URL, so unsetting it must be a no-op.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
AI_ENGINE_ROOT = REPO_ROOT / "services" / "ai-engine"

spec = importlib.util.spec_from_file_location(
    "giljob_v2_ai_engine_server_feed", AI_ENGINE_ROOT / "server.py"
)
assert spec is not None and spec.loader is not None
ai_engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ai_engine
spec.loader.exec_module(ai_engine)


class _FakeHashimotoHandler(BaseHTTPRequestHandler):
    received: list[tuple[str, dict]] = []  # (path, body) shared via class

    def log_message(self, *args):  # silence
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        type(self).received.append((self.path, body))
        if self.path == "/session":
            self._json(201, {"session_id": body.get("session_id"), "current_topic": "t", "topics": ["t"]})
        elif self.path == "/submit_turn":
            self._json(202, {"accepted": True, "turn_id": body.get("turn_id")})
        elif self.path == "/session/end":
            self._json(200, {"session_id": body.get("session_id"), "closed": True})
        else:
            self._json(404, {"error": "not_found"})

    def _json(self, status, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class HashimotoFeedTest(unittest.TestCase):
    def setUp(self) -> None:
        _FakeHashimotoHandler.received = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeHashimotoHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        host, port = self._server.server_address
        self._base = f"http://{host}:{port}"
        # each test seeds session uniqueness; clear the module's bootstrap memo
        ai_engine._HASHIMOTO_SEEN_SESSIONS.clear()
        self._prev_env = ai_engine.os.environ.get("HASHIMOTO_BASE_URL")
        ai_engine.os.environ["HASHIMOTO_BASE_URL"] = self._base

    def tearDown(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._prev_env is None:
            ai_engine.os.environ.pop("HASHIMOTO_BASE_URL", None)
        else:
            ai_engine.os.environ["HASHIMOTO_BASE_URL"] = self._prev_env
        ai_engine._HASHIMOTO_SEEN_SESSIONS.clear()

    def _paths(self):
        return [p for p, _ in _FakeHashimotoHandler.received]

    def _body_for(self, path):
        return next(b for p, b in _FakeHashimotoHandler.received if p == path)

    def test_disabled_when_base_url_unset(self) -> None:
        ai_engine.os.environ.pop("HASHIMOTO_BASE_URL", None)
        ai_engine._feed_hashimoto({"sessionId": "s1", "candidateProfile": "이력서",
                                   "lastAnswer": "답변", }, turn_index=2)
        self.assertEqual(_FakeHashimotoHandler.received, [])

    def test_turn1_bootstraps_session_only(self) -> None:
        ai_engine._feed_hashimoto(
            {"sessionId": "s1", "candidateProfile": "백엔드 3년 경력", "job": "https://jobs.example.com/42"},
            turn_index=1,
        )
        self.assertIn("/session", self._paths())
        self.assertNotIn("/submit_turn", self._paths())
        sess = self._body_for("/session")
        self.assertEqual(sess["session_id"], "s1")
        self.assertEqual(sess["resume_text"], "백엔드 3년 경력")
        self.assertEqual(sess["job_url"], "https://jobs.example.com/42")  # job URL forwarded

    def test_turn2_submits_previous_answer(self) -> None:
        ai_engine._feed_hashimoto(
            {"sessionId": "s1", "candidateProfile": "이력서", "lastAnswer": "FastAPI로 백엔드를 만들었습니다"},
            turn_index=2,
        )
        self.assertIn("/submit_turn", self._paths())
        turn = self._body_for("/submit_turn")
        self.assertEqual(turn["session_id"], "s1")
        self.assertEqual(turn["turn_id"], "turn_0001")  # answer belongs to the prior turn
        self.assertEqual(turn["text"], "FastAPI로 백엔드를 만들었습니다")

    def test_session_id_falls_back_to_interview_id(self) -> None:
        ai_engine._feed_hashimoto(
            {"interviewId": "iv_9", "candidateProfile": "이력서", "lastAnswer": "답변"}, turn_index=2)
        self.assertEqual(self._body_for("/submit_turn")["session_id"], "iv_9")

    def test_non_url_job_is_not_sent_as_job_url(self) -> None:
        ai_engine._feed_hashimoto(
            {"sessionId": "s1", "candidateProfile": "이력서", "job": "백엔드 엔지니어 공고 본문"}, turn_index=1)
        self.assertNotIn("job_url", self._body_for("/session"))

    def test_never_raises_when_hashimoto_unreachable(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        ai_engine.os.environ["HASHIMOTO_BASE_URL"] = "http://127.0.0.1:1"  # closed port
        ai_engine._HASHIMOTO_SEEN_SESSIONS.clear()
        # must not raise
        ai_engine._feed_hashimoto(
            {"sessionId": "s1", "candidateProfile": "이력서", "lastAnswer": "답변"}, turn_index=2)

    def test_finalize_ends_hashimoto_session_and_submits_last_completed_answer(self) -> None:
        status, payload = ai_engine.finalize_response({
            "interviewId": "s1",
            "sessionId": "s1",
            "turnIndex": 3,
            "answer": "마지막으로 완료된 답변",
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload["hashimoto"]["lastTurnSubmitStatus"], 202)
        self.assertEqual(payload["hashimoto"]["sessionEndStatus"], 200)
        self.assertIn("/submit_turn", self._paths())
        self.assertIn("/session/end", self._paths())
        self.assertEqual(self._body_for("/submit_turn")["turn_id"], "turn_0003")
        self.assertEqual(self._body_for("/session/end")["session_id"], "s1")


if __name__ == "__main__":
    unittest.main()
