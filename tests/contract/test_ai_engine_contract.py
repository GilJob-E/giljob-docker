from __future__ import annotations

from http.server import ThreadingHTTPServer
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
    "COACH_LLM_PROVIDER",
    "COACH_LLM_MODEL",
    "COACH_LLM_TIMEOUT_SECONDS",
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "COACH_GEMINI_API_KEY",
    "GEMINI_API_KEY",
    "GEMINI_API_BASE",
    "VOICE_PROVIDER",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_VOICE_ID",
    "ELEVENLABS_TTS_MODEL",
    "ELEVENLABS_OUTPUT_FORMAT",
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
        os.environ["LLM_PROVIDER"] = "fake"
        with urllib.request.urlopen(self.base_url + "/healthz", timeout=5) as res:
            body = res.read().decode("utf-8")
        payload = json.loads(body)
        self.assertEqual(payload["llmProvider"], "fake")
        self.assertIn("voiceProvider", payload)
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
        self.assertNotIn("ELEVENLABS_API_KEY", body)

    def test_fake_coach_feedback_route_returns_llm_shaped_feedback_without_raw_handoff(self) -> None:
        os.environ["LLM_PROVIDER"] = "fake"
        status, payload, body = self._post("/coach/feedback", {
            "interviewId": "local-demo",
            "turnIndex": 1,
            "turnHandoff": {
                "prompt_block": [
                    "raw candidate transcript should stay internal",
                    "raw visual note should stay internal",
                ],
                "meta": {
                    "coverage": {
                        "transcript": True,
                        "vision": True,
                        "prosody": False,
                    },
                },
            },
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(payload["provider"], "fake")
        self.assertEqual(payload["providerStatus"], "fake")
        self.assertEqual(payload["model"], "fake-coach")
        feedback = cast(dict[str, object], payload["coachFeedback"])
        self.assertTrue(feedback["ready"])
        self.assertIn("summary", feedback)
        self.assertIn("answerEvaluation", feedback)
        self.assertIn("multimodalEvaluation", feedback)
        self.assertGreaterEqual(len(cast(list[object], feedback["bullets"])), 2)
        self.assertNotIn("turnHandoff", body)
        self.assertNotIn("prompt_block", body)
        self.assertNotIn("raw candidate transcript should stay internal", body)
        self.assertNotIn("raw visual note should stay internal", body)

    def test_fake_coach_feedback_understands_actual_handoff_coverage_keys(self) -> None:
        status, payload, body = self._post("/coach/feedback", {
            "interviewId": "local-demo",
            "turnIndex": 1,
            "turnHandoff": {
                "prompt_block": ["[음성 전달 실측치]", "- 시선 안정성 관찰"],
                "meta": {
                    "coverage": {
                        "speech": 0,
                        "visual": 8,
                        "nv": 0,
                    },
                },
            },
        })

        self.assertEqual(status, 200, body)
        feedback = cast(dict[str, object], payload["coachFeedback"])
        self.assertIn("음성", str(feedback["multimodalEvaluation"]))
        self.assertIn("비언어", str(feedback["multimodalEvaluation"]))

    def test_openai_coach_feedback_route_calls_responses_api_without_key_or_raw_handoff_leak(self) -> None:
        os.environ["COACH_LLM_PROVIDER"] = "openai"
        os.environ["COACH_LLM_MODEL"] = "gpt-coach-test"
        os.environ["OPENAI_API_KEY"] = "secret-openai-key"
        captured: list[urllib.request.Request] = []

        class _OpenAIResponse:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args: object) -> None:
                return None
            def read(self) -> bytes:
                return json.dumps({
                    "id": "resp_coach_123",
                    "model": "gpt-coach-test",
                    "output": [{
                        "type": "message",
                        "content": [{
                            "type": "output_text",
                            "text": json.dumps({
                                "summary": "OpenAI coach summary",
                                "answerEvaluation": "OpenAI answer evaluation",
                                "multimodalEvaluation": "OpenAI multimodal evaluation",
                                "bullets": ["OpenAI bullet one", "OpenAI bullet two"],
                            }),
                        }],
                    }],
                    "usage": {"total_tokens": 123},
                }).encode("utf-8")

        def fake_urlopen(request: urllib.request.Request, timeout: float = 0) -> _OpenAIResponse:
            captured.append(request)
            return _OpenAIResponse()

        with patch.object(ai_engine.urllib.request, "urlopen", side_effect=fake_urlopen):
            status, payload = ai_engine.coach_feedback_response({
                "interviewId": "local-demo",
                "turnIndex": 1,
                "turnHandoff": {
                    "prompt_block": [
                        "raw candidate transcript should stay internal",
                        "raw visual note should stay internal",
                    ],
                    "meta": {"coverage": {"transcript": True, "vision": True, "prosody": True}},
                },
            })
        body = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(status, 200, body)
        self.assertEqual(payload["provider"], "openai")
        self.assertEqual(payload["providerStatus"], "live")
        self.assertEqual(payload["model"], "gpt-coach-test")
        feedback = cast(dict[str, object], payload["coachFeedback"])
        self.assertEqual(feedback["summary"], "OpenAI coach summary")
        self.assertEqual(feedback["answerEvaluation"], "OpenAI answer evaluation")
        self.assertEqual(feedback["multimodalEvaluation"], "OpenAI multimodal evaluation")
        self.assertEqual(feedback["bullets"], ["OpenAI bullet one", "OpenAI bullet two"])
        request = captured[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request.headers["Authorization"], "Bearer secret-openai-key")
        upstream_payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(upstream_payload["model"], "gpt-coach-test")
        self.assertFalse(upstream_payload["store"])
        self.assertIn("turnHandoff", json.dumps(upstream_payload, ensure_ascii=False))
        self.assertNotIn("secret-openai-key", body)
        self.assertNotIn("turnHandoff", body)
        self.assertNotIn("prompt_block", body)
        self.assertNotIn("raw candidate transcript should stay internal", body)
        self.assertNotIn("raw visual note should stay internal", body)

    def test_openai_coach_feedback_fails_closed_without_server_key(self) -> None:
        os.environ["COACH_LLM_PROVIDER"] = "openai"
        status, payload = ai_engine.coach_feedback_response({
            "interviewId": "local-demo",
            "turnIndex": 1,
            "turnHandoff": {"prompt_block": ["safe bounded handoff"]},
        })
        body = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(status, 503, body)
        self.assertEqual(payload["error"], "coach_llm_provider_unavailable")
        self.assertEqual(payload["provider"], "openai")
        self.assertNotIn("OPENAI_API_KEY", body)

    def test_gemini_coach_feedback_route_calls_generate_content_without_key_or_raw_handoff_leak(self) -> None:
        os.environ["COACH_LLM_PROVIDER"] = "gemini"
        os.environ["COACH_LLM_MODEL"] = "gemini-coach-test"
        os.environ["COACH_GEMINI_API_KEY"] = "secret-gemini-key"
        captured: list[urllib.request.Request] = []

        class _GeminiResponse:
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
                                    "summary": "Gemini coach summary",
                                    "answerEvaluation": "Gemini answer evaluation",
                                    "multimodalEvaluation": "Gemini multimodal evaluation",
                                    "bullets": ["Gemini bullet one", "Gemini bullet two"],
                                }),
                            }],
                            "role": "model",
                        },
                        "finishReason": "STOP",
                        "index": 0,
                    }],
                    "modelVersion": "gemini-coach-test",
                    "usageMetadata": {"totalTokenCount": 123},
                }).encode("utf-8")

        def fake_urlopen(request: urllib.request.Request, timeout: float = 0) -> _GeminiResponse:
            captured.append(request)
            return _GeminiResponse()

        with patch.object(ai_engine.urllib.request, "urlopen", side_effect=fake_urlopen):
            status, payload = ai_engine.coach_feedback_response({
                "interviewId": "local-demo",
                "turnIndex": 1,
                "turnHandoff": {
                    "prompt_block": [
                        "raw candidate transcript should stay internal",
                        "raw visual note should stay internal",
                    ],
                    "meta": {"coverage": {"transcript": True, "vision": True, "prosody": True}},
                },
            })
        body = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(status, 200, body)
        self.assertEqual(payload["provider"], "gemini")
        self.assertEqual(payload["providerStatus"], "live")
        self.assertEqual(payload["model"], "gemini-coach-test")
        feedback = cast(dict[str, object], payload["coachFeedback"])
        self.assertEqual(feedback["summary"], "Gemini coach summary")
        self.assertEqual(feedback["answerEvaluation"], "Gemini answer evaluation")
        self.assertEqual(feedback["multimodalEvaluation"], "Gemini multimodal evaluation")
        self.assertEqual(feedback["bullets"], ["Gemini bullet one", "Gemini bullet two"])
        request = captured[0]
        self.assertEqual(request.full_url, "https://generativelanguage.googleapis.com/v1beta/models/gemini-coach-test:generateContent")
        self.assertEqual(request.headers["X-goog-api-key"], "secret-gemini-key")
        upstream_payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(upstream_payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertIn("turnHandoff", json.dumps(upstream_payload, ensure_ascii=False))
        self.assertNotIn("secret-gemini-key", body)
        self.assertNotIn("turnHandoff", body)
        self.assertNotIn("prompt_block", body)
        self.assertNotIn("raw candidate transcript should stay internal", body)
        self.assertNotIn("raw visual note should stay internal", body)

    def test_gemini_coach_feedback_fails_closed_without_server_key(self) -> None:
        os.environ["COACH_LLM_PROVIDER"] = "gemini"
        status, payload = ai_engine.coach_feedback_response({
            "interviewId": "local-demo",
            "turnIndex": 1,
            "turnHandoff": {"prompt_block": ["safe bounded handoff"]},
        })
        body = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(status, 503, body)
        self.assertEqual(payload["error"], "coach_llm_provider_unavailable")
        self.assertEqual(payload["provider"], "gemini")
        self.assertNotIn("GEMINI_API_KEY", body)

    def test_coach_llm_model_default_tracks_selected_provider(self) -> None:
        os.environ["COACH_LLM_PROVIDER"] = "openai"
        self.assertEqual(ai_engine.load_coach_llm_settings().model, "gpt-4.1-mini")

        os.environ["COACH_LLM_PROVIDER"] = "gemini"
        self.assertEqual(ai_engine.load_coach_llm_settings().model, "gemini-2.5-flash")



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
            "OPENAI_API_KEY",
            "OPENAI_API_BASE",
            "COACH_GEMINI_API_KEY",
            "GEMINI_API_KEY",
            "GEMINI_API_BASE",
            "COACH_LLM_PROVIDER",
            "COACH_LLM_MODEL",
            "COACH_LLM_TIMEOUT_SECONDS",
            "VOICE_PROVIDER",
            "ELEVENLABS_API_KEY",
            "ELEVENLABS_VOICE_ID",
            "ELEVENLABS_TTS_MODEL",
            "ELEVENLABS_OUTPUT_FORMAT",
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


class AnalysisBlockInjectionContractTest(unittest.TestCase):
    """analysisBlock — turn_handoff prompt_block이 next-question 프롬프트에 도달하는 계약."""

    def test_question_prompt_includes_analysis_block_only_when_present(self) -> None:
        base = {"interviewId": "iv-1", "lastAnswer": "답변 전사"}
        without = ai_engine.build_question_prompt(base, 2)
        self.assertNotIn("이전 답변 분석", without)
        block = "[음성 전달 실측치]\n- 조음 6.18음절/초\n\n[판단 규칙]\n- 실측치가 정본"
        with_block = ai_engine.build_question_prompt({**base, "analysisBlock": block}, 2)
        self.assertIn("이전 답변 분석", with_block)
        self.assertIn("- 조음 6.18음절/초", with_block)
        # 섹션 줄 구조 보존 — _safe_str의 \s+ 압축이 블록을 한 줄로 뭉개면 안 된다
        self.assertIn("[음성 전달 실측치]\n- 조음", with_block)

    def test_analysis_block_clamped_and_newline_normalized(self) -> None:
        ctx = ai_engine._candidate_context({"analysisBlock": "줄1\n\n\n\n줄2  끝" + "가" * 10_000})
        self.assertLessEqual(len(ctx["analysisBlock"]), 4_000)
        self.assertIn("줄1\n\n줄2 끝", ctx["analysisBlock"])
