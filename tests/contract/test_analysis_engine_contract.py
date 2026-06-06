from __future__ import annotations

import pathlib
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ANALYSIS_ENGINE_ROOT = REPO_ROOT / "services" / "analysis-engine"
PINNED_GILJOBE_REF = "88a4df5"
OLD_GILJOBE_REF = "b769120"


class AnalysisEngineContractTest(unittest.TestCase):
    def test_analysis_engine_runs_giljobe_server_not_deleted_wrapper(self) -> None:
        self.assertFalse(
            (ANALYSIS_ENGINE_ROOT / "server.py").exists(),
            "services/analysis-engine/server.py should stay removed; GilJobE owns the HTTP server",
        )
        dockerfile = (ANALYSIS_ENGINE_ROOT / "Dockerfile").read_text()
        self.assertIn("python:3.12-slim", dockerfile)
        self.assertNotIn("python:3.12-alpine", dockerfile)
        self.assertIn("git ffmpeg ca-certificates", dockerfile)
        self.assertIn("ANALYSIS_ENGINE_PORT=8200", dockerfile)
        self.assertIn(f"GILJOBE_GIT_REF={PINNED_GILJOBE_REF}", dockerfile)
        self.assertIn('CMD ["python", "-m", "giljobe.server"]', dockerfile)
        self.assertNotIn("COPY server.py", dockerfile)
        self.assertNotIn("/app/server.py", dockerfile)

    def test_pinned_giljobe_ref_is_consistent_across_runtime_files(self) -> None:
        requirements = (ANALYSIS_ENGINE_ROOT / "requirements.txt").read_text()
        compose = (REPO_ROOT / "infra" / "docker-compose.yml").read_text()
        env_example = (REPO_ROOT / ".env.example").read_text()
        dockerfile = (ANALYSIS_ENGINE_ROOT / "Dockerfile").read_text()
        for label, text in {
            "requirements": requirements,
            "compose": compose,
            "env_example": env_example,
            "dockerfile": dockerfile,
        }.items():
            self.assertIn(PINNED_GILJOBE_REF, text, label)
            self.assertNotIn(OLD_GILJOBE_REF, text, label)
        self.assertIn(f"git+https://github.com/GilJob-E/GilJobE.git@{PINNED_GILJOBE_REF}", requirements)
        self.assertIn("python -m giljobe.server", requirements)

    def test_compose_wires_analysis_engine_dependencies_without_public_token_leaks(self) -> None:
        compose = (REPO_ROOT / "infra" / "docker-compose.yml").read_text()
        media_compose = (REPO_ROOT / "infra" / "docker-compose.media.yml").read_text()
        caddyfile = (REPO_ROOT / "infra" / "caddy" / "Caddyfile").read_text()
        self.assertIn("analysis-engine:", compose)
        self.assertIn("../services/analysis-engine", compose)
        self.assertIn("VLLM_BASE_URL", compose)
        self.assertIn("LIVEKIT_URL", compose)
        self.assertIn("LIVEKIT_TOKEN: ${LIVEKIT_ANALYZER_TOKEN:-}", compose)
        self.assertIn("LIVEKIT_API_KEY", compose)
        self.assertIn("LIVEKIT_API_SECRET", compose)
        self.assertIn("handle_path /analysis/*", caddyfile)
        self.assertIn("reverse_proxy analysis-engine:8200", caddyfile)
        self.assertIn("Legacy scaffold flag", media_compose)
        self.assertIn("not consulted by the runtime", media_compose)

    def test_docs_describe_giljobe_owned_http_contract(self) -> None:
        analysis_docs = "\n".join(
            [
                (ANALYSIS_ENGINE_ROOT / "README.md").read_text(),
                (ANALYSIS_ENGINE_ROOT / "AGENTS.md").read_text(),
                (ANALYSIS_ENGINE_ROOT / "CLAUDE.md").read_text(),
            ]
        )
        for expected in (
            "python -m giljobe.server",
            "/subscriber/start",
            "/subscriber/stop",
            "/signals",
            "/healthz",
            "/readyz",
            "token-safe",
        ):
            self.assertIn(expected, analysis_docs)
        self.assertIn("There is no local wrapper", analysis_docs)
        self.assertIn("ANALYSIS_ENGINE_ENABLE_SUBSCRIBER", analysis_docs)
        self.assertIn("legacy", analysis_docs.lower())

    def test_root_docs_and_verification_no_longer_reference_deleted_wrapper(self) -> None:
        root_readme = (REPO_ROOT / "README.md").read_text()
        root_agents = (REPO_ROOT / "AGENTS.md").read_text()
        self.assertNotIn("services/analysis-engine/server.py", root_readme)
        self.assertIn("docker build -q services/analysis-engine", root_readme)
        self.assertIn("services/analysis-engine/", root_agents)
        self.assertIn("python -m giljobe.server", root_agents)

    def test_no_raw_secret_or_media_examples_in_analysis_docs(self) -> None:
        docs = "\n".join(
            path.read_text()
            for path in [
                ANALYSIS_ENGINE_ROOT / "README.md",
                ANALYSIS_ENGINE_ROOT / "AGENTS.md",
                ANALYSIS_ENGINE_ROOT / "CLAUDE.md",
                REPO_ROOT / ".env.example",
            ]
        )
        forbidden = [
            "secret-livekit-token-should-not-leak",
            "LIVEKIT_API_SECRET=devsecret",
            "access_token=",
            "join_request=",
            "raw media bytes",
        ]
        for marker in forbidden:
            self.assertNotIn(marker, docs)


if __name__ == "__main__":
    unittest.main()
