from __future__ import annotations

import pathlib
import re
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

DOC_PAIRS = [
    pathlib.Path("."),
    pathlib.Path("apps/web"),
    pathlib.Path("services/api"),
    pathlib.Path("services/ai-engine"),
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
    "services/ai-engine/AGENTS.md": ["Realtime-only", "VOICE_PROVIDER=fake", "VOICE_PROVIDER=elevenlabs"],
    "services/agent1/AGENTS.md": ["future multimodal placeholder", "structured signal", "raw media"],
    "infra/AGENTS.md": ["Caddy", "LiveKit", "coturn", "direct media", "/ai/*", "broker routes", "Direct public"],
    "tests/AGENTS.md": ["tests/contract", "tests/integration", "path-specific"],
    "docs/AGENTS.md": ["architecture.noml", "generated", "English"],
    "packages/shared/AGENTS.md": ["shared contracts", "premature abstractions"],
    "scripts/AGENTS.md": ["smoke", "token redaction", "fail-closed"],
}

RUNBOOK_SPECIFIC_TERMS = {
    "docs/runbooks/verification.md": [
        "ssh hoddukzoa@kiostation",
        "node --check apps/web/static/app.js",
        "py_compile services/api/server.py services/ai-engine/server.py services/analysis-engine/server.py",
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
        "VOICE_PROVIDER=fake",
        "Gemini TTS fallback is removed",
        "TTS_PROVIDER_FAILURE_FALLBACK",
        "AVATAR_PROVIDER=disabled",
        "AVATAR_PROVIDER_FAILURE_FALLBACK=disabled",
        "post-TTS publisher only",
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
    "PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile services/api/server.py services/ai-engine/server.py services/analysis-engine/server.py",
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


    def test_env_example_keeps_openai_realtime_primary_and_removes_gemini_fallback(self) -> None:
        body = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("OPENAI_REALTIME_PRIMARY=true", body)
        self.assertIn("LLM_PROVIDER=fake", body)
        self.assertIn("REALTIME_MMM_FORWARD_ENABLED=true", body)
        self.assertNotIn("GEMINI_API_KEY", body)
        self.assertNotIn("GEMINI_MODEL", body)
        self.assertNotIn("GEMINI_TTS_MODEL", body)
        self.assertIsNone(re.search(r"(?m)^OPENAI_REALTIME_PRIMARY=false$", body))

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
        self.assertIn("not complete product features yet", (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
