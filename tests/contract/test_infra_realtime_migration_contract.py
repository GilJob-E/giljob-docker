from __future__ import annotations

import pathlib
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
INFRA_ROOT = REPO_ROOT / "infra"


class RealtimeMigrationInfraContractTest(unittest.TestCase):
    def test_base_compose_keeps_livekit_and_coturn_out_of_primary_services(self) -> None:
        """Realtime migration starts from a base stack where RTC media is not a primary service."""
        base_compose = (INFRA_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertNotIn("\n  livekit:", base_compose)
        self.assertNotIn("\n  coturn:", base_compose)
        self.assertNotIn('"7880:7880"', base_compose)
        self.assertNotIn('"7881:7881"', base_compose)
        self.assertNotIn('"50000-50100:50000-50100/udp"', base_compose)
        self.assertIn("LIVEKIT_REQUIRED: ${LIVEKIT_REQUIRED:-false}", base_compose)
        self.assertIn("LIVEKIT_MEDIA_OVERLAY_ENABLED: ${LIVEKIT_MEDIA_OVERLAY_ENABLED:-false}", base_compose)

    def test_media_overlay_is_explicit_fail_closed_compatibility_path(self) -> None:
        media_compose = (INFRA_ROOT / "docker-compose.media.yml").read_text(encoding="utf-8")
        self.assertIn("Optional media ingress overlay", media_compose)
        self.assertIn("fail-closed", media_compose)
        self.assertIn('LIVEKIT_REQUIRED: "true"', media_compose)
        self.assertIn('LIVEKIT_MEDIA_OVERLAY_ENABLED: "true"', media_compose)
        self.assertIn("LIVEKIT_PUBLIC_URL:?set LIVEKIT_PUBLIC_URL", media_compose)
        self.assertIn("LIVEKIT_API_KEY:?set LIVEKIT_API_KEY", media_compose)
        self.assertIn("LIVEKIT_API_SECRET:?set LIVEKIT_API_SECRET", media_compose)
        self.assertIn("TURN_REALM:?set TURN_REALM", media_compose)
        self.assertIn("TURN_STATIC_AUTH_SECRET:?set TURN_STATIC_AUTH_SECRET", media_compose)
        self.assertIn("\n  livekit:", media_compose)
        self.assertIn("\n  coturn:", media_compose)

    def test_caddy_is_https_static_api_proxy_only_not_media_or_provider_ingress(self) -> None:
        caddyfile = (INFRA_ROOT / "caddy" / "Caddyfile").read_text(encoding="utf-8")
        self.assertIn("handle_path /api/*", caddyfile)
        self.assertIn("reverse_proxy api:8000", caddyfile)
        self.assertIn("reverse_proxy web:3000", caddyfile)
        self.assertIn("respond 404", caddyfile)
        for blocked in ("@blocked_tts", "@blocked_avatar", "@blocked_ai"):
            self.assertIn(blocked, caddyfile)
        self.assertNotIn("reverse_proxy livekit", caddyfile.lower())
        self.assertNotIn("reverse_proxy coturn", caddyfile.lower())
        self.assertNotIn(":7880", caddyfile)
        self.assertNotIn(":7881", caddyfile)
        self.assertNotIn("50000-50100", caddyfile)

    def test_smoke_script_keeps_config_check_separate_from_live_media_smoke(self) -> None:
        smoke_script = (REPO_ROOT / "scripts" / "smoke.sh").read_text(encoding="utf-8")
        self.assertIn("COMPOSE=(docker compose -f", smoke_script)
        self.assertIn("MEDIA_COMPOSE=(docker compose -f", smoke_script)
        self.assertIn("== base compose config ==", smoke_script)
        self.assertIn("== media overlay fail-closed check ==", smoke_script)
        self.assertIn("usage: $0 [config|media-up|browser-join|realtime-ready]", smoke_script)
        self.assertIn("realtime_ready()", smoke_script)
        self.assertIn("scripts/realtime-smoke-readiness.py", smoke_script)
        self.assertIn("REQUIRE_REALTIME_LIVE", smoke_script)


if __name__ == "__main__":
    unittest.main()
