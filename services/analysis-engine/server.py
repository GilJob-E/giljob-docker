#!/usr/bin/env python3
"""GilJobE analysis-engine entrypoint with GilJob v2 Realtime MMM ingress.

GilJobE still owns the STT/subscriber HTTP contract. This wrapper builds the
same GilJobE aiohttp app and adds one GilJob-v2-specific route:

    POST /realtime/turn-events

The route accepts only sanitized Realtime sideband readiness metadata forwarded
by services/api. It does not accept raw media, raw provider tokens, or raw
transcripts, and it does not replace GilJobE's LiveKit subscriber path.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

from aiohttp import web

from giljobe.server.__main__ import _build_critic, _make_lanes, _port, _vllm_ready
from giljobe.server.http_app import make_app
from giljobe.server.service import AnalysisService, signals_payload

try:
    from giljobe.emit.handoff import render_prompt_fragment
except ImportError:  # 구 핀(turn_handoff 이전) — turn-results는 pending으로 강등
    render_prompt_fragment = None

logger = logging.getLogger(__name__)

MAX_REALTIME_MMM_RECORD_BYTES = int(os.getenv("MAX_REALTIME_MMM_RECORD_BYTES", "16384"))
MAX_REALTIME_MMM_RECORDS = int(os.getenv("MAX_REALTIME_MMM_RECORDS", "500"))
RAW_FIELD_MARKERS = {"rawMedia", "frame", "audio", "video", "sdp", "client_secret", "token", "apiKey", "transcript", "text"}
INTERNAL_TRANSCRIPT_DETAIL_PATHS = {("detail", "transcript"), ("detail", "text")}
SAFE_LANE_KEYS = ("transcript", "prosody", "vision")


class _EventOnlySession:
    def __init__(self, session_id: str, critic_mode: str, started_at: float) -> None:
        self.session_id = session_id
        self.critic_mode = critic_mode
        self.started_at = started_at
        self.records: list[dict[str, Any]] = []
        self.seen_sentence_keys: set[str] = set()
        self.last_sentence_end_s = 0.0


class _EventOnlyRealtimeTurns:
    """External transcript fallback for the Realtime branch.

    GilJobE's normal `/subscriber/start` path still owns the full LiveKit media
    analyzer. The Realtime base stack can run without LiveKit, though, so an
    external transcript turn must still be able to accept API sideband sentence
    events and produce a candidate-safe turn handoff.
    """

    def __init__(self) -> None:
        self._active: _EventOnlySession | None = None
        self._last: _EventOnlySession | None = None

    @property
    def enabled(self) -> bool:
        return os.getenv("GILJOBE_TRANSCRIPT_SOURCE", "internal").strip().lower() == "external"

    def start(self, session_id: str, critic_mode: str = "window") -> dict[str, object]:
        if self._active is not None:
            self.stop()
        self._active = _EventOnlySession(session_id, critic_mode, time.monotonic())
        return {
            "sessionId": session_id,
            "criticMode": critic_mode,
            "startedAt": self._active.started_at,
            "state": "running",
            "status": "running",
            "eventOnlyFallback": True,
            "rawMediaAccepted": False,
            "rawSecretsExposed": False,
        }

    def stop(self) -> dict[str, object]:
        sess = self._active
        if sess is None:
            return {"status": "idle"}
        self._finish(sess)
        self._active = None
        self._last = sess
        return {
            "sessionId": sess.session_id,
            "status": "stopped",
            "eventOnlyFallback": True,
            "recordCount": len(sess.records),
            "rawMediaAccepted": False,
            "rawSecretsExposed": False,
        }

    def ingest(self, payload: dict[str, Any]) -> dict[str, object]:
        sess = self._active
        if sess is None:
            return {"accepted": False, "reason": "no_active_session"}
        session_id = _safe_str(payload.get("sessionId") or payload.get("interviewId"), 96)
        if session_id and session_id != sess.session_id:
            return {"accepted": False, "reason": "session_mismatch"}
        kind = _safe_str(payload.get("eventKind") or payload.get("normalizedType") or payload.get("type"), 120)
        detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else {}
        text = detail.get("transcript") or detail.get("text")
        item_id = detail.get("itemId") or payload.get("itemId")
        sentence_added = False
        if isinstance(text, str) and text.strip() and kind in {"transcript.completed", "analysis.transcript.completed"}:
            key = _safe_str(item_id or text, 160)
            if key and key not in sess.seen_sentence_keys:
                sess.seen_sentence_keys.add(key)
                sentence = _safe_str(text, 8000)
                start_s = sess.last_sentence_end_s
                duration_s = max(0.8, min(8.0, len(sentence) / 18.0))
                end_s = start_s + duration_s
                sess.records.append({
                    "type": "sentence",
                    "t": round(time.monotonic() - sess.started_at, 3),
                    "start_s": round(start_s, 3),
                    "end_s": round(end_s, 3),
                    "text": sentence,
                })
                sess.last_sentence_end_s = end_s
                sentence_added = True
        if kind in {"turn.answer_ended", "turn.answer.end"}:
            self._finish(sess)
        return {
            "accepted": True,
            "eventKind": kind,
            "eventOnlyFallback": True,
            "sentenceAdded": sentence_added,
            "recordCount": len(sess.records),
        }

    def signals(self, session_id: str | None = None) -> dict[str, object]:
        for sess in (self._active, self._last):
            if sess is not None and (session_id is None or session_id == sess.session_id):
                return signals_payload(sess.session_id, sess.records)
        return signals_payload(session_id or "", [])

    def _finish(self, sess: _EventOnlySession) -> None:
        if any(record.get("type") == "turn_end" for record in sess.records):
            return
        transcript = " ".join(
            str(record.get("text", "")).strip()
            for record in sess.records
            if record.get("type") == "sentence" and str(record.get("text", "")).strip()
        )
        sess.records.append({
            "type": "turn_end",
            "t": round(time.monotonic() - sess.started_at, 3),
            "transcript_full": transcript,
        })


def _install_event_only_realtime_fallback(service: AnalysisService) -> _EventOnlyRealtimeTurns:
    event_only = _EventOnlyRealtimeTurns()
    original_start = service.start
    original_stop = service.stop
    original_ingest = service.ingest_realtime_event
    original_signals = service.signals

    async def start(session_id: str, critic_mode: str = "window") -> dict[str, object]:
        try:
            return await original_start(session_id, critic_mode)
        except Exception as exc:
            if not event_only.enabled:
                raise
            logger.warning(
                "LiveKit subscriber start failed; using external transcript event-only turn session=%s detail=%s",
                session_id,
                type(exc).__name__,
            )
            return event_only.start(session_id, critic_mode)

    async def stop() -> dict[str, object]:
        if event_only._active is not None:
            return event_only.stop()
        return await original_stop()

    def ingest_realtime_event(payload: dict[str, Any]) -> dict[str, object]:
        result = original_ingest(payload)
        if result.get("accepted") is False and event_only.enabled:
            fallback = event_only.ingest(payload)
            if fallback.get("accepted"):
                return fallback
        return result

    def signals(session_id: str | None = None) -> dict[str, object]:
        payload = original_signals(session_id)
        if payload.get("recordCount"):
            return payload
        fallback = event_only.signals(session_id)
        if fallback.get("recordCount"):
            return fallback
        return payload

    service.start = start  # type: ignore[method-assign]
    service.stop = stop  # type: ignore[method-assign]
    service.ingest_realtime_event = ingest_realtime_event  # type: ignore[method-assign]
    service.signals = signals  # type: ignore[method-assign]
    return event_only


def _safe_str(value: object, max_len: int = 240) -> str:
    text = "" if value is None else str(value)
    return " ".join(text.split())[:max_len]


def _safe_list(value: object, max_items: int = 8, max_len: int = 80) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_safe_str(item, max_len) for item in value[:max_items] if _safe_str(item, max_len)]


def _safe_lanes(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    lanes: dict[str, object] = {}
    for key in SAFE_LANE_KEYS:
        lane = value.get(key)
        if isinstance(lane, dict):
            lanes[key] = {
                "ready": bool(lane.get("ready")),
                "observed": bool(lane.get("observed")),
                "status": _safe_str(lane.get("status") or lane.get("state"), 80),
            }
        elif isinstance(lane, bool):
            lanes[key] = {"ready": lane, "observed": lane, "status": "ready" if lane else "missing"}
    return lanes


def _per_turn_mmm_result(payload: dict[str, Any], readiness: dict[str, Any]) -> dict[str, object]:
    lanes = _safe_lanes(readiness.get("lanes"))
    reason_codes = _safe_list(readiness.get("reasonCodes"))
    return {
        "schemaVersion": "2026-06-12.per-turn-mmm-result.v1",
        "sessionId": _safe_str(payload.get("sessionId") or payload.get("interviewId"), 96),
        "turnId": _safe_str(payload.get("turnId"), 32),
        "turnIndex": payload.get("turnIndex") if isinstance(payload.get("turnIndex"), int) else None,
        "eventKind": _safe_str(payload.get("eventKind"), 120),
        "ready": bool(readiness.get("full_mmm_ready")),
        "state": _safe_str(readiness.get("state"), 80),
        "reasonCodes": reason_codes,
        "lanes": lanes,
        "rawTranscriptLogged": False,
        "rawMediaAccepted": False,
    }


def _candidate_safe_prompt_fragment(result: dict[str, object]) -> dict[str, object]:
    ready = bool(result.get("ready"))
    reason_codes = result.get("reasonCodes") if isinstance(result.get("reasonCodes"), list) else []
    lanes = result.get("lanes") if isinstance(result.get("lanes"), dict) else {}
    lane_states = []
    for key in SAFE_LANE_KEYS:
        lane = lanes.get(key)
        if isinstance(lane, dict):
            status = _safe_str(lane.get("status"), 40) or ("ready" if lane.get("ready") else "missing")
        else:
            status = "missing"
        lane_states.append(f"{key}:{status}")
    state = _safe_str(result.get("state"), 80) or ("full_mmm_ready" if ready else "degraded_not_ready")
    guidance = "Proceed with one natural next interview question." if ready else "Do not invent unseen evidence; ask a brief clarification or wait for complete analysis."
    text = f"MMM readiness for this turn: {state}; lanes {', '.join(lane_states)}; reasons {', '.join(reason_codes) if reason_codes else 'none'}. {guidance}"
    return {
        "schemaVersion": "2026-06-12.candidate-safe-prompt-fragment.v1",
        "kind": "candidate_safe_mmm_context",
        "text": _safe_str(text, 600),
        "containsRawTranscript": False,
        "containsRawMedia": False,
        "containsSecrets": False,
    }


def _json(payload: dict[str, object], status: int = 200) -> web.Response:
    return web.json_response(payload, status=status, dumps=lambda item: json.dumps(item, ensure_ascii=False))


def _contains_forbidden_raw_field(value: Any, path: tuple[str, ...] = ()) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_str = str(key)
            nested_path = (*path, key_str)
            if key_str in RAW_FIELD_MARKERS and nested_path not in INTERNAL_TRANSCRIPT_DETAIL_PATHS:
                return True
            if _contains_forbidden_raw_field(nested, nested_path):
                return True
    if isinstance(value, list):
        return any(_contains_forbidden_raw_field(item, path) for item in value)
    return False


def _public_record(payload: dict[str, Any]) -> dict[str, object]:
    readiness = payload.get("readiness") if isinstance(payload.get("readiness"), dict) else {}
    result = _per_turn_mmm_result(payload, readiness)
    prompt_fragment = _candidate_safe_prompt_fragment(result)
    return {
        "schema_version": _safe_str(payload.get("schema_version") or payload.get("schemaVersion"), 80),
        "source": "api-sideband",
        "sessionId": result["sessionId"],
        "turnId": result["turnId"],
        "turnIndex": result["turnIndex"],
        "eventKind": result["eventKind"],
        "sourceRoute": _safe_str(payload.get("sourceRoute"), 120),
        "receivedAt": _safe_str(payload.get("receivedAt"), 80),
        "analysisEngineReceivedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rawTranscriptLogged": False,
        "rawMediaAccepted": False,
        "readiness": {
            "full_mmm_ready": result["ready"],
            "state": result["state"],
            "reasonCodes": result["reasonCodes"],
            "lanes": result["lanes"],
        },
        "perTurnMmmResult": result,
        "candidateSafePromptFragment": prompt_fragment,
    }


async def _realtime_turn_events(req: web.Request) -> web.Response:
    raw = await req.read()
    if len(raw) > MAX_REALTIME_MMM_RECORD_BYTES:
        return _json({"error": "record_too_large"}, status=413)
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _json({"error": "invalid_json"}, status=400)
    if not isinstance(payload, dict):
        return _json({"error": "invalid_json"}, status=400)
    if payload.get("rawMediaAccepted") is True or payload.get("rawTranscriptLogged") is True:
        return _json({"error": "raw_payload_not_allowed"}, status=400)
    if _contains_forbidden_raw_field(payload):
        return _json({"error": "raw_payload_not_allowed"}, status=400)

    record = _public_record(payload)
    records: list[dict[str, object]] = req.app["realtime_mmm_records"]
    records.append(record)
    del records[:-MAX_REALTIME_MMM_RECORDS]
    return _json({
        "accepted": True,
        "service": "analysis-engine",
        "endpoint": "/realtime/turn-events",
        "rawTranscriptLogged": False,
        "rawMediaAccepted": False,
        "recordCount": len(records),
    }, status=202)


async def _realtime_turn_events_tail(req: web.Request) -> web.Response:
    records = req.app.get("realtime_mmm_records", [])
    session_id = req.query.get("sessionId")
    turn_index = req.query.get("turnIndex")
    filtered = [
        record
        for record in records
        if (not session_id or record.get("sessionId") == session_id)
        and (not turn_index or str(record.get("turnIndex")) == turn_index)
    ]
    return _json({
        "records": filtered[-50:],
        "recordCount": len(filtered),
        "rawTranscriptLogged": False,
        "rawMediaAccepted": False,
    })


async def _realtime_turn_results(req: web.Request) -> web.Response:
    """GilJob v2 계약: API가 next-question 직전 서버사이드로 당겨가는 턴 분석 결과
    (services/api `_fetch_analysis_result` → response.create instructions 주입).

    GilJobE turn_handoff v2가 있으면 status=ready + candidatePromptFragment(≤880자 단일라인,
    전사 인용 없음 — API의 900자 _safe_str·금칙어 필터를 통과하도록 설계). 턴 미완결이면
    pending(result=null) — API가 409로 게이트한다. 세션 룩업은 interviewId 정확 일치만
    (활성 폴백 없음 — 다른 인터뷰 결과가 새는 것보다 pending이 낫다). turnIndex는 에코 전용
    (엔진 세션=단일 턴, 인덱스 추적은 API 몫)."""
    interview_id = _safe_str(req.query.get("interviewId"), 96)
    turn_index = _safe_str(req.query.get("turnIndex"), 8)
    service = req.app.get("analysis_service")
    pending = {
        "result": None, "status": "pending",
        "rawTranscriptLogged": False, "rawMediaAccepted": False,
    }
    if service is None or render_prompt_fragment is None or not interview_id:
        return _json(pending)
    payload = service.signals(interview_id)
    handoff = payload.get("turnHandoff")
    if not handoff:
        return _json(pending)
    return _json({
        "result": {
            "schemaVersion": "2026-06-12.turn-handoff-fragment.v2",
            "status": "ready",
            "sessionId": _safe_str(payload.get("sessionId"), 96),
            "turnIndex": int(turn_index) if turn_index.isdigit() else None,
            "candidatePromptFragment": render_prompt_fragment(handoff),
            "coverage": (handoff.get("meta") or {}).get("coverage"),
            "rawTranscriptLogged": False,
            "rawMediaAccepted": False,
        },
        "rawTranscriptLogged": False,
        "rawMediaAccepted": False,
    })


def _route_registered(app: web.Application, method: str, path: str) -> bool:
    for route in app.router.routes():
        if route.method == method and route.resource.canonical == path:
            return True
    return False


def _add_realtime_sideband_routes(app: web.Application) -> None:
    routes = []
    # GilJobE 5ba7249 owns POST /realtime/turn-events for the external transcript
    # sentence lane. Keep this wrapper fallback only for older pins and never
    # duplicate a provider-owned route, because aiohttp rejects duplicate method/path.
    if not _route_registered(app, "POST", "/realtime/turn-events"):
        routes.append(web.post("/realtime/turn-events", _realtime_turn_events))
    if not _route_registered(app, "GET", "/realtime/turn-events"):
        routes.append(web.get("/realtime/turn-events", _realtime_turn_events_tail))
    if not _route_registered(app, "GET", "/realtime/turn-results"):
        routes.append(web.get("/realtime/turn-results", _realtime_turn_results))
    if routes:
        app.add_routes(routes)


def _make_app() -> web.Application:
    critic = _build_critic()
    service = AnalysisService(make_critic=lambda _mode: critic, make_lanes=_make_lanes)
    event_only = _install_event_only_realtime_fallback(service)
    app = make_app(service, ready_check=lambda: _vllm_ready(critic))
    app["realtime_mmm_records"] = []
    app["analysis_service"] = service  # turn-results가 turn_handoff를 읽는 경로
    app["event_only_realtime_turns"] = event_only
    _add_realtime_sideband_routes(app)

    async def _warmup(_app: web.Application) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, critic.warmup)
        logger.info("critic warmup 완료")

    app.on_startup.append(_warmup)
    return app


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    port = _port()
    logger.info("analysis-engine GilJobE+Realtime MMM ingress 기동 :%d", port)
    web.run_app(_make_app(), host="0.0.0.0", port=port, access_log=None)


if __name__ == "__main__":
    main()
