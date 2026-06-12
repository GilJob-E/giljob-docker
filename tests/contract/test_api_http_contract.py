from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pathlib
import tempfile
import sys
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

import server as api_server  # noqa: E402
from server import Handler, SESSION_HASH_STORE  # noqa: E402

DEFAULT_AI_ENGINE_INTERNAL_URL = api_server.AI_ENGINE_INTERNAL_URL
DEFAULT_ANALYSIS_ENGINE_INTERNAL_URL = api_server.ANALYSIS_ENGINE_INTERNAL_URL

LIVEKIT_ENV_NAMES = (
    "LIVEKIT_REQUIRED",
    "LIVEKIT_MEDIA_OVERLAY_ENABLED",
    "LIVEKIT_URL",
    "LIVEKIT_INTERNAL_URL",
    "LIVEKIT_PUBLIC_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "AI_ENGINE_INTERNAL_URL",
    "OPENAI_API_KEY",
    "OPENAI_REALTIME_API_BASE",
    "OPENAI_REALTIME_CALL_BROKER_ENABLED",
    "OPENAI_REALTIME_SAFETY_SALT",
    "REALTIME_MMM_EVENT_LOG_PATH",
    "REALTIME_MMM_FORWARD_ENABLED",
    "REALTIME_MMM_RESULT_TIMEOUT_SECONDS",
    "GILJOBE_VISION",
    "GILJOBE_PROSODY",
    "ELEVENLABS_API_KEY",
    "SPATIALREAL_API_KEY",
)


class ApiHttpContractTest(unittest.TestCase):
    def setUp(self) -> None:
        SESSION_HASH_STORE.clear()
        api_server.REALTIME_TURN_STATE.clear()
        api_server.REALTIME_RESPONSE_COMMANDS.clear()
        api_server.AI_ENGINE_INTERNAL_URL = DEFAULT_AI_ENGINE_INTERNAL_URL
        api_server.ANALYSIS_ENGINE_INTERNAL_URL = DEFAULT_ANALYSIS_ENGINE_INTERNAL_URL
        self._old_livekit_env = {name: os.environ.get(name) for name in LIVEKIT_ENV_NAMES}
        for name in self._old_livekit_env:
            os.environ.pop(name, None)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host = self.server.server_address[0]
        port = self.server.server_address[1]
        self.base_url = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        SESSION_HASH_STORE.clear()
        api_server.REALTIME_TURN_STATE.clear()
        api_server.REALTIME_RESPONSE_COMMANDS.clear()
        api_server.AI_ENGINE_INTERNAL_URL = DEFAULT_AI_ENGINE_INTERNAL_URL
        api_server.ANALYSIS_ENGINE_INTERNAL_URL = DEFAULT_ANALYSIS_ENGINE_INTERNAL_URL
        for name, value in self._old_livekit_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def _post(self, path: str, payload: bytes = b'{"role":"candidate"}') -> tuple[int, str]:
        req = urllib.request.Request(
            self.base_url + path,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.status, res.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    def _start_fake_ai_engine(self, response_payload: dict[str, object], *, status: int = 200) -> list[dict[str, object]]:
        captured: list[dict[str, object]] = []

        class FakeAiEngineHandler(BaseHTTPRequestHandler):
            def do_POST(inner_self) -> None:  # noqa: N802 - stdlib callback name
                length = int(inner_self.headers.get("Content-Length", "0") or "0")
                raw = inner_self.rfile.read(length) if length else b""
                captured.append({
                    "path": inner_self.path,
                    "body": raw.decode("utf-8"),
                })
                body = json.dumps(response_payload).encode("utf-8")
                inner_self.send_response(status)
                inner_self.send_header("Content-Type", "application/json")
                inner_self.send_header("Content-Length", str(len(body)))
                inner_self.end_headers()
                inner_self.wfile.write(body)

            def log_message(inner_self, format: str, *args: object) -> None:
                return None

        fake_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAiEngineHandler)
        fake_thread = threading.Thread(target=fake_server.serve_forever, daemon=True)
        fake_thread.start()

        def cleanup() -> None:
            fake_server.shutdown()
            fake_server.server_close()
            fake_thread.join(timeout=2)

        self.addCleanup(cleanup)
        host, port = fake_server.server_address
        api_server.AI_ENGINE_INTERNAL_URL = f"http://{host}:{port}"
        return captured

    def _start_fake_analysis_engine(self, *, status: int = 202, result_payload: dict[str, object] | None = None, result_status: int = 200) -> list[dict[str, object]]:
        captured: list[dict[str, object]] = []

        class FakeAnalysisEngineHandler(BaseHTTPRequestHandler):
            def do_POST(inner_self) -> None:  # noqa: N802 - stdlib callback name
                length = int(inner_self.headers.get("Content-Length", "0") or "0")
                raw = inner_self.rfile.read(length) if length else b""
                captured.append({
                    "method": "POST",
                    "path": inner_self.path,
                    "body": raw.decode("utf-8"),
                })
                body = b'{"accepted":true}'
                inner_self.send_response(status)
                inner_self.send_header("Content-Type", "application/json")
                inner_self.send_header("Content-Length", str(len(body)))
                inner_self.end_headers()
                inner_self.wfile.write(body)

            def do_GET(inner_self) -> None:  # noqa: N802 - stdlib callback name
                captured.append({
                    "method": "GET",
                    "path": inner_self.path,
                    "body": "",
                })
                body = json.dumps(result_payload if result_payload is not None else {"status": "pending"}).encode("utf-8")
                inner_self.send_response(result_status)
                inner_self.send_header("Content-Type", "application/json")
                inner_self.send_header("Content-Length", str(len(body)))
                inner_self.end_headers()
                inner_self.wfile.write(body)

            def log_message(inner_self, format: str, *args: object) -> None:
                return None

        fake_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAnalysisEngineHandler)
        fake_thread = threading.Thread(target=fake_server.serve_forever, daemon=True)
        fake_thread.start()

        def cleanup() -> None:
            fake_server.shutdown()
            fake_server.server_close()
            fake_thread.join(timeout=2)

        self.addCleanup(cleanup)
        host, port = fake_server.server_address
        api_server.ANALYSIS_ENGINE_INTERNAL_URL = f"http://{host}:{port}"
        return captured

    def test_create_session_routes_return_public_tokens_and_store_hashes_only(self) -> None:
        for path in ("/sessions", "/api/sessions"):
            with self.subTest(path=path):
                SESSION_HASH_STORE.clear()
                status, body = self._post(path)
                self.assertEqual(status, 201)
                public = json.loads(body)
                session_token = public["sessionToken"]
                report_token = public["reportToken"]
                self.assertNotEqual(session_token, report_token)
                self.assertEqual(public["livekit"]["tokenStatus"], "not_configured")
                self.assertEqual(public["livekit"]["deferredReason"], "livekit_media_overlay_disabled")
                self.assertEqual(public["livekit"]["publicUrl"], None)
                self.assertNotIn("Hash", body)
                self.assertNotIn("hash", body)

                self.assertEqual(set(SESSION_HASH_STORE), {public["sessionId"]})
                stored_json = json.dumps(next(iter(SESSION_HASH_STORE.values())), sort_keys=True)
                self.assertIn("sessionTokenHash", stored_json)
                self.assertIn("reportTokenHash", stored_json)
                self.assertNotIn(session_token, stored_json)
                self.assertNotIn(report_token, stored_json)

    def test_create_session_accepts_safe_interview_id_for_room_binding(self) -> None:
        status, body = self._post("/api/sessions", b'{"role":"candidate","interviewId":"local-demo"}')
        self.assertEqual(status, 201)
        public = json.loads(body)
        self.assertEqual(public["sessionId"], "local-demo")
        self.assertEqual(public["roomName"], "giljob-session-local-demo")
        self.assertEqual(set(SESSION_HASH_STORE), {"local-demo"})

    def test_create_session_realtime_metadata_includes_safe_experimental_avatar_bridge_sibling(self) -> None:
        status, body = self._post("/api/sessions", b'{"role":"candidate","interviewId":"local-demo"}')
        self.assertEqual(status, 201, body)
        payload = json.loads(body)
        self.assertIn("realtime", payload)
        self.assertIn("realtimeAvatarBridge", payload)
        bridge = payload["realtimeAvatarBridge"]

        self.assertEqual(bridge["mode"], "experimental-openai-realtime-audio-to-avatar")
        self.assertEqual(bridge["status"], "blocked")
        self.assertFalse(bridge["enabled"])
        self.assertEqual(bridge["directProviderRoutes"], "blocked")
        self.assertEqual(bridge["controlBoundary"], "api-metadata-and-browser-livekit-publication")
        self.assertEqual(bridge["requiresFeatureFlag"], "SPATIALREAL_BROWSER_AUDIO_BRIDGE_ENABLED")
        self.assertFalse(bridge["providerSecretsExposed"])
        self.assertFalse(bridge["rawMediaExposed"])
        self.assertFalse(bridge["rawTranscriptExposed"])
        self.assertIn("experimental", bridge["description"].lower())
        self.assertIn("blocked", bridge["blockedOutcome"].lower())

        serialized = json.dumps(payload, ensure_ascii=False)
        forbidden = [
            "secret-openai-key",
            "SPATIALREAL_API_KEY",
            "OPENAI_API_KEY",
            "client_secret",
            "server_secret",
            "raw media bytes",
            "raw candidate",
            "v=0",
        ]
        for marker in forbidden:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, serialized)

    def test_create_session_default_path_is_realtime_metadata_without_livekit_token(self) -> None:
        status, body = self._post("/api/sessions", b'{"role":"candidate","interviewId":"local-demo"}')
        self.assertEqual(status, 201, body)
        payload = json.loads(body)
        self.assertEqual(payload["sessionId"], "local-demo")
        self.assertIn("realtime", payload)
        self.assertEqual(payload["realtime"]["enabled"], True)
        self.assertEqual(payload["realtime"]["mode"], "primary")
        self.assertEqual(payload["realtime"]["browserWebrtcAttach"], "api-call-broker")
        self.assertEqual(payload["realtime"]["directProviderRoutes"], "blocked")
        self.assertIn("/api/interviews/local-demo/realtime/session", payload["realtime"]["sessionEndpoint"])
        self.assertIn("/api/interviews/local-demo/realtime/call", payload["realtime"]["callEndpoint"])
        self.assertIn("/api/interviews/local-demo/turns/{turnIndex}/mmm-ready", payload["realtime"]["mmmReadyEndpoint"])
        livekit = payload["livekit"]
        self.assertEqual(livekit["tokenStatus"], "not_configured")
        self.assertIsNone(livekit["candidateToken"])
        self.assertIsNone(livekit["url"])
        self.assertIsNone(livekit["publicUrl"])
        self.assertEqual(livekit["deferredReason"], "livekit_media_overlay_disabled")
        self.assertNotIn("livekitRequired", payload)
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        for forbidden in ("LIVEKIT_API_SECRET", "OPENAI_API_KEY", "client_secret", "server_secret", "v=0", "raw candidate"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)

    def test_create_session_rejects_unsafe_interview_id(self) -> None:
        status, body = self._post("/api/sessions", b'{"role":"candidate","interviewId":"../local-demo"}')
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "invalid_session_id")

    def test_invalid_json_returns_400(self) -> None:
        status, body = self._post("/sessions", b"{bad-json")
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "invalid_json")

    def test_internal_session_route_stays_hidden(self) -> None:
        status, body = self._post("/api/internal/sessions")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "not_found")



    def test_next_question_route_proxies_ai_engine_without_secret_leak(self) -> None:
        captured = self._start_fake_ai_engine({
            "interviewId": "local-demo",
            "turnIndex": 1,
            "questionId": "q_local-demo_0001",
            "question": "지원한 직무와 연결되는 경험을 설명해 주세요.",
            "provider": "fake",
            "providerStatus": "fake",
            "answerTurn": {"boundary": "manual_button"},
        })
        status, body = self._post(
            "/api/interviews/local-demo/turns/1/question",
            json.dumps({"lastAnswer": "아직 이전 답변 없음"}).encode("utf-8"),
        )
        self.assertEqual(status, 200, body)
        payload = json.loads(body)
        self.assertEqual(payload["interviewId"], "local-demo")
        self.assertEqual(payload["turnIndex"], 1)
        self.assertEqual(payload["delivery"]["mode"], "api-mediated-question")
        self.assertEqual(captured[0]["path"], "/interview/next-question")
        upstream_payload = json.loads(str(captured[0]["body"]))
        self.assertEqual(upstream_payload["interviewId"], "local-demo")
        self.assertEqual(upstream_payload["turnIndex"], 1)
        self.assertNotIn("ELEVENLABS_API_KEY", body)

    def test_next_question_route_accepts_caddy_stripped_path_and_bad_id_fails(self) -> None:
        self._start_fake_ai_engine({"interviewId": "local-demo", "turnIndex": 2, "question": "다음 질문입니다."})
        status, body = self._post("/interviews/local-demo/turns/2/question", b"{}")
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["turnIndex"], 2)

        status, body = self._post("/api/interviews/../turns/1/question", b"{}")
        self.assertEqual(status, 404, body)
        self.assertEqual(json.loads(body)["error"], "not_found")

    def test_realtime_turn_events_forward_start_end_transcript_prosody_to_analysis_engine(self) -> None:
        captured = self._start_fake_analysis_engine(status=202)
        os.environ["REALTIME_MMM_FORWARD_ENABLED"] = "true"
        with tempfile.NamedTemporaryFile(delete=False) as event_log:
            event_log_path = event_log.name
        self.addCleanup(lambda: pathlib.Path(event_log_path).unlink(missing_ok=True))
        os.environ["REALTIME_MMM_EVENT_LOG_PATH"] = event_log_path
        os.environ["GILJOBE_VISION"] = "off"
        os.environ["GILJOBE_PROSODY"] = "on"

        events = [
            {"type": "turn.answer_started"},
            {"type": "turn.answer_ended", "detail": {"transcriptAvailable": True}},
            {"type": "transcript.completed", "transcript": "bounded candidate answer", "detail": {"transcript": "bounded candidate answer", "itemId": "item-1"}},
            {"type": "prosody.window_metrics", "detail": {"energy": 0.3}},
        ]
        for event in events:
            status, body = self._post(
                "/api/interviews/local-demo/turns/1/events",
                json.dumps(event).encode("utf-8"),
            )
            self.assertEqual(status, 202, body)
            payload = json.loads(body)
            self.assertTrue(payload["ingress"]["analysisEngine"]["attempted"])
            self.assertEqual(payload["ingress"]["analysisEngine"]["status"], 202)
            self.assertEqual(payload["ingress"]["analysisEngine"]["endpoint"], "/realtime/turn-events")

        self.assertEqual([entry["path"] for entry in captured], ["/realtime/turn-events"] * 4)
        forwarded = [json.loads(str(entry["body"])) for entry in captured]
        self.assertEqual([entry["eventKind"] for entry in forwarded], ["turn.answer_started", "turn.answer_ended", "transcript.completed", "prosody.window_metrics"])
        transcript_forward = forwarded[2]
        self.assertEqual(transcript_forward["source"], "api-sideband")
        self.assertEqual(transcript_forward["sessionId"], "local-demo")
        self.assertFalse(transcript_forward["rawTranscriptLogged"])
        self.assertFalse(transcript_forward["rawMediaAccepted"])
        self.assertEqual(transcript_forward["detail"], {"transcript": "bounded candidate answer", "itemId": "item-1"})
        persisted = pathlib.Path(event_log_path).read_text()
        self.assertNotIn("bounded candidate answer", persisted)

    def test_realtime_vision_events_forward_to_analysis_engine(self) -> None:
        captured = self._start_fake_analysis_engine(status=202)
        os.environ["REALTIME_MMM_FORWARD_ENABLED"] = "true"
        os.environ["REALTIME_MMM_EVENT_LOG_PATH"] = "0"
        status, body = self._post(
            "/api/interviews/local-demo/turns/1/vision-events",
            json.dumps({"type": "vision.frame_metrics", "detail": {"faceVisible": True}}).encode("utf-8"),
        )
        self.assertEqual(status, 202, body)
        payload = json.loads(body)
        self.assertTrue(payload["ingress"]["analysisEngine"]["attempted"])
        self.assertEqual(captured[0]["path"], "/realtime/turn-events")
        forwarded = json.loads(str(captured[0]["body"]))
        self.assertEqual(forwarded["eventKind"], "vision.frame_metrics")
        self.assertEqual(forwarded["sourceRoute"], "vision-events")


    def test_realtime_response_create_allows_bootstrap_first_question_without_mmm_gate(self) -> None:
        os.environ["REALTIME_MMM_EVENT_LOG_PATH"] = "0"
        os.environ["REALTIME_MMM_FORWARD_ENABLED"] = "off"
        os.environ["GILJOBE_VISION"] = "off"
        os.environ["GILJOBE_PROSODY"] = "off"

        status, body = self._post("/api/interviews/local-demo/turns/1/realtime/response", b"{}")
        self.assertEqual(status, 202, body)
        payload = json.loads(body)
        self.assertEqual(payload["turnIndex"], 1)
        self.assertIsNone(payload["analysisTurnIndex"])
        self.assertEqual(payload["bootstrap"], {"firstQuestion": True, "mmmGateRequired": False, "reason": "no_prior_candidate_answer"})
        self.assertEqual(payload["responseCreate"], {"owner": "api", "created": True, "commandType": "response.create"})
        self.assertTrue(payload["sideband"]["browserTransportOnly"])
        self.assertEqual(payload["sideband"]["command"]["type"], "response.create")
        self.assertEqual(payload["sideband"]["command"]["response"]["output_modalities"], ["audio"])
        self.assertNotIn("modalities", payload["sideband"]["command"]["response"])
        self.assertNotIn("MMM", body)
        self.assertNotIn("analysis-engine", body)
        self.assertNotIn("backend", body)
        self.assertNotIn("readiness gate", body)

    def test_realtime_response_create_blocks_followup_until_prior_answer_analysis_ready(self) -> None:
        os.environ["REALTIME_MMM_EVENT_LOG_PATH"] = "0"
        os.environ["REALTIME_MMM_FORWARD_ENABLED"] = "off"
        os.environ["GILJOBE_VISION"] = "off"
        os.environ["GILJOBE_PROSODY"] = "off"

        status, body = self._post(
            "/api/interviews/local-demo/turns/2/realtime/response",
            json.dumps({"analysisResult": {"status": "ready", "sessionId": "local-demo", "turnIndex": 1, "candidatePromptFragment": "경험의 구체성을 자연스럽게 확인하세요."}}).encode("utf-8"),
        )
        self.assertEqual(status, 409, body)
        payload = json.loads(body)
        self.assertEqual(payload["error"], "analysis_result_not_ready")
        self.assertEqual(payload["analysisTurnIndex"], 1)
        self.assertEqual(payload["responseCreate"], {"owner": "api", "created": False, "reason": "full_mmm_required_for_prior_answer"})

    def test_realtime_response_create_uses_candidate_safe_analysis_fragment_only(self) -> None:
        os.environ["REALTIME_MMM_EVENT_LOG_PATH"] = "0"
        os.environ["REALTIME_MMM_FORWARD_ENABLED"] = "off"
        os.environ["GILJOBE_VISION"] = "off"
        os.environ["GILJOBE_PROSODY"] = "off"
        analysis = self._start_fake_analysis_engine(result_payload={
            "schemaVersion": "2026-06-12.mmm-result.v1",
            "status": "ready",
            "sessionId": "local-demo",
            "turnIndex": 1,
            "candidateSafePromptFragment": {
                "schemaVersion": "2026-06-12.candidate-safe-prompt-fragment.v1",
                "text": "이전 답변의 협업 경험을 바탕으로 갈등 해결 과정을 한 가지 더 물어보세요.",
                "containsRawTranscript": False,
                "containsRawMedia": False,
                "containsSecrets": False,
            },
            "confidence": 0.82,
            "latencyMs": 740,
            "rawTranscriptLogged": False,
            "rawMediaAccepted": False,
            "transcriptSummary": "raw text must not be returned",
        })

        self._post(
            "/api/interviews/local-demo/turns/1/events",
            json.dumps({"type": "turn.answer_ended", "detail": {"transcriptAvailable": True}}).encode("utf-8"),
        )
        self._post(
            "/api/interviews/local-demo/turns/1/events",
            json.dumps({"type": "transcript.completed", "transcript": "bounded candidate answer"}).encode("utf-8"),
        )
        status, body = self._post("/api/interviews/local-demo/turns/2/realtime/response", b"{}")
        self.assertEqual(status, 202, body)
        payload = json.loads(body)
        self.assertEqual(payload["turnIndex"], 2)
        self.assertEqual(payload["analysisTurnIndex"], 1)
        self.assertEqual(payload["status"], "response_create_queued")
        self.assertEqual(payload["responseCreate"], {"owner": "api", "created": True, "commandType": "response.create"})
        self.assertEqual(payload["sideband"]["singleResponseCreateOwner"], "api")
        self.assertEqual(payload["sideband"]["command"]["type"], "response.create")
        self.assertEqual(payload["sideband"]["command"]["response"]["output_modalities"], ["audio"])
        self.assertNotIn("modalities", payload["sideband"]["command"]["response"])
        self.assertIn("갈등 해결 과정", payload["sideband"]["command"]["response"]["instructions"])
        self.assertEqual(payload["analysisResult"]["schemaVersion"], "2026-06-12.mmm-result.v1")
        self.assertEqual(analysis[-1]["method"], "GET")
        self.assertIn("/realtime/turn-results", analysis[-1]["path"])
        self.assertIn("interviewId=local-demo", analysis[-1]["path"])
        self.assertIn("turnIndex=1", analysis[-1]["path"])
        self.assertNotIn("raw text must not be returned", body)
        for forbidden in ("MMM", "analysis-engine", "backend", "readiness gate"):
            self.assertNotIn(forbidden, payload["sideband"]["command"]["response"]["instructions"])

    def test_realtime_response_create_rejects_wrong_or_stale_turn_analysis_result(self) -> None:
        os.environ["REALTIME_MMM_EVENT_LOG_PATH"] = "0"
        os.environ["REALTIME_MMM_FORWARD_ENABLED"] = "off"
        os.environ["GILJOBE_VISION"] = "off"
        os.environ["GILJOBE_PROSODY"] = "off"
        analysis = self._start_fake_analysis_engine(result_payload={
            "schemaVersion": "2026-06-12.turn-handoff-fragment.v2",
            "status": "ready",
            "turnIndex": 2,
            "candidatePromptFragment": "STALE_GUIDANCE_SHOULD_NOT_BE_USED",
            "rawTranscriptLogged": False,
            "rawMediaAccepted": False,
        })

        self._post(
            "/api/interviews/local-demo/turns/1/events",
            json.dumps({"type": "turn.answer_ended", "detail": {"transcriptAvailable": True}}).encode("utf-8"),
        )
        self._post(
            "/api/interviews/local-demo/turns/1/events",
            json.dumps({"type": "transcript.completed", "transcript": "bounded candidate answer"}).encode("utf-8"),
        )
        status, body = self._post("/api/interviews/local-demo/turns/2/realtime/response", b"{}")
        self.assertEqual(status, 409, body)
        payload = json.loads(body)
        self.assertEqual(payload["error"], "analysis_result_stale_or_wrong_turn")
        self.assertEqual(payload["analysisTurnIndex"], 1)
        self.assertEqual(payload["responseCreate"], {"owner": "api", "created": False, "reason": "exact_turn_analysis_required"})
        self.assertIn("turnIndex=1", analysis[-1]["path"])
        self.assertNotIn("STALE_GUIDANCE_SHOULD_NOT_BE_USED", body)

    def test_realtime_response_create_rejects_unsafe_analysis_fragment(self) -> None:
        os.environ["REALTIME_MMM_EVENT_LOG_PATH"] = "0"
        os.environ["REALTIME_MMM_FORWARD_ENABLED"] = "off"
        os.environ["GILJOBE_VISION"] = "off"
        os.environ["GILJOBE_PROSODY"] = "off"
        self._start_fake_analysis_engine(result_payload={
            "schemaVersion": "2026-06-12.mmm-result.v1",
            "status": "ready",
            "sessionId": "local-demo",
            "turnIndex": 1,
            "candidatePromptFragment": "Use MMM backend readiness gate details.",
            "rawTranscriptLogged": False,
            "rawMediaAccepted": False,
        })
        self._post(
            "/api/interviews/local-demo/turns/1/events",
            json.dumps({"type": "turn.answer_ended", "detail": {"transcriptAvailable": True}}).encode("utf-8"),
        )
        self._post(
            "/api/interviews/local-demo/turns/1/events",
            json.dumps({"type": "transcript.completed", "transcript": "bounded candidate answer"}).encode("utf-8"),
        )

        status, body = self._post("/api/interviews/local-demo/turns/2/realtime/response", b"{}")
        self.assertEqual(status, 409, body)
        payload = json.loads(body)
        self.assertEqual(payload["error"], "analysis_result_not_usable")
        self.assertEqual(payload["responseCreate"]["created"], False)
        self.assertNotIn("Use MMM backend readiness gate details", body)

    def test_realtime_response_create_rejects_structured_fragment_with_raw_flags(self) -> None:
        os.environ["REALTIME_MMM_EVENT_LOG_PATH"] = "0"
        os.environ["REALTIME_MMM_FORWARD_ENABLED"] = "off"
        os.environ["GILJOBE_VISION"] = "off"
        os.environ["GILJOBE_PROSODY"] = "off"
        self._start_fake_analysis_engine(result_payload={
            "schemaVersion": "2026-06-12.mmm-result.v1",
            "status": "ready",
            "sessionId": "local-demo",
            "turnIndex": 1,
            "candidateSafePromptFragment": {
                "schemaVersion": "2026-06-12.candidate-safe-prompt-fragment.v1",
                "text": "raw-flagged fragment must not be used",
                "containsRawTranscript": True,
                "containsRawMedia": False,
                "containsSecrets": False,
            },
            "rawTranscriptLogged": False,
            "rawMediaAccepted": False,
        })
        self._post(
            "/api/interviews/local-demo/turns/1/events",
            json.dumps({"type": "turn.answer_ended", "detail": {"transcriptAvailable": True}}).encode("utf-8"),
        )
        self._post(
            "/api/interviews/local-demo/turns/1/events",
            json.dumps({"type": "transcript.completed", "transcript": "bounded candidate answer"}).encode("utf-8"),
        )

        status, body = self._post("/api/interviews/local-demo/turns/2/realtime/response", b"{}")
        self.assertEqual(status, 409, body)
        payload = json.loads(body)
        self.assertEqual(payload["error"], "analysis_result_not_usable")
        self.assertEqual(payload["responseCreate"]["created"], False)
        self.assertNotIn("raw-flagged fragment must not be used", body)


    def test_realtime_response_create_ignores_inline_analysis_and_requires_engine_result(self) -> None:
        os.environ["REALTIME_MMM_EVENT_LOG_PATH"] = "0"
        os.environ["REALTIME_MMM_FORWARD_ENABLED"] = "off"
        os.environ["GILJOBE_VISION"] = "off"
        os.environ["GILJOBE_PROSODY"] = "off"
        self._post(
            "/api/interviews/local-demo/turns/1/events",
            json.dumps({"type": "turn.answer_ended", "detail": {"transcriptAvailable": True}}).encode("utf-8"),
        )
        self._post(
            "/api/interviews/local-demo/turns/1/events",
            json.dumps({"type": "transcript.completed", "transcript": "bounded candidate answer"}).encode("utf-8"),
        )

        status, body = self._post(
            "/api/interviews/local-demo/turns/2/realtime/response",
            json.dumps({"analysisResult": {"status": "ready", "sessionId": "local-demo", "turnIndex": 1, "candidatePromptFragment": "inline result must be ignored"}}).encode("utf-8"),
        )
        self.assertEqual(status, 409, body)
        payload = json.loads(body)
        self.assertEqual(payload["error"], "analysis_result_unavailable")
        self.assertEqual(payload["responseCreate"], {"owner": "api", "created": False, "reason": "structured_analysis_required"})
        self.assertNotIn("inline result must be ignored", body)

    def test_realtime_response_create_rejects_wrong_turn_analysis_result(self) -> None:
        os.environ["REALTIME_MMM_EVENT_LOG_PATH"] = "0"
        os.environ["REALTIME_MMM_FORWARD_ENABLED"] = "off"
        os.environ["GILJOBE_VISION"] = "off"
        os.environ["GILJOBE_PROSODY"] = "off"
        self._start_fake_analysis_engine(result_payload={
            "schemaVersion": "2026-06-12.mmm-result.v1",
            "status": "ready",
            "sessionId": "local-demo",
            "turnIndex": 2,
            "candidatePromptFragment": "wrong turn fragment must not be used",
            "rawTranscriptLogged": False,
            "rawMediaAccepted": False,
        })
        self._post(
            "/api/interviews/local-demo/turns/1/events",
            json.dumps({"type": "turn.answer_ended", "detail": {"transcriptAvailable": True}}).encode("utf-8"),
        )
        self._post(
            "/api/interviews/local-demo/turns/1/events",
            json.dumps({"type": "transcript.completed", "transcript": "bounded candidate answer"}).encode("utf-8"),
        )

        status, body = self._post("/api/interviews/local-demo/turns/2/realtime/response", b"{}")
        self.assertEqual(status, 409, body)
        payload = json.loads(body)
        self.assertEqual(payload["error"], "analysis_result_not_usable")
        self.assertEqual(payload["responseCreate"]["reason"], "candidate_safe_ready_result_required")
        self.assertNotIn("wrong turn fragment must not be used", body)


    def test_realtime_response_create_rejects_wrong_turn_analysis_result(self) -> None:
        os.environ["REALTIME_MMM_EVENT_LOG_PATH"] = "0"
        os.environ["REALTIME_MMM_FORWARD_ENABLED"] = "off"
        os.environ["GILJOBE_VISION"] = "off"
        os.environ["GILJOBE_PROSODY"] = "off"
        self._start_fake_analysis_engine(result_payload={
            "schemaVersion": "2026-06-12.mmm-result.v1",
            "status": "ready",
            "sessionId": "local-demo",
            "turnIndex": 2,
            "candidatePromptFragment": "wrong turn fragment must not be used",
            "rawTranscriptLogged": False,
            "rawMediaAccepted": False,
        })
        self._post(
            "/api/interviews/local-demo/turns/1/events",
            json.dumps({"type": "turn.answer_ended", "detail": {"transcriptAvailable": True}}).encode("utf-8"),
        )
        self._post(
            "/api/interviews/local-demo/turns/1/events",
            json.dumps({"type": "transcript.completed", "transcript": "bounded candidate answer"}).encode("utf-8"),
        )

        status, body = self._post("/api/interviews/local-demo/turns/2/realtime/response", b"{}")
        self.assertEqual(status, 409, body)
        payload = json.loads(body)
        self.assertEqual(payload["error"], "analysis_result_not_usable")
        self.assertEqual(payload["responseCreate"]["reason"], "candidate_safe_ready_result_required")
        self.assertNotIn("wrong turn fragment must not be used", body)



    def test_realtime_response_create_rejects_wrong_turn_analysis_result(self) -> None:
        os.environ["REALTIME_MMM_EVENT_LOG_PATH"] = "0"
        os.environ["REALTIME_MMM_FORWARD_ENABLED"] = "off"
        os.environ["GILJOBE_VISION"] = "off"
        os.environ["GILJOBE_PROSODY"] = "off"
        self._post("/api/interviews/local-demo/turns/1/events", json.dumps({"type": "turn.answer_ended", "detail": {"transcriptAvailable": True}}).encode("utf-8"))
        self._post("/api/interviews/local-demo/turns/1/events", json.dumps({"type": "transcript.completed", "transcript": "bounded candidate answer"}).encode("utf-8"))

        status, body = self._post(
            "/api/interviews/local-demo/turns/2/realtime/response",
            json.dumps({"analysisResult": {"status": "ready", "interviewId": "local-demo", "turnIndex": 99, "candidatePromptFragment": "이전 답변을 바탕으로 구체 사례를 물어보세요."}}).encode("utf-8"),
        )
        self.assertEqual(status, 409, body)
        payload = json.loads(body)
        self.assertEqual(payload["error"], "analysis_result_wrong_turn")
        self.assertEqual(payload["responseCreate"], {"owner": "api", "created": False, "reason": "exact_turn_analysis_result_required"})

    def test_mmm_ready_requires_exact_turn_analysis_result_acceptance(self) -> None:
        os.environ["REALTIME_MMM_EVENT_LOG_PATH"] = "0"
        os.environ["REALTIME_MMM_FORWARD_ENABLED"] = "off"
        os.environ["GILJOBE_VISION"] = "off"
        os.environ["GILJOBE_PROSODY"] = "off"
        self._post("/api/interviews/local-demo/turns/1/events", json.dumps({"type": "turn.answer_ended", "detail": {"transcriptAvailable": True}}).encode("utf-8"))
        self._post("/api/interviews/local-demo/turns/1/events", json.dumps({"type": "transcript.completed", "transcript": "bounded candidate answer"}).encode("utf-8"))
        self._start_fake_analysis_engine(result_payload={"result": {"status": "pending", "reason": "no_exact_turn_result"}})

        with urllib.request.urlopen(self.base_url + "/api/interviews/local-demo/turns/1/mmm-ready", timeout=5) as res:
            body = res.read().decode("utf-8")
        payload = json.loads(body)
        self.assertFalse(payload["full_mmm_ready"])
        self.assertEqual(payload["reason"], "analysis_result_not_ready")
        self.assertEqual(payload["analysisEngine"]["endpoint"], "/realtime/turn-results")

    def test_realtime_session_broker_uses_server_key_and_disables_auto_response(self) -> None:
        os.environ["OPENAI_API_KEY"] = "secret-openai-key"
        captured: list[urllib.request.Request] = []

        class FakeResponse:
            status = 200
            headers: dict[str, str] = {}

            def __enter__(self):
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps({
                    "id": "sess_123",
                    "client_secret": {"type": "ephemeral", "value": "browser-ephemeral-secret", "expires_at": 12345},
                    "server_secret": "must-not-return",
                    "session": {"model": "gpt-realtime-2"},
                }).encode("utf-8")

        def fake_urlopen(request: urllib.request.Request, timeout: float = 0) -> FakeResponse:
            captured.append(request)
            return FakeResponse()

        with patch("server.urllib.request.urlopen", side_effect=fake_urlopen):
            status, payload = api_server.create_realtime_session("local-demo", {})

        self.assertEqual(status, 200)
        self.assertEqual(captured[0].full_url, "https://api.openai.com/v1/realtime/client_secrets")
        self.assertEqual(captured[0].headers.get("Authorization"), "Bearer secret-openai-key")
        upstream = json.loads(captured[0].data.decode("utf-8"))
        self.assertFalse(upstream["session"]["audio"]["input"]["turn_detection"]["create_response"])
        body = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("browser-ephemeral-secret", body)
        self.assertNotIn("client_secret", body)
        self.assertNotIn("secret-openai-key", body)
        self.assertNotIn("must-not-return", body)
        self.assertEqual(payload["clientSecretPolicy"], "server-only-api-call-broker")
        update = payload["webrtc"]["postConnectSessionUpdate"]
        self.assertEqual(update["type"], "session.update")
        self.assertEqual(update["session"]["type"], "realtime")
        self.assertFalse(update["session"]["audio"]["input"]["turn_detection"]["create_response"])
        self.assertEqual(update["session"]["audio"]["input"]["transcription"]["model"], "gpt-realtime-whisper")
        self.assertEqual(payload["sideband"]["controlBoundary"], "server-sideband")

    def test_realtime_call_broker_prepared_does_not_echo_sdp_when_explicitly_disabled(self) -> None:
        os.environ["OPENAI_API_KEY"] = "secret-openai-key"
        os.environ["OPENAI_REALTIME_CALL_BROKER_ENABLED"] = "false"
        offer = "v=0\r\no=- raw-offer-sdp\r\n"
        status, payload = api_server.create_realtime_call("local-demo", {"sdp": offer})

        self.assertEqual(status, 202)
        self.assertEqual(payload["status"], "call_broker_prepared")
        self.assertIsNone(payload["sdpAnswer"])
        body = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("raw-offer-sdp", body)
        self.assertNotIn("secret-openai-key", body)
        self.assertEqual(payload["sideband"]["serverControlUrl"], "wss://api.openai.com/v1/realtime?call_id=<callId>")

    def test_realtime_call_broker_default_extracts_call_id_without_key_leak(self) -> None:
        os.environ["OPENAI_API_KEY"] = "secret-openai-key"
        captured: list[urllib.request.Request] = []

        class FakeHeaders(dict[str, str]):
            def get(self, key: str, default: str | None = None) -> str | None:
                return super().get(key, default)

        class FakeResponse:
            status = 201
            headers = FakeHeaders({"Location": "https://api.openai.com/v1/realtime/calls?call_id=call_abc123"})

            def __enter__(self):
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self) -> bytes:
                return b"v=0\r\no=- answer-sdp\r\n"

        def fake_urlopen(request: urllib.request.Request, timeout: float = 0) -> FakeResponse:
            captured.append(request)
            return FakeResponse()

        with patch("server.urllib.request.urlopen", side_effect=fake_urlopen):
            status, payload = api_server.create_realtime_call("local-demo", {"sdp": "v=0\r\no=- offer-sdp\r\n"})

        self.assertEqual(status, 200)
        self.assertEqual(payload["callId"], "call_abc123")
        self.assertEqual(captured[0].full_url, "https://api.openai.com/v1/realtime/calls")
        self.assertEqual(captured[0].headers.get("Authorization"), "Bearer secret-openai-key")
        self.assertIn(b"v=0\r\no=- offer-sdp\r\n", captured[0].data)
        self.assertNotIn(b"v=0 o=- offer-sdp", captured[0].data)
        self.assertIn(b'"type": "realtime"', captured[0].data)
        self.assertIn(b'"audio": {"output":', captured[0].data)
        self.assertNotIn(b'"turn_detection"', captured[0].data)
        self.assertNotIn(b'"transcription"', captured[0].data)
        body = json.dumps(payload, ensure_ascii=False)
        self.assertIn("answer-sdp", body)
        self.assertNotIn("offer-sdp", body)
        self.assertNotIn("secret-openai-key", body)


    def test_question_broker_redacts_upstream_provider_failure_markers(self) -> None:
        marker = "UPSTREAM_PROVIDER_DIAGNOSTIC_MARKER"
        self._start_fake_ai_engine({
            "error": "llm_provider_failed",
            "provider": "ai-engine",
            "message": marker,
            "model": "fake-interviewer",
        }, status=502)
        status, body = self._post(
            "/api/interviews/local-demo/turns/1/question",
            json.dumps({"lastAnswer": "없음"}).encode("utf-8"),
        )
        self.assertEqual(status, 502, body)
        payload = json.loads(body)
        self.assertEqual(payload["message"], "provider request failed")
        self.assertEqual(payload["delivery"]["mode"], "api-mediated-question")
        self.assertNotIn(marker, body)

    def test_tts_broker_redacts_upstream_provider_failure_markers(self) -> None:
        marker = "UPSTREAM_PROVIDER_DIAGNOSTIC_MARKER"
        self._start_fake_ai_engine({
            "error": "tts_provider_failed",
            "provider": "elevenlabs",
            "message": marker,
            "audio": {"base64": marker},
        }, status=502)
        status, body = self._post(
            "/api/interviews/local-demo/turns/1/tts",
            json.dumps({"text": "질문"}).encode("utf-8"),
        )
        self.assertEqual(status, 502, body)
        payload = json.loads(body)
        self.assertEqual(payload["message"], "provider request failed")
        self.assertEqual(payload["delivery"]["mode"], "api-mediated-base64")
        self.assertNotIn(marker, body)

    def test_avatar_broker_redacts_upstream_provider_failure_markers(self) -> None:
        marker = "UPSTREAM_PROVIDER_DIAGNOSTIC_MARKER"
        self._start_fake_ai_engine({
            "error": "avatar_provider_failed",
            "provider": "spatialreal",
            "message": marker,
            "client": {"sessionToken": marker},
        }, status=502)
        status, body = self._post(
            "/api/interviews/local-demo/avatar/session",
            json.dumps({"reason": "room-join"}).encode("utf-8"),
        )
        self.assertEqual(status, 502, body)
        payload = json.loads(body)
        self.assertEqual(payload["message"], "provider request failed")
        self.assertEqual(payload["delivery"]["mode"], "api-mediated-spatialreal-session")
        self.assertEqual(payload["ready"], False)
        self.assertNotIn(marker, body)
        self.assertNotIn("sessionToken", body)

    def test_avatar_session_route_proxies_ai_engine_without_secret_leak(self) -> None:
        os.environ["SPATIALREAL_API_KEY"] = "secret-spatialreal-key"
        captured = self._start_fake_ai_engine({
            "interviewId": "local-demo",
            "provider": "spatialreal",
            "ready": True,
            "status": "session_issued",
            "client": {
                "appId": "app-123",
                "avatarId": "avatar-456",
                "sessionToken": "sr-session-token",
                "audioFormat": {"channelCount": 1, "sampleRate": 16000, "sampleEncoding": "pcm_s16le"},
            },
        })
        status, body = self._post(
            "/api/interviews/local-demo/avatar/session",
            json.dumps({"reason": "session-created"}).encode("utf-8"),
        )
        self.assertEqual(status, 200, body)
        payload = json.loads(body)
        self.assertEqual(payload["interviewId"], "local-demo")
        self.assertEqual(payload["status"], "session_issued")
        self.assertEqual(payload["delivery"]["mode"], "api-mediated-spatialreal-session")
        client = payload["client"]
        self.assertIn("livekit", client)
        self.assertEqual(client["livekit"]["tokenStatus"], "not_configured")
        self.assertIsNone(client["livekit"]["avatarClientToken"])
        self.assertEqual(captured[0]["path"], "/avatar/session")
        upstream_payload = json.loads(str(captured[0]["body"]))
        self.assertEqual(upstream_payload["interviewId"], "local-demo")
        self.assertNotIn("secret-spatialreal-key", body)
        self.assertNotIn("SPATIALREAL_API_KEY", body)

    def test_avatar_session_route_accepts_caddy_stripped_path_and_bad_id_fails(self) -> None:
        self._start_fake_ai_engine({"provider": "disabled", "ready": False, "status": "disabled", "reason": "avatar_provider_disabled"})
        status, body = self._post("/interviews/local-demo/avatar/session", b"{}")
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["status"], "disabled")

        status, body = self._post("/api/interviews/../avatar/session", b"{}")
        self.assertEqual(status, 404, body)
        self.assertEqual(json.loads(body)["error"], "not_found")

    def test_room_tts_route_proxies_ai_engine_without_secret_leak(self) -> None:
        os.environ["ELEVENLABS_API_KEY"] = "secret-elevenlabs-key"

        class _FakeAiTtsResponse:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args: object) -> None:
                return None
            def read(self) -> bytes:
                return json.dumps({
                    "sessionId": "local-demo",
                    "turnId": "q_local-demo_0001",
                    "status": "ok",
                    "audio": {
                        "provider": "fake",
                        "contentType": "audio/wav",
                        "codec": "wav",
                        "sampleRate": 16000,
                        "channels": 1,
                        "byteLength": 8044,
                        "requestId": "tts_local-demo-q_local-demo_0001-fake",
                        "base64": "UklGRg==",
                    },
                }).encode("utf-8")

        captured = self._start_fake_ai_engine(json.loads(_FakeAiTtsResponse().read().decode("utf-8")))
        status, body = self._post(
            "/api/interviews/local-demo/turns/1/tts",
            json.dumps({"text": "첫 질문입니다."}).encode("utf-8"),
        )
        self.assertEqual(status, 200, body)
        payload = json.loads(body)
        self.assertEqual(payload["interviewId"], "local-demo")
        self.assertEqual(payload["turnIndex"], 1)
        self.assertEqual(payload["audio"]["provider"], "fake")
        self.assertEqual(payload["delivery"], {
            "mode": "api-mediated-base64",
            "source": "ai-engine",
            "publicDirectTtsRoutes": "blocked",
        })
        self.assertEqual(captured[0]["path"], "/tts/synthesize")
        upstream_payload = json.loads(str(captured[0]["body"]))
        self.assertEqual(upstream_payload["sessionId"], "local-demo")
        self.assertEqual(upstream_payload["turnId"], "q_local-demo_0001")
        self.assertNotIn("secret-elevenlabs-key", body)
        self.assertNotIn("ELEVENLABS_API_KEY", body)

    def test_room_tts_route_accepts_caddy_stripped_path(self) -> None:
        class _FakeAiTtsResponse:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args: object) -> None:
                return None
            def read(self) -> bytes:
                return b'{"status":"ok","audio":{"provider":"fake","base64":"UklGRg=="}}'

        self._start_fake_ai_engine(json.loads(_FakeAiTtsResponse().read().decode("utf-8")))
        status, body = self._post(
            "/interviews/local-demo/turns/2/tts",
            json.dumps({"text": "다음 질문입니다."}).encode("utf-8"),
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["turnIndex"], 2)

    def test_room_tts_route_fails_closed_without_text_or_bad_id(self) -> None:
        status, body = self._post("/api/interviews/local-demo/turns/1/tts", b'{"text":""}')
        self.assertEqual(status, 400, body)
        self.assertEqual(json.loads(body)["error"], "missing_text")

        status, body = self._post("/api/interviews/../turns/1/tts", json.dumps({"text": "질문"}).encode("utf-8"))
        self.assertEqual(status, 404, body)
        self.assertEqual(json.loads(body)["error"], "not_found")

    def test_room_tts_route_sanitizes_upstream_network_failure(self) -> None:
        os.environ["ELEVENLABS_API_KEY"] = "secret-elevenlabs-key"
        api_server.AI_ENGINE_INTERNAL_URL = "http://127.0.0.1:9"
        status, body = self._post(
            "/api/interviews/local-demo/turns/1/tts",
            json.dumps({"text": "질문"}).encode("utf-8"),
        )
        self.assertEqual(status, 502, body)
        payload = json.loads(body)
        self.assertEqual(payload["error"], "tts_provider_failed")
        self.assertNotIn("secret-elevenlabs-key", body)

    def test_caddy_keeps_public_tts_blocked_but_allows_api_tts_route(self) -> None:
        caddyfile = (REPO_ROOT / "infra" / "caddy" / "Caddyfile").read_text()
        self.assertIn("@blocked_tts path /tts /tts/* /ai/tts /ai/tts/*", caddyfile)
        self.assertIn("@blocked_avatar path /avatar /avatar/* /ai/avatar /ai/avatar/*", caddyfile)
        self.assertIn("@blocked_ai path /ai /ai/*", caddyfile)
        self.assertLess(caddyfile.index("@blocked_tts"), caddyfile.index("handle_path /api/*"))
        self.assertLess(caddyfile.index("@blocked_avatar"), caddyfile.index("handle_path /api/*"))
        self.assertLess(caddyfile.index("@blocked_ai"), caddyfile.index("handle {"))
        self.assertIn("handle_path /api/*", caddyfile)
        self.assertNotIn("handle_path /ai/*", caddyfile)

    def test_compose_wires_api_to_ai_engine_internal_url(self) -> None:
        compose = (REPO_ROOT / "infra" / "docker-compose.yml").read_text()
        self.assertIn("AI_ENGINE_INTERNAL_URL", compose)
        self.assertIn("http://ai-engine:8100", compose)


if __name__ == "__main__":
    unittest.main()
