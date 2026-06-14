from __future__ import annotations

import pathlib
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class RemoteVerificationAndAvatarBoundaryContractTest(unittest.TestCase):
    def test_kiostation_archive_harness_runs_checks_only_over_ssh(self) -> None:
        script = (REPO_ROOT / "scripts" / "kiostation-verify-archive.sh").read_text(encoding="utf-8")
        self.assertIn("hoddukzoa@kiostation", script)
        self.assertIn('git archive --format=tar.gz --output="$archive" HEAD', script)
        self.assertIn("Commit changes before running", script)
        self.assertIn("scp -q", script)
        self.assertIn("ssh \"$REMOTE_HOST\"", script)
        self.assertIn("npm ci --ignore-scripts --no-audit --no-fund", script)
        self.assertIn("node --check apps/web/static/app.js", script)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile services/api/server.py services/analysis-engine/server.py", script)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -v", script)
        self.assertIn("git diff --cached --check", script)
        self.assertIn("never sources or prints .env values", script)
        self.assertNotIn("source .env", script)
        self.assertNotIn("cat .env", script)
        self.assertNotIn("docker compose", script)

    def test_spatialreal_avatar_boundary_does_not_claim_realtime_remote_audio_bridge(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        avatar_runbook = (REPO_ROOT / "docs" / "runbooks" / "tts-avatar-contract.md").read_text(encoding="utf-8")
        app_js = (REPO_ROOT / "apps" / "web" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("OpenAI Realtime primary mode", readme)
        self.assertIn("SPATIALREAL_RTC_EGRESS_ENABLED=false", avatar_runbook)
        self.assertIn("No interviewer/avatar audio publication", avatar_runbook)
        self.assertNotIn("/api/interviews/${encodeURIComponent(activeInterviewId)}/turns/${turnIndex}/tts", app_js)
        self.assertIn("legacy TTS fallback removed", app_js)
        self.assertNotIn("source\": \"ai-engine", app_js)

        combined_claim_surface = "\n".join([readme, avatar_runbook])
        forbidden_claims = [
            "SpatialReal lip-sync uses OpenAI Realtime audio",
            "OpenAI Realtime remote audio is bridged into SpatialReal",
            "Realtime audio drives SpatialReal",
            "SpatialReal receives OpenAI Realtime remote audio",
        ]
        for phrase in forbidden_claims:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, combined_claim_surface)

    def test_avatar_contract_no_longer_depends_on_ai_engine_runtime(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        avatar_runbook = (REPO_ROOT / "docs" / "runbooks" / "tts-avatar-contract.md").read_text(encoding="utf-8")
        app_js = (REPO_ROOT / "apps" / "web" / "static" / "app.js").read_text(encoding="utf-8")
        combined = "\n".join([readme, avatar_runbook, app_js])
        self.assertNotIn("source=ai-engine", combined)
        self.assertNotIn("services/ai-engine/server.py", combined)
        self.assertNotIn("/tts/synthesize", combined)
        self.assertNotIn("ai-engine /avatar/session", avatar_runbook)
        self.assertNotIn("http://ai-engine:8100/avatar/session", avatar_runbook)


if __name__ == "__main__":
    unittest.main()
