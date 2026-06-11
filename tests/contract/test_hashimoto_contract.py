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
    """Stands in for LowLatencyHashimotoEngine — per-instance, no network.

    Models the real engine's asynchrony: submit_turn() only enqueues; the strategy
    (and its as_of turn) is NOT updated until complete_next() simulates the
    background worker finishing. This lets tests assert that /strategy reports the
    *completed* turn, not the most recently submitted one."""

    def __init__(self, topics):
        self._topics = list(topics) or ["t"]
        self.submitted: list[str] = []   # every turn_id handed to submit_turn
        self._pending: list[str] = []     # queued, worker not yet finished
        self._latest = None
        self._latest_turn_id = None
        self.started = False
        self.stopped = False

    # factory-compatible
    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    def submit_turn(self, engine_input):
        # enqueue only — strategy stays stale until the (simulated) worker completes
        self.submitted.append(engine_input.turn_id)
        self._pending.append(engine_input.turn_id)

    def complete_next(self):
        """Simulate the background worker finishing the oldest queued turn."""
        if not self._pending:
            return
        turn_id = self._pending.pop(0)
        self._latest = _FakePackage(turn_id)
        self._latest_turn_id = turn_id

    @property
    def latest_strategy(self):
        return self._latest

    @property
    def latest_strategy_turn_id(self):
        return self._latest_turn_id

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
        # worker finishes turn_0001's analysis → /strategy flips to ready
        hashimoto_server._sessions["sess_a"].engine.complete_next()
        warm = asyncio.run(hashimoto_server.strategy(session_id="sess_a"))
        wb = _body(warm)
        self.assertTrue(wb["ready"])
        self.assertEqual(wb["as_of_turn_id"], "turn_0001")
        self.assertIn("logic_goal", wb["interaction_strategy"])

    def test_strategy_reports_completed_turn_not_submitted(self) -> None:
        """Regression (C1): /strategy.as_of_turn_id must track the turn whose
        analysis actually completed, never a turn that was merely submitted.

        Sequence: submit+complete turn_1, then submit turn_2 WITHOUT completing it.
        While turn_2's analysis is still in flight, /strategy must keep reporting
        the turn_1-based package as_of turn_1 — not pretend it is turn_2-fresh."""
        self._open("sess_a")
        engine = hashimoto_server._sessions["sess_a"].engine

        asyncio.run(hashimoto_server.submit_turn(
            hashimoto_server.SubmitTurnRequest(session_id="sess_a", turn_id="turn_1", text="A1")))
        engine.complete_next()  # turn_1 analysis done
        first = _body(asyncio.run(hashimoto_server.strategy(session_id="sess_a")))
        self.assertTrue(first["ready"])
        self.assertEqual(first["as_of_turn_id"], "turn_1")

        # turn_2 submitted but worker has NOT finished it yet
        asyncio.run(hashimoto_server.submit_turn(
            hashimoto_server.SubmitTurnRequest(session_id="sess_a", turn_id="turn_2", text="A2")))
        stale = _body(asyncio.run(hashimoto_server.strategy(session_id="sess_a")))
        self.assertTrue(stale["ready"])
        self.assertEqual(stale["as_of_turn_id"], "turn_1",
                         "submitted-but-unanalyzed turn must not be reported as_of")
        self.assertEqual(stale["interaction_strategy"]["logic_goal"], "goal-after-turn_1")

        # once the worker finishes turn_2, /strategy advances
        engine.complete_next()
        fresh = _body(asyncio.run(hashimoto_server.strategy(session_id="sess_a")))
        self.assertEqual(fresh["as_of_turn_id"], "turn_2")
        self.assertEqual(fresh["interaction_strategy"]["logic_goal"], "goal-after-turn_2")

    def test_retried_past_turn_is_deduped_out_of_order(self) -> None:
        """Regression (C2): once a turn_id has been accepted, a later re-submit of
        that same id (even after newer turns) is rejected as duplicate — dedup is a
        full set keyed by turn_id, not just the last one."""
        self._open("sess_a")
        engine = hashimoto_server._sessions["sess_a"].engine
        for tid, txt in (("turn_1", "A1"), ("turn_2", "A2")):
            res = asyncio.run(hashimoto_server.submit_turn(
                hashimoto_server.SubmitTurnRequest(session_id="sess_a", turn_id=tid, text=txt)))
            self.assertEqual(res.status_code, 202)
        # retry of the older turn_1 after turn_2 → duplicate, not re-enqueued
        retry = asyncio.run(hashimoto_server.submit_turn(
            hashimoto_server.SubmitTurnRequest(session_id="sess_a", turn_id="turn_1", text="A1-retry")))
        self.assertEqual(retry.status_code, 200)
        self.assertFalse(_body(retry)["accepted"])
        self.assertEqual(_body(retry)["reason"], "duplicate_turn")
        self.assertEqual(engine.submitted, ["turn_1", "turn_2"])

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
