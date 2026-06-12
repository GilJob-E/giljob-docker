from __future__ import annotations

import importlib.util
import json
import pathlib
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "realtime-smoke-readiness.py"

spec = importlib.util.spec_from_file_location("realtime_smoke_readiness", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
readiness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readiness)


class RealtimeSmokeReadinessContractTest(unittest.TestCase):
    def test_redaction_and_payload_shape_never_emit_tokens_or_raw_media(self) -> None:
        raw = "access_token=abc join_request=def gj_session_secret eyJabc.def.ghi sk-server rt_secret_123"
        redacted = readiness.redact_secret_shapes(raw)
        self.assertIn("access_token=<redacted>", redacted)
        self.assertIn("join_request=<redacted>", redacted)
        self.assertIn("gj_session_<redacted>", redacted)
        self.assertIn("<jwt-redacted>", redacted)
        self.assertIn("sk-<redacted>", redacted)
        self.assertIn("rt_<redacted>", redacted)
        for leaked in ("gj_session_secret", "eyJabc.def.ghi", "sk-server", "rt_secret_123"):
            self.assertNotIn(leaked, redacted)

        shaped = readiness.public_payload_shape({
            "sessionToken": "gj_session_secret",
            "client_secret": {"value": "rt_secret_123"},
            "sdp": "v=0",
            "transcript": "raw candidate text",
            "delivery": {"mode": "api-mediated-realtime-call"},
            "full_mmm_ready": False,
        })
        body = json.dumps(shaped, sort_keys=True)
        self.assertIn('"sessionToken": "<redacted>"', body)
        self.assertIn('"client_secret": "<redacted>"', body)
        self.assertIn('"sdp": "<redacted>"', body)
        self.assertIn('"transcript": "<redacted>"', body)
        self.assertNotIn("gj_session_secret", body)
        self.assertNotIn("rt_secret_123", body)
        self.assertNotIn("raw candidate text", body)

    def test_script_documents_realtime_live_blocker_and_gate_checks(self) -> None:
        body = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("--require-live", body)
        self.assertIn("realtime_not_configured", body)
        self.assertIn("check_mmm_gate", body)
        self.assertIn("raw_media_not_allowed", body)
        self.assertIn("browser tools disabled; backend sideband required", body)
        self.assertIn("summary-only; token/secret/sdp/transcript/media values redacted", body)
        self.assertIn("primaryOk", body)
        self.assertIn("optionalChecks", body)
        self.assertIn("realtimeCallBoundary", body)
        self.assertIn("roomBlocker", body)
        self.assertIn("appBlocker", body)
        self.assertIn("blocker", body)
        self.assertNotIn("print(payload)", body)

    def test_operator_docs_label_stale_runtime_blockers_separately(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("./scripts/smoke.sh realtime-ready", readme)
        self.assertIn("REQUIRE_REALTIME_LIVE=1", readme)
        self.assertIn("request_failed / Connection refused", readme)
        self.assertIn("stale-runtime evidence", readme)
        self.assertIn("provider-secret", readme)
        self.assertIn("frontend-contract leak", readme)

    def test_operator_docs_pin_realtime_webrtc_secret_and_gate_contract(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("OPENAI_API_KEY is the only OpenAI server key", readme)
        self.assertIn("do not add OPENAI_REALTIME_API_KEY", readme)
        self.assertIn("browser-safe ephemeral client_secret", readme)
        self.assertIn('{\"session\": {...}} wrapper', readme)
        self.assertIn("omit session.metadata", readme)
        self.assertIn("full_mmm_ready must pass before realtime.response.create", readme)
        self.assertIn("latency evidence is redacted spans only", readme)
        self.assertIn("realtime.call broker 501/not implemented is acceptable", readme)
        self.assertIn("OPENAI_API_KEY=replace-me-openai-server-key", env_example)
        self.assertNotIn("OPENAI_REALTIME_API_KEY", env_example)


if __name__ == "__main__":
    unittest.main()
