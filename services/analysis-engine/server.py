#!/usr/bin/env python3
"""GilJobE analysis-engine entrypoint with GilJob v2 Realtime MMM ingress.

GilJobE still owns the STT/subscriber HTTP contract. This wrapper builds the
same GilJobE aiohttp app and adds one GilJob-v2-specific route:

    POST /realtime/turn-events

The route accepts sanitized Realtime sideband readiness metadata plus an optional
low-resolution internal vision sample forwarded by services/api. It does not
persist raw media, raw provider tokens, or raw transcripts, and it does not
replace GilJobE's LiveKit subscriber path.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import logging
import os
import threading
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

MAX_REALTIME_MMM_RECORD_BYTES = int(os.getenv("MAX_REALTIME_MMM_RECORD_BYTES", "65536"))
MAX_REALTIME_MMM_RECORDS = int(os.getenv("MAX_REALTIME_MMM_RECORDS", "500"))
RAW_FIELD_MARKERS = {"rawMedia", "frame", "audio", "video", "sdp", "client_secret", "token", "apiKey", "transcript", "text"}
INTERNAL_DETAIL_PATHS = {
    ("detail", "transcript"),
    ("detail", "text"),
    ("detail", "visionFrame"),
    ("detail", "visionFrame", "data"),
}
SAFE_LANE_KEYS = ("transcript", "prosody", "vision")
_VISION_GROUNDER_LOCK = threading.RLock()
_VISION_GROUNDER: Any | None = None
_VISION_GROUNDER_INIT_ATTEMPTED = False


class _RnasSession:
    def __init__(self, interview_id: str, turn_index: int, critic_mode: str, started_at: float) -> None:
        self.interview_id = interview_id
        self.turn_index = turn_index
        self.critic_mode = critic_mode
        self.started_at = started_at
        self.records: list[dict[str, Any]] = []
        self.seen_sentence_keys: set[str] = set()
        self.last_sentence_end_s = 0.0
        self.transcript_observed = False
        self.prosody_observed = False
        self.vision_observed = False
        self.answer_ended = False
        self.sentence_count = 0
        self.transcript_char_count = 0
        self.transcript_question_like = False
        self.transcript_has_numbers = False
        self.transcript_specificity_score = 0.0
        self.prosody_marker_count = 0
        self.prosody_vad_event_count = 0
        self.prosody_audio_start_ms: int | float | None = None
        self.prosody_audio_end_ms: int | float | None = None
        self.prosody_speech_duration_ms: int | float | None = None
        self.prosody_energy_samples: list[float] = []
        self.vision_marker_count = 0
        self.vision_frame_count = 0
        self.vision_frame_bytes = 0
        self.vision_camera_enabled: bool | None = None
        self.vision_face_visible: bool | None = None
        self.vision_person_visible: bool | None = None
        self.vision_quality = ""
        self.vision_average_luma: int | float | None = None
        self.vision_analysis_source = ""
        self.vision_analysis_status = ""
        self.vision_face_seen_ratio: int | float | None = None
        self.vision_pose_seen_ratio: int | float | None = None

    @property
    def key(self) -> tuple[str, int]:
        return (self.interview_id, self.turn_index)


class _EventOnlySession(_RnasSession):
    """Backward-compatible alias for older tests/importers."""

    def __init__(self, session_id: str, critic_mode: str, started_at: float, turn_index: int = 0) -> None:
        super().__init__(session_id, turn_index, critic_mode, started_at)

    @property
    def session_id(self) -> str:
        return self.interview_id


class _EventOnlyRealtimeTurns:
    """First-class Realtime-native analysis sessions keyed by interview + turn.

    The Realtime main path does not depend on the LiveKit subscriber lifecycle.
    API-forwarded answer lifecycle and internal STT/prosody/vision sideband open, update,
    finalize, and expose candidate-safe results for the exact
    ``(interviewId, turnIndex)`` requested by the ordinary response gate. No
    active/last/session-wide fallback is used for `/realtime/turn-results`.
    """

    def __init__(self) -> None:
        self._active_by_key: dict[tuple[str, int], _RnasSession] = {}
        self._finalized_by_key: dict[tuple[str, int], _RnasSession] = {}
        # Legacy subscriber fallback fields are retained only for the wrapped
        # GilJobE /subscriber/start|stop compatibility path.
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
            "realtimeNativeMainPath": False,
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

    def start_turn(self, interview_id: str, turn_index: int, critic_mode: str = "window") -> dict[str, object]:
        key = (interview_id, turn_index)
        sess = _RnasSession(interview_id, turn_index, critic_mode, time.monotonic())
        self._active_by_key[key] = sess
        self._finalized_by_key.pop(key, None)
        return {
            "accepted": True,
            "status": "running",
            "sessionId": interview_id,
            "interviewId": interview_id,
            "turnIndex": turn_index,
            "realtimeNativeAnalysisSession": True,
            "rawMediaAccepted": False,
            "rawTranscriptLogged": False,
        }

    def ingest(self, payload: dict[str, Any]) -> dict[str, object]:
        interview_id = _safe_str(payload.get("interviewId") or payload.get("sessionId"), 96)
        turn_index = _safe_turn_index(payload.get("turnIndex"))
        kind = _safe_str(payload.get("eventKind") or payload.get("normalizedType") or payload.get("type"), 120)
        if interview_id and turn_index is not None:
            return self.ingest_turn(payload, interview_id=interview_id, turn_index=turn_index, kind=kind)
        return self._ingest_legacy(payload, kind)

    def ingest_turn(self, payload: dict[str, Any], *, interview_id: str, turn_index: int, kind: str) -> dict[str, object]:
        key = (interview_id, turn_index)
        if kind in {"turn.answer_started", "turn.answer.start"}:
            return self.start_turn(interview_id, turn_index)
        sess = self._active_by_key.get(key)
        if sess is None:
            return {"accepted": False, "reason": "no_active_rnas_session", "interviewId": interview_id, "turnIndex": turn_index}
        detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else {}
        sentence_added = self._apply_payload(sess, kind, payload, detail)
        if kind in {"turn.answer_ended", "turn.answer.end"}:
            self._finish(sess)
            sess.answer_ended = True
            self._finalized_by_key[key] = sess
            self._active_by_key.pop(key, None)
        return {
            "accepted": True,
            "eventKind": kind,
            "realtimeNativeAnalysisSession": True,
            "sentenceAdded": sentence_added,
            "recordCount": len(sess.records),
            "resultStatus": self.turn_result_status(interview_id, turn_index),
            "rawMediaAccepted": False,
            "rawTranscriptLogged": False,
        }

    def _ingest_legacy(self, payload: dict[str, Any], kind: str) -> dict[str, object]:
        sess = self._active
        if sess is None:
            return {"accepted": False, "reason": "no_active_session"}
        session_id = _safe_str(payload.get("sessionId") or payload.get("interviewId"), 96)
        if session_id and session_id != sess.session_id:
            return {"accepted": False, "reason": "session_mismatch"}
        turn_index = payload.get("turnIndex")
        if isinstance(turn_index, int):
            sess.turn_index = turn_index
        kind = _safe_str(payload.get("eventKind") or payload.get("normalizedType") or payload.get("type"), 120)
        detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else {}
        sentence_added = self._apply_payload(sess, kind, payload, detail)
        if kind in {"turn.answer_ended", "turn.answer.end"}:
            self._finish(sess)
            sess.answer_ended = True
        return {
            "accepted": True,
            "eventKind": kind,
            "eventOnlyFallback": True,
            "sentenceAdded": sentence_added,
            "recordCount": len(sess.records),
        }

    def _apply_payload(self, sess: _RnasSession, kind: str, payload: dict[str, Any], detail: dict[str, Any]) -> bool:
        sentence_added = False
        text = detail.get("transcript") or detail.get("text")
        item_id = detail.get("itemId") or payload.get("itemId")
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
                    "turnIndex": sess.turn_index,
                    "t": round(time.monotonic() - sess.started_at, 3),
                    "start_s": round(start_s, 3),
                    "end_s": round(end_s, 3),
                    "text": sentence,
                })
                _update_transcript_signals(sess, sentence)
                sess.last_sentence_end_s = end_s
                sess.transcript_observed = True
                sentence_added = True
        if kind in {"vad.speech_started", "analysis.vad.speech_started"}:
            sess.prosody_observed = True
            sess.prosody_marker_count += 1
            sess.prosody_vad_event_count += 1
            start_ms = _safe_signal_number(detail.get("audioStartMs"), maximum=24 * 60 * 60 * 1000)
            if start_ms is not None:
                sess.prosody_audio_start_ms = start_ms
            sess.records.append({
                "type": "prosody_vad_start",
                "turnIndex": sess.turn_index,
                "t": round(time.monotonic() - sess.started_at, 3),
                "audioStartMs": start_ms,
            })
        if kind in {"vad.speech_stopped", "analysis.vad.speech_stopped"}:
            sess.prosody_observed = True
            sess.prosody_marker_count += 1
            sess.prosody_vad_event_count += 1
            end_ms = _safe_signal_number(detail.get("audioEndMs"), maximum=24 * 60 * 60 * 1000)
            if end_ms is not None:
                sess.prosody_audio_end_ms = end_ms
                if sess.prosody_audio_start_ms is not None and end_ms >= sess.prosody_audio_start_ms:
                    sess.prosody_speech_duration_ms = round(float(end_ms) - float(sess.prosody_audio_start_ms), 3)
            sess.records.append({
                "type": "prosody_vad_stop",
                "turnIndex": sess.turn_index,
                "t": round(time.monotonic() - sess.started_at, 3),
                "audioEndMs": end_ms,
                "speechDurationMs": sess.prosody_speech_duration_ms,
            })
        if kind in {"prosody.window_metrics", "analysis.prosody.window_metrics"}:
            sess.prosody_observed = True
            sess.prosody_marker_count += 1
            energy = _safe_signal_number(
                detail.get("energy") or detail.get("rmsEnergy") or detail.get("energyMean"),
                maximum=10_000,
            )
            if energy is not None:
                sess.prosody_energy_samples.append(float(energy))
            sess.records.append({
                "type": "prosody_marker",
                "turnIndex": sess.turn_index,
                "t": round(time.monotonic() - sess.started_at, 3),
                "energy": energy,
            })
        if kind in {"vision.frame_metrics", "vision_metadata"}:
            sess.vision_observed = True
            _update_vision_signals(sess, detail)
            sess.records.append({
                "type": "vision_marker",
                "turnIndex": sess.turn_index,
                "t": round(time.monotonic() - sess.started_at, 3),
                "status": _vision_status(sess),
            })
        return sentence_added

    def turn_result_status(self, interview_id: str, turn_index: int) -> str:
        result = self.turn_result(interview_id, turn_index)
        return _safe_str(result.get("status"), 40)

    def turn_result(self, interview_id: str, turn_index: int) -> dict[str, object]:
        key = (interview_id, turn_index)
        sess = self._finalized_by_key.get(key)
        if sess is None:
            if key in self._active_by_key:
                return _pending_result(interview_id, turn_index, "answer_not_finalized")
            return _pending_result(interview_id, turn_index, "no_exact_turn_result")
        missing = []
        if not sess.answer_ended:
            missing.append("missing_answer_end")
        if not sess.transcript_observed:
            missing.append("missing_transcript")
        if not sess.prosody_observed:
            missing.append("missing_prosody")
        if not sess.vision_observed:
            missing.append("missing_vision")
        if missing:
            return _pending_result(interview_id, turn_index, missing[0], missing)
        transcript_signals = _transcript_signals(sess)
        prosody_signals = _prosody_signals(sess)
        vision_signals = _vision_signals(sess)
        behavioral_signals = _behavioral_signals(transcript_signals, prosody_signals, vision_signals)
        coverage = {
            "transcript": {"observed": True, "status": "complete"},
            "prosody": {"observed": True, "status": prosody_signals["status"]},
            "vision": {"observed": True, "status": vision_signals["status"]},
        }
        guidance = _next_question_guidance(transcript_signals, vision_signals)
        fragment = _candidate_safe_structured_fragment(guidance)
        return {
            "schemaVersion": "2026-06-13.rnas-turn-result.v2",
            "status": "ready",
            "sessionId": interview_id,
            "interviewId": interview_id,
            "turnIndex": turn_index,
            "candidatePromptFragment": fragment["text"],
            "candidateSafePromptFragment": fragment,
            "nextQuestionGuidance": guidance,
            "transcriptSignals": transcript_signals,
            "visionSignals": vision_signals,
            "prosodySignals": prosody_signals,
            "behavioralSignals": behavioral_signals,
            "coverage": coverage,
            "confidence": _turn_confidence(transcript_signals, prosody_signals, vision_signals),
            "latencyMs": max(0, round((time.monotonic() - sess.started_at) * 1000)),
            "recordCount": len(sess.records),
            "rawTranscriptLogged": False,
            "rawMediaAccepted": False,
        }

    def signals(self, session_id: str | None = None) -> dict[str, object]:
        for sess in (self._active, self._last):
            if sess is not None and (session_id is None or session_id == sess.session_id):
                return signals_payload(sess.session_id, sess.records)
        return signals_payload(session_id or "", [])

    def _finish(self, sess: _RnasSession) -> None:
        if any(record.get("type") == "turn_end" for record in sess.records):
            return
        transcript = " ".join(
            str(record.get("text", "")).strip()
            for record in sess.records
            if record.get("type") == "sentence" and str(record.get("text", "")).strip()
        )
        sess.records.append({
            "type": "turn_end",
            "turnIndex": sess.turn_index,
            "t": round(time.monotonic() - sess.started_at, 3),
            "transcript_full": transcript,
        })


def _safe_signal_number(value: object, *, maximum: float | None = None) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number < 0:
        return None
    if maximum is not None and number > maximum:
        return None
    return int(number) if number.is_integer() else round(number, 3)


def _bool_or_none(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _update_transcript_signals(sess: _RnasSession, sentence: str) -> None:
    sess.sentence_count += 1
    sess.transcript_char_count += len(sentence)
    sess.transcript_question_like = sess.transcript_question_like or any(marker in sentence for marker in ("?", "？", "인가요", "나요", "습니까"))
    sess.transcript_has_numbers = sess.transcript_has_numbers or any(ch.isdigit() for ch in sentence)
    concrete_markers = ("예를", "구체", "프로젝트", "결과", "성과", "문제", "해결", "역할", "수치", "기간", "팀")
    marker_hits = sum(1 for marker in concrete_markers if marker in sentence)
    length_score = min(1.0, len(sentence) / 180.0)
    sess.transcript_specificity_score = max(sess.transcript_specificity_score, round(min(1.0, length_score + marker_hits * 0.08), 3))


def _get_vision_grounder() -> Any | None:
    """Return GilJobE's optional objective vision grounder without making startup depend on it."""
    global _VISION_GROUNDER, _VISION_GROUNDER_INIT_ATTEMPTED
    if os.getenv("GILJOBE_VISION", "on").strip().lower() == "off":
        return None
    with _VISION_GROUNDER_LOCK:
        if not _VISION_GROUNDER_INIT_ATTEMPTED:
            _VISION_GROUNDER_INIT_ATTEMPTED = True
            try:
                from giljobe.analysis.grounding import maybe_vision_grounder

                _VISION_GROUNDER = maybe_vision_grounder()
            except Exception as exc:  # pragma: no cover - depends on optional runtime deps/models
                logger.info("GilJobE vision grounding unavailable: %s", type(exc).__name__)
                _VISION_GROUNDER = None
        return _VISION_GROUNDER


def _decode_internal_vision_frame(frame: dict[str, Any]) -> Any | None:
    """Decode the internal-only low-resolution JPEG sample into an RGB array.

    This accepts only the API-forwarded internal frame shape and intentionally
    returns no raw bytes or image content to callers/logs.
    """
    encoding = _safe_str(frame.get("encoding"), 80).lower()
    data = frame.get("data")
    if "base64" not in encoding or not isinstance(data, str) or not data.strip():
        return None
    encoded = data.split(",", 1)[1] if data.startswith("data:") and "," in data else data
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not raw or len(raw) > 2_000_000:
        return None

    try:  # Prefer cv2 when present in the runtime image.
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        buffer = np.frombuffer(raw, dtype=np.uint8)
        bgr = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if bgr is None:
            return None
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    except Exception:
        pass

    try:  # Pillow fallback for local/dev environments.
        import numpy as np  # type: ignore
        from PIL import Image  # type: ignore

        with Image.open(io.BytesIO(raw)) as image:
            return np.asarray(image.convert("RGB"))
    except Exception:
        return None


def _metric_ratio(metrics: dict[str, Any], ratio_key: str) -> int | float | None:
    ratio = _safe_signal_number(metrics.get(ratio_key), maximum=1)
    if ratio is None:
        return None
    return ratio


def _metric_detected(metrics: dict[str, Any], ratio_key: str, count_key: str) -> bool | None:
    ratio = _metric_ratio(metrics, ratio_key)
    if ratio is not None:
        return float(ratio) > 0
    count = _safe_signal_number(metrics.get(count_key), maximum=1_000_000)
    if count is not None:
        return float(count) > 0
    return None


def _analyze_internal_vision_frame(frame: dict[str, Any]) -> dict[str, object]:
    """Run GilJobE objective vision grounding on an internal frame sample.

    The returned object is deliberately structured/small: booleans, ratios, and
    status only. No raw frame bytes or candidate image data leave this helper.
    """
    rgb_frame = _decode_internal_vision_frame(frame)
    if rgb_frame is None:
        return {"status": "frame_decode_failed", "source": "internal_vision_frame"}

    grounder = _get_vision_grounder()
    if grounder is None:
        return {"status": "grounder_unavailable", "source": "giljobe_vision_grounder"}

    try:
        configured_timeout = float(os.getenv("REALTIME_VISION_ANALYSIS_TIMEOUT_SECONDS", "1.5"))
    except ValueError:
        configured_timeout = 1.5
    timeout = _safe_signal_number(configured_timeout, maximum=10)
    with _VISION_GROUNDER_LOCK:
        try:
            if hasattr(grounder, "reset"):
                grounder.reset()
            grounder.add_frame(0.001, rgb_frame)
            if hasattr(grounder, "wait_idle"):
                grounder.wait_idle(timeout=float(timeout or 1.5))
            metrics = grounder.window_metrics(0.0, 1.0) or {}
        except Exception as exc:  # pragma: no cover - depends on optional runtime deps/models
            logger.info("GilJobE vision grounding frame analysis failed: %s", type(exc).__name__)
            return {"status": "analysis_failed", "source": "giljobe_vision_grounder"}
        finally:
            try:
                if hasattr(grounder, "reset"):
                    grounder.reset()
            except Exception:
                pass

    if not isinstance(metrics, dict) or not metrics:
        return {"status": "no_detection_metrics", "source": "giljobe_vision_grounder"}

    result: dict[str, object] = {
        "status": "analyzed",
        "source": "giljobe_vision_grounder",
    }
    face_seen_ratio = _metric_ratio(metrics, "face_seen_ratio")
    pose_seen_ratio = _metric_ratio(metrics, "pose_seen_ratio")
    face_visible = _metric_detected(metrics, "face_seen_ratio", "face_frames")
    person_visible = _metric_detected(metrics, "pose_seen_ratio", "pose_frames")
    if face_seen_ratio is not None:
        result["faceSeenRatio"] = face_seen_ratio
    if pose_seen_ratio is not None:
        result["poseSeenRatio"] = pose_seen_ratio
    if face_visible is not None:
        result["faceVisible"] = face_visible
    if person_visible is not None:
        result["personVisible"] = person_visible
    return result


def _update_vision_signals(sess: _RnasSession, detail: dict[str, Any]) -> None:
    sess.vision_marker_count += 1
    signals = detail.get("visionSignals") if isinstance(detail.get("visionSignals"), dict) else {}
    for source in (detail, signals):
        camera_enabled = _bool_or_none(source.get("cameraEnabled"))
        if camera_enabled is not None:
            sess.vision_camera_enabled = camera_enabled
        face_visible = _bool_or_none(source.get("faceVisible"))
        if face_visible is not None:
            sess.vision_face_visible = face_visible
        person_visible = _bool_or_none(source.get("personVisible"))
        if person_visible is not None:
            sess.vision_person_visible = person_visible
        average_luma = _safe_signal_number(source.get("averageLuma"), maximum=255)
        if average_luma is not None:
            sess.vision_average_luma = average_luma
        visual_quality = _safe_str(source.get("visualQuality"), 80)
        if visual_quality:
            sess.vision_quality = visual_quality
    frame = detail.get("visionFrame") if isinstance(detail.get("visionFrame"), dict) else {}
    frame_available = _bool_or_none(signals.get("frameAvailable"))
    if frame or frame_available:
        sess.vision_frame_count += 1
        byte_length = _safe_signal_number(frame.get("byteLength") or signals.get("frameByteLength"), maximum=10_000_000)
        if byte_length is not None:
            sess.vision_frame_bytes += int(byte_length)
    if frame:
        analysis = _analyze_internal_vision_frame(frame)
        status = _safe_str(analysis.get("status"), 80)
        source = _safe_str(analysis.get("source"), 80)
        if status:
            sess.vision_analysis_status = status
        if source:
            sess.vision_analysis_source = source
        face_visible = _bool_or_none(analysis.get("faceVisible"))
        if face_visible is not None:
            sess.vision_face_visible = face_visible
        person_visible = _bool_or_none(analysis.get("personVisible"))
        if person_visible is not None:
            sess.vision_person_visible = person_visible
        face_seen_ratio = _safe_signal_number(analysis.get("faceSeenRatio"), maximum=1)
        if face_seen_ratio is not None:
            sess.vision_face_seen_ratio = face_seen_ratio
        pose_seen_ratio = _safe_signal_number(analysis.get("poseSeenRatio"), maximum=1)
        if pose_seen_ratio is not None:
            sess.vision_pose_seen_ratio = pose_seen_ratio


def _vision_status(sess: _RnasSession) -> str:
    if sess.vision_frame_count:
        return "frame_observed"
    if sess.vision_marker_count:
        return "signals_observed"
    return "missing"


def _transcript_signals(sess: _RnasSession) -> dict[str, object]:
    return {
        "observed": sess.transcript_observed,
        "status": "complete" if sess.transcript_observed else "missing",
        "sentenceCount": sess.sentence_count,
        "charCount": sess.transcript_char_count,
        "specificityScore": sess.transcript_specificity_score,
        "questionLike": sess.transcript_question_like,
        "hasNumbers": sess.transcript_has_numbers,
    }


def _prosody_signals(sess: _RnasSession) -> dict[str, object]:
    status = "timing_observed" if sess.prosody_speech_duration_ms is not None else ("lifecycle_observed" if sess.prosody_observed else "missing")
    signals: dict[str, object] = {
        "observed": sess.prosody_observed,
        "status": status,
        "markerCount": sess.prosody_marker_count,
        "vadEventCount": sess.prosody_vad_event_count,
        "rawAudioIncluded": False,
    }
    if sess.prosody_audio_start_ms is not None:
        signals["audioStartMs"] = sess.prosody_audio_start_ms
    if sess.prosody_audio_end_ms is not None:
        signals["audioEndMs"] = sess.prosody_audio_end_ms
    if sess.prosody_speech_duration_ms is not None:
        signals["speechDurationMs"] = sess.prosody_speech_duration_ms
    if sess.prosody_energy_samples:
        signals["energyMean"] = round(sum(sess.prosody_energy_samples) / len(sess.prosody_energy_samples), 3)
        signals["energySampleCount"] = len(sess.prosody_energy_samples)
    return signals


def _vision_signals(sess: _RnasSession) -> dict[str, object]:
    signals: dict[str, object] = {
        "observed": sess.vision_observed,
        "status": _vision_status(sess),
        "markerCount": sess.vision_marker_count,
        "sampledFrameCount": sess.vision_frame_count,
        "frameBytesObserved": sess.vision_frame_bytes,
        "cameraEnabled": bool(sess.vision_camera_enabled) if sess.vision_camera_enabled is not None else False,
        "faceVisible": sess.vision_face_visible,
        "personVisible": sess.vision_person_visible,
        "visualQuality": sess.vision_quality or ("frame_observed" if sess.vision_frame_count else "metadata_only"),
    }
    if sess.vision_average_luma is not None:
        signals["averageLuma"] = sess.vision_average_luma
    if sess.vision_analysis_source:
        signals["analysisSource"] = sess.vision_analysis_source
    if sess.vision_analysis_status:
        signals["objectiveVisionStatus"] = sess.vision_analysis_status
    if sess.vision_face_seen_ratio is not None:
        signals["faceSeenRatio"] = sess.vision_face_seen_ratio
    if sess.vision_pose_seen_ratio is not None:
        signals["poseSeenRatio"] = sess.vision_pose_seen_ratio
    return signals


def _behavioral_signals(transcript: dict[str, object], prosody: dict[str, object], vision: dict[str, object]) -> dict[str, object]:
    return {
        "observed": bool(transcript.get("observed")) and bool(prosody.get("observed")) and bool(vision.get("observed")),
        "status": "ready",
        "needsConcreteFollowup": float(transcript.get("specificityScore") or 0) < 0.55,
        "visualEvidenceLevel": "frame" if int(vision.get("sampledFrameCount") or 0) > 0 else "signals",
    }


def _next_question_guidance(transcript: dict[str, object], vision: dict[str, object]) -> str:
    focus = "구체적인 사례, 본인 역할, 결과 수치"
    if transcript.get("hasNumbers"):
        focus = "수치로 언급한 결과의 기준, 본인 기여도, 재현 가능성"
    elif float(transcript.get("specificityScore") or 0) >= 0.65:
        focus = "방금 답변의 핵심 선택 이유와 어려웠던 트레이드오프"
    visual_note = "시각 신호는 참고만 하고 표정·자세를 단정하지 마세요."
    if vision.get("faceVisible") is True:
        visual_note = (
            "카메라 신호상 후보자 얼굴이 프레임 안에 확인되었습니다. "
            "후보자가 화면 확인을 물으면 그 사실만 짧게 답하되, 영상을 직접 본다고 말하거나 표정·외모를 평가하지 마세요."
        )
    elif vision.get("personVisible") is True:
        visual_note = (
            "카메라 신호상 후보자 상반신/사람이 프레임 안에 확인되었습니다. "
            "후보자가 화면 확인을 물으면 그 사실만 짧게 답하되, 영상을 직접 본다고 말하거나 표정·외모를 평가하지 마세요."
        )
    elif vision.get("faceVisible") is False or vision.get("personVisible") is False:
        visual_note = "카메라 신호상 얼굴/사람 확인은 아직 불충분합니다. 보인다고 단정하지 말고 필요하면 카메라 위치 확인을 요청하세요."
    elif int(vision.get("sampledFrameCount") or 0) > 0:
        visual_note = "카메라 프레임은 수신됐지만 얼굴/사람 판정은 아직 없습니다. 외형 판단 없이 답변 내용 중심으로 이어가세요."
    return f"직전 답변을 바탕으로 {focus}를 자연스럽게 확인하는 한국어 후속 질문 하나를 하세요. {visual_note}"


def _candidate_safe_structured_fragment(guidance: str) -> dict[str, object]:
    return {
        "schemaVersion": "2026-06-13.candidate-safe-prompt-fragment.v2",
        "kind": "candidate_safe_realtime_mmm_context",
        "text": _safe_str(guidance, 600),
        "containsRawTranscript": False,
        "containsRawMedia": False,
        "containsSecrets": False,
    }


def _turn_confidence(transcript: dict[str, object], prosody: dict[str, object], vision: dict[str, object]) -> float:
    score = 0.0
    score += 0.5 if transcript.get("observed") else 0.0
    score += 0.2 if prosody.get("observed") else 0.0
    score += 0.2 if vision.get("observed") else 0.0
    score += 0.1 if int(vision.get("sampledFrameCount") or 0) > 0 else 0.0
    return round(min(0.98, score), 2)


def _safe_turn_index(value: object) -> int | None:
    if isinstance(value, int) and 0 <= value <= 9999:
        return value
    text = _safe_str(value, 8)
    if text.isdigit():
        return int(text)
    return None


def _pending_result(interview_id: str, turn_index: int, reason: str, reasons: list[str] | None = None) -> dict[str, object]:
    return {
        "result": None,
        "status": "pending",
        "reason": reason,
        "reasonCodes": reasons or [reason],
        "interviewId": interview_id,
        "turnIndex": turn_index,
        "rawTranscriptLogged": False,
        "rawMediaAccepted": False,
    }


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


def _extract_turn_index(value: object) -> int | None:
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _record_matches_turn(record: object, requested_turn_index: int) -> bool:
    if not isinstance(record, dict):
        return False
    for key in ("turnIndex", "turn_index", "answerTurnIndex", "analysisTurnIndex"):
        observed = _extract_turn_index(record.get(key))
        if observed == requested_turn_index:
            return True
    turn_id = _safe_str(record.get("turnId") or record.get("turn_id"), 32)
    return bool(turn_id and turn_id == str(requested_turn_index))


def _turn_handoff_matches_requested_turn(payload: dict[str, Any], handoff: dict[str, Any], requested_turn_index: int | None) -> bool:
    """Fail closed when a handoff cannot be tied to the requested answer turn."""
    if requested_turn_index is None:
        return False
    for container in (
        handoff,
        handoff.get("meta") if isinstance(handoff.get("meta"), dict) else None,
        payload,
    ):
        if _record_matches_turn(container, requested_turn_index):
            return True
    records = payload.get("records")
    if isinstance(records, list):
        return any(_record_matches_turn(record, requested_turn_index) for record in records)
    return False


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
            if key_str in RAW_FIELD_MARKERS and nested_path not in INTERNAL_DETAIL_PATHS:
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
    rnas = req.app.get("event_only_realtime_turns")
    rnas_result = {"accepted": False, "reason": "rnas_unavailable"}
    if isinstance(rnas, _EventOnlyRealtimeTurns):
        rnas_result = rnas.ingest(payload)
    status = 202 if rnas_result.get("accepted") is not False else 409
    return _json({
        "accepted": bool(rnas_result.get("accepted")),
        "service": "analysis-engine",
        "endpoint": "/realtime/turn-events",
        "realtimeNativeAnalysisSession": bool(rnas_result.get("realtimeNativeAnalysisSession")),
        "reason": _safe_str(rnas_result.get("reason"), 120),
        "rawTranscriptLogged": False,
        "rawMediaAccepted": False,
        "recordCount": len(records),
    }, status=status)


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
    """Return the exact turn-keyed RNAS result consumed by the API gate.

    This route intentionally resolves only ``(interviewId, turnIndex)`` from
    Realtime-native storage. It never falls back to active, last, global, or
    session-wide GilJobE state, preventing stale cross-turn bleed into ordinary
    ``response.create`` authorization.
    """
    interview_id = _safe_str(req.query.get("interviewId"), 96)
    turn_index_param = _safe_str(req.query.get("turnIndex"), 8)
    turn_index = _extract_turn_index(turn_index_param)
    service = req.app.get("analysis_service")
    pending = {
        "result": None, "status": "pending",
        "rawTranscriptLogged": False, "rawMediaAccepted": False,
    }
    if service is None or render_prompt_fragment is None or not interview_id:
        return _json(pending)
    rnas = req.app.get("event_only_realtime_turns")
    if isinstance(rnas, _EventOnlyRealtimeTurns) and turn_index is not None:
        rnas_result = rnas.turn_result(interview_id, turn_index)
        if rnas_result.get("status") == "ready":
            return _json({
                "result": rnas_result,
                "rawTranscriptLogged": False,
                "rawMediaAccepted": False,
            })
    payload = service.signals(interview_id)
    handoff = payload.get("turnHandoff")
    if not handoff:
        return _json(pending)
    if not isinstance(handoff, dict) or not _turn_handoff_matches_requested_turn(payload, handoff, turn_index):
        return _json(pending)
    return _json({
        "result": {
            "schemaVersion": "2026-06-12.turn-handoff-fragment.v2",
            "status": "ready",
            "sessionId": _safe_str(payload.get("sessionId"), 96),
            "turnIndex": turn_index,
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
    # GilJobE f7307fc owns POST /realtime/turn-events for the external transcript
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
