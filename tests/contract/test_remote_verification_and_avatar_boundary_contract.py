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
        self.assertIn("PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile services/api/server.py services/ai-engine/server.py services/analysis-engine/server.py", script)
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
        ai_engine = (REPO_ROOT / "services" / "ai-engine" / "server.py").read_text(encoding="utf-8")

        self.assertIn("OpenAI Realtime primary mode", readme)
        self.assertIn("SpatialReal 서버 SDK egress는 post-TTS WAV/PCM audio", readme)
        self.assertIn("SPATIALREAL_RTC_EGRESS_ENABLED=false", avatar_runbook)
        self.assertIn("No interviewer/avatar audio publication", avatar_runbook)
        self.assertIn("/api/interviews/${encodeURIComponent(activeInterviewId)}/turns/${turnIndex}/tts", app_js)
        self.assertIn("interviewerAudio.play", app_js)
        self.assertIn("SPATIALREAL_RTC_EGRESS_ENABLED", ai_engine)
        self.assertIn("audio_payload", ai_engine)

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


if __name__ == "__main__":
    unittest.main()
