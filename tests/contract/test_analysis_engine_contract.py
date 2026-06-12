from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ANALYSIS_ENGINE_ROOT = REPO_ROOT / "services" / "analysis-engine"
PINNED_GILJOBE_REF = "5ba7249"
# Superseded pins must not resurface anywhere a stale copy could mislead operators.
OLD_GILJOBE_REFS = ("b769120", "88a4df5", "e0671f5")


def load_analysis_engine_wrapper():
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.web = types.SimpleNamespace()

    server_main = types.ModuleType("giljobe.server.__main__")
    server_main._build_critic = lambda: types.SimpleNamespace(warmup=lambda: None)
    server_main._make_lanes = lambda: []
    server_main._port = lambda: 8200
    server_main._vllm_ready = lambda _critic: True

    http_app = types.ModuleType("giljobe.server.http_app")
    http_app.make_app = lambda _service, ready_check=None: None

    service_mod = types.ModuleType("giljobe.server.service")
    service_mod.AnalysisService = lambda **_kwargs: object()
    service_mod.signals_payload = lambda session_id, records: {
        "service": "analysis-engine",
        "sessionId": session_id,
        "records": records,
        "recordCount": len(records),
        "turnHandoff": None,
        "rawMediaExposed": False,
        "rawSecretsExposed": False,
    }

    sys.modules["aiohttp"] = aiohttp
    sys.modules.setdefault("giljobe", types.ModuleType("giljobe"))
    sys.modules.setdefault("giljobe.server", types.ModuleType("giljobe.server"))
    sys.modules["giljobe.server.__main__"] = server_main
    sys.modules["giljobe.server.http_app"] = http_app
    sys.modules["giljobe.server.service"] = service_mod

    spec = importlib.util.spec_from_file_location("analysis_engine_wrapper_contract", ANALYSIS_ENGINE_ROOT / "server.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AnalysisEngineContractTest(unittest.TestCase):
    def test_analysis_engine_runs_giljobe_app_with_realtime_mmm_ingress_wrapper(self) -> None:
        wrapper = (ANALYSIS_ENGINE_ROOT / "server.py").read_text()
        self.assertIn("from giljobe.server.http_app import make_app", wrapper)
        self.assertIn('web.post("/realtime/turn-events"', wrapper)
        self.assertIn("raw_payload_not_allowed", wrapper)
        self.assertIn("rawTranscriptLogged", wrapper)
        self.assertIn("rawMediaAccepted", wrapper)
        self.assertIn("perTurnMmmResult", wrapper)
        self.assertIn("candidateSafePromptFragment", wrapper)
        self.assertIn("class _EventOnlyRealtimeTurns", wrapper)
        self.assertIn("_install_event_only_realtime_fallback", wrapper)
        self.assertIn("realtimeNativeAnalysisSession", wrapper)
        self.assertIn("_active_by_key", wrapper)
        self.assertIn("_finalized_by_key", wrapper)
        self.assertIn("2026-06-12.per-turn-mmm-result.v1", wrapper)
        self.assertIn("2026-06-12.candidate-safe-prompt-fragment.v1", wrapper)
        dockerfile = (ANALYSIS_ENGINE_ROOT / "Dockerfile").read_text()
        self.assertIn("python:3.12-slim", dockerfile)
        self.assertNotIn("python:3.12-alpine", dockerfile)
        self.assertIn("git ffmpeg ca-certificates", dockerfile)
        self.assertIn("ANALYSIS_ENGINE_PORT=8200", dockerfile)
        self.assertIn(f"GILJOBE_GIT_REF={PINNED_GILJOBE_REF}", dockerfile)
        self.assertIn("COPY server.py /app/server.py", dockerfile)
        self.assertIn('CMD ["python", "/app/server.py"]', dockerfile)

    def test_realtime_mmm_ingress_outputs_candidate_safe_per_turn_context(self) -> None:
        module = load_analysis_engine_wrapper()
        record = module._public_record({
            "schema_version": "2026-06-11.realtime-mmm-ingress.v1",
            "sessionId": "local-demo",
            "turnId": "2",
            "turnIndex": 2,
            "eventKind": "readiness_gate.full_mmm_ready",
            "readiness": {
                "full_mmm_ready": True,
                "state": "full_mmm_ready",
                "reasonCodes": ["ready"],
                "lanes": {
                    "transcript": {"ready": True, "observed": True, "status": "complete"},
                    "prosody": {"ready": True, "observed": True, "status": "complete"},
                    "vision": {"ready": True, "observed": True, "status": "complete"},
                },
            },
        })
        self.assertEqual(record["perTurnMmmResult"]["schemaVersion"], "2026-06-12.per-turn-mmm-result.v1")
        self.assertTrue(record["perTurnMmmResult"]["ready"])
        self.assertEqual(record["perTurnMmmResult"]["lanes"]["transcript"]["status"], "complete")
        fragment = record["candidateSafePromptFragment"]
        self.assertEqual(fragment["schemaVersion"], "2026-06-12.candidate-safe-prompt-fragment.v1")
        self.assertIn("full_mmm_ready", fragment["text"])
        self.assertFalse(fragment["containsRawTranscript"])
        self.assertFalse(fragment["containsRawMedia"])
        self.assertFalse(fragment["containsSecrets"])

    def test_realtime_mmm_ingress_rejects_public_raw_media_and_secret_shapes_but_allows_internal_sentence_detail(self) -> None:
        module = load_analysis_engine_wrapper()
        for payload in (
            {"transcript": "raw candidate answer"},
            {"text": "raw candidate answer"},
            {"rawMedia": "bytes"},
            {"provider": {"token": "secret"}},
        ):
            self.assertTrue(module._contains_forbidden_raw_field(payload), payload)
        for payload in (
            {"detail": {"transcript": "bounded candidate answer"}},
            {"detail": {"text": "bounded candidate answer", "itemId": "item-1"}},
        ):
            self.assertFalse(module._contains_forbidden_raw_field(payload), payload)

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
            for old_ref in OLD_GILJOBE_REFS:
                self.assertNotIn(old_ref, text, label)
        self.assertIn(f"git+https://github.com/GilJob-E/GilJobE.git@{PINNED_GILJOBE_REF}", requirements)
        self.assertIn("/realtime/turn-events", requirements)

    def test_grounding_lane_assets_and_toggles_are_wired(self) -> None:
        """GilJobE objective grounding lanes (vision/prosody): the image must install the
        extras and bake the MediaPipe models; compose must pass the lane toggles through."""
        requirements = (ANALYSIS_ENGINE_ROOT / "requirements.txt").read_text()
        dockerfile = (ANALYSIS_ENGINE_ROOT / "Dockerfile").read_text()
        compose = (REPO_ROOT / "infra" / "docker-compose.yml").read_text()
        env_example = (REPO_ROOT / ".env.example").read_text()
        self.assertIn("giljobe[vision,prosody]", requirements)
        self.assertIn("GILJOBE_VISION_MODELS_DIR=/app/models", dockerfile)
        self.assertIn("face_landmarker.task", dockerfile)
        self.assertIn("pose_landmarker.task", dockerfile)
        # MediaPipe C bindings dlopen GLES/EGL even for CPU inference (verified in-container);
        # dropping these silently disables the vision lane at runtime.
        self.assertIn("libegl1", dockerfile)
        self.assertIn("libgles2", dockerfile)
        for text in (compose, env_example):
            self.assertIn("GILJOBE_VISION", text)
            self.assertIn("GILJOBE_PROSODY", text)
            # Realtime sentence lane: transcript-source toggle must stay wired and default to sideband.
            self.assertIn("GILJOBE_TRANSCRIPT_SOURCE", text)
        self.assertIn("GILJOBE_TRANSCRIPT_SOURCE: ${GILJOBE_TRANSCRIPT_SOURCE:-external}", compose)

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
            "/subscriber/start",
            "/subscriber/stop",
            "/signals",
            "/realtime/turn-events",
            "/healthz",
            "/readyz",
            "token-safe",
        ):
            self.assertIn(expected, analysis_docs)
        self.assertIn("builds GilJobE", analysis_docs)
        self.assertIn("ANALYSIS_ENGINE_ENABLE_SUBSCRIBER", analysis_docs)
        self.assertIn("legacy", analysis_docs.lower())

    def test_root_docs_and_verification_no_longer_reference_deleted_wrapper(self) -> None:
        root_readme = (REPO_ROOT / "README.md").read_text()
        analysis_agents = (ANALYSIS_ENGINE_ROOT / "AGENTS.md").read_text()
        self.assertIn("services/analysis-engine/server.py", root_readme)
        self.assertIn("docker build -q services/analysis-engine", root_readme)
        self.assertIn("/realtime/turn-events", analysis_agents)
        self.assertIn("analysis-engine", analysis_agents)

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


class TurnResultsContractTest(unittest.TestCase):
    """GET /realtime/turn-results — API _fetch_analysis_result가 당겨가는 turn_handoff 운반 계약."""

    def test_turn_results_route_serves_turn_handoff_fragment(self) -> None:
        wrapper = (ANALYSIS_ENGINE_ROOT / "server.py").read_text()
        self.assertIn('web.get("/realtime/turn-results"', wrapper)
        self.assertIn("from giljobe.emit.handoff import render_prompt_fragment", wrapper)
        self.assertIn("candidatePromptFragment", wrapper)
        # 구 핀 강등(ImportError → None) + 턴 미완결 pending — API 409 게이트와 정합
        self.assertIn("render_prompt_fragment = None", wrapper)
        self.assertIn('"status": "pending"', wrapper)
        # 활성/last/session-wide 폴백 금지 — exact turn-keyed RNAS storage only.
        self.assertIn("rnas.turn_result(interview_id, turn_index)", wrapper)
        self.assertIn("no_exact_turn_result", wrapper)
        self.assertNotIn("service.signals(None)", wrapper)
        # exact-turn RNAS: stale/wrong turn handoffs must degrade to pending
        self.assertIn("_turn_handoff_matches_requested_turn", wrapper)
        self.assertIn("requested_turn_index", wrapper)

    def test_realtime_native_analysis_session_is_exact_turn_keyed_and_requires_all_lanes(self) -> None:
        module = load_analysis_engine_wrapper()
        rnas = module._EventOnlyRealtimeTurns()
        start = rnas.ingest({"interviewId": "demo", "turnIndex": 1, "eventKind": "turn.answer_started"})
        self.assertTrue(start["accepted"])
        rnas.ingest({"interviewId": "demo", "turnIndex": 1, "eventKind": "analysis.transcript.completed", "detail": {"transcript": "bounded answer", "itemId": "i1"}})
        rnas.ingest({"interviewId": "demo", "turnIndex": 1, "eventKind": "prosody.window_metrics"})
        rnas.ingest({"interviewId": "demo", "turnIndex": 1, "eventKind": "vision.frame_metrics"})
        end = rnas.ingest({"interviewId": "demo", "turnIndex": 1, "eventKind": "turn.answer_ended"})
        self.assertTrue(end["accepted"])
        ready = rnas.turn_result("demo", 1)
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["turnIndex"], 1)
        self.assertIn("candidatePromptFragment", ready)
        self.assertFalse(ready["rawTranscriptLogged"])
        self.assertEqual(rnas.turn_result("demo", 2)["reason"], "no_exact_turn_result")
        self.assertEqual(rnas.turn_result("other", 1)["reason"], "no_exact_turn_result")

    def test_realtime_native_analysis_session_missing_lane_stays_pending(self) -> None:
        module = load_analysis_engine_wrapper()
        rnas = module._EventOnlyRealtimeTurns()
        rnas.ingest({"interviewId": "demo", "turnIndex": 1, "eventKind": "turn.answer_started"})
        rnas.ingest({"interviewId": "demo", "turnIndex": 1, "eventKind": "analysis.transcript.completed", "detail": {"transcript": "bounded answer", "itemId": "i1"}})
        rnas.ingest({"interviewId": "demo", "turnIndex": 1, "eventKind": "turn.answer_ended"})
        pending = rnas.turn_result("demo", 1)
        self.assertEqual(pending["status"], "pending")
        self.assertIn(pending["reason"], {"missing_prosody", "missing_vision"})

    def test_turn_results_loads_with_legacy_pin_mocks(self) -> None:
        # giljobe.emit.handoff가 없는(구 핀) 모킹 환경에서도 래퍼 로드는 성공해야 한다
        module = load_analysis_engine_wrapper()
        self.assertTrue(hasattr(module, "_realtime_turn_results"))
        self.assertIsNone(module.render_prompt_fragment)

    def test_turn_results_exact_turn_guard_rejects_wrong_stale_or_ambiguous_handoff(self) -> None:
        module = load_analysis_engine_wrapper()
        handoff = {"meta": {"turnIndex": 3, "coverage": {"transcript": True}}}
        payload = {"sessionId": "local-demo", "turnHandoff": handoff}

        self.assertTrue(module._turn_handoff_matches_requested_turn(payload, handoff, 3))
        self.assertFalse(module._turn_handoff_matches_requested_turn(payload, handoff, 2))
        self.assertFalse(module._turn_handoff_matches_requested_turn({"turnHandoff": {"meta": {}}}, {"meta": {}}, 3))

    def test_turn_results_exact_turn_guard_accepts_record_backed_event_only_fallback(self) -> None:
        module = load_analysis_engine_wrapper()
        handoff = {"meta": {"coverage": {"transcript": True}}}
        payload = {
            "sessionId": "local-demo",
            "turnHandoff": handoff,
            "records": [
                {"type": "sentence", "turnIndex": 4},
                {"type": "turn_end", "turnIndex": 4},
            ],
        }

        self.assertTrue(module._turn_handoff_matches_requested_turn(payload, handoff, 4))
        self.assertFalse(module._turn_handoff_matches_requested_turn(payload, handoff, 5))
