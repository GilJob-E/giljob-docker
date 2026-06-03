"""Contract test for services/hashimoto (internal strategy engine).

Network-free: a fake engine is injected via ``server._build_engine`` so no Gemini
call or API key is needed. The whole module is skipped if the service deps
(fastapi / pydantic / google-genai) are not installed in the test environment,
matching the deps-gated nature of this service (other contract tests are stdlib).
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SERVICE_ROOT = REPO_ROOT / "services" / "hashimoto"

# services/hashimoto vendored package (engine/llm/models) must be importable for
# server.py's internal `from engine... / from models...` imports to resolve.
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

# Load server.py under a unique module name (the bare name "server" collides with
# other services' server.py in sys.modules — same pattern as the ai-engine test).
try:
    from fastapi import HTTPException  # noqa: E402

    _spec = importlib.util.spec_from_file_location(
        "giljob_v2_hashimoto_server", SERVICE_ROOT / "server.py"
    )
    assert _spec is not None and _spec.loader is not None
    hashimoto_server = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = hashimoto_server
    _spec.loader.exec_module(hashimoto_server)
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - env without service deps
    hashimoto_server = None
    HTTPException = Exception  # type: ignore
    _IMPORT_ERROR = exc


def _body(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


class _FakePackage:
    def __init__(self, turn_id: str) -> None:
        self.interaction_strategy = {
            "logic_goal": f"goal-after-{turn_id}",
            "current_context": {"topic": "t", "resolved_history": []},
        }


class _FakeEngine:
    """Stands in for LowLatencyHashimotoEngine — per-instance, no network."""

    def __init__(self, topics):
        self._topics = list(topics) or ["t"]
        self.submitted: list[str] = []
        self._latest = None
        self.started = False
        self.stopped = False

    # factory-compatible
    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    def submit_turn(self, engine_input):
        # simulate synchronous "analysis done" so /strategy can flip to ready
        self.submitted.append(engine_input.turn_id)
        self._latest = _FakePackage(engine_input.turn_id)

    @property
    def latest_strategy(self):
        return self._latest

    @property
    def session_complete(self):
        return False

    @property
    def current_topic(self):
        return self._topics[0]

    @property
    def remaining_topics(self):
        return self._topics[1:]

    @property
    def verified_archive(self):
        return []

    @property
    def refused_archive(self):
        return []


@unittest.skipIf(hashimoto_server is None, f"service deps unavailable: {_IMPORT_ERROR}")
class HashimotoContractTest(unittest.TestCase):
    def setUp(self) -> None:
        hashimoto_server._sessions.clear()
        self._orig_build = hashimoto_server._build_engine
        hashimoto_server._build_engine = lambda resume_text, topics, topic_count, config: _FakeEngine(
            topics or ["주제1", "주제2"]
        )

    def tearDown(self) -> None:
        hashimoto_server._build_engine = self._orig_build
        hashimoto_server._sessions.clear()

    def _open(self, session_id="sess_a", topics=("주제1", "주제2")):
        req = hashimoto_server.OpenSessionRequest(session_id=session_id, topics=list(topics))
        return asyncio.run(hashimoto_server.open_session(req))

    def test_open_session_creates_isolated_engine(self) -> None:
        res = self._open("sess_a")
        self.assertEqual(res.status_code, 201)
        body = _body(res)
        self.assertEqual(body["session_id"], "sess_a")
        self.assertEqual(body["current_topic"], "주제1")
        self.assertIn("sess_a", hashimoto_server._sessions)

    def test_open_session_is_idempotent(self) -> None:
        self._open("sess_a")
        res = self._open("sess_a")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(_body(res)["already_open"])

    def test_submit_turn_dedupes_same_turn_id(self) -> None:
        self._open("sess_a")
        req = hashimoto_server.SubmitTurnRequest(session_id="sess_a", turn_id="turn_0001", text="첫 답변")
        first = asyncio.run(hashimoto_server.submit_turn(req))
        second = asyncio.run(hashimoto_server.submit_turn(req))
        self.assertEqual(first.status_code, 202)
        self.assertTrue(_body(first)["accepted"])
        self.assertEqual(second.status_code, 200)
        self.assertFalse(_body(second)["accepted"])
        self.assertEqual(_body(second)["reason"], "duplicate_turn")
        # engine saw the turn exactly once
        self.assertEqual(hashimoto_server._sessions["sess_a"].engine.submitted, ["turn_0001"])

    def test_sessions_are_isolated(self) -> None:
        self._open("sess_a")
        self._open("sess_b")
        asyncio.run(hashimoto_server.submit_turn(
            hashimoto_server.SubmitTurnRequest(session_id="sess_a", turn_id="turn_0001", text="A")))
        self.assertEqual(hashimoto_server._sessions["sess_a"].engine.submitted, ["turn_0001"])
        self.assertEqual(hashimoto_server._sessions["sess_b"].engine.submitted, [])

    def test_strategy_cold_then_ready(self) -> None:
        self._open("sess_a")
        cold = asyncio.run(hashimoto_server.strategy(session_id="sess_a"))
        self.assertFalse(_body(cold)["ready"])
        asyncio.run(hashimoto_server.submit_turn(
            hashimoto_server.SubmitTurnRequest(session_id="sess_a", turn_id="turn_0001", text="A")))
        warm = asyncio.run(hashimoto_server.strategy(session_id="sess_a"))
        wb = _body(warm)
        self.assertTrue(wb["ready"])
        self.assertEqual(wb["as_of_turn_id"], "turn_0001")
        self.assertIn("logic_goal", wb["interaction_strategy"])

    def test_unknown_session_is_404(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(hashimoto_server.strategy(session_id="nope"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_end_session_is_idempotent_and_stops_engine(self) -> None:
        self._open("sess_a")
        engine = hashimoto_server._sessions["sess_a"].engine
        res = asyncio.run(hashimoto_server.end_session(
            hashimoto_server.EndSessionRequest(session_id="sess_a")))
        self.assertEqual(res.status_code, 200)
        self.assertTrue(engine.stopped)
        self.assertNotIn("sess_a", hashimoto_server._sessions)
        again = asyncio.run(hashimoto_server.end_session(
            hashimoto_server.EndSessionRequest(session_id="sess_a")))
        self.assertTrue(_body(again)["already_closed"])

    def test_healthz_reports_status_without_leaking_key(self) -> None:
        res = asyncio.run(hashimoto_server.healthz())
        body = _body(res)
        self.assertEqual(body["service"], "hashimoto")
        self.assertEqual(body["status"], "ok")
        self.assertIn("geminiKeyConfigured", body)
        self.assertIsInstance(body["geminiKeyConfigured"], bool)


if __name__ == "__main__":
    unittest.main()
