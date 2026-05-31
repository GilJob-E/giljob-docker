from __future__ import annotations

from http.server import ThreadingHTTPServer
import importlib.util
import json
import os
import pathlib
import sys
import threading
import unittest
import urllib.error
import urllib.request
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

    def test_caddy_routes_ai_prefix_to_ai_engine(self) -> None:
        caddyfile = (REPO_ROOT / "infra" / "caddy" / "Caddyfile").read_text()
        self.assertIn("handle_path /ai/*", caddyfile)
        self.assertIn("reverse_proxy ai-engine:8100", caddyfile)


if __name__ == "__main__":
    unittest.main()
