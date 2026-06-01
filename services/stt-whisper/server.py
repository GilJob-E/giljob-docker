#!/usr/bin/env python3
"""Local faster-whisper STT service for GilJob v2.

This service accepts answer-turn audio after the candidate presses the manual
"answer end" button. It does not subscribe to LiveKit tracks and does not log
raw media or raw transcript text.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

SERVICE_NAME = os.getenv("SERVICE_NAME", "stt-whisper")
PORT = int(os.getenv("SERVICE_PORT", "8200"))
MAX_AUDIO_BYTES = int(os.getenv("STT_MAX_AUDIO_BYTES", str(25 * 1024 * 1024)))
INTERVIEW_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_CONTENT_TYPE_SUFFIXES = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/wave": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".mp4",
    "application/octet-stream": ".bin",
}
_MODEL: Any | None = None
_MODEL_LOCK = threading.Lock()


@dataclass(frozen=True)
class WhisperSettings:
    model_name: str
    device: str
    device_index: int
    compute_type: str
    language: str
    beam_size: int
    vad_filter: bool
    host_gpu_device_id: str

    @property
    def provider(self) -> str:
        return "local-whisper"


def load_settings() -> WhisperSettings:
    return WhisperSettings(
        model_name=os.getenv("WHISPER_MODEL", "Systran/faster-whisper-large-v3").strip() or "Systran/faster-whisper-large-v3",
        device=os.getenv("WHISPER_DEVICE", "cuda").strip() or "cuda",
        device_index=int(os.getenv("WHISPER_DEVICE_INDEX", "0")),
        compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "float16").strip() or "float16",
        language=os.getenv("STT_LANGUAGE", "ko").strip() or "ko",
        beam_size=int(os.getenv("WHISPER_BEAM_SIZE", "5")),
        vad_filter=os.getenv("WHISPER_VAD_FILTER", "true").strip().lower() in {"1", "true", "yes", "on"},
        host_gpu_device_id=os.getenv("WHISPER_HOST_GPU_DEVICE_ID", "1").strip() or "1",
    )


def _load_faster_whisper_class() -> Any:
    from faster_whisper import WhisperModel  # type: ignore[import-not-found]

    return WhisperModel


def get_model(settings: WhisperSettings) -> Any:
    global _MODEL
    if _MODEL is None:
        with _MODEL_LOCK:
            if _MODEL is None:
                whisper_model = _load_faster_whisper_class()
                _MODEL = whisper_model(
                    settings.model_name,
                    device=settings.device,
                    device_index=settings.device_index,
                    compute_type=settings.compute_type,
                )
    return _MODEL


def warmup_model() -> tuple[int, dict[str, object]]:
    settings = load_settings()
    started = time.monotonic()
    try:
        get_model(settings)
        duration_ms = int((time.monotonic() - started) * 1000)
        return 200, {
            "service": SERVICE_NAME,
            "status": "ready",
            "provider": settings.provider,
            "model": settings.model_name,
            "device": settings.device,
            "deviceIndex": settings.device_index,
            "hostGpuDeviceId": settings.host_gpu_device_id,
            "computeType": settings.compute_type,
            "language": settings.language,
            "modelLoaded": _MODEL is not None,
            "warmupMs": duration_ms,
        }
    except Exception as error:  # do not leak secrets or raw media
        return 502, {
            "error": "stt_warmup_failed",
            "provider": settings.provider,
            "model": settings.model_name,
            "message": str(error)[:500],
        }


def _safe_interview_id(value: str | None) -> str:
    interview_id = (value or "local-demo").strip()
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        raise ValueError("invalid_interview_id")
    return interview_id


def _content_suffix(content_type: str) -> str:
    bare_type = content_type.split(";", 1)[0].strip().lower()
    return _CONTENT_TYPE_SUFFIXES.get(bare_type, ".bin")


def transcribe_audio_bytes(audio: bytes, *, content_type: str, query: dict[str, list[str]]) -> tuple[int, dict[str, object]]:
    if not audio:
        return 400, {"error": "empty_audio"}
    if len(audio) > MAX_AUDIO_BYTES:
        return 413, {"error": "audio_too_large", "maxBytes": MAX_AUDIO_BYTES}

    try:
        interview_id = _safe_interview_id((query.get("interviewId") or [None])[0])
    except ValueError as error:
        return 400, {"error": str(error)}

    settings = load_settings()
    language = (query.get("language") or [settings.language])[0] or settings.language
    turn_index_raw = (query.get("turnIndex") or ["1"])[0]
    try:
        turn_index = int(turn_index_raw)
    except (TypeError, ValueError):
        return 400, {"error": "invalid_turn_index"}
    if turn_index < 1:
        return 400, {"error": "invalid_turn_index"}

    started = time.monotonic()
    suffix = _content_suffix(content_type)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="giljob-answer-", suffix=suffix, delete=False) as tmp:
            tmp.write(audio)
            temp_path = Path(tmp.name)

        model = get_model(settings)
        segments_iter, info = model.transcribe(
            str(temp_path),
            language=language,
            task="transcribe",
            beam_size=settings.beam_size,
            vad_filter=settings.vad_filter,
        )
        segments = list(segments_iter)
        text = " ".join(str(getattr(segment, "text", "")).strip() for segment in segments).strip()
        duration_ms = int((time.monotonic() - started) * 1000)
        return 200, {
            "interviewId": interview_id,
            "turnIndex": turn_index,
            "provider": settings.provider,
            "model": settings.model_name,
            "language": getattr(info, "language", language),
            "languageProbability": getattr(info, "language_probability", None),
            "durationSeconds": getattr(info, "duration", None),
            "processingMs": duration_ms,
            "text": text,
            "segments": [
                {
                    "start": getattr(segment, "start", None),
                    "end": getattr(segment, "end", None),
                    "text": str(getattr(segment, "text", "")).strip(),
                }
                for segment in segments
            ],
        }
    except Exception as error:  # do not leak raw media/transcript in logs or response
        return 502, {
            "error": "stt_provider_failed",
            "provider": settings.provider,
            "model": settings.model_name,
            "message": str(error)[:500],
        }
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


class Handler(BaseHTTPRequestHandler):
    server_version = "GilJobV2STTWhisper/0.1"

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path in {"/healthz", "/readyz"}:
            settings = load_settings()
            self._json(200, {
                "service": SERVICE_NAME,
                "status": "ok",
                "provider": settings.provider,
                "model": settings.model_name,
                "device": settings.device,
                "deviceIndex": settings.device_index,
                "hostGpuDeviceId": settings.host_gpu_device_id,
                "computeType": settings.compute_type,
                "language": settings.language,
                "modelLoaded": _MODEL is not None,
            })
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        parsed = urlparse(self.path)
        if parsed.path in {"/warmup", "/stt/warmup"}:
            status, payload = warmup_model()
            self._json(status, payload)
            return
        if parsed.path not in {"/transcribe", "/stt/transcribe"}:
            self._json(404, {"error": "not_found", "path": parsed.path})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            self._json(400, {"error": "invalid_content_length"})
            return
        if content_length > MAX_AUDIO_BYTES:
            self._json(413, {"error": "audio_too_large", "maxBytes": MAX_AUDIO_BYTES})
            return
        audio = self.rfile.read(content_length)
        status, payload = transcribe_audio_bytes(
            audio,
            content_type=self.headers.get("Content-Type", "application/octet-stream"),
            query=parse_qs(parsed.query),
        )
        self._json(status, payload)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
