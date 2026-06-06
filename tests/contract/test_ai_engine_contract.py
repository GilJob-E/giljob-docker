from __future__ import annotations

from http.server import ThreadingHTTPServer
import base64
import io
import importlib.util
import json
import os
import pathlib
import sys
import threading
import unittest
import urllib.error
import urllib.request
from typing import cast
from unittest.mock import patch

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
AI_ENGINE_ROOT = REPO_ROOT / "services" / "ai-engine"

spec = importlib.util.spec_from_file_location("giljob_v2_ai_engine_server", AI_ENGINE_ROOT / "server.py")
assert spec is not None and spec.loader is not None
ai_engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ai_engine
spec.loader.exec_module(ai_engine)

LLM_ENV_NAMES = (
    "LLM_PROVIDER",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_TIMEOUT_SECONDS",
    "VOICE_PROVIDER",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_VOICE_ID",
    "ELEVENLABS_TTS_MODEL",
    "ELEVENLABS_OUTPUT_FORMAT",
    "GEMINI_TTS_MODEL",
    "GEMINI_TTS_VOICE",
    "TTS_PROVIDER_FAILURE_FALLBACK",
    "AVATAR_PROVIDER",
    "SPATIALREAL_API_KEY",
    "SPATIALREAL_APP_ID",
    "SPATIALREAL_AVATAR_ID",
    "SPATIALREAL_CONSOLE_ENDPOINT",
    "SPATIALREAL_INGRESS_ENDPOINT",
    "SPATIALREAL_REGION",
    "SPATIALREAL_SESSION_TTL_SECONDS",
    "AVATAR_PROVIDER_FAILURE_FALLBACK",
    "SPATIALREAL_AUDIO_SAMPLE_RATE",
    "SPATIALREAL_AUDIO_CHANNEL_COUNT",
    "SPATIALREAL_RTC_EGRESS_ENABLED",
    "SPATIALREAL_RTC_LIVEKIT_URL",
    "SPATIALREAL_RTC_PUBLISHER_ID_PREFIX",
    "SPATIALREAL_RTC_IDLE_TIMEOUT_SECONDS",
    "SPATIALREAL_RTC_SETTLE_SECONDS",
    "LIVEKIT_PUBLIC_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
)


def restore_env(old_env: dict[str, str | None]) -> None:
    for name, value in old_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


class _FakeResponse:
    status = 200

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps({
            "candidates": [
                {"content": {"parts": [{"text": "지원한 직무와 가장 연결되는 프로젝트 하나를 설명해 주세요."}]}}
            ]
        }).encode("utf-8")


class AIEngineContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self._old_env = {name: os.environ.get(name) for name in LLM_ENV_NAMES}
        for name in self._old_env:
            os.environ.pop(name, None)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ai_engine.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host = self.server.server_address[0]
        port = self.server.server_address[1]
        self.base_url = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        restore_env(self._old_env)

    def _post(self, path: str, payload: dict[str, object]) -> tuple[int, dict[str, object], str]:
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                body = res.read().decode("utf-8")
                return res.status, json.loads(body), body
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            return exc.code, json.loads(body), body

    def test_health_reports_llm_contract_without_key_value(self) -> None:
        os.environ["LLM_PROVIDER"] = "gemini"
        os.environ["GEMINI_API_KEY"] = "test-key-should-not-leak"
        os.environ["GEMINI_MODEL"] = "gemini-3.5-flash"
        with urllib.request.urlopen(self.base_url + "/healthz", timeout=5) as res:
            body = res.read().decode("utf-8")
        payload = json.loads(body)
        self.assertEqual(payload["llmProvider"], "gemini")
        self.assertEqual(payload["geminiModel"], "gemini-3.5-flash")
        self.assertEqual(payload["geminiKeyConfigured"], True)
        self.assertNotIn("test-key-should-not-leak", body)
        self.assertIn("voiceProvider", payload)
        self.assertIn("geminiTtsKeyConfigured", payload)
        self.assertIn("geminiTtsModel", payload)
        self.assertIn("geminiTtsVoice", payload)
        self.assertIn("avatarProvider", payload)
        self.assertIn("spatialRealAudioFormat", payload)
        self.assertNotIn("ELEVENLABS_API_KEY", body)
        self.assertNotIn("SPATIALREAL_API_KEY", body)

    def test_fake_tts_provider_returns_audio_metadata_without_secrets(self) -> None:
        os.environ["VOICE_PROVIDER"] = "fake"
        status, payload, body = self._post("/tts/synthesize", {
            "sessionId": "local-demo",
            "turnId": "q-local-demo-0001",
            "text": "다음 질문을 시작하겠습니다.",
        })
        self.assertEqual(status, 200, body)
        audio = payload["audio"]
        self.assertIsInstance(audio, dict)
        audio_payload = cast(dict[str, object], audio)
        self.assertEqual(audio_payload["provider"], "fake")
        self.assertEqual(audio_payload["contentType"], "audio/wav")
        self.assertEqual(audio_payload["codec"], "wav")
        self.assertEqual(audio_payload["sampleRate"], 16000)
        self.assertEqual(audio_payload["channels"], 1)
        byte_length = audio_payload["byteLength"]
        self.assertIsInstance(byte_length, int)
        byte_length_int = cast(int, byte_length)
        self.assertGreater(byte_length_int, 44)
        self.assertIn("base64", audio_payload)
        self.assertNotIn("ELEVENLABS_API_KEY", body)
        self.assertNotIn("secret", body.lower())

    def test_gemini_tts_call_uses_official_generate_content_audio_contract_without_key_leak(self) -> None:
        os.environ["VOICE_PROVIDER"] = "gemini"
        os.environ["GEMINI_API_KEY"] = "secret-gemini-key"
        os.environ["GEMINI_TTS_MODEL"] = "gemini-3.1-flash-tts-preview"
        os.environ["GEMINI_TTS_VOICE"] = "Kore"
        pcm = b"\x00\x00" * 240

        class _GeminiAudioResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args: object) -> None:
                return None
            def read(self) -> bytes:
                return json.dumps({
                    "candidates": [{
                        "content": {
                            "parts": [{
                                "inlineData": {
                                    "mimeType": "audio/L16;rate=24000",
                                    "data": base64.b64encode(pcm).decode("ascii"),
                                }
                            }]
                        }
                    }]
                }).encode("utf-8")

        with patch.object(ai_engine.urllib.request, "urlopen", return_value=_GeminiAudioResponse()) as mocked:
            status, payload = ai_engine.tts_response({"sessionId": "local-demo", "turnId": "q1", "text": "질문입니다."})
        body = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(status, 200, body)
        audio = payload["audio"]
        self.assertIsInstance(audio, dict)
        audio_payload = cast(dict[str, object], audio)
        self.assertEqual(audio_payload["provider"], "gemini")
        self.assertEqual(audio_payload["contentType"], "audio/wav")
        self.assertEqual(audio_payload["codec"], "wav")
        self.assertEqual(audio_payload["sampleRate"], 24000)
        self.assertEqual(audio_payload["channels"], 1)
        self.assertEqual(audio_payload["model"], "gemini-3.1-flash-tts-preview")
        self.assertEqual(audio_payload["voiceName"], "Kore")
        self.assertGreater(cast(int, audio_payload["byteLength"]), len(pcm))
        request = mocked.call_args.args[0]
        self.assertIn("models/gemini-3.1-flash-tts-preview:generateContent", request.full_url)
        self.assertEqual(request.headers["X-goog-api-key"], "secret-gemini-key")
        request_body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request_body["generationConfig"]["responseModalities"], ["AUDIO"])
        voice_config = request_body["generationConfig"]["speechConfig"]["voiceConfig"]
        self.assertEqual(voice_config["prebuiltVoiceConfig"]["voiceName"], "Kore")
        self.assertNotIn("secret-gemini-key", body)

    def test_gemini_tts_provider_failure_can_fallback_to_fake_for_room_ux(self) -> None:
        os.environ["VOICE_PROVIDER"] = "gemini"
        os.environ["GEMINI_API_KEY"] = "secret-gemini-key"
        os.environ["GEMINI_TTS_MODEL"] = "gemini-3.1-flash-tts-preview"
        os.environ["GEMINI_TTS_VOICE"] = "Kore"
        os.environ["TTS_PROVIDER_FAILURE_FALLBACK"] = "fake"
        gemini_error = urllib.error.HTTPError(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-tts-preview:generateContent",
            429,
            "Too Many Requests",
            {},
            io.BytesIO(b'{"detail":"provider quota marker"}'),
        )
        with patch.object(ai_engine.urllib.request, "urlopen", side_effect=gemini_error):
            status, payload = ai_engine.tts_response({"sessionId": "local-demo", "turnId": "q1", "text": "질문입니다."})
        body = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(status, 200, body)
        self.assertEqual(payload["providerStatus"], "fallback")
        audio = cast(dict[str, object], payload["audio"])
        self.assertEqual(audio["provider"], "fake")
        self.assertEqual(audio["fallbackFrom"], "gemini")
        self.assertNotIn("secret-gemini-key", body)
        self.assertNotIn("provider quota marker", body)

    def test_elevenlabs_tts_fails_closed_without_key_or_voice(self) -> None:
        os.environ["VOICE_PROVIDER"] = "elevenlabs"
        status, payload, body = self._post("/tts/synthesize", {
            "sessionId": "local-demo",
            "turnId": "q-local-demo-0001",
            "text": "다음 질문을 시작하겠습니다.",
        })
        self.assertEqual(status, 503, body)
        self.assertEqual(payload["error"], "tts_provider_unavailable")
        self.assertEqual(payload["provider"], "elevenlabs")
        self.assertNotIn("ELEVENLABS_API_KEY", body)

    def test_elevenlabs_tts_call_uses_official_endpoint_without_key_leak(self) -> None:
        os.environ["VOICE_PROVIDER"] = "elevenlabs"
        os.environ["ELEVENLABS_API_KEY"] = "secret-elevenlabs-key"
        os.environ["ELEVENLABS_VOICE_ID"] = "voice-123"
        os.environ["ELEVENLABS_TTS_MODEL"] = "eleven_flash_v2_5"
        os.environ["ELEVENLABS_OUTPUT_FORMAT"] = "mp3_22050_32"

        class _AudioResponse:
            headers = {"Content-Type": "audio/mpeg"}
            def __enter__(self):
                return self
            def __exit__(self, *args: object) -> None:
                return None
            def read(self) -> bytes:
                return b"fake-mp3-bytes"

        with patch.object(ai_engine.urllib.request, "urlopen", return_value=_AudioResponse()) as mocked:
            status, payload = ai_engine.tts_response({"sessionId": "local-demo", "turnId": "q1", "text": "질문입니다."})
        body = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(status, 200, body)
        audio = payload["audio"]
        self.assertIsInstance(audio, dict)
        audio_payload = cast(dict[str, object], audio)
        self.assertEqual(audio_payload["provider"], "elevenlabs")
        self.assertEqual(audio_payload["codec"], "mp3")
        self.assertEqual(audio_payload["sampleRate"], 22050)
        self.assertEqual(audio_payload["byteLength"], len(b"fake-mp3-bytes"))
        request = mocked.call_args.args[0]
        self.assertIn("/v1/text-to-speech/voice-123", request.full_url)
        self.assertIn("output_format=mp3_22050_32", request.full_url)
        self.assertEqual(request.headers["Xi-api-key"], "secret-elevenlabs-key")
        self.assertNotIn("secret-elevenlabs-key", body)

    def test_elevenlabs_tts_network_failure_fails_closed_without_key_leak(self) -> None:
        os.environ["VOICE_PROVIDER"] = "elevenlabs"
        os.environ["ELEVENLABS_API_KEY"] = "secret-elevenlabs-key"
        os.environ["ELEVENLABS_VOICE_ID"] = "voice-123"

        with patch.object(
            ai_engine.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("timed out"),
        ):
            status, payload = ai_engine.tts_response({"sessionId": "local-demo", "turnId": "q1", "text": "질문입니다."})
        body = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(status, 502, body)
        self.assertEqual(payload["error"], "tts_provider_failed")
        self.assertEqual(payload["provider"], "elevenlabs")
        self.assertNotIn("secret-elevenlabs-key", body)


    def test_elevenlabs_provider_failure_can_fallback_to_fake_for_room_ux(self) -> None:
        os.environ["VOICE_PROVIDER"] = "elevenlabs"
        os.environ["ELEVENLABS_API_KEY"] = "secret-elevenlabs-key"
        os.environ["ELEVENLABS_VOICE_ID"] = "voice-123"
        os.environ["TTS_PROVIDER_FAILURE_FALLBACK"] = "fake"

        with patch.object(
            ai_engine.urllib.request,
            "urlopen",
            side_effect=urllib.error.HTTPError(
                "https://api.elevenlabs.io/v1/text-to-speech/voice-123",
                402,
                "Payment Required",
                {},
                io.BytesIO(b'{"detail":"provider quota marker"}'),
            ),
        ):
            status, payload = ai_engine.tts_response({"sessionId": "local-demo", "turnId": "q1", "text": "질문입니다."})
        body = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(status, 200, body)
        self.assertEqual(payload["providerStatus"], "fallback")
        audio = cast(dict[str, object], payload["audio"])
        self.assertEqual(audio["provider"], "fake")
        self.assertEqual(audio["fallbackFrom"], "elevenlabs")
        self.assertNotIn("secret-elevenlabs-key", body)
        self.assertNotIn("provider quota marker", body)



    def test_provider_http_errors_do_not_expose_upstream_bodies(self) -> None:
        marker = "UPSTREAM_PROVIDER_DIAGNOSTIC_MARKER"

        os.environ["LLM_PROVIDER"] = "gemini"
        os.environ["GEMINI_API_KEY"] = "secret-gemini-key"
        os.environ["GEMINI_MODEL"] = "gemini-3.5-flash"
        gemini_error = urllib.error.HTTPError(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent",
            429,
            "Too Many Requests",
            {},
            io.BytesIO(f'{{"error":"{marker}","key":"secret-gemini-key"}}'.encode()),
        )
        with patch.object(ai_engine.urllib.request, "urlopen", side_effect=gemini_error):
            status, payload = ai_engine.question_response({"interviewId": "local-demo", "turnIndex": 1})
        body = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(status, 502, body)
        self.assertEqual(payload["message"], "provider request failed")
        self.assertNotIn(marker, body)
        self.assertNotIn("secret-gemini-key", body)

        os.environ["VOICE_PROVIDER"] = "elevenlabs"
        os.environ["ELEVENLABS_API_KEY"] = "secret-elevenlabs-key"
        os.environ["ELEVENLABS_VOICE_ID"] = "voice-123"
        eleven_error = urllib.error.HTTPError(
            "https://api.elevenlabs.io/v1/text-to-speech/voice-123",
            500,
            "Provider Error",
            {},
            io.BytesIO(f'{{"detail":"{marker}","key":"secret-elevenlabs-key"}}'.encode()),
        )
        with patch.object(ai_engine.urllib.request, "urlopen", side_effect=eleven_error):
            status, payload = ai_engine.tts_response({"sessionId": "local-demo", "turnId": "q1", "text": "질문입니다."})
        body = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(status, 502, body)
        self.assertEqual(payload["message"], "provider request failed")
        self.assertNotIn(marker, body)
        self.assertNotIn("secret-elevenlabs-key", body)

        os.environ["AVATAR_PROVIDER"] = "spatialreal"
        os.environ["SPATIALREAL_API_KEY"] = "secret-spatialreal-key"
        os.environ["SPATIALREAL_APP_ID"] = "app-123"
        spatial_error = urllib.error.HTTPError(
            "https://console.ap-northeast.spatialwalk.cloud/v1/console/session-tokens",
            500,
            "Provider Error",
            {},
            io.BytesIO(f'{{"detail":"{marker}","key":"secret-spatialreal-key"}}'.encode()),
        )
        with patch.object(ai_engine.urllib.request, "urlopen", side_effect=spatial_error):
            status, payload = ai_engine.avatar_session_response({"interviewId": "local-demo"})
        body = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(status, 502, body)
        self.assertEqual(payload["message"], "provider request failed")
        self.assertNotIn(marker, body)
        self.assertNotIn("secret-spatialreal-key", body)

    def test_avatar_session_disabled_degrades_cleanly_without_key(self) -> None:
        os.environ["AVATAR_PROVIDER"] = "disabled"
        status, payload, body = self._post("/avatar/session", {"interviewId": "local-demo"})
        self.assertEqual(status, 200, body)
        self.assertEqual(payload["status"], "disabled")
        self.assertEqual(payload["reason"], "avatar_provider_disabled")
        self.assertEqual(payload["ready"], False)
        self.assertNotIn("SPATIALREAL_API_KEY", body)
        self.assertNotIn("sessionToken", body)

    def test_spatialreal_avatar_fails_closed_without_key_or_app(self) -> None:
        os.environ["AVATAR_PROVIDER"] = "spatialreal"
        status, payload, body = self._post("/avatar/session", {"interviewId": "local-demo"})
        self.assertEqual(status, 503, body)
        self.assertEqual(payload["error"], "avatar_provider_unavailable")
        self.assertEqual(payload["provider"], "spatialreal")
        self.assertEqual(payload["reason"], "missing_api_key_or_app_id")
        self.assertNotIn("SPATIALREAL_API_KEY", body)

    def test_spatialreal_provider_failure_can_fallback_to_disabled_for_room_ux(self) -> None:
        os.environ["AVATAR_PROVIDER"] = "spatialreal"
        os.environ["SPATIALREAL_API_KEY"] = "secret-spatialreal-key"
        os.environ["SPATIALREAL_APP_ID"] = "app-123"
        os.environ["AVATAR_PROVIDER_FAILURE_FALLBACK"] = "disabled"
        spatial_error = urllib.error.HTTPError(
            "https://console.ap-northeast.spatialwalk.cloud/v1/console/session-tokens",
            402,
            "Payment Required",
            {},
            io.BytesIO(b'{"detail":"provider quota marker"}'),
        )
        with patch.object(ai_engine.urllib.request, "urlopen", side_effect=spatial_error):
            status, payload = ai_engine.avatar_session_response({"interviewId": "local-demo"})
        body = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(status, 200, body)
        self.assertEqual(payload["providerStatus"], "fallback")
        self.assertEqual(payload["fallbackFrom"], "spatialreal")
        self.assertEqual(payload["status"], "disabled")
        self.assertEqual(payload["ready"], False)
        self.assertNotIn("secret-spatialreal-key", body)
        self.assertNotIn("provider quota marker", body)


    def test_spatialreal_avatar_uses_official_session_token_endpoint_without_key_leak(self) -> None:
        os.environ["AVATAR_PROVIDER"] = "spatialreal"
        os.environ["SPATIALREAL_API_KEY"] = "secret-spatialreal-key"
        os.environ["SPATIALREAL_APP_ID"] = "app-123"
        os.environ["SPATIALREAL_AVATAR_ID"] = "avatar-456"
        os.environ["SPATIALREAL_CONSOLE_ENDPOINT"] = "https://console.ap-northeast.spatialwalk.cloud"
        os.environ["SPATIALREAL_SESSION_TTL_SECONDS"] = "900"

        class _SpatialRealResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args: object) -> None:
                return None
            def read(self) -> bytes:
                return b'{"sessionToken":"sr-session-token"}'

        with patch.object(ai_engine.urllib.request, "urlopen", return_value=_SpatialRealResponse()) as mocked:
            status, payload = ai_engine.avatar_session_response({"interviewId": "local-demo"})
        body = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(status, 200, body)
        self.assertEqual(payload["status"], "session_issued")
        self.assertEqual(payload["provider"], "spatialreal")
        client = cast(dict[str, object], payload["client"])
        self.assertEqual(client["appId"], "app-123")
        self.assertEqual(client["avatarId"], "avatar-456")
        self.assertEqual(client["sessionToken"], "sr-session-token")
        audio_format = cast(dict[str, object], client["audioFormat"])
        self.assertEqual(audio_format["channelCount"], 1)
        self.assertEqual(audio_format["sampleRate"], 16000)
        self.assertEqual(client["drivingServiceMode"], "host")
        request = mocked.call_args.args[0]
        self.assertEqual(request.full_url, "https://console.ap-northeast.spatialwalk.cloud/v1/console/session-tokens")
        self.assertEqual(request.headers["X-api-key"], "secret-spatialreal-key")
        self.assertEqual(request.headers.get("User-agent") or request.headers.get("User-Agent"), "GilJobV2/0.1 (+server-mediated-avatar-token)")
        self.assertEqual(request.headers.get("Accept"), "application/json")
        request_body = json.loads(request.data.decode("utf-8"))
        self.assertIn("expireAt", request_body)
        self.assertNotIn("secret-spatialreal-key", body)

    def test_fake_provider_returns_manual_answer_turn_contract(self) -> None:
        os.environ["LLM_PROVIDER"] = "fake"
        status, payload, body = self._post("/interview/next-question", {"interviewId": "local-demo", "turnIndex": 1})
        self.assertEqual(status, 200)
        self.assertEqual(payload["provider"], "fake")
        self.assertEqual(payload["answerTurn"], {
            "boundary": "manual_button",
            "enableEvent": "giljob:interviewer-question-ended",
            "startLabel": "답변 시작",
            "endLabel": "답변 종료",
        })
        self.assertIn("question", payload)
        self.assertNotIn("GEMINI_API_KEY", body)

    def test_gemini_provider_calls_generate_content_without_leaking_key(self) -> None:
        os.environ["LLM_PROVIDER"] = "gemini"
        os.environ["GEMINI_API_KEY"] = "secret-gemini-key"
        os.environ["GEMINI_MODEL"] = "gemini-3.5-flash"
        with patch.object(ai_engine.urllib.request, "urlopen", return_value=_FakeResponse()) as mocked:
            status, payload = ai_engine.question_response({"interviewId": "local-demo", "turnIndex": 1})
        body = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(status, 200, body)
        self.assertEqual(payload["provider"], "gemini")
        self.assertEqual(payload["model"], "gemini-3.5-flash")
        self.assertEqual(payload["question"], "지원한 직무와 가장 연결되는 프로젝트 하나를 설명해 주세요.")
        request = mocked.call_args.args[0]
        self.assertIn("models/gemini-3.5-flash:generateContent", request.full_url)
        self.assertEqual(request.headers["X-goog-api-key"], "secret-gemini-key")
        self.assertNotIn("secret-gemini-key", body)

    def test_gemini_provider_fails_closed_without_key(self) -> None:
        os.environ["LLM_PROVIDER"] = "gemini"
        os.environ["GEMINI_MODEL"] = "gemini-3.5-flash"
        status, payload, body = self._post("/interview/next-question", {"interviewId": "local-demo", "turnIndex": 1})
        self.assertEqual(status, 502)
        self.assertEqual(payload["error"], "llm_provider_failed")
        self.assertNotIn("GEMINI_API_KEY=", body)

    def test_caddy_blocks_public_ai_prefix_after_api_broker_migration(self) -> None:
        caddyfile = (REPO_ROOT / "infra" / "caddy" / "Caddyfile").read_text()
        self.assertIn("@blocked_ai path /ai /ai/*", caddyfile)
        self.assertNotIn("handle_path /ai/*", caddyfile)
        self.assertLess(caddyfile.index("@blocked_ai"), caddyfile.index("handle {"))

    def test_public_tts_and_avatar_routes_are_blocked_before_ai_proxy(self) -> None:
        caddyfile = (REPO_ROOT / "infra" / "caddy" / "Caddyfile").read_text()
        self.assertIn("@blocked_tts path /tts /tts/* /ai/tts /ai/tts/*", caddyfile)
        self.assertIn("@blocked_avatar path /avatar /avatar/* /ai/avatar /ai/avatar/*", caddyfile)
        self.assertLess(caddyfile.index("@blocked_tts"), caddyfile.index("@blocked_ai"))
        self.assertLess(caddyfile.index("@blocked_avatar"), caddyfile.index("@blocked_ai"))


    def test_tts_response_reports_avatar_rtc_skipped_when_disabled(self) -> None:
        os.environ["VOICE_PROVIDER"] = "fake"
        os.environ["AVATAR_PROVIDER"] = "spatialreal"
        os.environ["SPATIALREAL_API_KEY"] = "secret-spatialreal-key"
        os.environ["SPATIALREAL_APP_ID"] = "app-123"
        os.environ["SPATIALREAL_AVATAR_ID"] = "avatar-456"
        status, payload = ai_engine.tts_response({"sessionId": "local-demo", "turnId": "turn-0001", "text": "테스트 질문"})
        body = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(status, 200, body)
        self.assertEqual(payload["avatarRtc"]["mode"], "livekit-egress")
        self.assertEqual(payload["avatarRtc"]["status"], "skipped")
        self.assertEqual(payload["avatarRtc"]["reason"], "rtc_egress_disabled")
        self.assertNotIn("secret-spatialreal-key", body)

    def test_spatialreal_ingress_endpoint_defaults_by_region_for_rtc_egress(self) -> None:
        os.environ["SPATIALREAL_REGION"] = "us-west"
        settings = ai_engine.load_avatar_settings()
        self.assertEqual(settings.ingress_endpoint, "wss://api.us-west.spatialwalk.cloud/v2/driveningress")

        os.environ["SPATIALREAL_REGION"] = "ap-northeast"
        settings = ai_engine.load_avatar_settings()
        self.assertEqual(settings.ingress_endpoint, "wss://api.ap-northeast.spatialwalk.cloud/v2/driveningress")

    def test_avatar_rtc_egress_fails_fast_for_loopback_livekit_url(self) -> None:
        os.environ["VOICE_PROVIDER"] = "fake"
        os.environ["AVATAR_PROVIDER"] = "spatialreal"
        os.environ["SPATIALREAL_RTC_EGRESS_ENABLED"] = "true"
        os.environ["SPATIALREAL_API_KEY"] = "secret-spatialreal-key"
        os.environ["SPATIALREAL_APP_ID"] = "app-123"
        os.environ["SPATIALREAL_AVATAR_ID"] = "avatar-456"
        os.environ["LIVEKIT_PUBLIC_URL"] = "ws://127.0.0.1:7880"
        os.environ["LIVEKIT_API_KEY"] = "devkey"
        os.environ["LIVEKIT_API_SECRET"] = "devsecret-minimum-32-bytes"
        status, payload = ai_engine.tts_response({"sessionId": "local-demo", "turnId": "turn-0001", "text": "테스트 질문"})
        body = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(status, 200, body)
        self.assertEqual(payload["avatarRtc"]["status"], "skipped")
        self.assertEqual(payload["avatarRtc"]["reason"], "livekit_egress_url_not_public")
        self.assertNotIn("secret-spatialreal-key", body)

    def test_compose_wires_tts_and_avatar_env_to_ai_engine(self) -> None:
        compose = (REPO_ROOT / "infra" / "docker-compose.yml").read_text()
        for name in (
            "VOICE_PROVIDER",
            "ELEVENLABS_API_KEY",
            "ELEVENLABS_VOICE_ID",
            "ELEVENLABS_TTS_MODEL",
            "ELEVENLABS_OUTPUT_FORMAT",
            "GEMINI_TTS_MODEL",
            "GEMINI_TTS_VOICE",
            "TTS_PROVIDER_FAILURE_FALLBACK",
            "AVATAR_PROVIDER",
            "SPATIALREAL_API_KEY",
            "SPATIALREAL_APP_ID",
            "SPATIALREAL_AVATAR_ID",
            "SPATIALREAL_REGION",
            "SPATIALREAL_SESSION_TTL_SECONDS",
            "AVATAR_PROVIDER_FAILURE_FALLBACK",
            "SPATIALREAL_AUDIO_SAMPLE_RATE",
            "SPATIALREAL_AUDIO_CHANNEL_COUNT",
            "SPATIALREAL_RTC_EGRESS_ENABLED",
            "SPATIALREAL_RTC_LIVEKIT_URL",
            "SPATIALREAL_RTC_PUBLISHER_ID_PREFIX",
            "SPATIALREAL_RTC_IDLE_TIMEOUT_SECONDS",
            "SPATIALREAL_RTC_SETTLE_SECONDS",
            "LIVEKIT_PUBLIC_URL",
            "LIVEKIT_API_KEY",
            "LIVEKIT_API_SECRET",
        ):
            self.assertIn(name, compose)


if __name__ == "__main__":
    unittest.main()
