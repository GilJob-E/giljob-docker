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

DEFAULT_ANALYSIS_ENGINE_INTERNAL_URL = api_server.ANALYSIS_ENGINE_INTERNAL_URL

LIVEKIT_ENV_NAMES = (
    "LIVEKIT_REQUIRED",
    "LIVEKIT_MEDIA_OVERLAY_ENABLED",
    "LIVEKIT_URL",
    "LIVEKIT_INTERNAL_URL",
    "LIVEKIT_PUBLIC_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "OPENAI_REALTIME_API_BASE",
    "OPENAI_REALTIME_CALL_BROKER_ENABLED",
    "OPENAI_REALTIME_SAFETY_SALT",
    "GEMINI_API_BASE",
    "COACH_GEMINI_API_KEY",
    "COACH_LLM_PROVIDER",
    "COACH_LLM_MODEL",
    "COACH_LLM_TIMEOUT_SECONDS",
    "REALTIME_MMM_EVENT_LOG_PATH",
    "REALTIME_MMM_FORWARD_ENABLED",
    "REALTIME_MMM_RESULT_TIMEOUT_SECONDS",
    "HASHIMOTO_BASE_URL",
    "GILJOBE_VISION",
    "GILJOBE_PROSODY",
    "ELEVENLABS_API_KEY",
    "SPATIALREAL_API_KEY",
    "SPATIALREAL_SDK_MODE_WEB_ENABLED",
    "SPATIALREAL_APP_ID",
    "SPATIALREAL_SESSION_TOKEN",
    "SPATIALREAL_AVATAR_ID",
    "SPATIALREAL_ENVIRONMENT",
    "SPATIALREAL_REGION",
    "SPATIALREAL_CONSOLE_API_HOST",
    "SPATIALREAL_CONSOLE_ENDPOINT",
    "SPATIALREAL_SESSION_TTL_SECONDS",
    "SPATIALREAL_SESSION_TOKEN_TIMEOUT_SECONDS",
    "SPATIALREAL_AUDIO_SAMPLE_RATE",
    "SPATIALREAL_AUDIO_CHANNEL_COUNT",
)


class ApiHttpContractTest(unittest.TestCase):
    def setUp(self) -> None:
        SESSION_HASH_STORE.clear()
        api_server.REALTIME_TURN_STATE.clear()
        api_server.REALTIME_RESPONSE_COMMANDS.clear()
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

    def _get(self, path: str) -> tuple[int, str]:
        try:
            with urllib.request.urlopen(self.base_url + path, timeout=5) as res:
                return res.status, res.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    def _start_fake_spatialreal_console(
        self,
        *,
        status: int = 200,
        response_payload: dict[str, object] | None = None,
    ) -> tuple[str, list[dict[str, object]]]:
        captured: list[dict[str, object]] = []

        class FakeSpatialRealConsoleHandler(BaseHTTPRequestHandler):
            def do_POST(inner_self) -> None:  # noqa: N802 - stdlib callback name
                length = int(inner_self.headers.get("Content-Length", "0") or "0")
                raw = inner_self.rfile.read(length) if length else b""
                captured.append({
                    "method": "POST",
                    "path": inner_self.path,
                    "x_api_key": inner_self.headers.get("X-Api-Key"),
                    "body": raw.decode("utf-8"),
                })
                body = json.dumps(
                    response_payload if response_payload is not None else {
                        "id": "token-record-id",
                        "sessionToken": "browser-safe-spatialreal-session-token",
                        "expireAt": 1893456000,
                    }
                ).encode("utf-8")
                inner_self.send_response(status)
                inner_self.send_header("Content-Type", "application/json")
                inner_self.send_header("Content-Length", str(len(body)))
                inner_self.end_headers()
                inner_self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

        fake_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeSpatialRealConsoleHandler)
        thread = threading.Thread(target=fake_server.serve_forever, daemon=True)
        thread.start()

        def cleanup() -> None:
            fake_server.shutdown()
            fake_server.server_close()
            thread.join(timeout=2)

        self.addCleanup(cleanup)
        host, port = fake_server.server_address
        return f"http://{host}:{port}", captured


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

    def _start_fake_hashimoto_strategy(self, payload: dict[str, object], *, status: int = 200) -> list[dict[str, object]]:
        captured: list[dict[str, object]] = []

        class FakeHashimotoHandler(BaseHTTPRequestHandler):
            def do_GET(inner_self) -> None:  # noqa: N802 - stdlib callback name
                captured.append({
                    "method": "GET",
                    "path": inner_self.path,
                    "body": "",
                })
                body = json.dumps(payload).encode("utf-8")
                inner_self.send_response(status)
                inner_self.send_header("Content-Type", "application/json")
                inner_self.send_header("Content-Length", str(len(body)))
                inner_self.end_headers()
                inner_self.wfile.write(body)

            def log_message(inner_self, format: str, *args: object) -> None:
                return None

        fake_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHashimotoHandler)
        fake_thread = threading.Thread(target=fake_server.serve_forever, daemon=True)
        fake_thread.start()

        def cleanup() -> None:
            fake_server.shutdown()
            fake_server.server_close()
            fake_thread.join(timeout=2)

        self.addCleanup(cleanup)
        host, port = fake_server.server_address
        os.environ["HASHIMOTO_BASE_URL"] = f"http://{host}:{port}"
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

    def test_create_session_realtime_metadata_includes_safe_sdk_mode_sibling(self) -> None:
        status, body = self._post("/api/sessions", b'{"role":"candidate","interviewId":"local-demo"}')
        self.assertEqual(status, 201, body)
        payload = json.loads(body)
        self.assertIn("realtime", payload)
        self.assertIn("avatarSdkMode", payload)
        self.assertNotIn("realtimeAvatarBridge", payload)
        sdk_mode = payload["avatarSdkMode"]

        self.assertEqual(sdk_mode["mode"], "spatialreal-sdk-mode-web")
        self.assertEqual(sdk_mode["transport"], "spatialreal-sdk-websocket")
        self.assertEqual(sdk_mode["status"], "deferred")
        self.assertEqual(sdk_mode["outcome"], "sdk_mode_deferred")
        self.assertFalse(sdk_mode["enabled"])
        self.assertFalse(sdk_mode["livekitRequired"])
        self.assertEqual(sdk_mode["directProviderRoutes"], "blocked")
        self.assertEqual(sdk_mode["requiresFeatureFlag"], "SPATIALREAL_SDK_MODE_WEB_ENABLED")
        self.assertFalse(sdk_mode["providerSecretsExposed"])
        self.assertFalse(sdk_mode["rawMediaExposed"])
        self.assertFalse(sdk_mode["rawTranscriptExposed"])
        self.assertFalse(sdk_mode["defaultEnabled"])
        self.assertTrue(sdk_mode["tokenHidden"])
        self.assertFalse(sdk_mode["rawMediaLogged"])
        self.assertTrue(sdk_mode["requiresKiostationBrowserProof"])
        self.assertEqual(sdk_mode["audioFormat"]["encoding"], "pcm16")
        self.assertEqual(sdk_mode["audioFormat"]["channelCount"], 1)
        self.assertEqual(sdk_mode["audioFormat"]["sampleRateHz"], 16000)
        self.assertEqual(sdk_mode["audioFormat"]["source"], "openai-realtime-output-audio")
        self.assertTrue(sdk_mode["audioFormat"]["mutedUntilVerified"])
        self.assertIn("sdk mode", sdk_mode["description"].lower())
        self.assertIn("sdk_mode_deferred", sdk_mode["blockedOutcome"].lower())

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
            "experimental-openai-realtime-audio-to-avatar",
            "SPATIALREAL_BROWSER_AUDIO_BRIDGE_ENABLED",
            "AvatarPlayer.publishAudio",
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



    def test_api_source_has_no_ai_engine_internal_url_or_upstream_routes(self) -> None:
        source = (REPO_ROOT / "services" / "api" / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("AI_ENGINE_INTERNAL_URL", source)
        self.assertNotIn("/interview/next-question", source)
        self.assertNotIn("/tts/synthesize", source)
        self.assertNotIn('"source": "ai-engine"', source)

    def test_next_question_route_is_deprecated_realtime_only_without_ai_engine_upstream(self) -> None:
        status, body = self._post(
            "/api/interviews/local-demo/turns/1/question",
            json.dumps({"lastAnswer": "아직 이전 답변 없음"}).encode("utf-8"),
        )
        self.assertEqual(status, 410, body)
        payload = json.loads(body)
        self.assertEqual(payload["error"], "deprecated_ai_engine_removed")
        self.assertEqual(payload["reason"], "realtime_only")
        self.assertEqual(payload["interviewId"], "local-demo")
        self.assertEqual(payload["turnIndex"], 1)
        self.assertNotIn("ai-engine", body)
        self.assertNotIn("AI_ENGINE_INTERNAL_URL", body)

    def test_next_question_route_accepts_caddy_stripped_path_as_deprecated_and_bad_id_fails(self) -> None:
        status, body = self._post("/interviews/local-demo/turns/2/question", b"{}")
        self.assertEqual(status, 410, body)
        payload = json.loads(body)
        self.assertEqual(payload["error"], "deprecated_ai_engine_removed")
        self.assertEqual(payload["reason"], "realtime_only")
        self.assertEqual(payload["turnIndex"], 2)

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
            {"type": "analysis.vad.speech_started", "detail": {"audioStartMs": 120, "rawAudioIncluded": False}},
            {"type": "analysis.vad.speech_stopped", "detail": {"audioEndMs": 1780, "rawAudioIncluded": False}},
            {"type": "prosody.window_metrics", "detail": {"energy": 0.3, "rawAudioIncluded": False}},
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

        self.assertEqual([entry["path"] for entry in captured], ["/realtime/turn-events"] * 6)
        forwarded = [json.loads(str(entry["body"])) for entry in captured]
        self.assertEqual([entry["eventKind"] for entry in forwarded], [
            "turn.answer_started",
            "turn.answer_ended",
            "transcript.completed",
            "analysis.vad.speech_started",
            "analysis.vad.speech_stopped",
            "prosody.window_metrics",
        ])
        transcript_forward = forwarded[2]
        self.assertEqual(transcript_forward["source"], "api-sideband")
        self.assertEqual(transcript_forward["sessionId"], "local-demo")
        self.assertFalse(transcript_forward["rawTranscriptLogged"])
        self.assertFalse(transcript_forward["rawMediaAccepted"])
        self.assertEqual(transcript_forward["detail"], {"transcript": "bounded candidate answer", "itemId": "item-1"})
        vad_start_forward = forwarded[3]
        self.assertEqual(vad_start_forward["detail"], {"audioStartMs": 120, "rawAudioIncluded": False})
        vad_stop_forward = forwarded[4]
        self.assertEqual(vad_stop_forward["detail"], {"audioEndMs": 1780, "rawAudioIncluded": False})
        prosody_forward = forwarded[5]
        self.assertEqual(prosody_forward["detail"], {"energy": 0.3, "rawAudioIncluded": False})
        persisted = pathlib.Path(event_log_path).read_text()
        self.assertNotIn("bounded candidate answer", persisted)

    def test_realtime_vision_events_forward_to_analysis_engine(self) -> None:
        captured = self._start_fake_analysis_engine(status=202)
        os.environ["REALTIME_MMM_FORWARD_ENABLED"] = "true"
        os.environ["REALTIME_MMM_EVENT_LOG_PATH"] = "0"
        status, body = self._post(
            "/api/interviews/local-demo/turns/1/vision-events",
            json.dumps({
                "type": "vision.frame_metrics",
                "detail": {
                    "visionSignals": {"cameraEnabled": True, "faceVisible": True, "frameAvailable": True},
                    "visionFrame": {
                        "schemaVersion": "2026-06-13.internal-vision-frame.v1",
                        "encoding": "image/jpeg;base64",
                        "width": 2,
                        "height": 2,
                        "byteLength": 4,
                        "data": "ZmFrZQ==",
                    },
                },
            }).encode("utf-8"),
        )
        self.assertEqual(status, 202, body)
        payload = json.loads(body)
        self.assertTrue(payload["internalVisionFrameForwarded"])
        self.assertTrue(payload["ingress"]["analysisEngine"]["attempted"])
        self.assertEqual(captured[0]["path"], "/realtime/turn-events")
        forwarded = json.loads(str(captured[0]["body"]))
        self.assertEqual(forwarded["eventKind"], "vision.frame_metrics")
        self.assertEqual(forwarded["sourceRoute"], "vision-events")
        self.assertTrue(forwarded["detail"]["visionSignals"]["faceVisible"])
        self.assertEqual(forwarded["detail"]["visionFrame"]["encoding"], "image/jpeg;base64")
        self.assertEqual(forwarded["detail"]["visionFrame"]["data"], "ZmFrZQ==")
        self.assertNotIn("visionFrame", payload)

    def test_coach_feedback_reads_exact_turn_result_without_exposing_raw_analysis(self) -> None:
        analysis = self._start_fake_analysis_engine(result_payload={
            "result": {
                "schemaVersion": "2026-06-13.rnas-turn-result.v2",
                "status": "ready",
                "sessionId": "local-demo",
                "turnIndex": 1,
                "confidence": 0.86,
                "latencyMs": 412,
                "candidatePromptFragment": "raw transcript must not leak",
                "candidateSafePromptFragment": {
                    "text": "다음 답변에서는 프로젝트 맥락과 본인 기여를 더 구체적으로 확인하세요.",
                    "containsRawTranscript": False,
                    "containsRawMedia": False,
                },
                "transcriptSignals": {"status": "sentence_observed", "specificityScore": 0.58},
                "visionSignals": {"status": "frame_observed", "faceVisible": True},
                "prosodySignals": {"status": "timing_observed", "speechDurationMs": 1660},
                "behavioralSignals": {"engagement": "steady"},
                "coverage": {"speech": 6, "visual": 8, "nv": 8},
                "rawTranscriptLogged": False,
                "rawMediaAccepted": False,
            }
        })

        status, body = self._get("/api/interviews/local-demo/turns/1/coach-feedback")

        self.assertEqual(status, 200, body)
        payload = json.loads(body)
        self.assertEqual(payload["interviewId"], "local-demo")
        self.assertEqual(payload["turnIndex"], 1)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["delivery"]["mode"], "api-mediated-coach-feedback")
        self.assertEqual(payload["delivery"]["analysisEndpoint"], "/realtime/turn-results")
        self.assertFalse(payload["delivery"]["rawAnalysisReturned"])
        self.assertTrue(payload["coachFeedback"]["ready"])
        self.assertIn("summary", payload["coachFeedback"])
        self.assertIn("answerEvaluation", payload["coachFeedback"])
        self.assertIn("multimodalEvaluation", payload["coachFeedback"])
        self.assertIsInstance(payload["coachFeedback"]["bullets"], list)
        self.assertEqual(payload["coachLlm"]["provider"], "fake")
        self.assertEqual(payload["coachLlm"]["providerStatus"], "fake")
        self.assertEqual(payload["coachLlm"]["model"], "fake-coach")
        self.assertEqual(payload["analysis"]["endpoint"], "/realtime/turn-results")
        self.assertEqual(payload["analysis"]["resultStatus"], "ready")
        self.assertEqual(payload["analysis"]["coverage"], {"nv": 8, "speech": 6, "visual": 8})
        self.assertEqual(analysis[-1]["method"], "GET")
        self.assertIn("/realtime/turn-results?interviewId=local-demo&turnIndex=1", analysis[-1]["path"])
        self.assertNotIn('"candidatePromptFragment":', body)
        self.assertNotIn("raw transcript must not leak", body)
        self.assertNotIn("candidateSafePromptFragment", body)
        self.assertNotIn("ai-engine", body)

    def test_coach_feedback_is_pending_until_exact_turn_result_is_ready(self) -> None:
        captured = self._start_fake_analysis_engine(result_payload={
            "result": {
                "status": "pending",
                "sessionId": "local-demo",
                "turnIndex": 1,
            }
        })

        status, body = self._get("/api/interviews/local-demo/turns/1/coach-feedback")

        self.assertEqual(status, 202, body)
        payload = json.loads(body)
        self.assertEqual(payload["status"], "pending")
        self.assertFalse(payload["coachFeedback"]["ready"])
        self.assertEqual(payload["coachFeedback"]["reason"], "analysis_result_not_ready")
        self.assertFalse(payload["coachLlm"]["attempted"])
        self.assertEqual(payload["analysis"]["endpoint"], "/realtime/turn-results")
        self.assertEqual(captured[-1]["method"], "GET")
        self.assertIn("/realtime/turn-results?interviewId=local-demo&turnIndex=1", captured[-1]["path"])
        self.assertNotIn('"candidatePromptFragment":', body)

    def test_coach_feedback_rejects_wrong_turn_result_as_pending(self) -> None:
        self._start_fake_analysis_engine(result_payload={
            "result": {
                "status": "ready",
                "sessionId": "local-demo",
                "turnIndex": 2,
                "candidateSafePromptFragment": {"text": "다른 턴 결과입니다."},
                "rawTranscriptLogged": False,
                "rawMediaAccepted": False,
            }
        })

        status, body = self._get("/api/interviews/local-demo/turns/1/coach-feedback")

        self.assertEqual(status, 202, body)
        payload = json.loads(body)
        self.assertEqual(payload["status"], "pending")
        self.assertEqual(payload["coachFeedback"]["reason"], "exact_turn_analysis_result_required")
        self.assertFalse(payload["coachLlm"]["attempted"])
        self.assertNotIn("다른 턴 결과입니다", body)

    def test_gemini_coach_feedback_calls_provider_without_key_or_raw_leak(self) -> None:
        os.environ["COACH_LLM_PROVIDER"] = "gemini"
        os.environ["COACH_LLM_MODEL"] = "gemini-test-model"
        os.environ["COACH_GEMINI_API_KEY"] = "secret-gemini-key"
        captured: list[urllib.request.Request] = []

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps({
                    "candidates": [{
                        "content": {
                            "parts": [{
                                "text": json.dumps({
                                    "summary": "멀티모달 신호를 함께 본 코칭입니다.",
                                    "answerEvaluation": "답변은 구체성이 조금 더 필요합니다.",
                                    "multimodalEvaluation": "시선과 발화 흐름은 안정적입니다.",
                                    "bullets": ["핵심 성과를 수치로 덧붙이세요."],
                                })
                            }]
                        }
                    }]
                }).encode("utf-8")

        def fake_urlopen(request: urllib.request.Request, timeout: float = 0) -> FakeResponse:
            captured.append(request)
            self.assertIn("generativelanguage.googleapis.com", request.full_url)
            upstream_body = request.data.decode("utf-8")
            self.assertIn("다음 답변에서는 근거를 확인하세요.", upstream_body)
            self.assertNotIn("raw transcript must not leak", upstream_body)
            return FakeResponse()

        result = {
            "schemaVersion": "2026-06-13.rnas-turn-result.v2",
            "status": "ready",
            "sessionId": "local-demo",
            "turnIndex": 1,
            "candidatePromptFragment": "raw transcript must not leak",
            "candidateSafePromptFragment": {
                "text": "다음 답변에서는 근거를 확인하세요.",
                "containsRawTranscript": False,
                "containsRawMedia": False,
            },
            "coverage": {"speech": 6, "visual": 8, "nv": 8},
            "rawTranscriptLogged": False,
            "rawMediaAccepted": False,
        }

        with patch("server.urllib.request.urlopen", side_effect=fake_urlopen):
            status, payload = api_server._gemini_coach_feedback(api_server._coach_llm_settings(), result, "local-demo", 1)

        self.assertEqual(status, 200)
        self.assertEqual(payload["provider"], "gemini")
        self.assertEqual(payload["providerStatus"], "provider")
        self.assertEqual(payload["model"], "gemini-test-model")
        self.assertEqual(payload["coachFeedback"]["summary"], "멀티모달 신호를 함께 본 코칭입니다.")
        self.assertEqual(captured[0].headers.get("X-goog-api-key"), "secret-gemini-key")
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("secret-gemini-key", serialized)
        self.assertNotIn("raw transcript must not leak", serialized)


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

    def test_realtime_response_create_merges_exact_hashimoto_strategy_guidance(self) -> None:
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
                "text": "Ask one concise follow-up about production ownership.",
                "containsRawTranscript": False,
                "containsRawMedia": False,
                "containsSecrets": False,
            },
            "rawTranscriptLogged": False,
            "rawMediaAccepted": False,
        })
        hashimoto = self._start_fake_hashimoto_strategy({
            "ready": True,
            "session_id": "local-demo",
            "as_of_turn_id": "turn_0001",
            "session_complete": False,
            "interaction_strategy": {
                "logic_goal": "Confirm the candidate personally owned a production incident.",
                "logical_gap_to_bridge": "The prior answer did not explain the decision criteria.",
                "interviewer_persona_guidance": {
                    "intent": "Ask for one concrete incident.",
                    "focus_point": "Their role, decision, and tradeoff.",
                    "emotion_direction": "Calm and specific.",
                },
                "current_context": {
                    "topic": "production operations",
                    "depth_level": 2,
                    "topic_changed": False,
                    "transition_hint": "Stay on the same topic for one deeper question.",
                    "resolved_history": [
                        {"proposition": "They used FastAPI", "status": "covered"},
                    ],
                },
            },
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
        instructions = payload["sideband"]["command"]["response"]["instructions"]
        self.assertIn("Ask one concise follow-up about production ownership.", instructions)
        self.assertIn("Confirm the candidate personally owned a production incident.", instructions)
        self.assertIn("Their role, decision, and tradeoff.", instructions)
        self.assertEqual(payload["hashimotoStrategy"]["used"], True)
        self.assertEqual(payload["hashimotoStrategy"]["asOfTurnId"], "turn_0001")
        self.assertEqual(payload["hashimotoStrategy"]["expectedTurnId"], "turn_0001")
        self.assertEqual(payload["hashimotoStrategy"]["sessionComplete"], False)
        self.assertEqual(hashimoto[-1]["method"], "GET")
        self.assertIn("/strategy", hashimoto[-1]["path"])
        self.assertIn("session_id=local-demo", hashimoto[-1]["path"])

    def test_realtime_response_create_ignores_stale_hashimoto_strategy(self) -> None:
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
                "text": "Ask from the analysis fragment only.",
                "containsRawTranscript": False,
                "containsRawMedia": False,
                "containsSecrets": False,
            },
            "rawTranscriptLogged": False,
            "rawMediaAccepted": False,
        })
        self._start_fake_hashimoto_strategy({
            "ready": True,
            "session_id": "local-demo",
            "as_of_turn_id": "turn_0000",
            "session_complete": False,
            "interaction_strategy": {
                "logic_goal": "STALE_STRATEGY_MUST_NOT_APPEAR",
            },
        })

        self._post("/api/interviews/local-demo/turns/1/events", json.dumps({"type": "turn.answer_ended", "detail": {"transcriptAvailable": True}}).encode("utf-8"))
        self._post("/api/interviews/local-demo/turns/1/events", json.dumps({"type": "transcript.completed", "transcript": "bounded candidate answer"}).encode("utf-8"))
        status, body = self._post("/api/interviews/local-demo/turns/2/realtime/response", b"{}")
        self.assertEqual(status, 202, body)
        payload = json.loads(body)
        instructions = payload["sideband"]["command"]["response"]["instructions"]
        self.assertIn("Ask from the analysis fragment only.", instructions)
        self.assertNotIn("STALE_STRATEGY_MUST_NOT_APPEAR", instructions)
        self.assertEqual(payload["hashimotoStrategy"]["used"], False)
        self.assertEqual(payload["hashimotoStrategy"]["reason"], "turn_mismatch")
        self.assertEqual(payload["hashimotoStrategy"]["asOfTurnId"], "turn_0000")
        self.assertEqual(payload["hashimotoStrategy"]["expectedTurnId"], "turn_0001")

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


    def test_legacy_question_route_does_not_expose_provider_failure_markers(self) -> None:
        marker = "UPSTREAM_PROVIDER_DIAGNOSTIC_MARKER"
        status, body = self._post(
            "/api/interviews/local-demo/turns/1/question",
            json.dumps({"lastAnswer": marker}).encode("utf-8"),
        )
        self.assertEqual(status, 410, body)
        payload = json.loads(body)
        self.assertEqual(payload["error"], "deprecated_ai_engine_removed")
        self.assertEqual(payload["reason"], "realtime_only")
        self.assertNotIn(marker, body)
        self.assertNotIn("ai-engine", body)

    def test_legacy_tts_route_is_deprecated_realtime_only_without_ai_engine_upstream(self) -> None:
        status, body = self._post(
            "/api/interviews/local-demo/turns/1/tts",
            json.dumps({"text": "첫 질문입니다."}).encode("utf-8"),
        )
        self.assertEqual(status, 410, body)
        payload = json.loads(body)
        self.assertEqual(payload["error"], "deprecated_ai_engine_removed")
        self.assertEqual(payload["reason"], "realtime_only")
        self.assertEqual(payload["interviewId"], "local-demo")
        self.assertEqual(payload["turnIndex"], 1)
        self.assertNotIn("ai-engine", body)
        self.assertNotIn("AI_ENGINE_INTERNAL_URL", body)

    def test_avatar_session_route_is_api_owned_or_disabled_never_ai_engine_sourced(self) -> None:
        os.environ["SPATIALREAL_API_KEY"] = "secret-spatialreal-key"
        status, body = self._post(
            "/api/interviews/local-demo/avatar/session",
            json.dumps({"reason": "session-created"}).encode("utf-8"),
        )
        self.assertIn(status, {200, 202, 410}, body)
        payload = json.loads(body)
        self.assertEqual(payload["interviewId"], "local-demo")
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("secret-spatialreal-key", serialized)
        self.assertNotIn("SPATIALREAL_API_KEY", serialized)
        self.assertNotIn("ai-engine", serialized)
        delivery = payload.get("delivery")
        if isinstance(delivery, dict):
            self.assertNotEqual(delivery.get("source"), "ai-engine")
        self.assertIn("sdkMode", payload)
        self.assertNotIn("bridge", payload)
        self.assertNotIn("client", payload)
        for forbidden_livekit_field in ("avatarClientToken", "livekitUrl", "url", "roomName", "participantIdentity"):
            with self.subTest(forbidden_livekit_field=forbidden_livekit_field):
                self.assertNotIn(forbidden_livekit_field, serialized)
        sdk_mode = payload["sdkMode"]
        self.assertEqual(sdk_mode["mode"], "spatialreal-sdk-mode-web")
        self.assertEqual(sdk_mode["transport"], "spatialreal-sdk-websocket")
        self.assertFalse(sdk_mode["livekitRequired"])
        self.assertEqual(sdk_mode["requiresFeatureFlag"], "SPATIALREAL_SDK_MODE_WEB_ENABLED")
        self.assertEqual(sdk_mode["outcome"], "sdk_mode_deferred")
        self.assertFalse(sdk_mode["providerSecretsExposed"])
        self.assertFalse(sdk_mode["rawMediaExposed"])
        self.assertFalse(sdk_mode["rawTranscriptExposed"])
        self.assertFalse(sdk_mode["defaultEnabled"])
        self.assertTrue(sdk_mode["tokenHidden"])
        self.assertFalse(sdk_mode["rawMediaLogged"])
        self.assertTrue(sdk_mode["requiresKiostationBrowserProof"])
        self.assertEqual(sdk_mode["audioFormat"]["encoding"], "pcm16")
        self.assertEqual(sdk_mode["audioFormat"]["channelCount"], 1)
        self.assertEqual(sdk_mode["audioFormat"]["sampleRateHz"], 16000)
        self.assertEqual(sdk_mode["audioFormat"]["source"], "openai-realtime-output-audio")
        self.assertTrue(sdk_mode["audioFormat"]["mutedUntilVerified"])
        self.assertIn("sdk mode", sdk_mode["description"].lower())
        self.assertIn("sdk_mode_deferred", sdk_mode["blockedOutcome"].lower())
        if payload.get("error") == "deprecated_ai_engine_removed":
            self.assertEqual(payload.get("reason"), "realtime_only")
        else:
            self.assertIn(payload.get("status"), {"disabled", "deferred", "session_issued", "not_configured"})

    def test_avatar_session_sdk_enabled_configured_returns_ready_client_metadata_without_livekit(self) -> None:
        os.environ["SPATIALREAL_SDK_MODE_WEB_ENABLED"] = "true"
        os.environ["SPATIALREAL_APP_ID"] = "public-app-id-for-browser"
        os.environ["SPATIALREAL_SESSION_TOKEN"] = "short-lived-spatialreal-session-token"
        os.environ["SPATIALREAL_AVATAR_ID"] = "avatar-demo-01"
        os.environ["SPATIALREAL_AUDIO_SAMPLE_RATE"] = "16000"
        os.environ["SPATIALREAL_AUDIO_CHANNEL_COUNT"] = "1"

        status, body = self._post(
            "/api/interviews/local-demo/avatar/session",
            json.dumps({"reason": "sdk-ready-contract"}).encode("utf-8"),
        )
        self.assertEqual(status, 200, body)
        payload = json.loads(body)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["provider"], "spatialreal")
        self.assertIn("client", payload)
        self.assertIn("sdkMode", payload)
        self.assertIn("spatialrealSdk", payload["client"])

        sdk_mode = payload["sdkMode"]
        self.assertTrue(sdk_mode["enabled"])
        self.assertEqual(sdk_mode["mode"], "spatialreal-sdk-mode-web")
        self.assertEqual(sdk_mode["transport"], "spatialreal-sdk-websocket")
        self.assertFalse(sdk_mode["livekitRequired"])
        self.assertFalse(sdk_mode["providerSecretsExposed"])
        self.assertFalse(sdk_mode["rawMediaLogged"])

        client_sdk = payload["client"]["spatialrealSdk"]
        self.assertEqual(client_sdk["appId"], "public-app-id-for-browser")
        self.assertEqual(client_sdk["sessionToken"], "short-lived-spatialreal-session-token")
        self.assertEqual(client_sdk["avatarId"], "avatar-demo-01")
        self.assertEqual(client_sdk["audioFormat"], {"encoding": "pcm16", "channelCount": 1, "sampleRateHz": 16000})

        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        for forbidden_livekit_field in ("avatarClientToken", "candidateToken", "livekitUrl", "url", "roomName", "participantIdentity"):
            with self.subTest(forbidden_livekit_field=forbidden_livekit_field):
                self.assertNotIn(forbidden_livekit_field, serialized)
        self.assertNotIn("SPATIALREAL_API_KEY", serialized)
        self.assertNotIn("LIVEKIT_API_SECRET", serialized)

    def test_avatar_session_sdk_enabled_brokers_short_lived_token_with_server_api_key(self) -> None:
        console_base_url, captured = self._start_fake_spatialreal_console()
        os.environ["SPATIALREAL_SDK_MODE_WEB_ENABLED"] = "true"
        os.environ["SPATIALREAL_API_KEY"] = "secret-spatialreal-api-key"
        os.environ["SPATIALREAL_APP_ID"] = "public-app-id-for-browser"
        os.environ["SPATIALREAL_AVATAR_ID"] = "avatar-demo-01"
        os.environ["SPATIALREAL_CONSOLE_API_HOST"] = console_base_url
        os.environ["SPATIALREAL_SESSION_TTL_SECONDS"] = "600"

        status, body = self._post(
            "/api/interviews/local-demo/avatar/session",
            json.dumps({"reason": "sdk-ready-api-key-broker-contract"}).encode("utf-8"),
        )

        self.assertEqual(status, 200, body)
        payload = json.loads(body)
        client_sdk = payload["client"]["spatialrealSdk"]
        self.assertEqual(client_sdk["appId"], "public-app-id-for-browser")
        self.assertEqual(client_sdk["avatarId"], "avatar-demo-01")
        self.assertEqual(client_sdk["sessionToken"], "browser-safe-spatialreal-session-token")
        self.assertEqual(client_sdk["sessionTokenExpiresAt"], 1893456000)
        self.assertEqual(client_sdk["tokenPolicy"], "api-key-brokered-single-use-session-token")
        self.assertEqual(client_sdk["tokenSource"], "server-side-spatialreal-api-key")
        self.assertEqual(client_sdk["consoleRegion"], "ap-northeast")
        self.assertFalse(payload["sdkMode"]["livekitRequired"])

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["path"], "/v1/console/session-tokens")
        self.assertEqual(captured[0]["x_api_key"], "secret-spatialreal-api-key")
        token_request = json.loads(str(captured[0]["body"]))
        self.assertIsInstance(token_request["expireAt"], int)

        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("secret-spatialreal-api-key", serialized)
        self.assertNotIn("SPATIALREAL_API_KEY", serialized)
        self.assertNotIn("AvatarKit RTC", serialized)
        self.assertNotIn("livekitUrl", serialized)

    def test_avatar_session_sdk_enabled_api_key_broker_failure_is_redacted(self) -> None:
        console_base_url, _captured = self._start_fake_spatialreal_console(
            status=401,
            response_payload={"error": "invalid_api_key", "message": "secret-spatialreal-api-key"},
        )
        os.environ["SPATIALREAL_SDK_MODE_WEB_ENABLED"] = "true"
        os.environ["SPATIALREAL_API_KEY"] = "secret-spatialreal-api-key"
        os.environ["SPATIALREAL_APP_ID"] = "public-app-id-for-browser"
        os.environ["SPATIALREAL_AVATAR_ID"] = "avatar-demo-01"
        os.environ["SPATIALREAL_CONSOLE_API_HOST"] = console_base_url

        status, body = self._post("/api/interviews/local-demo/avatar/session", b"{}")

        self.assertEqual(status, 502, body)
        payload = json.loads(body)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "spatialreal_session_token_http_401")
        self.assertEqual(payload["sdkMode"]["outcome"], "sdk_mode_blocked_provider_token_broker")
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("secret-spatialreal-api-key", serialized)
        self.assertNotIn("invalid_api_key", serialized)
        self.assertNotIn("SPATIALREAL_API_KEY", serialized)

    def test_sdk_enabled_avatar_metadata_does_not_bypass_full_mmm_gate(self) -> None:
        os.environ["SPATIALREAL_SDK_MODE_WEB_ENABLED"] = "true"
        os.environ["SPATIALREAL_APP_ID"] = "public-app-id-for-browser"
        os.environ["SPATIALREAL_SESSION_TOKEN"] = "short-lived-spatialreal-session-token"
        os.environ["SPATIALREAL_AVATAR_ID"] = "avatar-demo-01"

        avatar_status, avatar_body = self._post("/api/interviews/local-demo/avatar/session", b"{}")
        self.assertIn(avatar_status, {200, 202}, avatar_body)
        status, body = self._post(
            "/api/interviews/local-demo/turns/2/realtime/response",
            json.dumps({"reason": "sdk-enabled-followup"}).encode("utf-8"),
        )
        self.assertEqual(status, 409, body)
        payload = json.loads(body)
        self.assertEqual(payload["responseCreate"]["owner"], "api")
        self.assertFalse(payload["responseCreate"]["created"])
        self.assertIn(
            payload["responseCreate"]["reason"],
            {"full_mmm_required_for_prior_answer", "structured_analysis_required"},
        )
        self.assertNotIn("avatar", json.dumps(payload, ensure_ascii=False).lower())

    def test_avatar_session_route_accepts_caddy_stripped_path_and_bad_id_fails(self) -> None:
        status, body = self._post("/interviews/local-demo/avatar/session", b"{}")
        self.assertIn(status, {200, 202, 410}, body)
        payload = json.loads(body)
        self.assertEqual(payload["interviewId"], "local-demo")
        self.assertNotIn("ai-engine", body)

        status, body = self._post("/api/interviews/../avatar/session", b"{}")
        self.assertEqual(status, 404, body)
        self.assertEqual(json.loads(body)["error"], "not_found")

    def test_room_tts_route_accepts_caddy_stripped_path_as_deprecated(self) -> None:
        status, body = self._post(
            "/interviews/local-demo/turns/2/tts",
            json.dumps({"text": "다음 질문입니다."}).encode("utf-8"),
        )
        self.assertEqual(status, 410, body)
        payload = json.loads(body)
        self.assertEqual(payload["error"], "deprecated_ai_engine_removed")
        self.assertEqual(payload["reason"], "realtime_only")
        self.assertEqual(payload["turnIndex"], 2)

    def test_room_tts_route_fails_closed_for_bad_id_before_deprecated_response(self) -> None:
        status, body = self._post("/api/interviews/../turns/1/tts", json.dumps({"text": "질문"}).encode("utf-8"))
        self.assertEqual(status, 404, body)
        self.assertEqual(json.loads(body)["error"], "not_found")

    def test_room_tts_route_does_not_depend_on_upstream_network(self) -> None:
        with patch("server.urllib.request.urlopen", side_effect=AssertionError("legacy ai-engine upstream must not be called")):
            status, payload = api_server.synthesize_room_tts("local-demo", 1, {"text": "질문"})
        self.assertEqual(status, 410)
        self.assertEqual(payload["error"], "deprecated_ai_engine_removed")
        self.assertEqual(payload["reason"], "realtime_only")

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

    def test_compose_removes_ai_engine_and_keeps_analysis_engine_internal_url(self) -> None:
        compose = (REPO_ROOT / "infra" / "docker-compose.yml").read_text()
        self.assertNotIn("AI_ENGINE_INTERNAL_URL", compose)
        self.assertNotIn("http://ai-engine:8100", compose)
        self.assertNotIn("ai-engine:", compose)
        self.assertIn("ANALYSIS_ENGINE_INTERNAL_URL", compose)
        self.assertIn("http://analysis-engine:8200", compose)
        for sdk_env_name in (
            "SPATIALREAL_SDK_MODE_WEB_ENABLED",
            "SPATIALREAL_API_KEY",
            "SPATIALREAL_APP_ID",
            "SPATIALREAL_AVATAR_ID",
            "SPATIALREAL_SESSION_TOKEN",
            "SPATIALREAL_ENVIRONMENT",
            "SPATIALREAL_REGION",
            "SPATIALREAL_CONSOLE_API_HOST",
            "SPATIALREAL_CONSOLE_ENDPOINT",
            "SPATIALREAL_SESSION_TTL_SECONDS",
            "SPATIALREAL_SESSION_TOKEN_TIMEOUT_SECONDS",
        ):
            with self.subTest(sdk_env_name=sdk_env_name):
                self.assertIn(f"{sdk_env_name}: ${{{sdk_env_name}", compose)
        self.assertNotIn("SPATIALREAL_BROWSER_AUDIO_BRIDGE_ENABLED", compose)


if __name__ == "__main__":
    unittest.main()
