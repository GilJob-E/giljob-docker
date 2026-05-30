from __future__ import annotations

from datetime import datetime, timezone
import os
import json
import pathlib
import sys
import unittest
from unittest.mock import patch
from typing import Any, cast

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from app.livekit_tokens import LiveKitConfigurationError, load_livekit_settings  # noqa: E402
from app.token_contract import (  # noqa: E402
    REPORT_TTL_SECONDS,
    SESSION_TTL_SECONDS,
    TOKEN_HASH_VERSION,
    hash_token,
    issue_session,
)

LIVEKIT_ENV_NAMES = (
    "LIVEKIT_REQUIRED",
    "LIVEKIT_URL",
    "LIVEKIT_INTERNAL_URL",
    "LIVEKIT_PUBLIC_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "LIVEKIT_TOKEN_TTL_SECONDS",
)


def restore_env(old_env: dict[str, str | None]) -> None:
    for name, value in old_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


class TokenContractTest(unittest.TestCase):
    def test_default_ttls_match_execution_spec(self) -> None:
        self.assertEqual(SESSION_TTL_SECONDS, 7200)
        self.assertEqual(REPORT_TTL_SECONDS, 2592000)

    def test_issue_session_separates_public_tokens_from_stored_hashes(self) -> None:
        old_env = {name: os.environ.get(name) for name in LIVEKIT_ENV_NAMES}
        try:
            for name in old_env:
                os.environ.pop(name, None)
            issued = issue_session(now=datetime(2026, 5, 30, 7, 0, tzinfo=timezone.utc))
        finally:
            restore_env(old_env)
        public = cast(dict[str, Any], issued["public"])
        stored = cast(dict[str, Any], issued["stored"])

        self.assertIn("sessionToken", public)
        self.assertIn("reportToken", public)
        self.assertNotEqual(public["sessionToken"], public["reportToken"])
        self.assertEqual(public["stateVersion"], 1)
        self.assertEqual(stored["stateVersion"], 1)

        stored_json = json.dumps(stored, sort_keys=True)
        self.assertNotIn(str(public["sessionToken"]), stored_json)
        self.assertNotIn(str(public["reportToken"]), stored_json)
        self.assertTrue(str(stored["sessionTokenHash"]).startswith(f"{TOKEN_HASH_VERSION}:session:"))
        self.assertTrue(str(stored["reportTokenHash"]).startswith(f"{TOKEN_HASH_VERSION}:report:"))

    def test_issue_session_reports_livekit_not_configured_without_credentials(self) -> None:
        old_env = {name: os.environ.get(name) for name in LIVEKIT_ENV_NAMES}
        try:
            for name in old_env:
                os.environ.pop(name, None)
            issued = issue_session(now=datetime(2026, 5, 30, 7, 0, tzinfo=timezone.utc))
            public = cast(dict[str, Any], issued["public"])
            livekit = cast(dict[str, Any], public["livekit"])
            self.assertEqual(livekit["tokenStatus"], "not_configured")
            self.assertEqual(livekit["candidateToken"], None)
            self.assertEqual(livekit["url"], None)
            self.assertEqual(livekit["publicUrl"], None)
            self.assertEqual(livekit["deferredReason"], "livekit_credentials_missing")
        finally:
            restore_env(old_env)

    def test_issue_session_uses_public_livekit_url_without_storing_token(self) -> None:
        old_env = {name: os.environ.get(name) for name in LIVEKIT_ENV_NAMES}
        try:
            os.environ.pop("LIVEKIT_URL", None)
            os.environ["LIVEKIT_INTERNAL_URL"] = "ws://livekit:7880"
            os.environ["LIVEKIT_PUBLIC_URL"] = "ws://127.0.0.1:7880"
            os.environ["LIVEKIT_API_KEY"] = "devkey"
            os.environ["LIVEKIT_API_SECRET"] = "devsecret-with-at-least-32-bytes"
            os.environ["LIVEKIT_TOKEN_TTL_SECONDS"] = "900"
            with patch("app.livekit_tokens._create_livekit_join_token", return_value="signed-livekit-jwt"):
                issued = issue_session(now=datetime(2026, 5, 30, 7, 0, tzinfo=timezone.utc))
            public = cast(dict[str, Any], issued["public"])
            livekit = cast(dict[str, Any], public["livekit"])
            stored_json = json.dumps(issued["stored"], sort_keys=True)
            self.assertEqual(livekit["tokenStatus"], "issued")
            self.assertEqual(livekit["url"], "ws://127.0.0.1:7880")
            self.assertEqual(livekit["publicUrl"], "ws://127.0.0.1:7880")
            self.assertEqual(livekit["candidateToken"], "signed-livekit-jwt")
            self.assertEqual(livekit["tokenTtlSeconds"], 900)
            self.assertNotIn("signed-livekit-jwt", stored_json)
            self.assertNotIn("LIVEKIT_INTERNAL_URL", json.dumps(public, sort_keys=True))
            settings = load_livekit_settings()
            self.assertIsNotNone(settings)
            assert settings is not None
            self.assertEqual(settings.internal_url, "ws://livekit:7880")
        finally:
            restore_env(old_env)

    def test_legacy_livekit_url_remains_fallback(self) -> None:
        old_env = {name: os.environ.get(name) for name in LIVEKIT_ENV_NAMES}
        try:
            for name in old_env:
                os.environ.pop(name, None)
            os.environ["LIVEKIT_URL"] = "ws://legacy-livekit.example.test"
            os.environ["LIVEKIT_API_KEY"] = "devkey"
            os.environ["LIVEKIT_API_SECRET"] = "devsecret-with-at-least-32-bytes"
            with patch("app.livekit_tokens._create_livekit_join_token", return_value="legacy-signed-jwt"):
                issued = issue_session(now=datetime(2026, 5, 30, 7, 0, tzinfo=timezone.utc))
            livekit = cast(dict[str, Any], cast(dict[str, Any], issued["public"])["livekit"])
            self.assertEqual(livekit["url"], "ws://legacy-livekit.example.test")
            self.assertEqual(livekit["publicUrl"], "ws://legacy-livekit.example.test")
        finally:
            restore_env(old_env)

    def test_required_livekit_mode_fails_closed_without_public_url(self) -> None:
        old_env = {name: os.environ.get(name) for name in LIVEKIT_ENV_NAMES}
        try:
            for name in old_env:
                os.environ.pop(name, None)
            os.environ["LIVEKIT_REQUIRED"] = "true"
            os.environ["LIVEKIT_INTERNAL_URL"] = "ws://livekit:7880"
            os.environ["LIVEKIT_API_KEY"] = "devkey"
            os.environ["LIVEKIT_API_SECRET"] = "devsecret-with-at-least-32-bytes"
            with self.assertRaisesRegex(LiveKitConfigurationError, "LIVEKIT_PUBLIC_URL"):
                load_livekit_settings()
        finally:
            restore_env(old_env)

    def test_required_livekit_mode_does_not_accept_legacy_single_url(self) -> None:
        old_env = {name: os.environ.get(name) for name in LIVEKIT_ENV_NAMES}
        try:
            for name in old_env:
                os.environ.pop(name, None)
            os.environ["LIVEKIT_REQUIRED"] = "true"
            os.environ["LIVEKIT_URL"] = "ws://127.0.0.1:7880"
            os.environ["LIVEKIT_API_KEY"] = "devkey"
            os.environ["LIVEKIT_API_SECRET"] = "devsecret-with-at-least-32-bytes"
            with self.assertRaisesRegex(LiveKitConfigurationError, "LIVEKIT_INTERNAL_URL"):
                load_livekit_settings()
        finally:
            restore_env(old_env)

    def test_hashes_are_purpose_separated(self) -> None:
        raw = "same-raw-token"
        self.assertNotEqual(hash_token(raw, "session"), hash_token(raw, "report"))

    def test_missing_production_secret_fails_closed(self) -> None:
        old_env = {name: os.environ.get(name) for name in (
            "GILJOB_ENV",
            "SESSION_TOKEN_HASH_SECRET",
            "REPORT_TOKEN_HASH_SECRET",
        )}
        try:
            os.environ["GILJOB_ENV"] = "production"
            os.environ.pop("SESSION_TOKEN_HASH_SECRET", None)
            with self.assertRaisesRegex(RuntimeError, "SESSION_TOKEN_HASH_SECRET"):
                hash_token("raw", "session")
        finally:
            restore_env(old_env)

    def test_postgres_schema_contains_hash_only_contract(self) -> None:
        schema = (REPO_ROOT / "services" / "api" / "db" / "schema.sql").read_text()
        self.assertIn("session_token_hash TEXT NOT NULL", schema)
        self.assertIn("report_token_hash TEXT NOT NULL", schema)
        self.assertIn("state_version INTEGER NOT NULL DEFAULT 1", schema)
        self.assertNotIn("session_token TEXT", schema)
        self.assertNotIn("report_token TEXT", schema)


if __name__ == "__main__":
    unittest.main()
