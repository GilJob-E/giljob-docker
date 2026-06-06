from __future__ import annotations

from http.server import ThreadingHTTPServer
import importlib.util
import json
import os
import pathlib
import tempfile
import sys
import threading
import unittest
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ANALYSIS_ENGINE_ROOT = REPO_ROOT / "services" / "analysis-engine"

spec = importlib.util.spec_from_file_location("giljob_v2_analysis_engine_server", ANALYSIS_ENGINE_ROOT / "server.py")
assert spec is not None and spec.loader is not None
analysis_engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = analysis_engine
spec.loader.exec_module(analysis_engine)

ANALYSIS_ENV_NAMES = (
    "ANALYSIS_ENGINE_ENABLE_SUBSCRIBER",
    "LIVEKIT_URL",
    "LIVEKIT_TOKEN",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "LIVEKIT_SESSION_ID",
    "GILJOBE_GIT_URL",
    "GILJOBE_GIT_REF",
)


def restore_env(old_env: dict[str, str | None]) -> None:
    for name, value in old_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


class AnalysisEngineContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self._old_env = {name: os.environ.get(name) for name in ANALYSIS_ENV_NAMES}
        for name in self._old_env:
            os.environ.pop(name, None)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), analysis_engine.Handler)
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

    def _get(self, path: str) -> tuple[int, dict[str, object], str]:
        try:
            with urllib.request.urlopen(self.base_url + path, timeout=5) as res:
                body = res.read().decode("utf-8")
                return res.status, json.loads(body), body
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            return exc.code, json.loads(body), body

    def test_health_contract_names_giljobe_without_secret_leaks(self) -> None:
        os.environ["LIVEKIT_URL"] = "ws://livekit:7880"
        os.environ["LIVEKIT_TOKEN"] = "secret-livekit-token-should-not-leak"
        status, payload, body = self._get("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(payload["service"], "analysis-engine")
        self.assertEqual(payload["mode"], "standby")
        self.assertEqual(payload["sttPath"], "GilJobE")
        self.assertIn("transcript_full", payload["owns"])
        self.assertIn("main-llm", payload["doesNotOwn"])
        self.assertIn("tts", payload["doesNotOwn"])
        self.assertEqual(payload["livekit"]["tokenConfigured"], True)
        self.assertEqual(payload["livekit"]["rawSecretsExposed"], False)
        self.assertNotIn("secret-livekit-token-should-not-leak", body)

    def test_readyz_standby_is_safe_without_livekit_or_giljobe_installed(self) -> None:
        status, payload, _body = self._get("/readyz")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "standby")
        self.assertEqual(payload["subscriberEnabled"], False)

    def test_readyz_fails_closed_when_subscriber_enabled_without_credentials(self) -> None:
        os.environ["ANALYSIS_ENGINE_ENABLE_SUBSCRIBER"] = "true"
        status, payload, _body = self._get("/readyz")
        self.assertEqual(status, 503)
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(payload["subscriberEnabled"], True)
        self.assertEqual(payload["livekit"]["tokenSource"], "missing")

    def test_service_files_pin_giljobe_and_compose_wires_analysis_engine(self) -> None:
        requirements = (ANALYSIS_ENGINE_ROOT / "requirements.txt").read_text()
        self.assertIn("https://github.com/GilJob-E/GilJobE.git@b769120", requirements)
        dockerfile = (ANALYSIS_ENGINE_ROOT / "Dockerfile").read_text()
        self.assertIn("python:3.12-slim", dockerfile)
        self.assertNotIn("python:3.12-alpine", dockerfile)
        compose = (REPO_ROOT / "infra" / "docker-compose.yml").read_text()
        self.assertIn("analysis-engine:", compose)
        self.assertIn("../services/analysis-engine", compose)
        self.assertIn("ANALYSIS_ENGINE_ENABLE_SUBSCRIBER", compose)
        self.assertIn("LIVEKIT_ANALYZER_TOKEN", compose)

    def test_subscriber_start_endpoint_spawns_runtime_without_secret_leaks(self) -> None:
        class FakeRuntime:
            def status(self) -> dict[str, object]:
                return {"state": "stopped"}

            def start(self, *, session_id: str | None = None, critic_mode: str | None = None) -> tuple[int, dict[str, object]]:
                return 202, {"status": "starting", "sessionId": session_id, "criticMode": critic_mode}

        old_runtime = analysis_engine.RUNTIME
        analysis_engine.RUNTIME = FakeRuntime()
        self.addCleanup(lambda: setattr(analysis_engine, "RUNTIME", old_runtime))
        req = urllib.request.Request(
            self.base_url + "/subscriber/start",
            data=json.dumps({"sessionId": "local-demo", "criticMode": "mock"}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as res:
            body = res.read().decode("utf-8")
            status = res.status
        payload = json.loads(body)
        self.assertEqual(status, 202)
        self.assertEqual(payload["status"], "starting")
        self.assertEqual(payload["sessionId"], "local-demo")
        self.assertEqual(payload["criticMode"], "mock")
        self.assertNotIn("LIVEKIT_API_SECRET", body)

    def test_signals_endpoint_returns_transcript_without_secret_or_media_leaks(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            old_signal_dir = analysis_engine.SIGNAL_DIR
            analysis_engine.SIGNAL_DIR = pathlib.Path(tempdir)
            self.addCleanup(lambda: setattr(analysis_engine, "SIGNAL_DIR", old_signal_dir))
            signal_path = pathlib.Path(tempdir) / "local-demo.jsonl"
            signal_path.write_text(
                '\n'.join([
                    json.dumps({"type": "window", "session_id": "local-demo", "transcript": "안녕하세요"}, ensure_ascii=False),
                    json.dumps({"type": "turn_end", "session_id": "local-demo", "transcript_full": "안녕하세요 지원자입니다"}, ensure_ascii=False),
                ]),
                encoding="utf-8",
            )
            status, payload, body = self._get("/signals?sessionId=local-demo")
        self.assertEqual(status, 200)
        self.assertEqual(payload["sessionId"], "local-demo")
        self.assertEqual(payload["recordCount"], 2)
        self.assertEqual(payload["transcriptFull"], "안녕하세요 지원자입니다")
        self.assertEqual(payload["windowTranscripts"], ["안녕하세요"])
        self.assertEqual(payload["rawSecretsExposed"], False)
        self.assertEqual(payload["rawMediaExposed"], False)
        self.assertNotIn("LIVEKIT_API_SECRET", body)

    def test_signals_endpoint_rejects_path_traversal_session_id(self) -> None:
        status, payload, _body = self._get("/signals?sessionId=../local-demo")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_session_id")

    def test_caddy_routes_analysis_prefix_to_analysis_engine(self) -> None:
        caddyfile = (REPO_ROOT / "infra" / "caddy" / "Caddyfile").read_text()
        self.assertIn("handle_path /analysis/*", caddyfile)
        self.assertIn("reverse_proxy analysis-engine:8200", caddyfile)

    def test_subscriber_status_endpoint_reports_runtime_state(self) -> None:
        status, payload, _body = self._get("/subscriber/status")
        self.assertEqual(status, 200)
        self.assertEqual(payload["service"], "analysis-engine")
        self.assertIn("runtime", payload)
        self.assertIn("state", payload["runtime"])


    def test_runtime_errors_are_redacted_from_public_status_payloads(self) -> None:
        secret = "secret-livekit-token-should-not-leak"
        analysis_engine.RUNTIME._status = {
            "state": "error",
            "errorType": "RuntimeError",
            "errorCode": "subscriber_runtime_error",
            "endedAt": 1.0,
        }
        for path in ("/healthz", "/readyz", "/subscriber/status"):
            status, payload, body = self._get(path)
            self.assertIn(status, {200, 503})
            self.assertNotIn(secret, body)
            self.assertNotIn("LIVEKIT_API_SECRET", body)
            self.assertIn("runtime", payload)
            self.assertNotIn("error", payload["runtime"])
            self.assertEqual(payload["runtime"].get("errorCode"), "subscriber_runtime_error")


if __name__ == "__main__":
    unittest.main()
