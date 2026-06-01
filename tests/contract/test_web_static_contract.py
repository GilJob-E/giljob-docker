from __future__ import annotations

from http.server import ThreadingHTTPServer
import importlib.util
import json
import pathlib
import threading
import unittest
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB_ROOT = REPO_ROOT / "apps" / "web"

spec = importlib.util.spec_from_file_location("giljob_v2_web_server", WEB_ROOT / "server.py")
assert spec is not None and spec.loader is not None
web_server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web_server)


class WebStaticContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web_server.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host = self.server.server_address[0]
        port = self.server.server_address[1]
        self.base_url = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _get(self, path: str) -> tuple[int, str, str]:
        try:
            with urllib.request.urlopen(self.base_url + path, timeout=5) as res:
                return res.status, res.headers.get("Content-Type", ""), res.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers.get("Content-Type", ""), exc.read().decode("utf-8")

    def test_root_serves_landing_page_with_room_link(self) -> None:
        status, content_type, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn("Self-hosted LiveKit", body)
        self.assertIn("session route", body)
        self.assertIn('href="/interviews/new"', body)
        self.assertIn("새 면접 시작", body)
        self.assertNotIn('id="join-form"', body)
        self.assertNotIn('src="/app.js"', body)

    def test_production_interview_routes_serve_static_shells(self) -> None:
        route_expectations = {
            "/interviews/new": ["Production flow · Step 1", "local-demo", "CV upload"],
            "/interviews/prod-demo_01/lobby": ["Production flow · Step 2", "Pre-join lobby", "Device check"],
            "/interviews/prod-demo_01/room": ["production-room-shell", "light-media-room-shell", "room-context-drawer", 'src="/app.js"'],
            "/interviews/prod-demo_01/report": ["Production flow · Step 4", "리포트 placeholder", "Background analysis"],
        }
        for path, expected_strings in route_expectations.items():
            with self.subTest(path=path):
                status, content_type, body = self._get(path)
                self.assertEqual(status, 200)
                self.assertIn("text/html", content_type)
                for expected in expected_strings:
                    self.assertIn(expected, body)

    def test_legacy_interview_room_page_remains_available(self) -> None:
        status, content_type, body = self._get("/interview-room.html")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn("production-room-shell", body)
        self.assertIn('src="/app.js"', body)

    def test_invalid_interview_route_is_rejected(self) -> None:
        status, _, body = self._get("/interviews/%2e%2e/room")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "not_found")

    def test_interview_room_page_is_production_room_not_prejoin(self) -> None:
        status, content_type, body = self._get("/interviews/local-demo/room")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn("production-room-shell", body)
        self.assertIn("light-media-room-shell", body)
        self.assertIn("meet-style-video-stage", body)
        self.assertIn("active-speaker", body)
        self.assertIn("meet-control-dock", body)
        self.assertIn("room-context-drawer", body)
        self.assertIn('hidden aria-hidden="true"', body)
        self.assertIn("Interviewer", body)
        self.assertIn("답변 시작", body)
        self.assertIn('aria-disabled="true"', body)
        self.assertIn("면접관 질문이 끝나면 답변 시작 버튼이 활성화됩니다", body)
        self.assertIn("답변 대기", body)
        self.assertIn("질문 준비 중", body)
        self.assertIn("current-question-title", body)
        self.assertIn("transcript-body", body)
        self.assertIn("interviewer-question-text", body)
        self.assertIn('src="/app.js"', body)
        self.assertIn('data-interview-route="report"', body)
        self.assertIn('id="session-summary"', body)
        self.assertIn('id="event-log"', body)
        self.assertNotIn("room-runtime-bar", body)
        self.assertNotIn("INTERVIEWID", body)
        self.assertNotIn("Self-hosted LiveKit · Interview Room", body)
        self.assertNotIn("이 페이지가 실제 면접룸입니다", body)
        self.assertNotIn("Pre-join checklist", body)
        self.assertNotIn('id="join-form"', body)
        self.assertNotIn('id="join-room"', body)
        self.assertNotIn("Camera preview", body)
        self.assertNotIn('value="/api/sessions"', body)


    def test_interview_context_panel_is_right_sidebar_not_overlay(self) -> None:
        status, content_type, body = self._get("/styles.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", content_type)
        self.assertIn(".room-app-main.is-context-open", body)
        self.assertIn("grid-template-columns: minmax(0, 1fr) minmax(320px, 380px);", body)
        self.assertIn(".room-context-drawer {", body)
        self.assertIn("position: static;", body)
        self.assertNotIn("right: 24px;", body)
        self.assertNotIn("bottom: 24px;", body)

    def test_app_js_uses_browser_public_url_and_hides_tokens_from_log(self) -> None:
        status, content_type, body = self._get("/app.js")
        self.assertEqual(status, 200)
        self.assertIn("text/javascript", content_type)
        self.assertIn("livekit-client.esm.mjs", body)
        self.assertIn("setLogLevel", body)
        self.assertIn('setLogLevel("silent")', body)
        self.assertIn("publicUrl", body)
        self.assertIn("candidateToken", body)
        self.assertIn("tokens hidden", body)
        self.assertIn("function interviewIdFromPath", body)
        self.assertIn("function isProductionRoomPath", body)
        self.assertIn("function autoJoinRoomRoute", body)
        self.assertIn("data-interview-route", body)
        self.assertIn("navigator.mediaDevices", body)
        self.assertIn("setMicrophoneEnabled", body)
        self.assertIn("setCameraEnabled", body)
        self.assertIn("답변 시작", body)
        self.assertIn("답변 종료", body)
        self.assertIn("candidate answer turn", body)
        self.assertIn("giljob:interviewer-question-ended", body)
        self.assertIn("MediaRecorder", body)
        self.assertIn("/stt/transcribe", body)
        self.assertIn("lastAnswer", body)
        self.assertIn("local Whisper STT", body)
        self.assertIn("answer start blocked until interviewer question ends", body)
        self.assertIn("function failClosedAfterJoinMediaError", body)
        self.assertIn("disconnecting room fail-closed", body)
        self.assertIn("Promise.allSettled", body)
        self.assertIn("aria-pressed", body)
        self.assertIn("setContextDrawerOpen", body)
        self.assertIn("toggle-context-drawer", body)
        self.assertIn("aria-expanded", body)
        self.assertIn("function redactSensitiveText", body)
        self.assertIn("access_token=<redacted>", body)
        self.assertIn("join_request=<redacted>", body)
        self.assertIn("<jwt-redacted>", body)
        self.assertIn("redactSensitiveText(message)", body)
        self.assertIn("replaceChildren", body)
        self.assertNotIn("innerHTML", body)
        self.assertNotIn("localStorage", body)

    def test_styles_are_served_and_path_traversal_is_rejected(self) -> None:
        status, content_type, body = self._get("/styles.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", content_type)
        self.assertIn(".status", body)

        status, _, body = self._get("/%2e%2e/services/api/server.py")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "not_found")

    def test_browser_smoke_redacts_sensitive_console_output(self) -> None:
        smoke_script = (REPO_ROOT / "scripts" / "browser-join-smoke.mjs").read_text()
        self.assertIn("/interviews/local-demo/room", smoke_script)
        self.assertIn("function redactSensitiveText", smoke_script)
        self.assertIn("access_token=<redacted>", smoke_script)
        self.assertIn("join_request=<redacted>", smoke_script)
        self.assertIn("<jwt-redacted>", smoke_script)
        self.assertIn("redactSensitiveText(message.text())", smoke_script)
        self.assertIn("redactSensitiveText(error.message)", smoke_script)
        self.assertNotIn("${message.text()}", smoke_script)

    def test_smoke_script_does_not_assert_raw_livekit_payload(self) -> None:
        smoke_script = (REPO_ROOT / "scripts" / "smoke.sh").read_text()
        self.assertIn("invalid LiveKit candidate token shape", smoke_script)
        self.assertNotIn('payload["livekit"]', smoke_script)
        self.assertNotIn('candidateToken"], payload', smoke_script)

    def test_package_declares_exact_livekit_client_dependency(self) -> None:
        package_json = json.loads((WEB_ROOT / "package.json").read_text())
        self.assertEqual(package_json["dependencies"]["livekit-client"], "2.19.1")


if __name__ == "__main__":
    unittest.main()
