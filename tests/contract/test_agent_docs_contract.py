from __future__ import annotations

import pathlib
import re
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

DOC_PAIRS = [
    pathlib.Path("."),
    pathlib.Path("apps/web"),
    pathlib.Path("services/api"),
    pathlib.Path("services/analysis-engine"),
    pathlib.Path("services/agent1"),
    pathlib.Path("infra"),
    pathlib.Path("tests"),
    pathlib.Path("docs"),
    pathlib.Path("packages/shared"),
    pathlib.Path("scripts"),
]

PATH_SPECIFIC_TERMS = {
    "AGENTS.md": ["single-server", "multi-container", "LIVEKIT_INTERNAL_URL", "LIVEKIT_PUBLIC_URL"],
    "apps/web/AGENTS.md": ["DESIGN.md", "manual button", "right sidebar", "redaction", "raw token"],
    "services/api/AGENTS.md": ["hash-only", "raw token", "LIVEKIT_INTERNAL_URL", "LIVEKIT_PUBLIC_URL"],
    "services/analysis-engine/AGENTS.md": ["GilJobE", "STT and multimodal", "source of truth", "Do not add the Main LLM loop", "avatar/TTS"],
    "services/agent1/AGENTS.md": ["future multimodal placeholder", "structured signal", "raw media"],
    "infra/AGENTS.md": ["Caddy", "LiveKit", "coturn", "direct media", "/ai/*", "broker routes", "direct public"],
    "tests/AGENTS.md": ["tests/contract", "tests/integration", "path-specific"],
    "docs/AGENTS.md": ["architecture.noml", "generated", "English"],
    "packages/shared/AGENTS.md": ["shared contracts", "premature abstractions"],
    "scripts/AGENTS.md": ["smoke", "token redaction", "fail-closed"],
}

RUNBOOK_SPECIFIC_TERMS = {
    "docs/runbooks/verification.md": [
        "ssh hoddukzoa@kiostation",
        "node --check apps/web/static/app.js",
        "py_compile services/api/server.py services/analysis-engine/server.py",
        "python3 -m unittest discover -s tests/contract -v",
        "git diff --check",
        "Do not use `/home/hoddukzoa/GilJob`",
    ],
    "docs/runbooks/local-livekit-media.md": [
        "LIVEKIT_INTERNAL_URL",
        "LIVEKIT_PUBLIC_URL",
        "7880/tcp",
        "7881/tcp",
        "50000-50100/udp",
        "browser-join",
    ],
    "docs/runbooks/tts-avatar-contract.md": [
        "Legacy question/TTS routes return deprecated_ai_engine_removed",
        "Gemini TTS fallback is removed",
        "Avatar metadata is API-owned",
        "disabled/deferred",
        "does not ingest OpenAI Realtime remote audio",
        "No OpenAI Realtime remote-audio injection into SpatialReal",
        "Do not downgrade `livekit-client`",
    ],
    "docs/source-manifest.md": [
        "Target root: `/home/hoddukzoa/GilJob_v2`",
        "Legacy rule: `/home/hoddukzoa/GilJob`",
        "Verify remote SHA256 against this manifest",
    ],
}

REMOTE_VERIFICATION_COMMANDS = [
    "node --check apps/web/static/app.js",
    "PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile services/api/server.py services/analysis-engine/server.py",
    "PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -v",
    "git diff --check",
]

FORBIDDEN_IMPLEMENTED_CLAIMS = [
    "full Main LLM loop is implemented",
    "SpatialReal avatar is implemented",
    "ElevenLabs avatar is implemented",
    "multimodal analysis is implemented",
    "final report generation is implemented",
]

JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
GOOGLE_AI_KEY_RE = re.compile(r"AIza[0-9A-Za-z_-]{20,}")
LIVEKIT_SECRET_RE = re.compile(r"(?i)(livekit[_-]api[_-]secret\s*[=:]\s*)(?!your-|example|placeholder|devsecret)[A-Za-z0-9_-]{16,}")


class AgentDocsContractTest(unittest.TestCase):
    def agent_doc_paths(self) -> list[pathlib.Path]:
        paths: list[pathlib.Path] = []
        for directory in DOC_PAIRS:
            paths.append(REPO_ROOT / directory / "AGENTS.md")
            paths.append(REPO_ROOT / directory / "CLAUDE.md")
        return paths

    def test_expected_agent_and_claude_docs_exist(self) -> None:
        for directory in DOC_PAIRS:
            with self.subTest(directory=str(directory)):
                self.assertTrue((REPO_ROOT / directory / "AGENTS.md").is_file())
                self.assertTrue((REPO_ROOT / directory / "CLAUDE.md").is_file())

    def test_claude_docs_point_to_local_agents_first(self) -> None:
        for directory in DOC_PAIRS:
            path = REPO_ROOT / directory / "CLAUDE.md"
            body = path.read_text(encoding="utf-8")
            with self.subTest(path=str(path.relative_to(REPO_ROOT))):
                self.assertIn("Read the local `AGENTS.md` first", body)

    def test_path_specific_agent_doc_semantics(self) -> None:
        for relative_path, required_terms in PATH_SPECIFIC_TERMS.items():
            body = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
            for term in required_terms:
                with self.subTest(path=relative_path, term=term):
                    self.assertIn(term, body)


    def test_runbook_docs_preserve_operational_contracts(self) -> None:
        for relative_path, required_terms in RUNBOOK_SPECIFIC_TERMS.items():
            body = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
            for term in required_terms:
                with self.subTest(path=relative_path, term=term):
                    self.assertIn(term, body)

    def test_verification_runbook_documents_remote_only_final_checks(self) -> None:
        body = (REPO_ROOT / "docs/runbooks/verification.md").read_text(encoding="utf-8")
        self.assertIn("ssh hoddukzoa@kiostation", body)
        for command in REMOTE_VERIFICATION_COMMANDS:
            with self.subTest(command=command):
                self.assertIn(command, body)


    def test_env_example_keeps_openai_realtime_primary_and_scopes_gemini_to_coach_feedback(self) -> None:
        body = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("OPENAI_REALTIME_PRIMARY=true", body)
        self.assertIn("REALTIME_MMM_FORWARD_ENABLED=true", body)
        self.assertIn("COACH_LLM_PROVIDER=fake", body)
        self.assertIn("COACH_LLM_MODEL=", body)
        self.assertIn("COACH_LLM_TIMEOUT_SECONDS=15", body)
        self.assertIn("COACH_GEMINI_API_KEY=", body)
        self.assertIn("GEMINI_API_BASE=https://generativelanguage.googleapis.com/v1beta", body)
        self.assertNotIn("AI_ENGINE_INTERNAL_URL", body)
        self.assertNotIn("services/ai-engine", body)
        self.assertIsNone(re.search(r"(?m)^GEMINI_API_KEY=", body))
        self.assertIsNone(re.search(r"(?m)^GEMINI_MODEL=", body))
        self.assertIsNone(re.search(r"(?m)^GEMINI_TTS_MODEL=", body))
        self.assertIsNone(re.search(r"(?m)^OPENAI_REALTIME_PRIMARY=false$", body))

    def test_default_runtime_contracts_do_not_reference_ai_engine_service(self) -> None:
        checked_paths = [
            REPO_ROOT / ".env.example",
            REPO_ROOT / "infra" / "docker-compose.yml",
            REPO_ROOT / "docs" / "runbooks" / "verification.md",
            REPO_ROOT / "scripts" / "kiostation-verify-archive.sh",
        ]
        forbidden_terms = [
            "AI_ENGINE_INTERNAL_URL",
            "http://ai-engine:8100",
            "services/ai-engine/server.py",
        ]
        for path in checked_paths:
            body = path.read_text(encoding="utf-8")
            for term in forbidden_terms:
                with self.subTest(path=str(path.relative_to(REPO_ROOT)), term=term):
                    self.assertNotIn(term, body)

    def test_analysis_engine_remains_core_default_runtime_boundary(self) -> None:
        compose = (REPO_ROOT / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("analysis-engine", compose)
        self.assertIn("ANALYSIS_ENGINE_INTERNAL_URL", compose)
        self.assertIn("http://analysis-engine:8200", compose)
        self.assertNotRegex(compose, r"analysis-engine:[\s\S]*?depends_on:[\s\S]*?ai-engine")

    def test_agent_docs_do_not_include_raw_secret_shapes(self) -> None:
        for path in self.agent_doc_paths():
            body = path.read_text(encoding="utf-8")
            rel = str(path.relative_to(REPO_ROOT))
            with self.subTest(path=rel):
                self.assertIsNone(JWT_RE.search(body))
                self.assertIsNone(GOOGLE_AI_KEY_RE.search(body))
                self.assertIsNone(LIVEKIT_SECRET_RE.search(body))

    def test_agent_docs_do_not_claim_future_features_are_complete(self) -> None:
        combined = "\n".join(path.read_text(encoding="utf-8") for path in self.agent_doc_paths())
        for phrase in FORBIDDEN_IMPLEMENTED_CLAIMS:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, combined)
        self.assertIn("not complete product features yet", (REPO_ROOT / "services" / "analysis-engine" / "AGENTS.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
