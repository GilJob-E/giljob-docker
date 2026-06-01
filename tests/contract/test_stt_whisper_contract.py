from __future__ import annotations

from dataclasses import dataclass
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
STT_ROOT = REPO_ROOT / "services" / "stt-whisper"

spec = importlib.util.spec_from_file_location("giljob_v2_stt_whisper_server", STT_ROOT / "server.py")
assert spec is not None and spec.loader is not None
stt_server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = stt_server
spec.loader.exec_module(stt_server)

STT_ENV_NAMES = (
    "WHISPER_MODEL",
    "WHISPER_DEVICE",
    "WHISPER_DEVICE_INDEX",
    "WHISPER_HOST_GPU_DEVICE_ID",
    "WHISPER_COMPUTE_TYPE",
    "STT_LANGUAGE",
)


def restore_env(old_env: dict[str, str | None]) -> None:
    for name, value in old_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@dataclass
class _Segment:
    start: float
    end: float
    text: str


@dataclass
class _Info:
    language: str = "ko"
    language_probability: float = 0.99
    duration: float = 1.25


class _FakeWhisperModel:
    init_args: tuple[object, ...] = ()
    init_kwargs: dict[str, object] = {}

    def __init__(self, *args: object, **kwargs: object) -> None:
        type(self).init_args = args
        type(self).init_kwargs = kwargs

    def transcribe(self, audio_path: str, **kwargs: object) -> tuple[list[_Segment], _Info]:
        self.last_audio_path = audio_path
        self.last_kwargs = kwargs
        return [_Segment(0.0, 1.25, "안녕하세요. 저는 백엔드 경험이 있습니다.")], _Info()


class STTWhisperContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self._old_env = {name: os.environ.get(name) for name in STT_ENV_NAMES}
        for name in STT_ENV_NAMES:
            os.environ.pop(name, None)
        stt_server._MODEL = None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), stt_server.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host = self.server.server_address[0]
        port = self.server.server_address[1]
        self.base_url = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        stt_server._MODEL = None
        restore_env(self._old_env)


    def _post_warmup(self) -> tuple[int, dict[str, object], str]:
        req = urllib.request.Request(
            self.base_url + "/warmup",
            data=b"",
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

    def _post_audio(self, query: str = "interviewId=local-demo&turnIndex=1&language=ko") -> tuple[int, dict[str, object], str]:
        req = urllib.request.Request(
            self.base_url + "/transcribe?" + query,
            data=b"fake-webm-audio-bytes",
            headers={"Content-Type": "audio/webm"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                body = res.read().decode("utf-8")
                return res.status, json.loads(body), body
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            return exc.code, json.loads(body), body

    def test_health_reports_gpu1_contract_without_loading_model(self) -> None:
        os.environ["WHISPER_MODEL"] = "Systran/faster-whisper-large-v3"
        os.environ["WHISPER_DEVICE"] = "cuda"
        os.environ["WHISPER_DEVICE_INDEX"] = "0"
        os.environ["WHISPER_HOST_GPU_DEVICE_ID"] = "1"
        with urllib.request.urlopen(self.base_url + "/healthz", timeout=5) as res:
            body = res.read().decode("utf-8")
        payload = json.loads(body)
        self.assertEqual(payload["provider"], "local-whisper")
        self.assertEqual(payload["model"], "Systran/faster-whisper-large-v3")
        self.assertEqual(payload["device"], "cuda")
        self.assertEqual(payload["deviceIndex"], 0)
        self.assertEqual(payload["hostGpuDeviceId"], "1")
        self.assertEqual(payload["modelLoaded"], False)

    def test_warmup_loads_model_without_audio_payload(self) -> None:
        with patch.object(stt_server, "_load_faster_whisper_class", return_value=_FakeWhisperModel):
            status, payload, body = self._post_warmup()
        self.assertEqual(status, 200, body)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["provider"], "local-whisper")
        self.assertEqual(payload["model"], "Systran/faster-whisper-large-v3")
        self.assertEqual(payload["modelLoaded"], True)
        self.assertEqual(_FakeWhisperModel.init_args[0], "Systran/faster-whisper-large-v3")
        self.assertEqual(_FakeWhisperModel.init_kwargs["device"], "cuda")
        self.assertEqual(_FakeWhisperModel.init_kwargs["device_index"], 0)

    def test_transcribe_uses_faster_whisper_cuda_contract(self) -> None:
        with patch.object(stt_server, "_load_faster_whisper_class", return_value=_FakeWhisperModel):
            status, payload, body = self._post_audio()
        self.assertEqual(status, 200, body)
        self.assertEqual(payload["provider"], "local-whisper")
        self.assertEqual(payload["model"], "Systran/faster-whisper-large-v3")
        self.assertEqual(payload["language"], "ko")
        self.assertEqual(payload["text"], "안녕하세요. 저는 백엔드 경험이 있습니다.")
        self.assertEqual(_FakeWhisperModel.init_args[0], "Systran/faster-whisper-large-v3")
        self.assertEqual(_FakeWhisperModel.init_kwargs["device"], "cuda")
        self.assertEqual(_FakeWhisperModel.init_kwargs["device_index"], 0)
        self.assertEqual(_FakeWhisperModel.init_kwargs["compute_type"], "float16")

    def test_invalid_interview_id_is_rejected_before_model_load(self) -> None:
        with patch.object(stt_server, "_load_faster_whisper_class", return_value=_FakeWhisperModel) as mocked:
            status, payload, _ = self._post_audio("interviewId=../secret&turnIndex=1")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_interview_id")
        mocked.assert_not_called()

    def test_compose_reserves_host_gpu_1_for_stt_service(self) -> None:
        compose = (REPO_ROOT / "infra" / "docker-compose.yml").read_text()
        self.assertIn("stt-whisper:", compose)
        self.assertIn('device_ids: ["1"]', compose)
        self.assertIn("WHISPER_HOST_GPU_DEVICE_ID", compose)
        self.assertIn("reverse_proxy stt-whisper:8200", (REPO_ROOT / "infra" / "caddy" / "Caddyfile").read_text())


if __name__ == "__main__":
    unittest.main()
