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
from giljobe.server.service import AnalysisService

logger = logging.getLogger(__name__)

MAX_REALTIME_MMM_RECORD_BYTES = int(os.getenv("MAX_REALTIME_MMM_RECORD_BYTES", "16384"))
MAX_REALTIME_MMM_RECORDS = int(os.getenv("MAX_REALTIME_MMM_RECORDS", "500"))
RAW_FIELD_MARKERS = {"rawMedia", "frame", "audio", "video", "sdp", "client_secret", "token", "apiKey"}


def _safe_str(value: object, max_len: int = 240) -> str:
    text = "" if value is None else str(value)
    return " ".join(text.split())[:max_len]


def _json(payload: dict[str, object], status: int = 200) -> web.Response:
    return web.json_response(payload, status=status, dumps=lambda item: json.dumps(item, ensure_ascii=False))


def _contains_forbidden_raw_field(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key) in RAW_FIELD_MARKERS:
                return True
            if _contains_forbidden_raw_field(nested):
                return True
    if isinstance(value, list):
        return any(_contains_forbidden_raw_field(item) for item in value)
    return False


def _public_record(payload: dict[str, Any]) -> dict[str, object]:
    readiness = payload.get("readiness") if isinstance(payload.get("readiness"), dict) else {}
    return {
        "schema_version": _safe_str(payload.get("schema_version") or payload.get("schemaVersion"), 80),
        "source": "api-sideband",
        "sessionId": _safe_str(payload.get("sessionId") or payload.get("interviewId"), 96),
        "turnId": _safe_str(payload.get("turnId"), 32),
        "turnIndex": payload.get("turnIndex") if isinstance(payload.get("turnIndex"), int) else None,
        "eventKind": _safe_str(payload.get("eventKind"), 120),
        "sourceRoute": _safe_str(payload.get("sourceRoute"), 120),
        "receivedAt": _safe_str(payload.get("receivedAt"), 80),
        "analysisEngineReceivedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rawTranscriptLogged": False,
        "rawMediaAccepted": False,
        "readiness": {
            "full_mmm_ready": bool(readiness.get("full_mmm_ready")),
            "state": _safe_str(readiness.get("state"), 80),
            "reasonCodes": readiness.get("reasonCodes") if isinstance(readiness.get("reasonCodes"), list) else [],
            "lanes": readiness.get("lanes") if isinstance(readiness.get("lanes"), dict) else {},
        },
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


def _make_app() -> web.Application:
    critic = _build_critic()
    service = AnalysisService(make_critic=lambda _mode: critic, make_lanes=_make_lanes)
    app = make_app(service, ready_check=lambda: _vllm_ready(critic))
    app["realtime_mmm_records"] = []
    app.add_routes([
        web.post("/realtime/turn-events", _realtime_turn_events),
        web.get("/realtime/turn-events", _realtime_turn_events_tail),
    ])

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
