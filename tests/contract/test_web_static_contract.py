from __future__ import annotations

from http.server import ThreadingHTTPServer
import importlib.util
import json
import pathlib
import tempfile
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
            "/interviews/prod-demo_01/room": ["production-room-shell", "light-media-room-shell", "room-context-drawer", "avatar-surface", 'src="/app.js"'],
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
        self.assertIn("coach-feedback-title", body)
        self.assertIn("coach-feedback-body", body)
        self.assertIn("coach-feedback-list", body)
        self.assertIn("Coach feedback", body)
        self.assertIn('class="feedback-panel-region"', body)
        self.assertIn('class="question-answer-panel-region"', body)
        self.assertLess(body.index('class="panel-card coach-card"'), body.index('class="question-answer-panel-region"'))
        self.assertLess(body.index('id="current-question-title"'), body.index('id="transcript-body"'))
        self.assertIn("mmm-debug-summary", body)
        self.assertIn("Operator MMM debug", body)
        self.assertIn("readiness/response", body)
        self.assertIn("interviewer-question-text", body)
        self.assertIn("avatar-surface", body)
        self.assertIn("avatar-status-text", body)
        self.assertIn("avatar-panel-body", body)
        self.assertIn("interviewer-audio", body)
        self.assertIn("SpatialReal Avatar", body)
        self.assertIn('type="importmap"', body)
        self.assertIn('"livekit-client": "/vendor/livekit-client/dist/livekit-client.esm.mjs"', body)
        self.assertIn('"@spatialwalk/avatarkit": "/vendor/@spatialwalk/avatarkit/dist/index.js"', body)
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
        self.assertIn("#transcript-body {", body)
        self.assertIn("max-height: min(36vh, 420px);", body)
        self.assertRegex(body, r"\.drawer-panel-stack\s*\{[^}]*grid-template-rows: minmax\(0, 1fr\) minmax\(0, 2fr\);")
        self.assertRegex(body, r"\.question-answer-panel-region\s*\{[^}]*overflow-y: auto;")
        self.assertIn("#current-question-body,\n#transcript-body,\n#coach-feedback-body,\n.coach-feedback-list", body)
        self.assertIn(".mmm-debug-summary {", body)
        self.assertIn("max-height: min(34vh, 360px);", body)
        self.assertIn(".room-debug-drawer details {", body)
        self.assertIn("overscroll-behavior: contain;", body)
        self.assertNotIn("right: 24px;", body)
        self.assertNotIn("bottom: 24px;", body)

    def test_app_js_default_room_is_livekit_free_and_hides_tokens_from_log(self) -> None:
        status, content_type, body = self._get("/app.js")
        self.assertEqual(status, 200)
        self.assertIn("text/javascript", content_type)

        # Default interview path is Realtime + API sideband MMM. It must not join
        # LiveKit or instantiate AvatarKit RTC before Realtime can start.
        forbidden_default_livekit_shapes = [
            "livekit-client.esm.mjs",
            "@spatialwalk/avatarkit-rtc",
            'setLogLevel("silent")',
            "function autoJoinRoomRoute",
            "function sessionLiveKitConfig",
            "function joinRoom",
            "new Room",
            "activeRoom.connect",
            "candidateToken",
            "avatarClientToken",
            "new LiveKitProvider",
            "new AvatarPlayer",
            "DrivingServiceMode.host",
            "publishAudio",
            "unpublishAudio",
            "Avatar RTC media muted",
        ]
        for forbidden in forbidden_default_livekit_shapes:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, body)

        self.assertIn("function interviewIdFromPath", body)
        self.assertIn("function isProductionRoomPath", body)
        self.assertIn("data-interview-route", body)
        self.assertIn("navigator.mediaDevices", body)
        self.assertIn("setMicrophoneEnabled", body)
        self.assertIn("setCameraEnabled", body)
        self.assertIn("답변 시작", body)
        self.assertIn("답변 종료", body)
        self.assertIn("candidate answer turn", body)
        self.assertIn("giljob:interviewer-question-ended", body)
        self.assertIn("lastAnswer", body)
        self.assertIn("function renderCoachFeedback", body)
        self.assertIn("function requestCoachFeedback", body)
        self.assertIn("/api/interviews/${encodeURIComponent(activeInterviewId)}/turns/${turnIndex}/coach-feedback", body)
        self.assertIn("requestCoachFeedback(completedTurnIndex)", body)
        self.assertIn("coach feedback unavailable", body)
        self.assertIn("coach feedback pending", body)
        self.assertIn("candidate-answer-ended-browser-clean-boundary", body)
        self.assertIn("API sideband", body)
        self.assertIn("browser analysis control disabled", body)
        self.assertIn("const mmmDebugSummary", body)
        self.assertIn("function renderMmmDebug", body)
        self.assertIn("isForbiddenDebugKey", body)
        self.assertIn("/mmm-ready", body)
        self.assertIn("/realtime/response", body)
        self.assertIn("analysisResult.confidence", body)
        self.assertIn("analysisEngine.endpoint", body)
        self.assertIn("captureInternalVisionFrame", body)
        self.assertIn("visionFrame", body)
        self.assertIn("internalVisionFrameIncluded", body)
        self.assertIn("raw media not logged", body)
        self.assertIn("LiveKit-free Realtime main path", body)
        self.assertIn("Avatar disabled/deferred", body)
        self.assertIn("SpatialReal SDK Mode", body)

        # Browser must relay API-owned Realtime commands and never author prompts,
        # provider calls, or analysis workers itself.
        self.assertNotIn("subscriber", body)
        self.assertNotIn("/analysis/subscriber", body)
        self.assertNotIn("/subscriber/start", body)
        self.assertNotIn("/subscriber/stop", body)
        self.assertNotIn("/analysis/signals", body)
        self.assertNotIn("function startRealtimeAnalysisTurn", body)
        self.assertNotIn("function flushRealtimeAnalysisTurn", body)
        self.assertNotIn("function sendRealtimeTranscriptToConversation", body)
        self.assertNotIn("conversation.item.create", body)
        self.assertNotIn("Realtime transcript injected into conversation context", body)
        self.assertNotIn("/ai/interview/next-question", body)
        self.assertIn("function playInterviewerQuestion", body)
        self.assertIn("function markInterviewerQuestionEnded", body)
        self.assertIn("/api/interviews/${encodeURIComponent(activeInterviewId)}/turns/${turnIndex}/realtime/response", body)
        self.assertNotIn("/realtime-response", body)
        self.assertIn("Realtime WebRTC SDP attached through API call broker", body)
        self.assertIn("sendRealtimePostConnectSessionUpdate", body)
        self.assertIn("function relayApiApprovedRealtimeCommand", body)
        self.assertIn("browser-data-channel-relay", body)
        self.assertIn("browser did not author prompt", body)
        self.assertIn("Realtime STT/VAD session.update sent after WebRTC attach", body)
        self.assertIn("Keep the OpenAI Realtime offer to a single audio m-section", body)
        self.assertIn("peerConnection.addTrack(track, localStream)", body)
        self.assertNotIn('peerConnection.addTransceiver("audio", { direction: "recvonly" })', body)
        self.assertIn("interviewerAudio.play", body)
        self.assertIn("audio hidden", body)
        self.assertNotIn("candidate-answer-ended-no-stt", body)
        self.assertNotIn("/stt/", body)
        self.assertIn("answer start blocked until interviewer question ends", body)
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
        self.assertNotIn("SPATIALREAL_API_KEY", body)
        self.assertNotIn("OPENAI_API_KEY", body)
        self.assertNotIn("client_secret.value", body)
        self.assertNotIn("/ai/tts", body)
        self.assertNotIn("/tts/synthesize", body)
        self.assertIn("deprecated_ai_engine_removed", body)
        self.assertIn("realtime_only", body)
        self.assertIn("no legacy ai-engine fallback", body)

    def test_app_js_gates_spatialreal_sdk_mode_without_livekit_rtc(self) -> None:
        status, content_type, body = self._get("/app.js")
        self.assertEqual(status, 200)
        self.assertIn("text/javascript", content_type)

        # Any avatar spike must be non-default SDK Mode Web, not the previous
        # AvatarKit RTC/LiveKit bridge. It remains disabled/deferred unless an
        # explicit SDK Mode feature flag is enabled, but must accept API-owned
        # sdk_mode_ready metadata once the token broker succeeds.
        self.assertIn("SPATIALREAL_SDK_MODE_WEB_ENABLED", body)
        self.assertIn("sdk_mode_deferred", body)
        self.assertIn("sdk_mode_ready", body)
        self.assertIn("SPATIALREAL_SDK_ACCEPTED_OUTCOMES", body)
        self.assertIn("Avatar disabled/deferred", body)
        self.assertIn("providerSecretsExposed === false", body)
        self.assertNotIn("sdkMode.outcome === SPATIALREAL_SDK_MODE_OUTCOME", body)
        self.assertIn("rawMediaExposed === false", body)
        self.assertNotIn("experimental-openai-realtime-audio-to-avatar", body)
        self.assertNotIn("SPATIALREAL_BROWSER_AUDIO_BRIDGE_ENABLED", body)
        self.assertNotIn("AvatarPlayer.publishAudio", body)
        self.assertNotIn("publishAudio(track", body)
        self.assertNotIn("LiveKitProvider", body)
        self.assertNotIn("livekit-client", body)

        forbidden_bridge_shapes = [
            "SPATIALREAL_API_KEY",
            "OPENAI_API_KEY",
            "server_secret",
            "raw offer",
            "raw media bytes",
            "raw transcript",
            "MediaRecorder",
        ]
        for forbidden in forbidden_bridge_shapes:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, body)

    def test_app_js_contains_actual_spatialreal_sdk_activation_and_pcm_bridge_contract(self) -> None:
        body = (WEB_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        required_activation_markers = [
            'import("@spatialwalk/avatarkit")',
            "AvatarSDK.initialize",
            "AvatarSDK.setSessionToken",
            "AvatarManager.shared.load",
            "new sdk.AvatarView",
            "AVATAR_SDK_SYNCED_PLAYBACK_VOLUME",
            "setAvatarSdkPlaybackVolume",
            "Realtime direct audio output",
            "controller.send",
            "PCM16",
            "sendAvatarSdkPcmChunk(controller, pcm, false)",
            "response.done",
            "function avatarSdkBeginResponseFeed",
            "function avatarSdkEndResponseFeed",
            "AVATAR_PCM_END_GRACE_MS",
            "avatar SDK PCM chunk",
            "avatarSdkResponseFeedActive",
            "interviewer-audio-element-capture",
            "realtime-remote-track-pre-output",
            "spatialreal-sdk-synced-playback",
            "waiting for Realtime response feed",
            "PCM feed opens when SDK is ready and silence is gated until speech",
            "first question waits for avatar session readiness check",
            "waiting for SDK init before first Realtime question",
            "waiting for SDK connection before first Realtime question",
            "avatar SDK PCM silence dropped before speech",
            "AVATAR_PCM_SPEECH_RMS_THRESHOLD",
        ]
        for marker in required_activation_markers:
            with self.subTest(marker=marker):
                self.assertIn(marker, body)

        safe_blocked_reasons = [
            "sdk_flag_disabled",
            "spatialreal_config_missing",
            "sdk_mode_blocked_missing_vendor_asset",
            "sdk_mode_blocked_wasm_mime",
            "sdk_mode_blocked_dynamic_import",
            "sdk_mode_blocked_double_audio_or_mute",
            "sdk_mode_blocked_pcm_feed_setup_failed",
            "sdk_mode_blocked_pcm_send_failed",
        ]
        for reason in safe_blocked_reasons:
            with self.subTest(reason=reason):
                self.assertIn(reason, body)

        self.assertIn("waitForFullMmmReady", body)
        self.assertIn("avatarSdkPcmStats", body)
        self.assertIn("avatar SDK response feed grace", body)
        self.assertIn("avatar SDK PCM bridge idle during response feed", body)
        self.assertIn("Realtime remote audio track observed for interviewer playback; avatar SDK PCM16 adapter waits for response feed", body)
        self.assertIn("SpatialReal SDK owns audible playback for lip-sync", body)
        self.assertIn("Realtime direct audio muted for lip-sync", body)
        self.assertIn("avatar SDK response feed active from", body)
        self.assertIn("realtime-connected-avatar-checked", body)
        self.assertIn("avatar SDK connection wait before first Realtime question", body)
        self.assertNotIn("avatarSdkBeginResponseFeed();", body)
        self.assertNotIn("PCM feed waits for Realtime audio delta", body)
        self.assertLess(body.index("waitForFullMmmReady"), body.index("requestRealtimeNextQuestion"))
        self.assertNotIn("AvatarPlayer.publishAudio", body)
        self.assertNotIn("SPATIALREAL_BROWSER_AUDIO_BRIDGE_ENABLED", body)

    def test_app_js_realtime_lifecycle_order_matrix_is_explicit(self) -> None:
        body = (WEB_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        order_pairs = [
            ("remoteStream.addTrack(event.track)", "captureRealtimeRemoteAudioTrack(event.track)"),
            ("remoteStream.addTrack(event.track)", "attachRealtimeRemoteAudio(remoteStream)"),
            ("response.done", "markInterviewerQuestionEnded"),
            ('markInterviewerQuestionEnded({ provider: "openai-realtime"', "avatarSdkEndResponseFeed(responseId)"),
            ("disconnectRealtimeRoom", "realtimeRemoteAudioTrack = null"),
        ]
        for before, after in order_pairs:
            with self.subTest(before=before, after=after):
                self.assertIn(before, body)
                self.assertIn(after, body)
                self.assertLess(body.index(before), body.rindex(after))

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

    def test_package_keeps_livekit_and_avatarkit_rtc_out_of_default_dependencies(self) -> None:
        package_json = json.loads((WEB_ROOT / "package.json").read_text())
        dependencies = package_json.get("dependencies", {})
        optional_dependencies = package_json.get("optionalDependencies", {})
        self.assertNotIn("livekit-client", dependencies)
        self.assertNotIn("@spatialwalk/avatarkit-rtc", dependencies)
        # Non-LiveKit SDK Mode Web may keep the base AvatarKit package, but RTC stays optional/legacy-only.
        if "@spatialwalk/avatarkit" in dependencies:
            self.assertIn("SPATIALREAL_SDK_MODE_WEB_ENABLED", (WEB_ROOT / "static" / "app.js").read_text(encoding="utf-8"))
        self.assertNotIn("livekit-client", optional_dependencies)
        self.assertNotIn("@spatialwalk/avatarkit-rtc", optional_dependencies)

    def test_web_dockerfile_does_not_vendor_livekit_rtc_assets_for_default_path(self) -> None:
        dockerfile = (WEB_ROOT / "Dockerfile").read_text()
        self.assertNotIn("node_modules/livekit-client/dist", dockerfile)
        self.assertNotIn("node_modules/@spatialwalk/avatarkit-rtc/dist", dockerfile)
        if "node_modules/@spatialwalk/avatarkit/dist" in dockerfile:
            self.assertIn("SPATIALREAL_SDK_MODE_WEB_ENABLED", (WEB_ROOT / "static" / "app.js").read_text(encoding="utf-8"))

    def test_web_server_serves_only_allowed_spatialreal_sdk_vendor_assets_with_safe_mime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            node_modules_root = pathlib.Path(tmp_dir)
            sdk_dist = node_modules_root / "@spatialwalk" / "avatarkit" / "dist"
            sdk_dist.mkdir(parents=True)
            (sdk_dist / "index.js").write_text("export const SpatialRealAvatarKit = {};\n", encoding="utf-8")
            (sdk_dist / "worker.mjs").write_text("export default {};\n", encoding="utf-8")
            (sdk_dist / "avatar.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00")
            (node_modules_root / "@spatialwalk" / "avatarkit" / "package.json").write_text("{}", encoding="utf-8")

            original_node_modules_root = web_server.NODE_MODULES_ROOT
            web_server.NODE_MODULES_ROOT = node_modules_root.resolve()
            try:
                expected_assets = {
                    "/vendor/@spatialwalk/avatarkit/dist/index.js": "text/javascript",
                    "/vendor/@spatialwalk/avatarkit/dist/worker.mjs": "text/javascript",
                    "/vendor/@spatialwalk/avatarkit/dist/avatar.wasm": "application/wasm",
                }
                for path, expected_content_type in expected_assets.items():
                    with self.subTest(path=path):
                        status, content_type, body = self._get(path)
                        self.assertEqual(status, 200)
                        self.assertIn(expected_content_type, content_type)
                        if path.endswith(".wasm"):
                            self.assertNotIn("text/javascript", content_type)
                        else:
                            self.assertIn("export", body)

                rejected_paths = [
                    "/vendor/@spatialwalk/avatarkit/package.json",
                    "/vendor/@spatialwalk/avatarkit-rtc/dist/index.js",
                    "/vendor/livekit-client/dist/livekit-client.esm.mjs",
                ]
                for path in rejected_paths:
                    with self.subTest(path=path):
                        status, content_type, body = self._get(path)
                        self.assertEqual(status, 404)
                        self.assertIn("application/json", content_type)
                        self.assertEqual(json.loads(body)["error"], "not_found")
            finally:
                web_server.NODE_MODULES_ROOT = original_node_modules_root

    def test_spatialreal_sdk_importmap_and_docs_keep_vendor_scope_explicit(self) -> None:
        room_html = (WEB_ROOT / "static" / "interview-room.html").read_text(encoding="utf-8")
        web_readme = (WEB_ROOT / "README.md").read_text(encoding="utf-8")
        verification_runbook = (REPO_ROOT / "docs" / "runbooks" / "verification.md").read_text(encoding="utf-8")
        env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

        self.assertIn('"@spatialwalk/avatarkit": "/vendor/@spatialwalk/avatarkit/dist/index.js"', room_html)
        self.assertNotIn('"@spatialwalk/avatarkit-rtc"', room_html)
        self.assertIn("allowed SDK vendor path", web_readme)
        self.assertIn("application/wasm", web_readme)
        self.assertIn("vendor/WASM/MIME contract", verification_runbook)
        self.assertIn("npm --prefix apps/web ci", verification_runbook)
        self.assertIn("SPATIALREAL_SDK_MODE_WEB_ENABLED=false", env_example)
        self.assertIn("browser SDK assets are public static files only", env_example)

    def test_web_server_does_not_serve_legacy_livekit_rtc_vendor_assets(self) -> None:
        status, content_type, body = self._get("/vendor/@spatialwalk/avatarkit-rtc/dist/index.js")
        self.assertEqual(status, 404)
        self.assertIn("application/json", content_type)
        self.assertEqual(json.loads(body)["error"], "not_found")

        status, content_type, body = self._get("/vendor/livekit-client/dist/livekit-client.esm.mjs")
        self.assertEqual(status, 404)
        self.assertIn("application/json", content_type)
        self.assertEqual(json.loads(body)["error"], "not_found")


if __name__ == "__main__":
    unittest.main()
