#!/usr/bin/env python3
"""Minimal GilJob v2 API scaffold.

Security contracts kept in scaffold:
- internal API paths are not exposed;
- raw session/report tokens are returned only in the create-session response;
- server-side records keep purpose-separated token hashes only.
"""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from app.livekit_tokens import issue_avatar_viewer_livekit_token
from app.token_contract import issue_session
from app.turn_store import get_turn_store

SERVICE_NAME = os.getenv("SERVICE_NAME", "api")
PORT = int(os.getenv("SERVICE_PORT", "8000"))
MAX_JSON_BODY_BYTES = int(os.getenv("MAX_JSON_BODY_BYTES", "65536"))
AI_ENGINE_INTERNAL_URL = os.getenv("AI_ENGINE_INTERNAL_URL", "http://ai-engine:8100").rstrip("/")
ANALYSIS_ENGINE_INTERNAL_URL = os.getenv("ANALYSIS_ENGINE_INTERNAL_URL", "http://analysis-engine:8200").rstrip("/")
INTERVIEW_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
TTS_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/turns/([0-9]{1,4})/tts/?$")
AVATAR_SESSION_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/avatar/session/?$")
NEXT_QUESTION_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/turns/([0-9]{1,4})/question/?$")
REPORT_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/report/?$")
FINALIZE_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/finalize/?$")
TURN_ANSWER_ROUTE_PATTERN = re.compile(r"^/(?:api/)?interviews/([A-Za-z0-9][A-Za-z0-9._-]{0,95})/turns/([0-9]{1,4})/answer/?$")
MAX_TTS_TEXT_CHARS = 1_200
MAX_TURN_TEXT_CHARS = 8_000
LAST_ANSWER_PLACEHOLDER = "아직 이전 답변 전사가 없습니다."

# In-process scaffold store for G006. The persistence contract is represented by
# services/api/db/schema.sql; a later M2 slice will wire this to Postgres.
SESSION_HASH_STORE: dict[str, dict[str, object]] = {}

# Per-turn Q&A + non-verbal signals live in the turn store (db/schema.sql
# interview_turns / interview_turn_signals). The backend is Postgres when
# API_DB_BACKEND=postgres, otherwise an in-process dict; both share the
# (session_id, turn_id) key, so these call sites are backend-agnostic.


def _trace_enabled() -> bool:
    return os.getenv("GILJOB_E2E_TRACE", "").strip().lower() in {"1", "true", "yes", "on"}


def _trace(event: str, **fields: object) -> None:
    """Print branch-local E2E trace logs without raw token/media payloads."""
    if not _trace_enabled():
        return
    safe_fields: dict[str, object] = {}
    for key, value in fields.items():
        if value is None or isinstance(value, (bool, int, float)):
            safe_fields[key] = value
        elif isinstance(value, str):
            safe_fields[key] = _safe_str(value, 240)
        elif isinstance(value, (list, tuple)):
            safe_fields[key] = [_safe_str(item, 120) for item in value[:8]]
        elif isinstance(value, dict):
            safe_fields[key] = {
                _safe_str(k, 80): (_safe_str(v, 160) if isinstance(v, str) else v)
                for k, v in list(value.items())[:12]
                if not any(secret in str(k).lower() for secret in ("token", "secret", "key", "jwt"))
            }
        else:
            safe_fields[key] = _safe_str(value, 160)
    print(
        "[api-trace] "
        + json.dumps({"event": event, **safe_fields}, ensure_ascii=False, sort_keys=True),
        flush=True,
    )


def _strategy_metadata_from_payload(payload: dict[str, Any]) -> dict[str, object]:
    metadata = payload.get("strategyMetadata")
    if not isinstance(metadata, dict):
        return {
            "topic": "미분류",
            "topicSource": "fallback_transcript_only",
            "hashimotoAsOfTurnId": None,
            "hashimotoTopicChanged": False,
            "strategyReady": False,
        }
    return {
        "topic": _safe_str(metadata.get("strategyTopicUsed") or "미분류", 200),
        "topicSource": _safe_str(metadata.get("strategyTopicSource") or "fallback_transcript_only", 80),
        "hashimotoAsOfTurnId": _safe_str(metadata.get("strategyAsOfTurnId"), 120) or None,
        "hashimotoTopicChanged": bool(metadata.get("strategyTopicChanged")),
        "strategyReady": bool(metadata.get("strategyReady")),
    }


def record_turn_question(session_id: str, turn_index: int, question: object, last_answer: object, upstream_payload: dict[str, Any] | None = None) -> None:
    """Persist one turn's brokered question and back-fill the previous turn's answer.

    The browser sends ``lastAnswer`` (the transcript of the *previous* turn) when it
    asks for turn N's question, so turn N-1's answer is stored here. The final turn's
    answer never arrives this way and is filled from analysis-engine transcripts.
    Best-effort: never let storage failures affect the brokered response.
    """
    if not INTERVIEW_ID_PATTERN.fullmatch(session_id) or turn_index < 1:
        return
    store = get_turn_store()
    question_text = _safe_str(question, MAX_TURN_TEXT_CHARS)
    metadata = _strategy_metadata_from_payload(upstream_payload or {})
    if question_text:
        store.upsert_question(session_id, turn_index, question_text, metadata)
        _trace(
            "dialog.question_saved",
            step="AI question broker response persisted to turn store",
            sessionId=session_id,
            turnId=turn_index,
            questionChars=len(question_text),
            topic=metadata.get("topic"),
            topicSource=metadata.get("topicSource"),
            hashimotoAsOfTurnId=metadata.get("hashimotoAsOfTurnId"),
            strategyReady=metadata.get("strategyReady"),
        )
    answer_text = _safe_str(last_answer, MAX_TURN_TEXT_CHARS)
    if answer_text and answer_text != LAST_ANSWER_PLACEHOLDER and turn_index - 1 >= 1:
        # overwrite=False so this back-fill never clobbers a real per-turn answer.
        store.upsert_answer(session_id, turn_index - 1, answer_text, overwrite=False)
        _trace(
            "dialog.previous_answer_backfilled",
            step="Previous answer transcript back-filled from next-question request",
            sessionId=session_id,
            turnId=turn_index - 1,
            answerChars=len(answer_text),
            overwrite=False,
        )


def finalize_interview(session_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """Close the interview with one final signal-ingest sweep.

    Per-turn answers are already stored as each turn completes (record_turn_answer),
    so this mainly does a last synchronous pull+ingest to capture the final turn's
    eval windows (which may finish just after the last answer). An optional last
    answer may be supplied for resilience. Best-effort ingest: an unreachable
    analysis-engine must not fail finalize.
    """
    if not INTERVIEW_ID_PATTERN.fullmatch(session_id):
        return 400, {"error": "invalid_interview_id"}
    try:
        turn_index = int(payload.get("turnIndex") or payload.get("turnId") or 0)
    except (TypeError, ValueError):
        turn_index = 0
    answer_text = _safe_str(payload.get("answer") or payload.get("lastAnswer") or "", MAX_TURN_TEXT_CHARS)
    answer_recorded = False
    if turn_index >= 1 and answer_text and answer_text != LAST_ANSWER_PLACEHOLDER:
        get_turn_store().upsert_answer(session_id, turn_index, answer_text)
        answer_recorded = True
        _trace(
            "dialog.final_answer_saved",
            step="Finalize payload contained a last answer, persisted before report build",
            sessionId=session_id,
            turnId=turn_index,
            answerChars=len(answer_text),
        )

    _trace(
        "finalize.started",
        step="Client requested interview end; stopping analysis and hashimoto-side work",
        sessionId=session_id,
        turnId=turn_index,
        answerRecorded=answer_recorded,
    )
    analysis_stopped = _stop_analysis_subscriber()
    ai_engine_finalize = _finalize_ai_engine(session_id, turn_index, answer_text)

    ingested_turns = 0
    try:
        ingested_turns = ingest_session_signals(session_id, _fetch_analysis_signals(session_id))
    except Exception:  # noqa: BLE001 - finalize stays resilient to analysis outages
        ingested_turns = 0
    _trace(
        "finalize.completed",
        step="Finalize completed; report endpoint will read turn store and aggregate features",
        sessionId=session_id,
        answerRecorded=answer_recorded,
        signalsIngestedTurns=ingested_turns,
        analysisStopped=analysis_stopped,
        aiEngineFinalized=ai_engine_finalize,
    )

    return 200, {
        "interviewId": session_id,
        "finalized": True,
        "answerRecorded": answer_recorded,
        "signalsIngestedTurns": ingested_turns,
        "analysisStopped": analysis_stopped,
        "aiEngineFinalized": ai_engine_finalize,
    }


def _post_json(url: str, body: dict[str, Any], timeout: float) -> tuple[int | None, dict[str, object]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            parsed = json.loads(response.read().decode("utf-8") or "{}")
            return response.status, parsed if isinstance(parsed, dict) else {}
    except urllib.error.HTTPError as error:
        try:
            parsed = json.loads(error.read().decode("utf-8", errors="replace") or "{}")
        except json.JSONDecodeError:
            parsed = {}
        return error.code, parsed if isinstance(parsed, dict) else {}
    except Exception:
        return None, {}


def _stop_analysis_subscriber() -> dict[str, object]:
    status, payload = _post_json(f"{ANALYSIS_ENGINE_INTERNAL_URL}/subscriber/stop", {}, timeout=10)
    return {
        "attempted": True,
        "ok": status is not None and 200 <= status < 300,
        "status": status,
        "state": _safe_str(payload.get("status") or payload.get("state") or "", 80) or None,
    }


def _finalize_ai_engine(session_id: str, turn_index: int, answer_text: str) -> dict[str, object]:
    body: dict[str, Any] = {
        "interviewId": session_id,
        "sessionId": session_id,
        "reason": "client_leave",
    }
    if turn_index >= 1 and answer_text and answer_text != LAST_ANSWER_PLACEHOLDER:
        body["turnIndex"] = turn_index
        body["answer"] = answer_text
    status, payload = _post_json(f"{AI_ENGINE_INTERNAL_URL}/interview/finalize", body, timeout=10)
    hashimoto = payload.get("hashimoto") if isinstance(payload, dict) else None
    return {
        "attempted": True,
        "ok": status is not None and 200 <= status < 300,
        "status": status,
        "hashimoto": hashimoto if isinstance(hashimoto, dict) else {},
    }


def record_turn_signals(session_id: str, turn_index: int, evals: list[dict[str, Any]], giljobe_ref: object = None) -> None:
    """Ingest one turn's analysis-engine eval payloads (segmented by turn_end).

    ``evals`` is the list of ``record["eval"]`` objects (kor-signals.json shape)
    that fall within this turn. Stored raw; window->turn aggregation happens at
    report build time so this row stays the source of truth.
    """
    if not INTERVIEW_ID_PATTERN.fullmatch(session_id) or turn_index < 1:
        return
    clean_evals = [e for e in (evals or []) if isinstance(e, dict)]
    get_turn_store().upsert_signals(session_id, turn_index, clean_evals, giljobe_ref)
    _trace(
        "features.signals_saved",
        step="Analysis eval windows persisted to turn feature store",
        sessionId=session_id,
        turnId=turn_index,
        evalWindowCount=len(clean_evals),
        giljobeRef=giljobe_ref,
    )


def ingest_session_signals(session_id: str, signals_payload: dict[str, Any]) -> int:
    """Segment a session's signal stream into per-turn rows and persist them.

    The analysis-engine produces one ``{sessionId}.jsonl`` (kor-signals.json shape)
    holding the whole session: 3s ``window`` STT chunks, 16s ``eval`` windows, and a
    ``turn_end`` per answer. A turn's eval windows are everything up to its turn_end,
    so this walks the records in order, buckets eval payloads, and flushes one
    ``interview_turn_signals`` row at each turn_end (turn_id = 1, 2, 3 ...).
    Returns the number of turns ingested.
    """
    if not INTERVIEW_ID_PATTERN.fullmatch(session_id) or not isinstance(signals_payload, dict):
        return 0
    records = signals_payload.get("records")
    if not isinstance(records, list):
        return 0
    giljobe_ref = signals_payload.get("giljobeRef") or signals_payload.get("giljobe_ref")
    _trace(
        "features.ingest_started",
        step="Fetched analysis-engine /signals and started segmenting eval windows by turn_end",
        sessionId=session_id,
        recordCount=len(records),
        giljobeRef=giljobe_ref,
    )

    turn_index = 1
    current_evals: list[dict[str, Any]] = []
    ingested = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        record_type = record.get("type")
        if record_type == "eval" and isinstance(record.get("eval"), dict):
            current_evals.append(record["eval"])
        elif record_type == "turn_end":
            record_turn_signals(session_id, turn_index, current_evals, giljobe_ref)
            ingested += 1
            turn_index += 1
            current_evals = []
    # Trailing eval windows with no closing turn_end → flush as the final turn.
    if current_evals:
        record_turn_signals(session_id, turn_index, current_evals, giljobe_ref)
        ingested += 1
    _trace(
        "features.ingest_completed",
        step="Signal stream segmented into per-turn feature rows",
        sessionId=session_id,
        ingestedTurns=ingested,
    )
    return ingested


def _fetch_analysis_signals(session_id: str, timeout: float = 15) -> dict[str, Any]:
    """Pull the session signal payload from the analysis-engine (internal only).

    session_id is constrained to ``INTERVIEW_ID_PATTERN`` (URL-safe), so it is
    interpolated directly. Never exposes analysis-engine to the browser.
    """
    url = f"{ANALYSIS_ENGINE_INTERNAL_URL}/signals?sessionId={session_id}"
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    return parsed if isinstance(parsed, dict) else {}


def _ingest_signals_async(session_id: str) -> None:
    """Pull + ingest the session signals off the request thread (real-time, per turn).

    Cumulative and idempotent: each call re-segments the whole stream and upserts
    every completed turn by (session_id, turn_id), so firing once per turn keeps
    interview_turn_signals current without blocking the browser.
    """
    def _run() -> None:
        try:
            ingest_session_signals(session_id, _fetch_analysis_signals(session_id))
        except Exception:  # noqa: BLE001 - background ingest never raises to the caller
            pass

    threading.Thread(target=_run, name="signals-ingest", daemon=True).start()


def record_turn_answer(session_id: str, turn_index: int, payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """Store one turn's answer the moment it completes and ingest signals in real time."""
    if not INTERVIEW_ID_PATTERN.fullmatch(session_id):
        return 400, {"error": "invalid_interview_id"}
    if turn_index < 1:
        return 400, {"error": "invalid_turn_index"}
    answer_text = _safe_str(payload.get("answer") or payload.get("lastAnswer") or "", MAX_TURN_TEXT_CHARS)
    if not answer_text or answer_text == LAST_ANSWER_PLACEHOLDER:
        return 400, {"error": "missing_answer"}
    get_turn_store().upsert_answer(session_id, turn_index, answer_text)
    _trace(
        "dialog.answer_saved",
        step="Candidate answer transcript persisted to turn store",
        sessionId=session_id,
        turnId=turn_index,
        answerChars=len(answer_text),
    )
    _ingest_signals_async(session_id)
    return 200, {"interviewId": session_id, "turnId": turn_index, "recorded": True}


def _nums(values: list[object]) -> list[float]:
    return [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]


def _mean(values: list[object], ndigits: int | None = None) -> float | int | None:
    nums = _nums(values)
    if not nums:
        return None
    avg = sum(nums) / len(nums)
    return round(avg, ndigits) if ndigits else round(avg)


def _sum(values: list[object]) -> int | float | None:
    nums = _nums(values)
    if not nums:
        return None
    total = sum(nums)
    return int(total) if float(total).is_integer() else total


def _dig(node: object, *path: str) -> object:
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def aggregate_turn_signals(evals: list[dict[str, Any]]) -> dict[str, object] | None:
    """Collapse a turn's eval windows into one feedback + metrics summary.

    Rates/pitch -> mean, pauses/blinks/gestures -> sum, and visual metrics use only
    windows where a face was actually seen (face_seen_ratio > 0) so unmeasured
    windows do not skew the average. Mirrors the report.js binding shape.
    """
    if not evals:
        return None
    vocal = [(e.get("objective_vocal") or {}) for e in evals]
    visual_all = [(e.get("objective_visual") or {}) for e in evals]
    visual_seen = [v for v in visual_all if isinstance(v, dict) and (v.get("face_seen_ratio") or 0) > 0]
    visual_measurable = len(visual_seen) > 0

    metrics: dict[str, object] = {
        "vocal": {
            "pitchMeanHz": _mean([_dig(v, "pitch", "mean_hz") for v in vocal]),
            "speechRateSylPerSec": _mean([_dig(v, "rate", "speech_rate_syl_per_s") for v in vocal], 1),
            "pauseCount": _sum([_dig(v, "pauses", "pause_count_ge_0p25") for v in vocal]),
        },
        "visual": {},
        "coverage": {"visualMeasurable": visual_measurable},
    }
    if visual_measurable:
        metrics["visual"] = {
            "faceSeenRatio": _mean([v.get("face_seen_ratio") for v in visual_seen], 2),
            "smileMean": _mean([v.get("smile_mean") for v in visual_seen], 3),
            "gazeOffMean": _mean([v.get("gaze_off_mean") for v in visual_seen], 3),
            "blinkCount": _sum([v.get("blink_count") for v in visual_seen]),
            "headSway": _mean([v.get("head_sway") for v in visual_seen], 4),
            "gestureEvents": _sum([v.get("gesture_events") for v in visual_seen]),
        }

    key_observations: list[str] = []
    critique: list[str] = []
    for evaluation in evals:
        for note in (evaluation.get("key_observations") or []):
            if isinstance(note, str) and note not in key_observations:
                key_observations.append(note)
        for note in (evaluation.get("critique") or []):
            if isinstance(note, str) and note not in critique:
                critique.append(note)

    return {
        "feedback": {"keyObservations": key_observations, "critique": critique},
        "metrics": metrics,
        "windowCount": len(evals),
    }


def build_topic_groups(turns: list[dict[str, object]]) -> list[dict[str, object]]:
    """Group consecutive dialog turns by the persisted question-generation topic."""
    groups: list[dict[str, object]] = []
    for turn in turns:
        topic = _safe_str(turn.get("topic") or "미분류", 200)
        source = _safe_str(turn.get("topicSource") or "fallback_transcript_only", 80)
        if not groups or groups[-1].get("topic") != topic:
            groups.append({
                "groupId": f"topic_{len(groups) + 1:02d}",
                "topic": topic,
                "topicSource": source,
                "startTurnId": turn.get("turnId"),
                "endTurnId": turn.get("turnId"),
                "turns": [turn],
            })
        else:
            groups[-1]["endTurnId"] = turn.get("turnId")
            group_turns = groups[-1].get("turns")
            if isinstance(group_turns, list):
                group_turns.append(turn)
    return groups


def _fallback_topic_for_position(position: int, total: int) -> str:
    labels = [
        "기본 역량 확인",
        "경험 회고와 성장 방향",
        "심화 역량 확인",
        "추가 응답 확인",
    ]
    if total <= 0:
        return labels[0]
    group_count = max(1, (total + 2) // 3)
    remaining = total
    cursor = 1
    for group_index in range(group_count):
        groups_left = group_count - group_index
        size = min(3, remaining - 2 * (groups_left - 1)) if groups_left > 1 else remaining
        if cursor <= position < cursor + size:
            return labels[group_index] if group_index < len(labels) else f"추가 응답 확인 {group_index + 1}"
        cursor += size
        remaining -= size
    return labels[-1]


def _report_topic_from_row(row: dict[str, object], position: int, total: int) -> tuple[str, str]:
    raw_topic = _safe_str(row.get("topic"), 200)
    raw_source = _safe_str(row.get("topicSource"), 80)
    if raw_topic and (raw_topic != "미분류" or raw_source not in ("", "fallback_transcript_only")):
        return raw_topic, raw_source or "fallback_transcript_only"

    return _fallback_topic_for_position(position, total), "fallback_demo_group"


def build_report(session_id: str) -> tuple[int, dict[str, object]]:
    """Assemble the report payload the browser (report.js) consumes.

    The turn store JOINs interview_turns (question/answer) with
    interview_turn_signals (signals) on (session_id, turn_id) and returns one row
    per turn, ordered. Per-turn eval windows are aggregated here; either side may
    be missing and report.js renders absent fields gracefully.

    Read-through: pull + ingest the analysis-engine signals once before reading, so
    the report reflects the latest eval windows at read time. This closes the
    finalize/producer-lag races (the report read itself refreshes the data) and is
    best-effort — an unreachable analysis-engine just serves what is already stored.
    """
    if not INTERVIEW_ID_PATTERN.fullmatch(session_id):
        return 400, {"error": "invalid_interview_id"}

    _trace(
        "report.refresh_started",
        step="Report endpoint called; refreshing analysis signals before reading store",
        sessionId=session_id,
    )
    try:
        ingest_session_signals(session_id, _fetch_analysis_signals(session_id, timeout=8))
    except Exception:  # noqa: BLE001 - read-through refresh is best-effort
        _trace(
            "report.refresh_skipped",
            step="Analysis refresh failed or analysis-engine unavailable; using stored rows",
            sessionId=session_id,
        )

    rows = list(get_turn_store().report_rows(session_id))
    _trace(
        "report.rows_loaded",
        step="Loaded dialog rows joined with feature rows from turn store",
        sessionId=session_id,
        rowCount=len(rows),
    )
    turns: list[dict[str, object]] = []
    for position, row in enumerate(rows, start=1):
        topic, topic_source = _report_topic_from_row(row, position, len(rows))
        turn: dict[str, object] = {
            "turnId": row.get("turnId"),
            "question": row.get("question"),
            "answer": row.get("answer"),
            "topic": topic,
            "topicSource": topic_source,
            "hashimotoAsOfTurnId": row.get("hashimotoAsOfTurnId"),
            "hashimotoTopicChanged": bool(row.get("hashimotoTopicChanged")),
            "strategyReady": bool(row.get("strategyReady")),
        }
        stored_signals = row.get("signals")
        if isinstance(stored_signals, list):
            aggregated = aggregate_turn_signals(stored_signals)
            if aggregated:
                turn["feedback"] = aggregated["feedback"]
                turn["metrics"] = aggregated["metrics"]
                metric_groups = list((aggregated.get("metrics") or {}).keys()) if isinstance(aggregated, dict) else []
                _trace(
                    "report.features_aggregated",
                    step="Per-window eval features collapsed into one report turn summary",
                    sessionId=session_id,
                    turnId=row.get("turnId"),
                    windowCount=aggregated.get("windowCount"),
                    metricGroups=metric_groups,
                    visualMeasurable=_dig(aggregated.get("metrics"), "coverage", "visualMeasurable"),
                )
        _trace(
            "report.turn_composed",
            step="Report turn composed from dialog, hashimoto topic metadata, and feature summary",
            sessionId=session_id,
            turnId=turn.get("turnId"),
            hasQuestion=bool(turn.get("question")),
            hasAnswer=bool(turn.get("answer")),
            hasMetrics=bool(turn.get("metrics")),
            topic=topic,
            topicSource=topic_source,
            hashimotoAsOfTurnId=turn.get("hashimotoAsOfTurnId"),
            strategyReady=turn.get("strategyReady"),
        )
        turns.append(turn)

    # Readiness: every answered turn should also have metrics. If some answered turn
    # still lacks them (analysis lagging), report.js retries a few times.
    answered = [turn for turn in turns if turn.get("answer")]
    complete = bool(turns) and all("metrics" in turn for turn in answered)

    topic_groups = build_topic_groups(turns)
    _trace(
        "report.completed",
        step="Final report payload assembled for browser",
        sessionId=session_id,
        turnCount=len(turns),
        topicGroupCount=len(topic_groups),
        complete=complete,
    )

    return 200, {
        "interviewId": session_id,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "turnCount": len(turns),
        "complete": complete,
        "topicGroups": topic_groups,
        "turns": turns,
        "rawMediaExposed": False,
        "rawSecretsExposed": False,
    }



def _safe_str(value: object, max_len: int = 4_000) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def _redact_provider_error(text: str) -> str:
    for name in ("ELEVENLABS_API_KEY", "SPATIALREAL_API_KEY", "LIVEKIT_API_SECRET"):
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


def _sanitize_upstream_provider_failure(upstream: dict[str, object], upstream_status: int, default_error: str, *, ready: bool | None = None) -> dict[str, object] | None:
    if upstream_status < 500:
        return None
    upstream_error = _safe_str(upstream.get("error") or default_error, 120)
    if upstream_error.endswith("_failed") or upstream_error in {"llm_provider_failed", "tts_provider_failed", "avatar_provider_failed"}:
        return _provider_failure_payload(upstream_error, upstream.get("provider") or "api-mediated", ready=ready)
    return None


def request_next_question(interview_id: str, turn_index: int, payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        return 400, {"error": "invalid_interview_id"}
    if turn_index < 1:
        return 400, {"error": "invalid_turn_index"}
    request_payload = json.dumps({
        "interviewId": interview_id,
        "sessionId": interview_id,
        "turnIndex": turn_index,
        "persona": _safe_str(payload.get("persona") or "차분하고 명확한 한국어 면접관", 500),
        "candidateProfile": _safe_str(payload.get("candidateProfile") or "not provided in this slice", 2_000),
        "job": _safe_str(payload.get("job") or "not provided in this slice", 2_000),
        "lastAnswer": _safe_str(payload.get("lastAnswer") or "아직 이전 답변 전사가 없습니다.", 2_000),
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{AI_ENGINE_INTERNAL_URL}/interview/next-question",
        data=request_payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            upstream_status = response.status
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        upstream_status = error.code
    except urllib.error.URLError as error:
        return 502, {
            "error": "llm_provider_failed",
            "provider": "api-mediated",
            "message": _redact_provider_error(str(error.reason)),
        }
    try:
        upstream = json.loads(body)
    except json.JSONDecodeError:
        return 502, {"error": "llm_provider_failed", "provider": "api-mediated", "message": "invalid upstream response"}
    if not isinstance(upstream, dict):
        return 502, {"error": "llm_provider_failed", "provider": "api-mediated", "message": "invalid upstream payload"}
    public_failure = _sanitize_upstream_provider_failure(upstream, upstream_status, "llm_provider_failed")
    if public_failure is not None:
        public_failure["interviewId"] = interview_id
        public_failure["turnIndex"] = turn_index
        public_failure["delivery"] = {
            "mode": "api-mediated-question",
            "source": "ai-engine",
            "publicDirectAiRoutes": "blocked",
        }
        return upstream_status, public_failure
    upstream["interviewId"] = interview_id
    upstream["turnIndex"] = turn_index
    upstream["delivery"] = {
        "mode": "api-mediated-question",
        "source": "ai-engine",
        "publicDirectAiRoutes": "blocked",
    }
    return upstream_status, upstream


def create_avatar_session(interview_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        return 400, {"error": "invalid_interview_id"}
    request_payload = json.dumps({
        "interviewId": interview_id,
        "reason": _safe_str(payload.get("reason") or "room-join", 120),
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{AI_ENGINE_INTERNAL_URL}/avatar/session",
        data=request_payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            upstream_status = response.status
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        upstream_status = error.code
    except urllib.error.URLError as error:
        return 502, {
            "error": "avatar_provider_failed",
            "provider": "api-mediated",
            "message": _redact_provider_error(str(error.reason)),
        }
    try:
        upstream = json.loads(body)
    except json.JSONDecodeError:
        return 502, {"error": "avatar_provider_failed", "provider": "api-mediated", "message": "invalid upstream response"}
    if not isinstance(upstream, dict):
        return 502, {"error": "avatar_provider_failed", "provider": "api-mediated", "message": "invalid upstream payload"}
    public_failure = _sanitize_upstream_provider_failure(upstream, upstream_status, "avatar_provider_failed", ready=False)
    if public_failure is not None:
        public_failure["interviewId"] = interview_id
        public_failure["delivery"] = {
            "mode": "api-mediated-spatialreal-session",
            "source": "ai-engine",
            "publicDirectAvatarRoutes": "blocked",
        }
        return upstream_status, public_failure
    client = upstream.get("client")
    if isinstance(client, dict):
        client["livekit"] = issue_avatar_viewer_livekit_token(
            room_name=f"giljob-session-{interview_id}",
            session_id=interview_id,
        )
    upstream["interviewId"] = interview_id
    upstream["delivery"] = {
        "mode": "api-mediated-spatialreal-session",
        "source": "ai-engine",
        "publicDirectAvatarRoutes": "blocked",
    }
    return upstream_status, upstream


def synthesize_room_tts(interview_id: str, turn_index: int, payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    text = _safe_str(payload.get("text") or payload.get("question") or "", MAX_TTS_TEXT_CHARS)
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        return 400, {"error": "invalid_interview_id"}
    if turn_index < 1:
        return 400, {"error": "invalid_turn_index"}
    if not text:
        return 400, {"error": "missing_text"}

    request_payload = json.dumps({
        "sessionId": interview_id,
        "turnId": f"q_{interview_id}_{turn_index:04d}",
        "text": text,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{AI_ENGINE_INTERNAL_URL}/tts/synthesize",
        data=request_payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            upstream_status = response.status
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        upstream_status = error.code
    except urllib.error.URLError as error:
        return 502, {
            "error": "tts_provider_failed",
            "provider": "api-mediated",
            "message": _redact_provider_error(str(error.reason)),
        }
    try:
        upstream = json.loads(body)
    except json.JSONDecodeError:
        return 502, {"error": "tts_provider_failed", "provider": "api-mediated", "message": "invalid upstream response"}
    if not isinstance(upstream, dict):
        return 502, {"error": "tts_provider_failed", "provider": "api-mediated", "message": "invalid upstream payload"}

    upstream.pop("sessionId", None)
    upstream.pop("turnId", None)
    public_failure = _sanitize_upstream_provider_failure(upstream, upstream_status, "tts_provider_failed")
    if public_failure is not None:
        public_failure["interviewId"] = interview_id
        public_failure["turnIndex"] = turn_index
        public_failure["delivery"] = {
            "mode": "api-mediated-base64",
            "source": "ai-engine",
            "publicDirectTtsRoutes": "blocked",
        }
        return upstream_status, public_failure
    upstream["interviewId"] = interview_id
    upstream["turnIndex"] = turn_index
    upstream["delivery"] = {
        "mode": "api-mediated-base64",
        "source": "ai-engine",
        "publicDirectTtsRoutes": "blocked",
    }
    return upstream_status, upstream

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
        SESSION_HASH_STORE[str(stored["sessionId"])] = stored
        self._json(201, public)

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if self._reject_internal_path():
            return
        if self.path == "/healthz":
            self._json(200, {"service": SERVICE_NAME, "status": "ok"})
            return
        if self.path == "/readyz":
            self._json(200, {"service": SERVICE_NAME, "status": "ok"})
            return
        report_match = REPORT_ROUTE_PATTERN.fullmatch(self.path)
        if report_match:
            status, payload = build_report(report_match.group(1))
            self._json(status, payload)
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
        question_match = NEXT_QUESTION_ROUTE_PATTERN.fullmatch(self.path)
        if question_match:
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self._json(400, {"error": "invalid_json", "message": str(exc)})
                return
            session_id = question_match.group(1)
            turn_index = int(question_match.group(2))
            status, payload = request_next_question(session_id, turn_index, body)
            if status == 200:
                try:
                    record_turn_question(session_id, turn_index, payload.get("question"), body.get("lastAnswer"), payload)
                except Exception:  # noqa: BLE001 - storage must never break the brokered response
                    pass
            self._json(status, payload)
            return
        turn_answer_match = TURN_ANSWER_ROUTE_PATTERN.fullmatch(self.path)
        if turn_answer_match:
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self._json(400, {"error": "invalid_json", "message": str(exc)})
                return
            status, payload = record_turn_answer(turn_answer_match.group(1), int(turn_answer_match.group(2)), body)
            self._json(status, payload)
            return
        finalize_match = FINALIZE_ROUTE_PATTERN.fullmatch(self.path)
        if finalize_match:
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self._json(400, {"error": "invalid_json", "message": str(exc)})
                return
            status, payload = finalize_interview(finalize_match.group(1), body)
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
