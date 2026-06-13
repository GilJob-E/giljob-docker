#!/usr/bin/env python3
"""Minimal GilJob v2 API scaffold.

Security contracts kept in scaffold:
- internal API paths are not exposed;
- raw session/report tokens are returned only in the create-session response;
- server-side records keep purpose-separated token hashes only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from app.token_contract import issue_session

SERVICE_NAME = os.getenv("SERVICE_NAME", "api")
PORT = int(os.getenv("SERVICE_PORT", "8000"))
MAX_JSON_BODY_BYTES = int(os.getenv("MAX_JSON_BODY_BYTES", "65536"))
ANALYSIS_ENGINE_INTERNAL_URL = os.getenv("ANALYSIS_ENGINE_INTERNAL_URL", "http://analysis-engine:8200").rstrip("/")
OPENAI_REALTIME_API_BASE = os.getenv("OPENAI_REALTIME_API_BASE", "https://api.openai.com/v1").rstrip("/")
OPENAI_REALTIME_MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2")
OPENAI_REALTIME_VOICE = os.getenv("OPENAI_REALTIME_VOICE", "marin")
OPENAI_REALTIME_TRANSCRIPTION_MODEL = os.getenv("OPENAI_REALTIME_TRANSCRIPTION_MODEL", "gpt-realtime-whisper").strip() or "gpt-realtime-whisper"
OPENAI_REALTIME_TRANSCRIPTION_LANGUAGE = os.getenv("OPENAI_REALTIME_TRANSCRIPTION_LANGUAGE", "ko").strip()
OPENAI_REALTIME_TRANSCRIPTION_DELAY = os.getenv("OPENAI_REALTIME_TRANSCRIPTION_DELAY", "low").strip()
OPENAI_REALTIME_TIMEOUT_SECONDS = float(os.getenv("OPENAI_REALTIME_TIMEOUT_SECONDS", "15"))
COACH_LLM_TIMEOUT_SECONDS = float(os.getenv("COACH_LLM_TIMEOUT_SECONDS", "15"))
INTERVIEW_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
TTS_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/turns/([0-9]{1,4})/tts/?$")
AVATAR_SESSION_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/avatar/session/?$")
NEXT_QUESTION_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/turns/([0-9]{1,4})/question/?$")
REALTIME_SESSION_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/realtime/session/?$")
REALTIME_CALL_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/realtime/call/?$")
REALTIME_TURN_EVENTS_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/turns/([0-9]{1,4})/events/?$")
REALTIME_VISION_EVENTS_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/turns/([0-9]{1,4})/vision-events/?$")
REALTIME_MMM_READY_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/turns/([0-9]{1,4})/mmm-ready/?$")
REALTIME_RESPONSE_CREATE_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/turns/([0-9]{1,4})/realtime/response/?$")
COACH_FEEDBACK_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/turns/([0-9]{1,4})/coach-feedback/?$")
MAX_TTS_TEXT_CHARS = 1_200
MAX_REALTIME_EVENT_BYTES = int(os.getenv("MAX_REALTIME_EVENT_BYTES", "8192"))
MAX_REALTIME_VISION_EVENT_BYTES = int(os.getenv("MAX_REALTIME_VISION_EVENT_BYTES", "65536"))
MAX_REALTIME_VISION_FRAME_BYTES = int(os.getenv("MAX_REALTIME_VISION_FRAME_BYTES", "49152"))
REALTIME_MMM_EVENT_LOG_PATH = os.getenv("REALTIME_MMM_EVENT_LOG_PATH", "/tmp/giljob-realtime-mmm-events.jsonl")
REALTIME_MMM_FORWARD_TIMEOUT_SECONDS = float(os.getenv("REALTIME_MMM_FORWARD_TIMEOUT_SECONDS", "2"))
REALTIME_MMM_RESULT_TIMEOUT_SECONDS = float(os.getenv("REALTIME_MMM_RESULT_TIMEOUT_SECONDS", "1.2"))
HASHIMOTO_STRATEGY_TIMEOUT_SECONDS = float(os.getenv("HASHIMOTO_STRATEGY_TIMEOUT_SECONDS", "0.5"))
MAX_REALTIME_INSTRUCTIONS_CHARS = 2_000
MAX_REALTIME_PROMPT_FRAGMENT_CHARS = 900
MAX_SDP_CHARS = 64_000

# In-process scaffold store for G006. The persistence contract is represented by
# services/api/db/schema.sql; a later M2 slice will wire this to Postgres.
SESSION_HASH_STORE: dict[str, dict[str, object]] = {}
REALTIME_TURN_STATE: dict[str, dict[int, dict[str, object]]] = {}
REALTIME_RESPONSE_COMMANDS: dict[str, dict[int, dict[str, object]]] = {}
REALTIME_MMM_EVENT_LOG_LOCK = threading.Lock()
HASHIMOTO_SESSION_SEEDS: dict[str, dict[str, str]] = {}
HASHIMOTO_BOOTSTRAPPED_SESSIONS: set[str] = set()
HASHIMOTO_FEED_LOCK = threading.Lock()


def _duration_ms(start: float) -> int:
    return max(0, round((time.perf_counter() - start) * 1000))


def _trace_id(session_id: str | None, turn_index: int | None = None) -> str:
    safe_session = _safe_str(session_id or "unknown", 96)
    if turn_index is None:
        return safe_session
    return f"{safe_session}:{turn_index}"


def _log_latency_span(stage: str, duration_ms: int, **fields: object) -> None:
    """Emit structured latency telemetry without raw secrets, transcripts, audio, or video."""
    payload: dict[str, object] = {
        "event": "latency_span",
        "service": SERVICE_NAME,
        "stage": stage,
        "durationMs": duration_ms,
    }
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, str):
            payload[key] = _safe_str(value, 160)
        elif isinstance(value, (int, float, bool)):
            payload[key] = value
        else:
            payload[key] = _safe_str(value, 160)
    print(json.dumps(payload, sort_keys=True, ensure_ascii=False), flush=True)


def _return_with_latency(
    status: int,
    payload: dict[str, object],
    start: float,
    stage: str,
    *,
    session_id: str | None = None,
    turn_index: int | None = None,
    provider: str | None = None,
) -> tuple[int, dict[str, object]]:
    _log_latency_span(
        stage,
        _duration_ms(start),
        status=status,
        sessionId=session_id,
        turnIndex=turn_index,
        traceId=_trace_id(session_id, turn_index) if session_id else None,
        provider=provider,
    )
    return status, payload


def _safe_str(value: object, max_len: int = 4_000) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def _safe_multiline(value: object, max_len: int = 4_000) -> str:
    """_safe_str의 멀티라인 변형 — analysisBlock은 섹션 헤더/불릿이 줄 구조라 개행을 보존한다
    (공백 압축·길이 클램프는 동일)."""
    text = "" if value is None else str(value)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:max_len]


def _safe_sdp(value: object, max_len: int = MAX_SDP_CHARS) -> str:
    """Sanitize SDP without destroying its line-oriented grammar."""
    text = "" if value is None else str(value)
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    normalized = "\r\n".join(lines).strip()
    if normalized:
        normalized += "\r\n"
    return normalized[:max_len]


def _hashimoto_base_url() -> str:
    return os.getenv("HASHIMOTO_BASE_URL", "").strip().rstrip("/")


def _post_hashimoto(path: str, body: dict[str, object], timeout: float = 0.5) -> int | None:
    base = _hashimoto_base_url()
    if not base:
        return None
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
            return response.status
    except urllib.error.HTTPError as error:
        error.read()
        return error.code
    except Exception:
        return None


def _hashimoto_seed_from_session_payload(payload: dict[str, Any]) -> dict[str, str]:
    seed: dict[str, str] = {}
    resume_text = _safe_str(
        payload.get("resume_text")
        or payload.get("resumeText")
        or payload.get("candidateProfile")
        or "",
        20_000,
    ).strip()
    if resume_text:
        seed["resume_text"] = resume_text
    job = _safe_str(payload.get("job_url") or payload.get("jobUrl") or payload.get("job") or "", 2_048).strip()
    if job[:4].lower() == "http":
        seed["job_url"] = job
    return seed


def _ensure_hashimoto_session(session_id: str) -> bool:
    with HASHIMOTO_FEED_LOCK:
        if session_id in HASHIMOTO_BOOTSTRAPPED_SESSIONS:
            return True
        seed = dict(HASHIMOTO_SESSION_SEEDS.get(session_id, {}))
    if not seed:
        return False
    body: dict[str, object] = {"session_id": session_id, **seed}
    if _post_hashimoto("/session", body, timeout=4.0) not in (200, 201):
        return False
    with HASHIMOTO_FEED_LOCK:
        HASHIMOTO_BOOTSTRAPPED_SESSIONS.add(session_id)
    return True


def _feed_hashimoto_turn(session_id: str, turn_index: int, transcript: str) -> dict[str, object]:
    if not _hashimoto_base_url():
        return {"attempted": False, "reason": "disabled"}
    if not transcript.strip():
        return {"attempted": False, "reason": "empty_transcript"}
    if not _ensure_hashimoto_session(session_id):
        return {"attempted": False, "reason": "missing_session_seed"}
    turn_id = f"turn_{turn_index:04d}"
    status = _post_hashimoto(
        "/submit_turn",
        {"session_id": session_id, "turn_id": turn_id, "text": transcript},
    )
    if status == 404:
        with HASHIMOTO_FEED_LOCK:
            HASHIMOTO_BOOTSTRAPPED_SESSIONS.discard(session_id)
        if _ensure_hashimoto_session(session_id):
            status = _post_hashimoto(
                "/submit_turn",
                {"session_id": session_id, "turn_id": turn_id, "text": transcript},
            )
    if status in (200, 202):
        return {"attempted": True, "status": status, "endpoint": "/submit_turn"}
    return {"attempted": True, "status": status, "endpoint": "/submit_turn", "error": "hashimoto_feed_failed"}


def _hashimoto_turn_id(turn_index: int) -> str:
    return f"turn_{turn_index:04d}"


def _fetch_hashimoto_strategy(session_id: str, expected_turn_id: str) -> tuple[dict[str, Any] | None, dict[str, object]]:
    base = _hashimoto_base_url()
    source: dict[str, object] = {
        "attempted": bool(base),
        "endpoint": "/strategy",
        "expectedTurnId": expected_turn_id,
        "used": False,
    }
    if not base:
        source["reason"] = "disabled"
        return None, source
    endpoint = f"{base}/strategy?{urllib.parse.urlencode({'session_id': session_id})}"
    request = urllib.request.Request(endpoint, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=HASHIMOTO_STRATEGY_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
            source["status"] = response.status
    except urllib.error.HTTPError as error:
        error.read()
        source["status"] = error.code
        source["error"] = "hashimoto_strategy_rejected"
        return None, source
    except Exception:
        source["error"] = "hashimoto_strategy_unavailable"
        return None, source
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        source["error"] = "invalid_hashimoto_strategy"
        return None, source
    if not isinstance(parsed, dict):
        source["error"] = "invalid_hashimoto_strategy"
        return None, source
    source["ready"] = bool(parsed.get("ready", False))
    source["asOfTurnId"] = _safe_str(parsed.get("as_of_turn_id") or parsed.get("asOfTurnId"), 120)
    source["sessionComplete"] = bool(parsed.get("session_complete") or parsed.get("sessionComplete"))
    if not source["ready"]:
        source["reason"] = "not_ready"
        return None, source
    if source["asOfTurnId"] != expected_turn_id:
        source["reason"] = "turn_mismatch"
        return None, source
    strategy = parsed.get("interaction_strategy")
    if not isinstance(strategy, dict):
        source["reason"] = "missing_strategy"
        return None, source
    return strategy, source


def _hashimoto_strategy_guidance(strategy: dict[str, Any]) -> str:
    lines: list[str] = []
    logic_goal = _candidate_safe_fragment(strategy.get("logic_goal"))
    if logic_goal:
        lines.append(f"Goal: {logic_goal}")
    gap = _candidate_safe_fragment(strategy.get("logical_gap_to_bridge"))
    if gap:
        lines.append(f"Gap to clarify: {gap}")
    persona = strategy.get("interviewer_persona_guidance")
    if isinstance(persona, dict):
        intent = _candidate_safe_fragment(persona.get("intent"))
        if intent:
            lines.append(f"Intent: {intent}")
        focus = _candidate_safe_fragment(persona.get("focus_point"))
        if focus:
            lines.append(f"Focus: {focus}")
        emotion = _candidate_safe_fragment(persona.get("emotion_direction"))
        if emotion:
            lines.append(f"Tone: {emotion}")
    context = strategy.get("current_context")
    if isinstance(context, dict):
        topic = _candidate_safe_fragment(context.get("topic"))
        depth = context.get("depth_level")
        if topic and isinstance(depth, (int, float)):
            lines.append(f"Current topic: {topic}, depth {int(depth)}")
        elif topic:
            lines.append(f"Current topic: {topic}")
        transition = _candidate_safe_fragment(context.get("transition_hint"))
        if transition:
            lines.append(f"Transition hint: {transition}")
        if context.get("topic_changed") is True:
            lines.append("The strategy indicates a topic transition; make the next question feel natural.")
        resolved = context.get("resolved_history")
        if isinstance(resolved, list) and resolved:
            summarized: list[str] = []
            for item in resolved[:3]:
                if not isinstance(item, dict):
                    continue
                proposition = _candidate_safe_fragment(item.get("proposition"))
                status = _candidate_safe_fragment(item.get("status"))
                if proposition and status:
                    summarized.append(f"{proposition} ({status})")
                elif proposition:
                    summarized.append(proposition)
            if summarized:
                lines.append("Avoid re-asking resolved points: " + "; ".join(summarized))
    guidance = "\n".join(lines)
    return _candidate_safe_fragment(guidance)


def _safe_hashimoto_strategy_debug(source: dict[str, object] | None) -> dict[str, object]:
    source = source or {}
    return {
        "attempted": bool(source.get("attempted", False)),
        "endpoint": _safe_str(source.get("endpoint"), 120),
        "status": source.get("status") if isinstance(source.get("status"), int) else None,
        "ready": bool(source.get("ready", False)),
        "used": bool(source.get("used", False)),
        "asOfTurnId": _safe_str(source.get("asOfTurnId"), 120),
        "expectedTurnId": _safe_str(source.get("expectedTurnId"), 120),
        "sessionComplete": bool(source.get("sessionComplete", False)),
        "reason": _safe_str(source.get("reason"), 120),
        "error": _safe_str(source.get("error"), 120),
    }


def _redact_provider_error(text: str) -> str:
    for name in ("ELEVENLABS_API_KEY", "SPATIALREAL_API_KEY", "LIVEKIT_API_SECRET", "OPENAI_API_KEY", "COACH_GEMINI_API_KEY", "GEMINI_API_KEY"):
        value = os.getenv(name, "").strip()
        if value:
            text = text.replace(value, "<redacted>")
    return text[:500]


def _provider_failure_payload(error: str, provider: object = "api-mediated", *, ready: bool | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "error": error,
        "provider": _safe_str(provider or "api-mediated", 80),
        "message": "provider request failed",
    }
    if ready is not None:
        payload["ready"] = ready
    return payload


def _realtime_delivery(mode: str) -> dict[str, object]:
    return {
        "mode": mode,
        "source": "openai-realtime",
        "standardOpenAIKey": "server-only",
        "publicDirectProviderRoutes": "blocked",
        "trustedBusinessLogicBoundary": "api-sideband",
    }


def _realtime_unavailable_payload(error: str = "realtime_not_configured") -> dict[str, object]:
    return {
        "error": error,
        "provider": "openai-realtime",
        "message": "realtime unavailable",
        "delivery": _realtime_delivery("api-mediated-realtime-session"),
    }


def _realtime_route_config(interview_id: str) -> dict[str, object]:
    primary = _env_enabled("OPENAI_REALTIME_PRIMARY", "true")
    return {
        "enabled": primary,
        "mode": "primary" if primary else "prepared",
        "transport": "webrtc" if primary else "prepared-webrtc",
        "sessionEndpoint": f"/api/interviews/{interview_id}/realtime/session",
        "callEndpoint": f"/api/interviews/{interview_id}/realtime/call",
        "turnEventsEndpoint": f"/api/interviews/{interview_id}/turns/{{turnIndex}}/events",
        "visionEventsEndpoint": f"/api/interviews/{interview_id}/turns/{{turnIndex}}/vision-events",
        "mmmReadyEndpoint": f"/api/interviews/{interview_id}/turns/{{turnIndex}}/mmm-ready",
        "responseCreateEndpoint": f"/api/interviews/{interview_id}/turns/{{turnIndex}}/realtime/response",
        "fullMmmRequiredBeforeResponseCreate": True,
        "browserWebrtcAttach": "api-call-broker",
        "standardOpenAIKey": "server-only",
        "directProviderRoutes": "blocked",
    }


def _turn_state(interview_id: str, turn_index: int) -> dict[str, object]:
    interview_state = REALTIME_TURN_STATE.setdefault(interview_id, {})
    return interview_state.setdefault(turn_index, {
        "events": [],
        "transcript_completed": False,
        "transcript_non_empty": False,
        "answer_ended": False,
        "vision_observed": False,
        "prosody_observed": False,
    })


def _event_kind(payload: dict[str, Any]) -> str:
    return _safe_str(payload.get("normalizedType") or payload.get("type") or "unknown", 120)


def _append_realtime_event(state: dict[str, object], kind: str, payload: dict[str, Any]) -> None:
    events = state.setdefault("events", [])
    if isinstance(events, list):
        events.append({"kind": kind, "timestamp": _safe_str(payload.get("timestamp") or payload.get("capturedAt") or "", 80)})
        del events[:-50]


def _contains_non_empty_transcript(payload: dict[str, Any]) -> bool:
    candidates = [payload.get("transcript"), payload.get("text")]
    detail = payload.get("detail")
    if isinstance(detail, dict):
        candidates.extend([detail.get("transcript"), detail.get("text")])
    return any(_safe_str(value, 400).strip() for value in candidates)


def _transcript_from_realtime_event(payload: dict[str, Any]) -> str:
    detail = payload.get("detail")
    if isinstance(detail, dict):
        transcript = _safe_str(detail.get("transcript") or detail.get("text") or "", 8_000)
        if transcript:
            return transcript
    return _safe_str(payload.get("transcript") or payload.get("text") or "", 8_000)


def _env_enabled(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _spatialreal_sdk_audio_format() -> dict[str, object]:
    return {
        "encoding": "pcm16",
        "channelCount": 1,
        "sampleRateHz": 16000,
        "source": "openai-realtime-output-audio",
        "mutedUntilVerified": True,
    }


def _avatar_sdk_mode_metadata(*, enabled: bool | None = None, status: str | None = None, outcome: str | None = None, reason: str | None = None) -> dict[str, object]:
    sdk_enabled = _env_enabled("SPATIALREAL_SDK_MODE_WEB_ENABLED", "false") if enabled is None else enabled
    resolved_status = status or ("ready" if sdk_enabled else "deferred")
    resolved_outcome = outcome or ("sdk_mode_ready" if resolved_status == "ready" else "sdk_mode_deferred")
    metadata: dict[str, object] = {
        "enabled": sdk_enabled,
        "mode": "spatialreal-sdk-mode-web",
        "transport": "spatialreal-sdk-websocket",
        "status": resolved_status,
        "outcome": resolved_outcome,
        "livekitRequired": False,
        "directProviderRoutes": "blocked",
        "requiresFeatureFlag": "SPATIALREAL_SDK_MODE_WEB_ENABLED",
        "providerSecretsExposed": False,
        "rawMediaExposed": False,
        "rawTranscriptExposed": False,
        "defaultEnabled": False,
        "tokenHidden": True,
        "rawMediaLogged": False,
        "requiresKiostationBrowserProof": True,
        "audioFormat": _spatialreal_sdk_audio_format(),
        "description": "Browser-safe SpatialReal SDK Mode metadata for non-LiveKit AvatarKit SDK Mode Web.",
        "blockedOutcome": "sdk_mode_deferred until SDK Mode Web package/API and muted PCM16 audio feed are verified on kiostation.",
    }
    if reason:
        metadata["reason"] = reason
    return metadata


def _spatialreal_sdk_client_config() -> tuple[dict[str, object] | None, list[str]]:
    app_id = os.getenv("SPATIALREAL_APP_ID", "").strip()
    avatar_id = os.getenv("SPATIALREAL_AVATAR_ID", "").strip()
    session_token = os.getenv("SPATIALREAL_SESSION_TOKEN", "").strip()
    environment = os.getenv("SPATIALREAL_ENVIRONMENT", "intl").strip() or "intl"
    missing = [
        name for name, value in (
            ("SPATIALREAL_APP_ID", app_id),
            ("SPATIALREAL_AVATAR_ID", avatar_id),
            ("SPATIALREAL_SESSION_TOKEN", session_token),
        ) if not value
    ]
    if missing:
        return None, missing
    return {
        "appId": app_id,
        "avatarId": avatar_id,
        "sessionToken": session_token,
        "environment": environment,
        "audioFormat": {"encoding": "pcm16", "channelCount": 1, "sampleRateHz": 16000},
        "tokenPolicy": "qa-only-manual-session-token-or-api-brokered-short-lived-token",
    }, []


def _readiness_payload(interview_id: str, turn_index: int) -> dict[str, object]:
    state = _turn_state(interview_id, turn_index)
    vision_required = _env_enabled("GILJOBE_VISION", "true")
    prosody_required = _env_enabled("GILJOBE_PROSODY", "true")
    missing: list[str] = []
    if not state.get("answer_ended"):
        missing.append("missing_answer_end")
    if not (state.get("transcript_completed") and state.get("transcript_non_empty")):
        missing.append("missing_transcript")
    if vision_required and not state.get("vision_observed"):
        missing.append("missing_vision")
    if prosody_required and not state.get("prosody_observed"):
        missing.append("missing_prosody")
    ready = not missing
    return {
        "interviewId": interview_id,
        "turnIndex": turn_index,
        "ready": ready,
        "full_mmm_ready": ready,
        "degraded": not ready,
        "state": "full_mmm_ready" if ready else "degraded_not_ready",
        "reason": "ready" if ready else missing[0],
        "reasonCodes": missing,
        "lanes": {
            "answerEnded": bool(state.get("answer_ended")),
            "transcriptCompleted": bool(state.get("transcript_completed")),
            "transcriptNonEmpty": bool(state.get("transcript_non_empty")),
            "visionObserved": bool(state.get("vision_observed")),
            "visionRequired": vision_required,
            "prosodyObserved": bool(state.get("prosody_observed")),
            "prosodyRequired": prosody_required,
        },
        "delivery": _realtime_delivery("api-mediated-realtime-mmm-ready"),
    }


def _realtime_mmm_event_log_path() -> str | None:
    configured = os.getenv("REALTIME_MMM_EVENT_LOG_PATH", REALTIME_MMM_EVENT_LOG_PATH).strip()
    if not configured or configured.lower() in {"0", "false", "no", "off", "disabled"}:
        return None
    return configured


def _realtime_mmm_record(interview_id: str, turn_index: int, kind: str, source_route: str) -> dict[str, object]:
    readiness = _readiness_payload(interview_id, turn_index)
    return {
        "schema_version": "2026-06-11.realtime-mmm-ingress.v1",
        "source": "api-sideband",
        "sessionId": interview_id,
        "turnId": str(turn_index),
        "interviewId": interview_id,
        "turnIndex": turn_index,
        "eventKind": kind,
        "sourceRoute": source_route,
        "receivedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rawTranscriptLogged": False,
        "rawMediaAccepted": False,
        "readiness": {
            "full_mmm_ready": bool(readiness.get("full_mmm_ready")),
            "state": _safe_str(readiness.get("state"), 80),
            "reasonCodes": list(readiness.get("reasonCodes", [])) if isinstance(readiness.get("reasonCodes"), list) else [],
            "lanes": readiness.get("lanes", {}),
        },
        "delivery": _realtime_delivery("api-sideband-realtime-mmm-ingress"),
    }


def _persist_realtime_mmm_record(record: dict[str, object]) -> dict[str, object]:
    path = _realtime_mmm_event_log_path()
    if path is None:
        return {"sink": "server-jsonl", "durable": False, "configured": False, "reason": "disabled"}
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        line = json.dumps(record, sort_keys=True, ensure_ascii=False)
        with REALTIME_MMM_EVENT_LOG_LOCK:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except OSError as exc:
        return {"sink": "server-jsonl", "durable": False, "configured": True, "error": _safe_str(exc, 160)}
    return {"sink": "server-jsonl", "durable": True, "configured": True}


def _forward_realtime_mmm_record(record: dict[str, object]) -> dict[str, object]:
    if not _env_enabled("REALTIME_MMM_FORWARD_ENABLED", "true"):
        return {"attempted": False, "reason": "disabled"}
    endpoint = f"{ANALYSIS_ENGINE_INTERNAL_URL}/realtime/turn-events"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(record, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REALTIME_MMM_FORWARD_TIMEOUT_SECONDS) as response:
            response.read()
            return {"attempted": True, "status": response.status, "endpoint": "/realtime/turn-events"}
    except urllib.error.HTTPError as error:
        error.read()
        return {"attempted": True, "status": error.code, "endpoint": "/realtime/turn-events", "error": "analysis_engine_rejected"}
    except urllib.error.URLError:
        return {"attempted": True, "endpoint": "/realtime/turn-events", "error": "analysis_engine_unavailable"}


def _sideband_detail_for_engine(payload: dict[str, Any]) -> dict[str, object] | None:
    """Forward-only transcript/prosody detail for the analysis engine lanes.

    The durable JSONL record stays metadata-only (rawTranscriptLogged: False) and the
    public response never echoes text or raw audio. Candidate transcript text and
    bounded VAD/prosody metrics travel only over the internal forward hop
    (REALTIME_MMM_FORWARD_ENABLED), where analysis-engine is the authority. Only
    known keys pass through, length-capped or range-clamped.
    """
    detail = payload.get("detail")
    if not isinstance(detail, dict):
        return None
    out: dict[str, object] = {}
    transcript = detail.get("transcript") or detail.get("text")
    if isinstance(transcript, str) and transcript.strip():
        out["transcript"] = transcript[:8000]
    item_id = detail.get("itemId")
    if isinstance(item_id, str) and item_id:
        out["itemId"] = item_id[:120]
    for key in ("audioStartMs", "audioEndMs", "energy", "rmsEnergy", "energyMean"):
        value = _bounded_number(detail.get(key), minimum=0, maximum=24 * 60 * 60 * 1000)
        if value is not None:
            out[key] = value
    if detail.get("rawAudioIncluded") is False:
        out["rawAudioIncluded"] = False
    return out or None


def _bounded_number(value: object, *, minimum: float | None = None, maximum: float | None = None) -> int | float | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return int(number) if number.is_integer() else round(number, 3)


def _sideband_vision_detail_for_engine(payload: dict[str, Any]) -> tuple[dict[str, object] | None, str | None]:
    """Forward-only visual signals/frame detail for the analysis engine.

    Durable API records remain metadata-only. A low-resolution image sample, when
    present, is sent only on the internal API→analysis-engine hop so the engine can
    derive visual signals before returning a candidate-safe prompt fragment.
    """
    detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else {}
    top_video = payload.get("video") if isinstance(payload.get("video"), dict) else {}
    out: dict[str, object] = {}
    signals: dict[str, object] = {"schemaVersion": "2026-06-13.vision-signals.v1"}

    def copy_bool(source: dict[str, Any], source_key: str, target_key: str | None = None) -> None:
        value = source.get(source_key)
        if isinstance(value, bool):
            signals[target_key or source_key] = value

    def copy_num(source: dict[str, Any], source_key: str, target_key: str | None = None, *, maximum: float | None = None) -> None:
        value = _bounded_number(source.get(source_key), minimum=0, maximum=maximum)
        if value is not None:
            signals[target_key or source_key] = value

    def copy_str(source: dict[str, Any], source_key: str, target_key: str | None = None) -> None:
        value = _safe_str(source.get(source_key), 120)
        if value:
            signals[target_key or source_key] = value

    for source in (top_video, detail):
        copy_bool(source, "cameraEnabled")
        copy_num(source, "width", maximum=4096)
        copy_num(source, "height", maximum=4096)
        copy_num(source, "readyState", maximum=4)
        copy_bool(source, "faceVisible")
        copy_bool(source, "personVisible")
        copy_str(source, "visualQuality")
        copy_str(source, "frameDroppedReason")
        copy_num(source, "averageLuma", maximum=255)
        copy_num(source, "darkPixelRatio", maximum=1)

    nested_signals = detail.get("visionSignals") if isinstance(detail.get("visionSignals"), dict) else {}
    for key in ("cameraEnabled", "frameAvailable", "faceVisible", "personVisible"):
        copy_bool(nested_signals, key)
    for key, maximum in (("width", 4096), ("height", 4096), ("averageLuma", 255), ("darkPixelRatio", 1)):
        copy_num(nested_signals, key, maximum=maximum)
    for key in ("visualQuality", "frameDroppedReason"):
        copy_str(nested_signals, key)

    frame = detail.get("visionFrame")
    if isinstance(frame, dict):
        encoding = _safe_str(frame.get("encoding"), 40).lower()
        data = frame.get("data")
        byte_length = _bounded_number(frame.get("byteLength"), minimum=1, maximum=MAX_REALTIME_VISION_FRAME_BYTES)
        if encoding and encoding != "image/jpeg;base64":
            return None, "unsupported_vision_frame_encoding"
        if data is not None:
            if not isinstance(data, str) or not data.strip():
                return None, "invalid_vision_frame"
            if len(data.encode("utf-8")) > MAX_REALTIME_VISION_FRAME_BYTES * 2:
                return None, "vision_frame_too_large"
            out["visionFrame"] = {
                "schemaVersion": _safe_str(frame.get("schemaVersion") or "2026-06-13.internal-vision-frame.v1", 80),
                "encoding": encoding or "image/jpeg;base64",
                "width": _bounded_number(frame.get("width"), minimum=1, maximum=4096),
                "height": _bounded_number(frame.get("height"), minimum=1, maximum=4096),
                "byteLength": byte_length,
                "data": data,
                "internalOnly": True,
                "notLogged": True,
            }
            signals["frameAvailable"] = True
            if byte_length is not None:
                signals["frameByteLength"] = byte_length

    if len(signals) > 1:
        out["visionSignals"] = signals
    return (out or None), None


def _record_realtime_mmm_ingress(
    interview_id: str, turn_index: int, kind: str, source_route: str,
    engine_detail: dict[str, object] | None = None,
) -> dict[str, object]:
    record = _realtime_mmm_record(interview_id, turn_index, kind, source_route)
    forward_record: dict[str, object] = dict(record)
    if engine_detail:
        forward_record["detail"] = engine_detail
    return {
        "schemaVersion": record["schema_version"],
        "durableStore": _persist_realtime_mmm_record(record),
        "analysisEngine": _forward_realtime_mmm_record(forward_record),
    }


def _latest_durable_realtime_mmm_record(interview_id: str, turn_index: int) -> dict[str, object] | None:
    path = _realtime_mmm_event_log_path()
    if path is None or not os.path.exists(path):
        return None
    latest: dict[str, object] | None = None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                if record.get("interviewId") == interview_id and record.get("turnIndex") == turn_index:
                    latest = record
    except OSError:
        return None
    return latest


def _durable_readiness_payload(interview_id: str, turn_index: int) -> dict[str, object] | None:
    record = _latest_durable_realtime_mmm_record(interview_id, turn_index)
    if not record:
        return None
    readiness = record.get("readiness")
    if not isinstance(readiness, dict):
        return None
    reason_codes = readiness.get("reasonCodes") if isinstance(readiness.get("reasonCodes"), list) else []
    lanes = readiness.get("lanes") if isinstance(readiness.get("lanes"), dict) else {}
    ready = bool(readiness.get("full_mmm_ready"))
    return {
        "interviewId": interview_id,
        "turnIndex": turn_index,
        "ready": ready,
        "full_mmm_ready": ready,
        "degraded": not ready,
        "state": "full_mmm_ready" if ready else "degraded_not_ready",
        "reason": "ready" if ready else (_safe_str(reason_codes[0], 80) if reason_codes else "missing_realtime_mmm_state"),
        "reasonCodes": reason_codes,
        "lanes": lanes,
        "source": "server-jsonl-outbox",
        "delivery": _realtime_delivery("api-mediated-realtime-mmm-ready"),
    }


def _readiness_payload_with_durable_fallback(interview_id: str, turn_index: int) -> dict[str, object]:
    in_process = _readiness_payload(interview_id, turn_index)
    durable = _durable_readiness_payload(interview_id, turn_index)
    if durable and (durable.get("full_mmm_ready") or not in_process.get("full_mmm_ready")):
        return durable
    return in_process

def _readiness_payload_with_analysis_result(interview_id: str, turn_index: int) -> dict[str, object]:
    readiness = _readiness_payload_with_durable_fallback(interview_id, turn_index)
    payload = dict(readiness)
    if not readiness.get("full_mmm_ready"):
        response_create = {"owner": "api", "created": False, "reason": "full_mmm_required_for_prior_answer"}
        payload["responseCreate"] = response_create
        payload["mmmDebug"] = _mmm_debug_envelope(
            interview_id,
            turn_index,
            analysis_turn_index=turn_index,
            readiness=readiness,
            response_create=response_create,
        )
        return payload

    result, source = _fetch_analysis_result(interview_id, turn_index)
    failure = _analysis_result_gate_failure(result, interview_id, turn_index)
    payload["analysisEngine"] = source
    if failure:
        reason = failure[0]
        response_reason = failure[1]
        payload["ready"] = False
        payload["full_mmm_ready"] = False
        payload["degraded"] = True
        payload["state"] = "analysis_result_not_ready"
        payload["reason"] = reason
        payload["reasonCodes"] = [reason]
        response_create = {"owner": "api", "created": False, "reason": response_reason}
        payload["responseCreate"] = response_create
        payload["mmmDebug"] = _mmm_debug_envelope(
            interview_id,
            turn_index,
            analysis_turn_index=turn_index,
            readiness=payload,
            analysis_engine=source,
            response_create=response_create,
            analysis_result=result,
        )
        return payload

    if result is not None and not _analysis_result_turn_matches(result, interview_id, turn_index):
        reason = "analysis_result_stale_or_wrong_turn"
        response_create = {"owner": "api", "created": False, "reason": "exact_turn_analysis_required"}
        payload["ready"] = False
        payload["full_mmm_ready"] = False
        payload["degraded"] = True
        payload["state"] = "analysis_result_not_ready"
        payload["reason"] = reason
        payload["reasonCodes"] = [reason]
        payload["responseCreate"] = response_create
        payload["mmmDebug"] = _mmm_debug_envelope(
            interview_id,
            turn_index,
            analysis_turn_index=turn_index,
            readiness=payload,
            analysis_engine=source,
            response_create=response_create,
            analysis_result=result,
        )
        return payload

    fragment = _candidate_safe_fragment_from_result(result or {})
    if not fragment or bool((result or {}).get("rawTranscriptLogged", False)) or bool((result or {}).get("rawMediaAccepted", False)):
        reason = "analysis_result_not_usable"
        response_create = {"owner": "api", "created": False, "reason": "candidate_safe_ready_result_required"}
        payload["ready"] = False
        payload["full_mmm_ready"] = False
        payload["degraded"] = True
        payload["state"] = "analysis_result_not_ready"
        payload["reason"] = reason
        payload["reasonCodes"] = [reason]
        payload["responseCreate"] = response_create
        payload["mmmDebug"] = _mmm_debug_envelope(
            interview_id,
            turn_index,
            analysis_turn_index=turn_index,
            readiness=payload,
            analysis_engine=source,
            response_create=response_create,
            analysis_result=result,
        )
        return payload

    analysis_summary = _analysis_result_public_summary(result or {})
    response_create = {"owner": "api", "created": True, "commandType": "response.create"}
    debug_response_create = {**response_create, "reason": "candidate_safe_ready_result_available"}
    payload["analysisResult"] = analysis_summary
    payload["responseCreate"] = response_create
    payload["mmmDebug"] = _mmm_debug_envelope(
        interview_id,
        turn_index,
        analysis_turn_index=turn_index,
        readiness=readiness,
        analysis_engine=source,
        response_create=debug_response_create,
        analysis_result=result,
    )
    return payload


_CANDIDATE_PROMPT_FORBIDDEN_RE = re.compile(
    r"\b(?:MMM|analysis-engine|backend|sideband|readiness\s*gate|raw\s*rubric|provider\s*internal|server-only)\b",
    re.IGNORECASE,
)


def _analysis_result_query(interview_id: str, turn_index: int) -> str:
    return urllib.parse.urlencode({"interviewId": interview_id, "turnIndex": str(turn_index)})


def _candidate_safe_fragment(value: object) -> str:
    fragment = _safe_str(value, MAX_REALTIME_PROMPT_FRAGMENT_CHARS)
    if not fragment:
        return ""
    if _CANDIDATE_PROMPT_FORBIDDEN_RE.search(fragment):
        return ""
    return fragment


_PUBLIC_ANALYSIS_FORBIDDEN_KEYS = {
    "transcript",
    "text",
    "data",
    "visionFrame",
    "rawMedia",
    "audio",
    "video",
    "sdp",
    "token",
    "client_secret",
    "apiKey",
}


def _safe_public_analysis_object(value: object, *, max_depth: int = 3) -> object:
    if max_depth <= 0:
        return None
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for key, nested in value.items():
            key_str = _safe_str(key, 80)
            if not key_str or key_str in _PUBLIC_ANALYSIS_FORBIDDEN_KEYS:
                continue
            safe_nested = _safe_public_analysis_object(nested, max_depth=max_depth - 1)
            if safe_nested is not None:
                out[key_str] = safe_nested
        return out
    if isinstance(value, list):
        return [
            item
            for item in (_safe_public_analysis_object(item, max_depth=max_depth - 1) for item in value[:8])
            if item is not None
        ]
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return _safe_str(value, 300)
    return None


def _analysis_result_public_summary(result: dict[str, Any]) -> dict[str, object]:
    summary: dict[str, object] = {
        "schemaVersion": _safe_str(result.get("schemaVersion") or result.get("schema_version"), 80),
        "status": _safe_str(result.get("status"), 40),
        "confidence": result.get("confidence") if isinstance(result.get("confidence"), (int, float)) else None,
        "latencyMs": result.get("latencyMs") if isinstance(result.get("latencyMs"), (int, float)) else None,
        "rawTranscriptLogged": bool(result.get("rawTranscriptLogged", False)),
        "rawMediaAccepted": bool(result.get("rawMediaAccepted", False)),
    }
    for key in ("transcriptSignals", "visionSignals", "prosodySignals", "behavioralSignals", "coverage"):
        value = result.get(key)
        if isinstance(value, dict):
            summary[key] = _safe_public_analysis_object(value)
    return summary


def _safe_analysis_engine_debug(source: dict[str, object] | None) -> dict[str, object]:
    source = source or {}
    return {
        "attempted": bool(source.get("attempted", False)),
        "endpoint": _safe_str(source.get("endpoint"), 120),
        "status": source.get("status") if isinstance(source.get("status"), int) else None,
        "source": _safe_str(source.get("source"), 80),
        "error": _safe_str(source.get("error"), 120),
        "reason": _safe_str(source.get("reason"), 120),
    }


def _safe_readiness_debug(readiness: dict[str, object] | None) -> dict[str, object]:
    readiness = readiness or {}
    reason_codes = readiness.get("reasonCodes") if isinstance(readiness.get("reasonCodes"), list) else []
    lanes = readiness.get("lanes") if isinstance(readiness.get("lanes"), dict) else {}
    return {
        "ready": bool(readiness.get("ready", readiness.get("full_mmm_ready", False))),
        "full_mmm_ready": bool(readiness.get("full_mmm_ready", False)),
        "state": _safe_str(readiness.get("state"), 80),
        "reason": _safe_str(readiness.get("reason"), 120),
        "reasonCodes": [_safe_str(reason, 120) for reason in reason_codes],
        "lanes": lanes,
        "source": _safe_str(readiness.get("source"), 80),
    }


def _mmm_debug_envelope(
    interview_id: str,
    turn_index: int,
    *,
    analysis_turn_index: int | None,
    readiness: dict[str, object] | None = None,
    analysis_engine: dict[str, object] | None = None,
    response_create: dict[str, object] | None = None,
    analysis_result: dict[str, Any] | None = None,
) -> dict[str, object]:
    response_create = response_create or {}
    envelope: dict[str, object] = {
        "schemaVersion": "2026-06-12.safe-mmm-debug.v1",
        "interviewId": interview_id,
        "turnIndex": turn_index,
        "analysisTurnIndex": analysis_turn_index,
        "readiness": _safe_readiness_debug(readiness),
        "analysisEngine": _safe_analysis_engine_debug(analysis_engine),
        "responseCreate": {
            "created": bool(response_create.get("created", False)),
            "reason": _safe_str(response_create.get("reason"), 120),
            "commandType": _safe_str(response_create.get("commandType"), 80),
            "owner": _safe_str(response_create.get("owner"), 80),
        },
        "rawTranscriptLogged": False,
        "rawMediaAccepted": False,
        "secretsExposed": False,
    }
    if analysis_result is not None:
        envelope["analysisResult"] = _analysis_result_public_summary(analysis_result)
    return envelope


def _extract_analysis_result(payload: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("result", "analysisResult", "mmmResult"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    if payload.get("schemaVersion") or payload.get("schema_version") or payload.get("candidatePromptFragment") or payload.get("candidateSafePromptFragment"):
        return payload
    return None


def _analysis_result_gate_failure(result: dict[str, Any] | None, interview_id: str, turn_index: int) -> tuple[str, str] | None:
    if result is None:
        return ("analysis_result_unavailable", "structured_analysis_required")
    status = _safe_str(result.get("status"), 40)
    if status != "ready":
        return ("analysis_result_not_ready", "ready_analysis_result_required")
    return None


def _fetch_analysis_result(interview_id: str, turn_index: int) -> tuple[dict[str, Any] | None, dict[str, object]]:
    endpoint = f"{ANALYSIS_ENGINE_INTERNAL_URL}/realtime/turn-results?{_analysis_result_query(interview_id, turn_index)}"
    request = urllib.request.Request(endpoint, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=REALTIME_MMM_RESULT_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as error:
        error.read()
        return None, {"attempted": True, "status": error.code, "endpoint": "/realtime/turn-results", "error": "analysis_result_rejected"}
    except urllib.error.URLError:
        return None, {"attempted": True, "endpoint": "/realtime/turn-results", "error": "analysis_engine_unavailable"}
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return None, {"attempted": True, "status": status, "endpoint": "/realtime/turn-results", "error": "invalid_analysis_result"}
    if not isinstance(parsed, dict):
        return None, {"attempted": True, "status": status, "endpoint": "/realtime/turn-results", "error": "invalid_analysis_result"}
    return _extract_analysis_result(parsed), {"attempted": True, "status": status, "endpoint": "/realtime/turn-results"}


def _analysis_result_turn_matches(result: dict[str, Any], interview_id: str, turn_index: int) -> bool:
    result_turn = result.get("turnIndex") or result.get("turn_index")
    try:
        if int(result_turn) != turn_index:
            return False
    except (TypeError, ValueError):
        return False
    result_session = _safe_str(result.get("sessionId") or result.get("interviewId"), 96)
    return result_session == interview_id


def _candidate_safe_fragment_from_result(result: dict[str, Any]) -> str:
    structured = result.get("candidateSafePromptFragment")
    if isinstance(structured, dict):
        if any(bool(structured.get(key)) for key in ("containsRawTranscript", "containsRawMedia", "containsSecrets")):
            return ""
        return _candidate_safe_fragment(structured.get("text"))
    return _candidate_safe_fragment(result.get("candidatePromptFragment") or result.get("realtimePromptFragment") or result.get("nextQuestionGuidance"))


def _coach_llm_settings() -> dict[str, object]:
    provider = _safe_str(os.getenv("COACH_LLM_PROVIDER", "fake"), 40).lower() or "fake"
    explicit_model = _safe_str(os.getenv("COACH_LLM_MODEL"), 120)
    if provider == "gemini":
        model = explicit_model or "gemini-2.5-flash"
    elif provider == "openai":
        model = explicit_model or "gpt-4.1-mini"
    else:
        model = explicit_model or "fake-coach"
    try:
        timeout = float(os.getenv("COACH_LLM_TIMEOUT_SECONDS", str(COACH_LLM_TIMEOUT_SECONDS)))
    except ValueError:
        timeout = COACH_LLM_TIMEOUT_SECONDS
    return {
        "provider": provider,
        "model": model,
        "timeout": max(1.0, min(timeout, 60.0)),
        "openaiApiBase": os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/"),
        "openaiApiKey": os.getenv("OPENAI_API_KEY", "").strip(),
        "geminiApiBase": os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta").rstrip("/"),
        "geminiApiKey": (os.getenv("COACH_GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")).strip(),
    }


def _coach_feedback_pending_payload(reason: str) -> dict[str, object]:
    return {
        "ready": False,
        "reason": reason,
        "summary": "분석 결과를 기다리는 중입니다.",
        "answerEvaluation": "",
        "multimodalEvaluation": "",
        "bullets": [],
    }


def _coach_analysis_summary(result: dict[str, Any] | None, source: dict[str, object]) -> dict[str, object]:
    result = result or {}
    public = _analysis_result_public_summary(result)
    coverage = public.get("coverage")
    return {
        "endpoint": _safe_str(source.get("endpoint"), 120),
        "attempted": bool(source.get("attempted", False)),
        "status": source.get("status") if isinstance(source.get("status"), int) else None,
        "error": _safe_str(source.get("error"), 120),
        "resultStatus": _safe_str(result.get("status"), 40),
        "schemaVersion": public.get("schemaVersion"),
        "confidence": public.get("confidence"),
        "latencyMs": public.get("latencyMs"),
        "coverage": coverage if isinstance(coverage, dict) else {},
        "rawTranscriptLogged": bool(result.get("rawTranscriptLogged", False)),
        "rawMediaAccepted": bool(result.get("rawMediaAccepted", False)),
    }


def _build_coach_feedback_prompt(result: dict[str, Any], interview_id: str, turn_index: int) -> str:
    safe_fragment = _candidate_safe_fragment_from_result(result)
    prompt_payload = {
        "task": "Korean interview coach feedback",
        "interviewId": interview_id,
        "turnIndex": turn_index,
        "safeGuidance": safe_fragment,
        "analysisSummary": _analysis_result_public_summary(result),
        "outputJsonSchema": {
            "summary": "one Korean sentence",
            "answerEvaluation": "short Korean feedback on answer quality",
            "multimodalEvaluation": "short Korean feedback on visual/prosody signals",
            "bullets": ["1-4 concise Korean coaching actions"],
        },
        "rules": [
            "Return only valid JSON.",
            "Do not expose raw transcript, raw media, provider keys, or internal transport labels.",
            "Do not mention implementation details.",
        ],
    }
    return json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True)


def _parse_json_object_from_text(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _coerce_coach_feedback(value: object) -> dict[str, object]:
    feedback = value.get("coachFeedback") if isinstance(value, dict) and isinstance(value.get("coachFeedback"), dict) else value
    feedback = feedback if isinstance(feedback, dict) else {}
    raw_bullets = feedback.get("bullets")
    bullets = [
        _safe_str(item, 280)
        for item in (raw_bullets if isinstance(raw_bullets, list) else [])
        if _safe_str(item, 280)
    ][:4]
    return {
        "ready": True,
        "summary": _safe_str(feedback.get("summary") or "코치 피드백이 준비되었습니다.", 420),
        "answerEvaluation": _safe_str(feedback.get("answerEvaluation"), 700),
        "multimodalEvaluation": _safe_str(feedback.get("multimodalEvaluation"), 700),
        "bullets": bullets,
    }


def _fake_coach_feedback(result: dict[str, Any], interview_id: str, turn_index: int, settings: dict[str, object]) -> tuple[int, dict[str, object]]:
    coverage = _analysis_result_public_summary(result).get("coverage")
    coverage_text = ", ".join(f"{key}:{value}" for key, value in sorted(coverage.items())) if isinstance(coverage, dict) and coverage else "available"
    feedback = {
        "ready": True,
        "summary": "답변 분석과 멀티모달 신호를 바탕으로 코치 피드백이 준비되었습니다.",
        "answerEvaluation": "다음 답변에서는 핵심 주장 뒤에 구체적인 근거와 본인 역할을 더 붙이면 좋습니다.",
        "multimodalEvaluation": f"시각/음성 신호는 공개 가능한 요약 범위에서 확인되었습니다. coverage={coverage_text}",
        "bullets": [
            "성과를 수치나 비교 기준으로 한 문장 더 구체화하세요.",
            "문제 상황, 행동, 결과를 순서대로 짧게 정리하세요.",
            "시선과 말의 속도는 안정적으로 유지하세요.",
        ],
    }
    return 200, {
        "provider": "fake",
        "providerStatus": "fake",
        "model": _safe_str(settings.get("model"), 120) or "fake-coach",
        "coachFeedback": feedback,
    }


def _extract_openai_output_text(payload: dict[str, Any]) -> str:
    output_text = _safe_str(payload.get("output_text"), 10_000)
    if output_text:
        return output_text
    texts: list[str] = []
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        text = _safe_str(part.get("text"), 10_000)
                        if text:
                            texts.append(text)
    return "\n".join(texts)


def _openai_coach_feedback(settings: dict[str, object], result: dict[str, Any], interview_id: str, turn_index: int) -> tuple[int, dict[str, object]]:
    api_key = _safe_str(settings.get("openaiApiKey"), 500)
    if not api_key:
        return 503, {"error": "coach_llm_missing_key", "provider": "openai", "providerStatus": "not_configured"}
    endpoint = f"{settings['openaiApiBase']}/responses"
    body = json.dumps({
        "model": settings["model"],
        "instructions": "Return only valid JSON for concise Korean interview coaching feedback.",
        "input": _build_coach_feedback_prompt(result, interview_id, turn_index),
        "store": False,
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=float(settings["timeout"])) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        return 502, {"error": "coach_llm_rejected", "provider": "openai", "providerStatus": "provider_error", "status": error.code, "message": _redact_provider_error(error_body)}
    except urllib.error.URLError as error:
        return 502, {"error": "coach_llm_unavailable", "provider": "openai", "providerStatus": "network_error", "message": _redact_provider_error(str(error))}
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError:
        return 502, {"error": "invalid_coach_llm_response", "provider": "openai", "providerStatus": "invalid_response", "status": status}
    if not isinstance(parsed, dict):
        return 502, {"error": "invalid_coach_llm_response", "provider": "openai", "providerStatus": "invalid_response", "status": status}
    feedback_json = _parse_json_object_from_text(_extract_openai_output_text(parsed))
    if feedback_json is None:
        return 502, {"error": "invalid_coach_llm_response", "provider": "openai", "providerStatus": "invalid_json", "status": status}
    return 200, {
        "provider": "openai",
        "providerStatus": "provider",
        "status": status,
        "model": _safe_str(settings.get("model"), 120),
        "coachFeedback": _coerce_coach_feedback(feedback_json),
    }


def _extract_gemini_output_text(payload: dict[str, Any]) -> str:
    texts: list[str] = []
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            parts = content.get("parts") if isinstance(content, dict) else None
            if isinstance(parts, list):
                for part in parts:
                    if isinstance(part, dict):
                        text = _safe_str(part.get("text"), 10_000)
                        if text:
                            texts.append(text)
    return "\n".join(texts)


def _gemini_coach_feedback(settings: dict[str, object], result: dict[str, Any], interview_id: str, turn_index: int) -> tuple[int, dict[str, object]]:
    api_key = _safe_str(settings.get("geminiApiKey"), 500)
    if not api_key:
        return 503, {"error": "coach_llm_missing_key", "provider": "gemini", "providerStatus": "not_configured"}
    model = _safe_str(settings.get("model"), 120) or "gemini-2.5-flash"
    endpoint = f"{settings['geminiApiBase']}/models/{urllib.parse.quote(model, safe='')}:generateContent"
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": _build_coach_feedback_prompt(result, interview_id, turn_index)}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "X-goog-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=float(settings["timeout"])) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        return 502, {"error": "coach_llm_rejected", "provider": "gemini", "providerStatus": "provider_error", "status": error.code, "message": _redact_provider_error(error_body)}
    except urllib.error.URLError as error:
        return 502, {"error": "coach_llm_unavailable", "provider": "gemini", "providerStatus": "network_error", "message": _redact_provider_error(str(error))}
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError:
        return 502, {"error": "invalid_coach_llm_response", "provider": "gemini", "providerStatus": "invalid_response", "status": status}
    if not isinstance(parsed, dict):
        return 502, {"error": "invalid_coach_llm_response", "provider": "gemini", "providerStatus": "invalid_response", "status": status}
    feedback_json = _parse_json_object_from_text(_extract_gemini_output_text(parsed))
    if feedback_json is None:
        return 502, {"error": "invalid_coach_llm_response", "provider": "gemini", "providerStatus": "invalid_json", "status": status}
    return 200, {
        "provider": "gemini",
        "providerStatus": "provider",
        "status": status,
        "model": model,
        "coachFeedback": _coerce_coach_feedback(feedback_json),
    }


def coach_feedback_response(interview_id: str, turn_index: int) -> tuple[int, dict[str, object]]:
    start = time.perf_counter()
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        return 400, {"error": "invalid_interview_id"}
    if turn_index < 1:
        return 400, {"error": "invalid_turn_index"}

    result, source = _fetch_analysis_result(interview_id, turn_index)
    reason = ""
    failure = _analysis_result_gate_failure(result, interview_id, turn_index)
    if failure:
        reason = failure[0]
    elif result is not None and not _analysis_result_turn_matches(result, interview_id, turn_index):
        reason = "exact_turn_analysis_result_required"
    elif not _candidate_safe_fragment_from_result(result or {}) or bool((result or {}).get("rawTranscriptLogged", False)) or bool((result or {}).get("rawMediaAccepted", False)):
        reason = "candidate_safe_ready_result_required"

    analysis = _coach_analysis_summary(result, source)
    delivery = {
        "mode": "api-mediated-coach-feedback",
        "source": "api-owned-coach-llm" if not reason else "analysis-turn-result",
        "analysisEndpoint": "/realtime/turn-results",
        "rawAnalysisReturned": False,
    }
    if reason:
        payload = {
            "interviewId": interview_id,
            "turnIndex": turn_index,
            "status": "pending",
            "coachFeedback": _coach_feedback_pending_payload(reason),
            "coachLlm": {"attempted": False, "reason": reason},
            "analysis": analysis,
            "delivery": delivery,
        }
        return _return_with_latency(202, payload, start, "api.coach.feedback", session_id=interview_id, turn_index=turn_index, provider="analysis-engine")

    settings = _coach_llm_settings()
    provider = _safe_str(settings.get("provider"), 40)
    assert result is not None
    if provider == "fake":
        llm_status, llm_payload = _fake_coach_feedback(result, interview_id, turn_index, settings)
    elif provider == "openai":
        llm_status, llm_payload = _openai_coach_feedback(settings, result, interview_id, turn_index)
    elif provider == "gemini":
        llm_status, llm_payload = _gemini_coach_feedback(settings, result, interview_id, turn_index)
    else:
        llm_status, llm_payload = 400, {"error": "unsupported_coach_llm_provider", "provider": provider, "providerStatus": "unsupported"}

    if llm_status != 200:
        payload = {
            "error": llm_payload.get("error", "coach_llm_failed"),
            "message": "provider request failed",
            "interviewId": interview_id,
            "turnIndex": turn_index,
            "status": "failed",
            "analysis": analysis,
            "coachLlm": {
                "attempted": True,
                "provider": _safe_str(llm_payload.get("provider") or provider, 80),
                "providerStatus": _safe_str(llm_payload.get("providerStatus"), 80),
                "model": _safe_str(settings.get("model"), 120),
                "status": llm_payload.get("status") if isinstance(llm_payload.get("status"), int) else None,
            },
            "delivery": delivery,
        }
        return _return_with_latency(llm_status, payload, start, "api.coach.feedback", session_id=interview_id, turn_index=turn_index, provider=provider)

    payload = {
        "interviewId": interview_id,
        "turnIndex": turn_index,
        "status": "ready",
        "coachFeedback": llm_payload["coachFeedback"],
        "coachLlm": {
            "attempted": True,
            "provider": _safe_str(llm_payload.get("provider") or provider, 80),
            "providerStatus": _safe_str(llm_payload.get("providerStatus"), 80),
            "model": _safe_str(llm_payload.get("model"), 120),
            "status": llm_payload.get("status") if isinstance(llm_payload.get("status"), int) else None,
        },
        "analysis": analysis,
        "delivery": delivery,
    }
    return _return_with_latency(200, payload, start, "api.coach.feedback", session_id=interview_id, turn_index=turn_index, provider=provider)


def _realtime_response_create_command(instructions: str) -> dict[str, object]:
    return {
        "type": "response.create",
        "response": {
            "output_modalities": ["audio"],
            "instructions": instructions,
        },
    }


def _initial_realtime_question_instructions(payload: dict[str, Any]) -> str:
    requested = payload.get("response") if isinstance(payload.get("response"), dict) else {}
    instructions = _candidate_safe_fragment(requested.get("instructions"))
    if instructions:
        return instructions
    return (
        "You are a Korean live interviewer. Ask one concise opening interview question in Korean. "
        "Do not mention implementation details or internal labels. "
        "If context is missing, ask a broadly useful first question about the candidate's recent relevant experience."
    )


def create_realtime_response(interview_id: str, turn_index: int, payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    start = time.perf_counter()
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        return 400, {"error": "invalid_interview_id"}
    if turn_index < 1:
        return 400, {"error": "invalid_turn_index"}

    analysis_turn_index = turn_index - 1
    if turn_index == 1:
        instructions = _initial_realtime_question_instructions(payload)
        command = _realtime_response_create_command(instructions)
        REALTIME_RESPONSE_COMMANDS.setdefault(interview_id, {})[turn_index] = {
            "commandType": "response.create",
            "bootstrap": True,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _log_latency_span("api.realtime.context.inject", 0, status=200, sessionId=interview_id, turnIndex=turn_index, traceId=_trace_id(interview_id, turn_index), provider="openai-realtime")
        response_create = {"owner": "api", "created": True, "commandType": "response.create"}
        debug_response_create = {**response_create, "reason": "no_prior_candidate_answer"}
        return _return_with_latency(202, {
            "interviewId": interview_id,
            "turnIndex": turn_index,
            "analysisTurnIndex": None,
            "status": "response_create_queued",
            "bootstrap": {"firstQuestion": True, "mmmGateRequired": False, "reason": "no_prior_candidate_answer"},
            "responseCreate": response_create,
            "mmmDebug": _mmm_debug_envelope(interview_id, turn_index, analysis_turn_index=None, response_create=debug_response_create),
            "sideband": {
                "controlBoundary": "server-sideband",
                "singleResponseCreateOwner": "api",
                "browserTransportOnly": True,
                "command": command,
            },
            "delivery": _realtime_delivery("api-sideband-response-create"),
        }, start, "api.realtime.response.create", session_id=interview_id, turn_index=turn_index, provider="openai-realtime")

    readiness = _readiness_payload_with_durable_fallback(interview_id, analysis_turn_index)
    if not readiness.get("full_mmm_ready"):
        response_create = {"owner": "api", "created": False, "reason": "full_mmm_required_for_prior_answer"}
        return _return_with_latency(409, {
            "error": "analysis_result_not_ready",
            "interviewId": interview_id,
            "turnIndex": turn_index,
            "analysisTurnIndex": analysis_turn_index,
            "readiness": readiness,
            "responseCreate": response_create,
            "mmmDebug": _mmm_debug_envelope(interview_id, turn_index, analysis_turn_index=analysis_turn_index, readiness=readiness, response_create=response_create),
            "delivery": _realtime_delivery("api-sideband-response-create"),
        }, start, "api.realtime.response.create", session_id=interview_id, turn_index=turn_index, provider="openai-realtime")

    wait_start = time.perf_counter()
    result, source = _fetch_analysis_result(interview_id, analysis_turn_index)
    _log_latency_span("api.analysis.result.wait", _duration_ms(wait_start), status=200 if result else 504, sessionId=interview_id, turnIndex=analysis_turn_index, traceId=_trace_id(interview_id, analysis_turn_index), provider="analysis-engine")
    inline_result = _extract_analysis_result(payload)
    if result is None and inline_result is not None and not _analysis_result_turn_matches(inline_result, interview_id, analysis_turn_index):
        response_create = {"owner": "api", "created": False, "reason": "exact_turn_analysis_result_required"}
        return _return_with_latency(409, {
            "error": "analysis_result_wrong_turn",
            "interviewId": interview_id,
            "turnIndex": turn_index,
            "analysisTurnIndex": analysis_turn_index,
            "readiness": readiness,
            "analysisEngine": source,
            "responseCreate": response_create,
            "mmmDebug": _mmm_debug_envelope(
                interview_id,
                turn_index,
                analysis_turn_index=analysis_turn_index,
                readiness=readiness,
                analysis_engine=source,
                response_create=response_create,
            ),
            "delivery": _realtime_delivery("api-sideband-response-create"),
        }, start, "api.realtime.response.create", session_id=interview_id, turn_index=turn_index, provider="openai-realtime")
    gate_failure = _analysis_result_gate_failure(result, interview_id, analysis_turn_index)
    if gate_failure:
        error, reason = gate_failure
        response_create = {"owner": "api", "created": False, "reason": reason}
        return _return_with_latency(409, {
            "error": error,
            "interviewId": interview_id,
            "turnIndex": turn_index,
            "analysisTurnIndex": analysis_turn_index,
            "readiness": readiness,
            "analysisResult": _analysis_result_public_summary(result or {}),
            "analysisEngine": source,
            "responseCreate": response_create,
            "mmmDebug": _mmm_debug_envelope(
                interview_id,
                turn_index,
                analysis_turn_index=analysis_turn_index,
                readiness=readiness,
                analysis_engine=source,
                response_create=response_create,
                analysis_result=result,
            ),
            "delivery": _realtime_delivery("api-sideband-response-create"),
        }, start, "api.realtime.response.create", session_id=interview_id, turn_index=turn_index, provider="openai-realtime")

    if result is not None and not _analysis_result_turn_matches(result, interview_id, analysis_turn_index):
        response_create = {"owner": "api", "created": False, "reason": "exact_turn_analysis_required"}
        return _return_with_latency(409, {
            "error": "analysis_result_stale_or_wrong_turn",
            "interviewId": interview_id,
            "turnIndex": turn_index,
            "analysisTurnIndex": analysis_turn_index,
            "readiness": readiness,
            "analysisResult": _analysis_result_public_summary(result),
            "analysisEngine": source,
            "responseCreate": response_create,
            "mmmDebug": _mmm_debug_envelope(
                interview_id,
                turn_index,
                analysis_turn_index=analysis_turn_index,
                readiness=readiness,
                analysis_engine=source,
                response_create=response_create,
                analysis_result=result,
            ),
            "delivery": _realtime_delivery("api-sideband-response-create"),
        }, start, "api.realtime.response.create", session_id=interview_id, turn_index=turn_index, provider="openai-realtime")

    fragment = _candidate_safe_fragment_from_result(result)
    if not fragment or bool((result or {}).get("rawTranscriptLogged", False)) or bool((result or {}).get("rawMediaAccepted", False)):
        response_create = {"owner": "api", "created": False, "reason": "candidate_safe_ready_result_required"}
        return _return_with_latency(409, {
            "error": "analysis_result_not_usable",
            "interviewId": interview_id,
            "turnIndex": turn_index,
            "analysisTurnIndex": analysis_turn_index,
            "readiness": readiness,
            "analysisResult": _analysis_result_public_summary(result or {}),
            "analysisEngine": source,
            "responseCreate": response_create,
            "mmmDebug": _mmm_debug_envelope(
                interview_id,
                turn_index,
                analysis_turn_index=analysis_turn_index,
                readiness=readiness,
                analysis_engine=source,
                response_create=response_create,
                analysis_result=result,
            ),
            "delivery": _realtime_delivery("api-sideband-response-create"),
        }, start, "api.realtime.response.create", session_id=interview_id, turn_index=turn_index, provider="openai-realtime")

    _log_latency_span("api.analysis.result.ready", 0, status=200, sessionId=interview_id, turnIndex=analysis_turn_index, traceId=_trace_id(interview_id, analysis_turn_index), provider="analysis-engine")
    expected_hashimoto_turn_id = _hashimoto_turn_id(analysis_turn_index)
    strategy_start = time.perf_counter()
    hashimoto_strategy, hashimoto_source = _fetch_hashimoto_strategy(interview_id, expected_hashimoto_turn_id)
    _log_latency_span(
        "api.hashimoto.strategy.wait",
        _duration_ms(strategy_start),
        status=hashimoto_source.get("status") if isinstance(hashimoto_source.get("status"), int) else (200 if hashimoto_strategy else 204),
        sessionId=interview_id,
        turnIndex=analysis_turn_index,
        traceId=_trace_id(interview_id, analysis_turn_index),
        provider="hashimoto",
    )
    strategy_guidance = _hashimoto_strategy_guidance(hashimoto_strategy) if hashimoto_strategy else ""
    if strategy_guidance:
        hashimoto_source["used"] = True
    elif hashimoto_strategy:
        hashimoto_source["reason"] = "no_safe_guidance"
    instructions = (
        "Use this candidate-safe guidance from the previous answer to ask the next Korean interview question. "
        "Do not mention internal infrastructure, private gating, or analysis labels. "
        f"Guidance: {fragment}"
    )
    if strategy_guidance:
        instructions = (
            f"{instructions}\n\n"
            "Interview strategy guidance:\n"
            f"{strategy_guidance}"
        )
    command = _realtime_response_create_command(instructions)
    analysis_summary = _analysis_result_public_summary(result)
    hashimoto_summary = _safe_hashimoto_strategy_debug(hashimoto_source)
    REALTIME_RESPONSE_COMMANDS.setdefault(interview_id, {})[turn_index] = {
        "commandType": "response.create",
        "analysisTurnIndex": analysis_turn_index,
        "analysis": analysis_summary,
        "hashimotoStrategy": hashimoto_summary,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _log_latency_span("api.realtime.context.inject", 0, status=200, sessionId=interview_id, turnIndex=turn_index, traceId=_trace_id(interview_id, turn_index), provider="openai-realtime")
    response_create = {"owner": "api", "created": True, "commandType": "response.create"}
    debug_response_create = {**response_create, "reason": "candidate_safe_ready_result_available"}
    return _return_with_latency(202, {
        "interviewId": interview_id,
        "turnIndex": turn_index,
        "analysisTurnIndex": analysis_turn_index,
        "status": "response_create_queued",
        "analysisResult": analysis_summary,
        "analysisEngine": source,
        "hashimotoStrategy": hashimoto_summary,
        "responseCreate": response_create,
        "mmmDebug": _mmm_debug_envelope(
            interview_id,
            turn_index,
            analysis_turn_index=analysis_turn_index,
            readiness=readiness,
            analysis_engine=source,
            response_create=debug_response_create,
            analysis_result=result,
        ),
        "sideband": {
            "controlBoundary": "server-sideband",
            "singleResponseCreateOwner": "api",
            "browserTransportOnly": True,
            "command": command,
        },
        "delivery": _realtime_delivery("api-sideband-response-create"),
    }, start, "api.realtime.response.create", session_id=interview_id, turn_index=turn_index, provider="openai-realtime")


def record_realtime_turn_event(interview_id: str, turn_index: int, payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    start = time.perf_counter()
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        return 400, {"error": "invalid_interview_id"}
    raw_payload = json.dumps(payload, ensure_ascii=False)
    if len(raw_payload.encode("utf-8")) > MAX_REALTIME_EVENT_BYTES:
        return 413, {"error": "event_too_large"}
    kind = _event_kind(payload)
    state = _turn_state(interview_id, turn_index)
    _append_realtime_event(state, kind, payload)
    if kind in {"turn.answer_ended", "turn.answer.end"}:
        state["answer_ended"] = True
        detail = payload.get("detail")
        if isinstance(detail, dict) and detail.get("transcriptAvailable") is True:
            state["transcript_non_empty"] = True
    if kind in {"transcript.delta", "analysis.transcript.delta"} and _contains_non_empty_transcript(payload):
        state["transcript_non_empty"] = True
    if kind in {"transcript.completed", "analysis.transcript.completed"}:
        state["transcript_completed"] = True
        if _contains_non_empty_transcript(payload):
            state["transcript_non_empty"] = True
    if kind == "prosody.window_metrics":
        state["prosody_observed"] = True
    if kind == "vision.frame_metrics":
        state["vision_observed"] = True
    if kind == "readiness_gate.full_mmm_ready":
        state["readiness_marker_observed"] = True
    engine_detail = _sideband_detail_for_engine(payload)
    public = {
        "interviewId": interview_id,
        "turnIndex": turn_index,
        "accepted": True,
        "eventKind": kind,
        "rawMediaAccepted": False,
        "rawTranscriptLogged": False,
        "delivery": _realtime_delivery("api-mediated-realtime-turn-event"),
        "readiness": _readiness_payload(interview_id, turn_index),
        "ingress": _record_realtime_mmm_ingress(interview_id, turn_index, kind, "turn-events", engine_detail=engine_detail),
    }
    if kind in {"transcript.completed", "analysis.transcript.completed"}:
        public["hashimoto"] = _feed_hashimoto_turn(interview_id, turn_index, _transcript_from_realtime_event(payload))
    return _return_with_latency(202, public, start, "api.realtime.turn_event.total", session_id=interview_id, turn_index=turn_index, provider="api-mediated")


def record_realtime_vision_event(interview_id: str, turn_index: int, payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    start = time.perf_counter()
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        return 400, {"error": "invalid_interview_id"}
    raw_payload = json.dumps(payload, ensure_ascii=False)
    if len(raw_payload.encode("utf-8")) > MAX_REALTIME_VISION_EVENT_BYTES:
        return 413, {"error": "event_too_large"}
    if payload.get("rawMediaIncluded") is True or "rawMedia" in payload or "frame" in payload:
        return 400, {"error": "raw_media_not_allowed"}
    kind = _event_kind(payload)
    if kind not in {"vision.frame_metrics", "vision_metadata"}:
        return 400, {"error": "unsupported_vision_event"}
    engine_detail, detail_error = _sideband_vision_detail_for_engine(payload)
    if detail_error:
        status = 413 if detail_error == "vision_frame_too_large" else 400
        return status, {"error": detail_error}
    state = _turn_state(interview_id, turn_index)
    state["vision_observed"] = True
    _append_realtime_event(state, "vision.frame_metrics", payload)
    public = {
        "interviewId": interview_id,
        "turnIndex": turn_index,
        "accepted": True,
        "eventKind": "vision.frame_metrics",
        "rawMediaAccepted": False,
        "internalVisionFrameForwarded": bool(engine_detail and "visionFrame" in engine_detail),
        "delivery": _realtime_delivery("api-mediated-realtime-vision-event"),
        "readiness": _readiness_payload(interview_id, turn_index),
        "ingress": _record_realtime_mmm_ingress(interview_id, turn_index, "vision.frame_metrics", "vision-events", engine_detail=engine_detail),
    }
    return _return_with_latency(202, public, start, "api.realtime.vision_event.total", session_id=interview_id, turn_index=turn_index, provider="api-mediated")


def _openai_realtime_key() -> str | None:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    return key or None


def _safety_identifier(interview_id: str) -> str:
    salt = os.getenv("OPENAI_REALTIME_SAFETY_SALT", "giljob-realtime-v1")
    digest = hashlib.sha256(f"{salt}:{interview_id}".encode("utf-8")).hexdigest()
    return f"giljob:{digest[:32]}"


def _default_realtime_session_config(interview_id: str, payload: dict[str, Any] | None = None) -> dict[str, object]:
    payload = payload or {}
    instructions = _safe_str(
        payload.get("instructions")
        or "You are a Korean interviewer for a live voice interview. Backend readiness is already enforced before responses. Never mention MMM, sideband, backend, transcript, analysis-engine, or internal gates to the candidate. If the candidate asks a clarification question, answer it briefly first, then ask one natural next interview question in Korean.",
        MAX_REALTIME_INSTRUCTIONS_CHARS,
    )
    return {
        "session": {
            "type": "realtime",
            "model": _safe_str(payload.get("model") or OPENAI_REALTIME_MODEL, 120),
            "instructions": instructions,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "transcription": {
                        "model": OPENAI_REALTIME_TRANSCRIPTION_MODEL,
                        **({"language": OPENAI_REALTIME_TRANSCRIPTION_LANGUAGE} if OPENAI_REALTIME_TRANSCRIPTION_LANGUAGE else {}),
                        **({"delay": OPENAI_REALTIME_TRANSCRIPTION_DELAY} if OPENAI_REALTIME_TRANSCRIPTION_DELAY else {}),
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "create_response": False,
                        "interrupt_response": False,
                    },
                },
                "output": {"voice": _safe_str(payload.get("voice") or OPENAI_REALTIME_VOICE, 80)},
            },
        }
    }


def _default_realtime_call_session_config(interview_id: str, payload: dict[str, Any] | None = None) -> dict[str, object]:
    """Session config for the unified WebRTC /realtime/calls attach.

    Keep the initial calls payload close to the official unified-interface
    example: SDP plus a small `session` object. STT/VAD knobs are applied after
    the data channel opens via `session.update`, which avoids provider-side 400s
    during SDP attach while preserving the API-owned response gate.
    """
    session = _default_realtime_session_config(interview_id, payload).get("session")
    if not isinstance(session, dict):
        session = {}
    audio = session.get("audio") if isinstance(session.get("audio"), dict) else {}
    output = audio.get("output") if isinstance(audio.get("output"), dict) else {"voice": OPENAI_REALTIME_VOICE}
    config: dict[str, object] = {
        "type": "realtime",
        "model": _safe_str(session.get("model") or OPENAI_REALTIME_MODEL, 120),
        "audio": {"output": output},
    }
    instructions = session.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        config["instructions"] = _safe_str(instructions, MAX_REALTIME_INSTRUCTIONS_CHARS)
    return config


def _realtime_post_connect_session_update() -> dict[str, object]:
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "audio": {
                "input": {
                    "transcription": {
                        "model": OPENAI_REALTIME_TRANSCRIPTION_MODEL,
                        **({"language": OPENAI_REALTIME_TRANSCRIPTION_LANGUAGE} if OPENAI_REALTIME_TRANSCRIPTION_LANGUAGE else {}),
                        **({"delay": OPENAI_REALTIME_TRANSCRIPTION_DELAY} if OPENAI_REALTIME_TRANSCRIPTION_DELAY else {}),
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "create_response": False,
                        "interrupt_response": False,
                    },
                }
            }
        },
    }


def _openai_realtime_sdp_endpoint(model: object | None = None) -> str:
    _ = model  # Realtime Calls SDP attach endpoint is model-less; model is set when minting the ephemeral session.
    return f"{OPENAI_REALTIME_API_BASE}/realtime/calls"


def _openai_realtime_calls_endpoint() -> str:
    return f"{OPENAI_REALTIME_API_BASE}/realtime/calls"


def _multipart_form_data(fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"giljob-realtime-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        safe_name = name.replace("\r", "").replace("\n", "")
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{safe_name}"\r\n\r\n'.encode("utf-8"))
        chunks.append(value.encode("utf-8"))
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _parse_realtime_response(raw_body: str, status: int) -> dict[str, object]:
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    if status >= 400:
        return {"error": "realtime_provider_failed", "provider": "openai-realtime", "message": "provider request failed"}
    client_secret = parsed.get("client_secret")
    if isinstance(client_secret, dict):
        parsed["client_secret"] = {key: value for key, value in client_secret.items() if key in {"type", "value", "expires_at", "expires_in"}}
    elif isinstance(parsed.get("value"), str):
        # OpenAI Realtime client_secrets can return the ephemeral secret as a
        # top-level value/expires_at pair instead of a nested client_secret dict.
        # Normalize both shapes for the browser-facing API without exposing
        # provider-only session internals.
        normalized_secret: dict[str, object] = {"type": "ephemeral", "value": parsed["value"]}
        if "expires_at" in parsed:
            normalized_secret["expires_at"] = parsed["expires_at"]
        if "expires_in" in parsed:
            normalized_secret["expires_in"] = parsed["expires_in"]
        parsed["client_secret"] = normalized_secret
    safe: dict[str, object] = {
        "provider": "openai-realtime",
        "status": "issued",
    }
    session = parsed.get("session")
    if isinstance(session, dict):
        for key in ("id", "object", "model", "modalities", "voice", "expires_at"):
            if key in session and key not in parsed:
                parsed[key] = session[key]
    for key in ("id", "object", "model", "modalities", "voice", "expires_at"):
        if key in parsed:
            safe[key] = parsed[key]
    safe["clientSecretPolicy"] = "server-only-api-call-broker"
    return safe


def create_realtime_session(interview_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    start = time.perf_counter()
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        return 400, {"error": "invalid_interview_id"}
    api_key = _openai_realtime_key()
    if not api_key:
        return _return_with_latency(503, _realtime_unavailable_payload(), start, "api.realtime.session.total", session_id=interview_id, provider="openai-realtime")
    request_payload = json.dumps(_default_realtime_session_config(interview_id, payload)).encode("utf-8")
    request = urllib.request.Request(
        f"{OPENAI_REALTIME_API_BASE}/realtime/client_secrets",
        data=request_payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "OpenAI-Safety-Identifier": _safety_identifier(interview_id),
        },
    )
    upstream_start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=OPENAI_REALTIME_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
            upstream_status = response.status
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        upstream_status = error.code
    except urllib.error.URLError:
        _log_latency_span("api.openai_realtime.session.upstream", _duration_ms(upstream_start), status=502, sessionId=interview_id, traceId=_trace_id(interview_id), provider="openai-realtime")
        return _return_with_latency(502, _realtime_unavailable_payload("realtime_provider_failed"), start, "api.realtime.session.total", session_id=interview_id, provider="openai-realtime")
    _log_latency_span("api.openai_realtime.session.upstream", _duration_ms(upstream_start), status=upstream_status, sessionId=interview_id, traceId=_trace_id(interview_id), provider="openai-realtime")
    public = _parse_realtime_response(body, upstream_status)
    public["interviewId"] = interview_id
    public["sideband"] = {
        "controlBoundary": "server-sideband",
        "fullMmmRequiredBeforeResponseCreate": True,
        "privilegedTools": "backend-only",
    }
    public["webrtc"] = {
        "sdpEndpoint": _openai_realtime_sdp_endpoint(public.get("model") or OPENAI_REALTIME_MODEL),
        "sdpContentType": "application/sdp",
        "auth": "api-call-broker-server-side-provider-auth",
        "standardOpenAIKey": "server-only",
        "rawSdpLogging": "forbidden",
        "postConnectSessionUpdate": _realtime_post_connect_session_update(),
    }
    public["delivery"] = _realtime_delivery("api-mediated-realtime-session")
    return _return_with_latency(upstream_status if upstream_status < 500 else 502, public, start, "api.realtime.session.total", session_id=interview_id, provider="openai-realtime")


def create_realtime_call(interview_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    start = time.perf_counter()
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        return 400, {"error": "invalid_interview_id"}
    api_key = _openai_realtime_key()
    if not api_key:
        return _return_with_latency(503, _realtime_unavailable_payload("realtime_not_configured"), start, "api.realtime.call.total", session_id=interview_id, provider="openai-realtime")
    sdp = _safe_sdp(payload.get("sdp") or payload.get("offerSdp") or "", MAX_SDP_CHARS)
    if not sdp:
        return 400, {"error": "missing_sdp"}
    if os.getenv("OPENAI_REALTIME_CALL_BROKER_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return _return_with_latency(202, {
            "interviewId": interview_id,
            "provider": "openai-realtime",
            "status": "call_broker_prepared",
            "callId": None,
            "sdpAnswer": None,
            "sideband": {
                "callIdSource": "OpenAI Location header when broker is enabled",
                "serverControlUrl": "wss://api.openai.com/v1/realtime?call_id=<callId>",
                "fullMmmRequiredBeforeResponseCreate": True,
            },
            "delivery": _realtime_delivery("api-mediated-realtime-call"),
        }, start, "api.realtime.call.total", session_id=interview_id, provider="openai-realtime")

    session_config = _default_realtime_call_session_config(interview_id, payload)
    multipart_body, content_type = _multipart_form_data({
        "sdp": sdp,
        "session": json.dumps(session_config),
    })
    request = urllib.request.Request(
        _openai_realtime_calls_endpoint(),
        data=multipart_body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": content_type,
            "OpenAI-Safety-Identifier": _safety_identifier(interview_id),
        },
    )
    upstream_start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=OPENAI_REALTIME_TIMEOUT_SECONDS) as response:
            answer_sdp = response.read().decode("utf-8", errors="replace")
            upstream_status = response.status
            location = response.headers.get("Location") or ""
    except urllib.error.HTTPError as error:
        error.read()
        upstream_status = error.code
        answer_sdp = ""
        location = ""
    except urllib.error.URLError:
        _log_latency_span("api.openai_realtime.call.upstream", _duration_ms(upstream_start), status=502, sessionId=interview_id, traceId=_trace_id(interview_id), provider="openai-realtime")
        return _return_with_latency(502, _realtime_unavailable_payload("realtime_provider_failed"), start, "api.realtime.call.total", session_id=interview_id, provider="openai-realtime")
    _log_latency_span("api.openai_realtime.call.upstream", _duration_ms(upstream_start), status=upstream_status, sessionId=interview_id, traceId=_trace_id(interview_id), provider="openai-realtime")
    if upstream_status >= 400 or not answer_sdp.strip():
        return _return_with_latency(502, _realtime_unavailable_payload("realtime_provider_failed"), start, "api.realtime.call.total", session_id=interview_id, provider="openai-realtime")
    call_id = ""
    if location:
        parsed_location = urllib.parse.urlparse(location)
        call_id = urllib.parse.parse_qs(parsed_location.query).get("call_id", [""])[0]
    return _return_with_latency(200, {
        "interviewId": interview_id,
        "provider": "openai-realtime",
        "status": "call_broker_connected",
        "callId": _safe_str(call_id, 120) if call_id else None,
        "sdpAnswer": {"type": "answer", "sdp": answer_sdp},
        "sideband": {
            "callIdSource": "OpenAI Location header",
            "serverControlUrl": "wss://api.openai.com/v1/realtime?call_id=<callId>",
            "fullMmmRequiredBeforeResponseCreate": True,
        },
        "delivery": _realtime_delivery("api-mediated-realtime-call"),
    }, start, "api.realtime.call.total", session_id=interview_id, provider="openai-realtime")


def _deprecated_ai_engine_payload(interview_id: str, turn_index: int | None = None, *, mode: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "interviewId": interview_id,
        "error": "deprecated_ai_engine_removed",
        "reason": "realtime_only",
        "status": "deprecated",
        "delivery": {
            "mode": mode,
            "source": "api",
            "publicDirectAiRoutes": "blocked",
            "publicDirectTtsRoutes": "blocked",
            "publicDirectAvatarRoutes": "blocked",
        },
    }
    if turn_index is not None:
        payload["turnIndex"] = turn_index
    return payload


def request_next_question(interview_id: str, turn_index: int, payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    start = time.perf_counter()
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        return 400, {"error": "invalid_interview_id"}
    if turn_index < 1:
        return 400, {"error": "invalid_turn_index"}
    return _return_with_latency(
        410,
        _deprecated_ai_engine_payload(interview_id, turn_index, mode="deprecated-question-route"),
        start,
        "api.next_question.deprecated",
        session_id=interview_id,
        turn_index=turn_index,
        provider="openai-realtime",
    )


def create_avatar_session(interview_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    start = time.perf_counter()
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        return 400, {"error": "invalid_interview_id"}

    if not _env_enabled("SPATIALREAL_SDK_MODE_WEB_ENABLED", "false"):
        return _return_with_latency(
            202,
            {
                "interviewId": interview_id,
                "provider": "spatialreal",
                "ready": False,
                "status": "deferred",
                "reason": "sdk_flag_disabled",
                "sdkMode": _avatar_sdk_mode_metadata(enabled=False, status="deferred", outcome="sdk_mode_deferred", reason="sdk_flag_disabled"),
                "delivery": {
                    "mode": "api-owned-avatar-session",
                    "source": "api",
                    "publicDirectAvatarRoutes": "blocked",
                },
            },
            start,
            "api.avatar_session.deferred",
            session_id=interview_id,
            provider="api-owned",
        )

    client_config, missing = _spatialreal_sdk_client_config()
    if client_config is None:
        return _return_with_latency(
            409,
            {
                "interviewId": interview_id,
                "provider": "spatialreal",
                "ready": False,
                "status": "blocked",
                "reason": "spatialreal_config_missing",
                "missing": missing,
                "sdkMode": _avatar_sdk_mode_metadata(enabled=True, status="blocked", outcome="sdk_mode_blocked_missing_provider_token", reason="spatialreal_config_missing"),
                "delivery": {
                    "mode": "api-owned-avatar-session",
                    "source": "api",
                    "publicDirectAvatarRoutes": "blocked",
                },
            },
            start,
            "api.avatar_session.blocked",
            session_id=interview_id,
            provider="api-owned",
        )

    return _return_with_latency(
        200,
        {
            "interviewId": interview_id,
            "provider": "spatialreal",
            "ready": True,
            "status": "ready",
            "reason": "sdk_mode_ready",
            "client": {"spatialrealSdk": client_config},
            "sdkMode": _avatar_sdk_mode_metadata(enabled=True, status="ready", outcome="sdk_mode_ready"),
            "delivery": {
                "mode": "api-owned-avatar-session",
                "source": "api",
                "publicDirectAvatarRoutes": "blocked",
                "livekitRequired": False,
            },
        },
        start,
        "api.avatar_session.ready",
        session_id=interview_id,
        provider="api-owned",
    )


def synthesize_room_tts(interview_id: str, turn_index: int, payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    start = time.perf_counter()
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        return 400, {"error": "invalid_interview_id"}
    if turn_index < 1:
        return 400, {"error": "invalid_turn_index"}
    return _return_with_latency(
        410,
        _deprecated_ai_engine_payload(interview_id, turn_index, mode="deprecated-tts-route"),
        start,
        "api.tts.deprecated",
        session_id=interview_id,
        turn_index=turn_index,
        provider="openai-realtime",
    )

class Handler(BaseHTTPRequestHandler):
    server_version = "GilJobV2API/0.2"

    def _json(self, status: int, payload: dict[str, object], *, write_body: bool = True) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if write_body:
            self.wfile.write(body)

    def _is_internal_path(self) -> bool:
        return self.path.startswith("/api/internal") or self.path.startswith("/internal")

    def _reject_internal_path(self, *, write_body: bool = True) -> bool:
        if self._is_internal_path():
            self._json(404, {"error": "not_found"}, write_body=write_body)
            return True
        return False

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            return {}
        if content_length > MAX_JSON_BODY_BYTES:
            raise ValueError("request body too large")
        raw_body = self.rfile.read(content_length)
        if not raw_body:
            return {}
        parsed = json.loads(raw_body.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("JSON body must be an object")
        return parsed

    def _handle_create_session(self) -> None:
        try:
            body = self._read_json_body()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self._json(400, {"error": "invalid_json", "message": str(exc)})
            return

        requested_role = str(body.get("role") or "candidate")
        requested_session_id = body.get("sessionId") or body.get("interviewId")
        try:
            issued = issue_session(requested_role=requested_role, requested_session_id=requested_session_id)
        except ValueError as exc:
            self._json(400, {"error": "invalid_session_id", "message": str(exc)})
            return
        stored = issued["stored"]
        public = issued["public"]
        session_id = str(public.get("sessionId") or stored["sessionId"])
        seed = _hashimoto_seed_from_session_payload(body)
        if seed:
            with HASHIMOTO_FEED_LOCK:
                HASHIMOTO_SESSION_SEEDS[session_id] = seed
                HASHIMOTO_BOOTSTRAPPED_SESSIONS.discard(session_id)
        public["realtime"] = _realtime_route_config(session_id)
        public["avatarSdkMode"] = _avatar_sdk_mode_metadata()
        SESSION_HASH_STORE[str(stored["sessionId"])] = stored
        self._json(201, public)

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if self._reject_internal_path():
            return
        coach_feedback_match = COACH_FEEDBACK_ROUTE_PATTERN.fullmatch(self.path)
        if coach_feedback_match:
            interview_id = coach_feedback_match.group(1)
            turn_index = int(coach_feedback_match.group(2))
            status, payload = coach_feedback_response(interview_id, turn_index)
            self._json(status, payload)
            return
        mmm_ready_match = REALTIME_MMM_READY_ROUTE_PATTERN.fullmatch(self.path)
        if mmm_ready_match:
            interview_id = mmm_ready_match.group(1)
            turn_index = int(mmm_ready_match.group(2))
            if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
                self._json(400, {"error": "invalid_interview_id"})
                return
            self._json(200, _readiness_payload_with_analysis_result(interview_id, turn_index))
            return
        if self.path == "/healthz":
            self._json(200, {"service": SERVICE_NAME, "status": "ok"})
            return
        if self.path == "/readyz":
            self._json(200, {"service": SERVICE_NAME, "status": "ok"})
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib callback name
        if self._reject_internal_path(write_body=False):
            return
        if self.path in {"/healthz", "/readyz"}:
            self._json(200, {"service": SERVICE_NAME, "status": "ok"}, write_body=False)
            return
        self._json(404, {"error": "not_found", "path": self.path}, write_body=False)

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib callback name
        if self._reject_internal_path():
            return
        self.send_response(204)
        self.send_header("Allow", "GET, HEAD, OPTIONS, POST, PUT, PATCH, DELETE")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        if self._reject_internal_path():
            return
        if self.path in {"/sessions", "/api/sessions"}:
            self._handle_create_session()
            return
        realtime_session_match = REALTIME_SESSION_ROUTE_PATTERN.fullmatch(self.path)
        if realtime_session_match:
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self._json(400, {"error": "invalid_json", "message": str(exc)})
                return
            status, payload = create_realtime_session(realtime_session_match.group(1), body)
            self._json(status, payload)
            return
        realtime_call_match = REALTIME_CALL_ROUTE_PATTERN.fullmatch(self.path)
        if realtime_call_match:
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self._json(400, {"error": "invalid_json", "message": str(exc)})
                return
            status, payload = create_realtime_call(realtime_call_match.group(1), body)
            self._json(status, payload)
            return
        realtime_response_match = REALTIME_RESPONSE_CREATE_ROUTE_PATTERN.fullmatch(self.path)
        if realtime_response_match:
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self._json(400, {"error": "invalid_json", "message": str(exc)})
                return
            status, payload = create_realtime_response(realtime_response_match.group(1), int(realtime_response_match.group(2)), body)
            self._json(status, payload)
            return
        turn_event_match = REALTIME_TURN_EVENTS_ROUTE_PATTERN.fullmatch(self.path)
        if turn_event_match:
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self._json(400, {"error": "invalid_json", "message": str(exc)})
                return
            status, payload = record_realtime_turn_event(turn_event_match.group(1), int(turn_event_match.group(2)), body)
            self._json(status, payload)
            return
        vision_event_match = REALTIME_VISION_EVENTS_ROUTE_PATTERN.fullmatch(self.path)
        if vision_event_match:
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self._json(400, {"error": "invalid_json", "message": str(exc)})
                return
            status, payload = record_realtime_vision_event(vision_event_match.group(1), int(vision_event_match.group(2)), body)
            self._json(status, payload)
            return
        question_match = NEXT_QUESTION_ROUTE_PATTERN.fullmatch(self.path)
        if question_match:
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self._json(400, {"error": "invalid_json", "message": str(exc)})
                return
            status, payload = request_next_question(question_match.group(1), int(question_match.group(2)), body)
            self._json(status, payload)
            return
        avatar_match = AVATAR_SESSION_ROUTE_PATTERN.fullmatch(self.path)
        if avatar_match:
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self._json(400, {"error": "invalid_json", "message": str(exc)})
                return
            status, payload = create_avatar_session(avatar_match.group(1), body)
            self._json(status, payload)
            return
        tts_match = TTS_ROUTE_PATTERN.fullmatch(self.path)
        if tts_match:
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self._json(400, {"error": "invalid_json", "message": str(exc)})
                return
            interview_id = tts_match.group(1)
            turn_index = int(tts_match.group(2))
            status, payload = synthesize_room_tts(interview_id, turn_index, body)
            self._json(status, payload)
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def do_PUT(self) -> None:  # noqa: N802 - stdlib callback name
        if self._reject_internal_path():
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def do_PATCH(self) -> None:  # noqa: N802 - stdlib callback name
        if self._reject_internal_path():
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib callback name
        if self._reject_internal_path():
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
