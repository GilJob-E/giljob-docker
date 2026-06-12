from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pathlib
import sys
import threading
import unittest
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
    "LIVEKIT_URL",
    "LIVEKIT_INTERNAL_URL",
    "LIVEKIT_PUBLIC_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "AI_ENGINE_INTERNAL_URL",
    "REALTIME_MMM_EVENT_LOG_PATH",
    "REALTIME_MMM_FORWARD_ENABLED",
    "GILJOBE_VISION",
    "GILJOBE_PROSODY",
    "ELEVENLABS_API_KEY",
    "SPATIALREAL_API_KEY",
)


class ApiHttpContractTest(unittest.TestCase):
    def setUp(self) -> None:
        SESSION_HASH_STORE.clear()
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

    def _start_fake_analysis_engine(self, *, status: int = 202) -> list[dict[str, object]]:
        captured: list[dict[str, object]] = []

        class FakeAnalysisEngineHandler(BaseHTTPRequestHandler):
            def do_POST(inner_self) -> None:  # noqa: N802 - stdlib callback name
                length = int(inner_self.headers.get("Content-Length", "0") or "0")
                raw = inner_self.rfile.read(length) if length else b""
                captured.append({
                    "path": inner_self.path,
                    "body": raw.decode("utf-8"),
                })
                body = b'{"accepted":true}'
                inner_self.send_response(status)
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
                self.assertEqual(public["livekit"]["deferredReason"], "livekit_credentials_missing")
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

    def test_realtime_turn_events_forward_sanitized_mmm_record_to_analysis_engine_by_default(self) -> None:
        captured = self._start_fake_analysis_engine(status=202)
        os.environ["REALTIME_MMM_FORWARD_ENABLED"] = "true"
        os.environ["REALTIME_MMM_EVENT_LOG_PATH"] = "0"
        os.environ["GILJOBE_VISION"] = "off"
        os.environ["GILJOBE_PROSODY"] = "off"

        status, body = self._post(
            "/api/interviews/local-demo/turns/1/events",
            json.dumps({
                "type": "transcript.completed",
                "transcript": "bounded candidate answer",
                "detail": {"transcript": "bounded candidate answer"},
            }).encode("utf-8"),
        )
        self.assertEqual(status, 202, body)
        payload = json.loads(body)
        self.assertTrue(payload["ingress"]["analysisEngine"]["attempted"])
        self.assertEqual(payload["ingress"]["analysisEngine"]["status"], 202)
        self.assertEqual(payload["ingress"]["analysisEngine"]["endpoint"], "/realtime/turn-events")
        self.assertEqual(captured[0]["path"], "/realtime/turn-events")
        forwarded = json.loads(str(captured[0]["body"]))
        self.assertEqual(forwarded["source"], "api-sideband")
        self.assertEqual(forwarded["sessionId"], "local-demo")
        self.assertFalse(forwarded["rawTranscriptLogged"])
        self.assertFalse(forwarded["rawMediaAccepted"])
        self.assertNotIn("bounded candidate answer", captured[0]["body"])


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
