#!/usr/bin/env python3
"""GilJobE-backed analysis-engine boundary for GilJob v2.

The service owns the GilJobE analysis boundary.  In standby it exposes a safe
contract; when `/subscriber/start` is called it starts a background LiveKit
subscriber as a hidden analyzer participant.  Signal generation can run in a
mock critic mode for join/smoke tests, or in GilJobE WindowCritic mode when the
model runtime is available.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SERVICE_NAME = os.getenv("SERVICE_NAME", "analysis-engine")
PORT = int(os.getenv("SERVICE_PORT", "8200"))
GILJOBE_GIT_URL = os.getenv("GILJOBE_GIT_URL", "https://github.com/GilJob-E/GilJobE.git")
GILJOBE_GIT_REF = os.getenv("GILJOBE_GIT_REF", "b769120")
SIGNAL_DIR = Path(os.getenv("ANALYSIS_ENGINE_SIGNAL_DIR", "/tmp/giljob-analysis-signals"))
DEFAULT_CRITIC_MODE = os.getenv("GILJOBE_CRITIC_MODE", "mock").strip().lower() or "mock"
DUMMY_SCENARIO_ENV = "ANALYSIS_ENGINE_DUMMY_SCENARIO"

SECRET_ENV_KEYS = ("LIVEKIT_TOKEN", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")


def _dummy_scenario_name() -> str:
    return os.getenv(DUMMY_SCENARIO_ENV, "").strip()


def _dummy_mode_enabled() -> bool:
    value = _dummy_scenario_name().lower()
    return bool(value and value not in {"0", "false", "off", "disabled", "none"})


def _safe_session_id(value: object | None) -> str:
    session_id = str(value or "").strip()
    if not SESSION_ID_RE.fullmatch(session_id):
        raise ValueError("invalid session id")
    return session_id


def _read_signal_records(session_id: str) -> list[dict[str, Any]]:
    signal_path = SIGNAL_DIR / f"{session_id}.jsonl"
    if not signal_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in signal_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            records.append({"type": "parse_error"})
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _signals_payload(session_id: str) -> dict[str, Any]:
    if _dummy_mode_enabled():
        return DUMMY_RUNTIME.signals(session_id)
    records = _read_signal_records(session_id)
    turn_ends = [record for record in records if record.get("type") == "turn_end"]
    window_transcripts = [
        str(record.get("transcript", "")).strip()
        for record in records
        if record.get("type") == "window" and str(record.get("transcript", "")).strip()
    ]
    latest_turn_end = turn_ends[-1] if turn_ends else None
    transcript_full = str((latest_turn_end or {}).get("transcript_full", "")).strip()
    return {
        "service": SERVICE_NAME,
        "sessionId": session_id,
        "records": records,
        "recordCount": len(records),
        "latestTurnEnd": latest_turn_end,
        "transcriptFull": transcript_full,
        "windowTranscripts": window_transcripts,
        "rawSecretsExposed": False,
        "rawMediaExposed": False,
    }

def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _secret_configured(name: str) -> bool:
    value = os.getenv(name, "")
    return bool(value and not value.startswith("replace-me"))


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    body = handler.rfile.read(length).decode("utf-8")
    if not body.strip():
        return {}
    return json.loads(body)


def _giljobe_dependency() -> dict[str, Any]:
    try:
        pkg = importlib.import_module("giljobe")
        importlib.import_module("giljobe.server.app")
        importlib.import_module("giljobe.server.config")
        importlib.import_module("giljobe.analysis.transcriber")
        importlib.import_module("giljobe.analysis.critic")
        importlib.import_module("giljobe.analysis.mocks")
        importlib.import_module("giljobe.emit.sink")
    except Exception as exc:  # noqa: BLE001 - health should expose class only, not secrets
        return {
            "importable": False,
            "errorType": exc.__class__.__name__,
        }
    return {
        "importable": True,
        "package": getattr(pkg, "__name__", "giljobe"),
        "sourceUrl": GILJOBE_GIT_URL,
        "sourceRef": GILJOBE_GIT_REF,
        "sttProvider": "GemmaNativeTranscriber",
        "subscriberFactory": "giljobe.server.app.build_subscriber",
    }


def _livekit_contract() -> dict[str, Any]:
    token_configured = _secret_configured("LIVEKIT_TOKEN")
    api_credentials_configured = _secret_configured("LIVEKIT_API_KEY") and _secret_configured("LIVEKIT_API_SECRET")
    return {
        "urlConfigured": bool(os.getenv("LIVEKIT_URL", "").strip()),
        "tokenConfigured": token_configured,
        "apiCredentialsConfigured": api_credentials_configured,
        "tokenSource": "preissued" if token_configured else ("api_credentials" if api_credentials_configured else "missing"),
        "sessionIdConfigured": bool(os.getenv("LIVEKIT_SESSION_ID", "").strip()),
        "rawSecretsExposed": False,
    }


def _contract_payload() -> dict[str, Any]:
    subscriber_enabled = _enabled(os.getenv("ANALYSIS_ENGINE_ENABLE_SUBSCRIBER"))
    dummy_enabled = _dummy_mode_enabled()
    return {
        "service": SERVICE_NAME,
        "mode": "dummy-scenario" if dummy_enabled else ("subscriber-enabled" if subscriber_enabled else "standby"),
        "subscriberEnabled": subscriber_enabled,
        "dummyScenario": _dummy_scenario_name() if dummy_enabled else None,
        "criticMode": DEFAULT_CRITIC_MODE,
        "giljobe": _giljobe_dependency(),
        "livekit": _livekit_contract(),
        "owns": ["stt", "nonverbal", "multimodal-signals", "transcript_full"],
        "doesNotOwn": ["candidate-token-issuance", "main-llm", "tts", "avatar", "final-report"],
        "sttPath": "GilJobE",
    }


def _ready_payload() -> tuple[int, dict[str, Any]]:
    payload = _contract_payload()
    if payload.get("dummyScenario"):
        return 200, {**payload, "status": "ready"}
    if not payload["subscriberEnabled"]:
        return 200, {**payload, "status": "standby"}
    giljobe_ready = bool(payload["giljobe"].get("importable"))
    livekit = payload["livekit"]
    livekit_ready = bool(livekit["urlConfigured"] and (livekit["tokenConfigured"] or livekit["apiCredentialsConfigured"]))
    ready = giljobe_ready and livekit_ready
    return (200 if ready else 503), {**payload, "status": "ready" if ready else "not_ready"}


def _make_critic(mode: str):
    mode = (mode or "mock").strip().lower()
    if mode == "window":
        from giljobe.analysis.critic import WindowCritic

        return WindowCritic()
    if mode == "mock":
        from giljobe.analysis.mocks import MockCritic

        return MockCritic()
    raise ValueError(f"unsupported critic mode: {mode}")


class DummyScenarioRuntime:
    """Small local stand-in for GilJobE/MMM signal IO.

    This is intentionally env-gated and process-local. It emits the same public
    `/signals` record shape the API ingests, but it never touches LiveKit, media,
    provider keys, or model runtimes.
    """

    _turns: tuple[dict[str, Any], ...] = (
        {
            "transcript": "I connected payment consistency work to the backend role.",
            "rate": 5.2,
            "pitch": 218,
            "pause": 1,
            "smile": 0.18,
            "gaze": 0.22,
            "blink": 1,
            "observations": ["Motivation is tied to a concrete backend experience."],
            "critique": ["Add one sharper business outcome when revisiting this story."],
        },
        {
            "transcript": "I narrowed duplicate payout failures with idempotency keys and timeline logs.",
            "rate": 5.8,
            "pitch": 235,
            "pause": 0,
            "smile": 0.12,
            "gaze": 0.31,
            "blink": 2,
            "observations": ["Root-cause flow is specific and technically grounded."],
            "critique": ["Name the detection signal before the implementation detail."],
        },
        {
            "transcript": "I resolved a schema disagreement by comparing trade-offs with the team.",
            "rate": 4.7,
            "pitch": 205,
            "pause": 2,
            "smile": 0.15,
            "gaze": 0.27,
            "blink": 1,
            "observations": ["Collaboration style shows evidence-based compromise."],
            "critique": ["Clarify which principle you would not compromise on."],
        },
    )

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, dict[str, Any]] = {}

    def status(self) -> dict[str, Any]:
        with self._lock:
            active = [sid for sid, state in self._sessions.items() if state.get("running")]
        return {
            "state": "dummy_running" if active else "dummy_standby",
            "scenario": _dummy_scenario_name(),
            "activeSessions": active,
            "rawSecretsExposed": False,
            "rawMediaExposed": False,
        }

    def start(self, *, session_id: str | None = None, critic_mode: str | None = None) -> tuple[int, dict[str, Any]]:
        sid = _safe_session_id(session_id or os.getenv("LIVEKIT_SESSION_ID", "local-demo"))
        with self._lock:
            state = self._state_for(sid)
            state["running"] = True
            state["criticMode"] = critic_mode or DEFAULT_CRITIC_MODE
            self._stage_turn_locked(sid, state)
            return 202, {
                "status": "starting",
                "state": "dummy_running",
                "sessionId": sid,
                "criticMode": state["criticMode"],
                "scenario": _dummy_scenario_name(),
                "rawSecretsExposed": False,
                "rawMediaExposed": False,
            }

    def stop(self) -> tuple[int, dict[str, Any]]:
        with self._lock:
            stopped: list[str] = []
            for sid, state in self._sessions.items():
                if state.get("running"):
                    self._finish_turn_locked(sid, state)
                    state["running"] = False
                    stopped.append(sid)
            return 200, {
                "status": "stopped",
                "state": "dummy_stopped",
                "sessions": stopped,
                "scenario": _dummy_scenario_name(),
            }

    def signals(self, session_id: str) -> dict[str, Any]:
        sid = _safe_session_id(session_id)
        with self._lock:
            state = self._state_for(sid)
            records = [dict(record) for record in state["records"]]
        turn_ends = [record for record in records if record.get("type") == "turn_end"]
        window_transcripts = [
            str(record.get("transcript", "")).strip()
            for record in records
            if record.get("type") == "window" and str(record.get("transcript", "")).strip()
        ]
        latest_turn_end = turn_ends[-1] if turn_ends else None
        return {
            "service": SERVICE_NAME,
            "sessionId": sid,
            "records": records,
            "recordCount": len(records),
            "latestTurnEnd": latest_turn_end,
            "transcriptFull": str((latest_turn_end or {}).get("transcript_full", "")).strip(),
            "windowTranscripts": window_transcripts,
            "giljobeRef": "dummy-scenario",
            "scenario": _dummy_scenario_name(),
            "rawSecretsExposed": False,
            "rawMediaExposed": False,
        }

    def _state_for(self, session_id: str) -> dict[str, Any]:
        return self._sessions.setdefault(session_id, {"records": [], "running": False, "turn": 1, "staged": None})

    def _stage_turn_locked(self, session_id: str, state: dict[str, Any]) -> None:
        if state.get("staged") is not None:
            return
        turn_index = int(state.get("turn") or 1)
        turn = self._turns[(turn_index - 1) % len(self._turns)]
        seq = len(state["records"]) + 1
        state["records"].append({
            "type": "window",
            "seq": seq,
            "session_id": session_id,
            "transcript": turn["transcript"],
            "ts": time.time(),
        })
        state["records"].append({
            "type": "eval",
            "seq": seq + 1,
            "session_id": session_id,
            "eval": self._eval_for_turn(turn),
            "ts": time.time(),
        })
        state["staged"] = turn

    def _finish_turn_locked(self, session_id: str, state: dict[str, Any]) -> None:
        turn = state.get("staged")
        if not isinstance(turn, dict):
            self._stage_turn_locked(session_id, state)
            turn = state.get("staged")
        if not isinstance(turn, dict):
            return
        state["records"].append({
            "type": "turn_end",
            "seq": len(state["records"]) + 1,
            "session_id": session_id,
            "transcript_full": turn["transcript"],
            "ts": time.time(),
        })
        state["turn"] = int(state.get("turn") or 1) + 1
        state["staged"] = None

    @staticmethod
    def _eval_for_turn(turn: dict[str, Any]) -> dict[str, Any]:
        return {
            "objective_vocal": {
                "pitch": {"mean_hz": turn["pitch"]},
                "rate": {"speech_rate_syl_per_s": turn["rate"]},
                "pauses": {
                    "pause_count_ge_0p25": turn["pause"],
                    "short_juncture_count_0p1_0p25": max(0, int(turn["pause"]) - 1),
                },
            },
            "objective_visual": {
                "face_seen_ratio": 0.95,
                "smile_mean": turn["smile"],
                "smile_ratio": turn["smile"],
                "gaze_off_mean": turn["gaze"],
                "blink_count": turn["blink"],
                "head_sway": 0.018 + (float(turn["gaze"]) / 10),
                "gesture_events": 1,
            },
            "key_observations": list(turn["observations"]),
            "critique": list(turn["critique"]),
        }


class SubscriberRuntime:
    """Process-local manager for one background GilJobE LiveKit subscriber."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._subscriber = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._status: dict[str, Any] = {"state": "stopped"}

    def status(self) -> dict[str, Any]:
        with self._lock:
            payload = dict(self._status)
            thread = self._thread
        payload["threadAlive"] = bool(thread and thread.is_alive())
        return payload

    def start(self, *, session_id: str | None = None, critic_mode: str | None = None) -> tuple[int, dict[str, Any]]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return 200, {"status": "already_running", **dict(self._status), "threadAlive": True}
            self._status = {
                "state": "starting",
                "startedAt": time.time(),
                "sessionId": session_id or os.getenv("LIVEKIT_SESSION_ID", "local"),
                "criticMode": (critic_mode or DEFAULT_CRITIC_MODE),
            }
            self._thread = threading.Thread(
                target=self._thread_main,
                kwargs={"session_id": session_id, "critic_mode": critic_mode or DEFAULT_CRITIC_MODE},
                name="giljobe-livekit-subscriber",
                daemon=True,
            )
            self._thread.start()
            return 202, {"status": "starting", **dict(self._status), "threadAlive": True}

    def stop(self) -> tuple[int, dict[str, Any]]:
        with self._lock:
            loop = self._loop
            subscriber = self._subscriber
            stop_event = self._stop_event
            if subscriber is None or loop is None:
                self._status = {"state": "stopped", "stoppedAt": time.time()}
                return 200, {"status": "stopped"}
            self._status = {**self._status, "state": "stopping", "stoppingAt": time.time()}
        if stop_event is not None:
            loop.call_soon_threadsafe(stop_event.set)
        fut = asyncio.run_coroutine_threadsafe(subscriber.aclose(), loop)
        try:
            fut.result(timeout=10)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._status = {**self._status, "state": "stop_error", "errorType": exc.__class__.__name__}
            return 500, {"status": "stop_error", "errorType": exc.__class__.__name__}
        with self._lock:
            self._status = {"state": "stopped", "stoppedAt": time.time()}
            self._subscriber = None
        return 200, {"status": "stopped"}

    def _thread_main(self, *, session_id: str | None, critic_mode: str) -> None:
        try:
            asyncio.run(self._run(session_id=session_id, critic_mode=critic_mode))
        except Exception as exc:  # noqa: BLE001 - surface class only; do not leak config/token
            with self._lock:
                self._status = {
                    **self._status,
                    "state": "error",
                    "errorType": exc.__class__.__name__,
                    "errorCode": "subscriber_runtime_error",
                    "endedAt": time.time(),
                }
        finally:
            with self._lock:
                self._loop = None
                self._subscriber = None
                self._stop_event = None

    async def _run(self, *, session_id: str | None, critic_mode: str) -> None:
        from giljobe.emit.sink import JSONLSink
        from giljobe.server.app import build_subscriber
        from giljobe.server.config import SubscriberConfig

        config = SubscriberConfig.from_env(session_id=session_id)
        if not config.token:
            raise RuntimeError("LiveKit token could not be resolved from LIVEKIT_TOKEN or API credentials")
        SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
        signal_path = SIGNAL_DIR / f"{config.session_id}.jsonl"
        critic = _make_critic(critic_mode)
        subscriber = build_subscriber(critic, [JSONLSink(signal_path)], config)
        loop = asyncio.get_running_loop()
        with self._lock:
            self._loop = loop
            self._subscriber = subscriber
            self._stop_event = asyncio.Event()
            self._status = {
                **self._status,
                "state": "connecting",
                "livekitUrlConfigured": True,
                "room": config.room,
                "identity": config.identity,
                "signalPath": str(signal_path),
            }
        await subscriber.start()
        await subscriber.connect(config.url, config.token)
        with self._lock:
            self._status = {**self._status, "state": "connected", "connectedAt": time.time()}
        assert self._stop_event is not None
        try:
            await self._stop_event.wait()
        finally:
            await subscriber.aclose()
        with self._lock:
            self._status = {**self._status, "state": "stopped", "endedAt": time.time()}


RUNTIME = SubscriberRuntime()
DUMMY_RUNTIME = DummyScenarioRuntime()


def _runtime_status() -> dict[str, Any]:
    return DUMMY_RUNTIME.status() if _dummy_mode_enabled() else RUNTIME.status()


class Handler(BaseHTTPRequestHandler):
    server_version = "GilJobV2AnalysisEngine/0.2"

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path == "/healthz":
            self._json(200, {"service": SERVICE_NAME, "status": "ok", **_contract_payload(), "runtime": _runtime_status()})
            return
        if self.path == "/readyz":
            status, payload = _ready_payload()
            self._json(status, {**payload, "runtime": _runtime_status()})
            return
        if self.path == "/contract":
            self._json(200, _contract_payload())
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/subscriber/status":
            self._json(200, {"service": SERVICE_NAME, "runtime": _runtime_status()})
            return
        if parsed.path == "/signals":
            params = urllib.parse.parse_qs(parsed.query)
            try:
                session_id = _safe_session_id((params.get("sessionId") or params.get("session_id") or [None])[0])
            except ValueError as exc:
                self._json(400, {"error": "invalid_session_id", "message": str(exc)})
                return
            self._json(200, _signals_payload(session_id))
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path == "/subscriber/start":
            try:
                body = _read_json_body(self)
                if _dummy_mode_enabled():
                    status, payload = DUMMY_RUNTIME.start(
                        session_id=body.get("sessionId") or body.get("session_id"),
                        critic_mode=body.get("criticMode") or body.get("critic_mode"),
                    )
                else:
                    status, payload = RUNTIME.start(
                        session_id=body.get("sessionId") or body.get("session_id"),
                        critic_mode=body.get("criticMode") or body.get("critic_mode"),
                    )
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid_json"})
                return
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": "subscriber_start_failed", "errorType": exc.__class__.__name__})
                return
            self._json(status, payload)
            return
        if self.path == "/subscriber/stop":
            status, payload = DUMMY_RUNTIME.stop() if _dummy_mode_enabled() else RUNTIME.stop()
            self._json(status, payload)
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def log_message(self, fmt: str, *args: object) -> None:
        # Do not include request headers or env values; path-only logs are token safe.
        print(f"{self.address_string()} - {fmt % args}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
