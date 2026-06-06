#!/usr/bin/env python3
"""GilJob v2 AI engine provider boundary.

This service owns server-mediated provider adapters for question generation,
room TTS, and avatar session metadata. It does not ingest raw media, run STT,
own browser rendering, or generate final reports. STT belongs to the GilJobE
analysis-engine boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import math
import os
import re
import struct
import time
import wave
from io import BytesIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
import urllib.error
import urllib.request

SERVICE_NAME = os.getenv("SERVICE_NAME", "ai-engine")
PORT = int(os.getenv("SERVICE_PORT", "8100"))
MAX_REQUEST_BYTES = 32_768
MAX_TTS_TEXT_CHARS = 1_200
INTERVIEW_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    gemini_api_key: str
    gemini_model: str
    timeout_seconds: float

    @property
    def key_configured(self) -> bool:
        return bool(self.gemini_api_key and not self.gemini_api_key.startswith("replace-me"))


@dataclass(frozen=True)
class TTSSettings:
    provider: str
    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    elevenlabs_model: str
    output_format: str
    gemini_api_key: str
    gemini_model: str
    gemini_voice_name: str
    timeout_seconds: float
    failure_fallback_provider: str

    @property
    def key_configured(self) -> bool:
        return self.elevenlabs_key_configured

    @property
    def voice_configured(self) -> bool:
        return self.elevenlabs_voice_configured

    @property
    def elevenlabs_key_configured(self) -> bool:
        return bool(self.elevenlabs_api_key and not self.elevenlabs_api_key.startswith("replace-me"))

    @property
    def elevenlabs_voice_configured(self) -> bool:
        return bool(self.elevenlabs_voice_id and not self.elevenlabs_voice_id.startswith("replace-me"))

    @property
    def gemini_key_configured(self) -> bool:
        return bool(self.gemini_api_key and not self.gemini_api_key.startswith("replace-me"))

    @property
    def gemini_voice_configured(self) -> bool:
        return bool(self.gemini_voice_name and not self.gemini_voice_name.startswith("replace-me"))


@dataclass(frozen=True)
class AvatarSettings:
    provider: str
    spatialreal_api_key: str
    spatialreal_app_id: str
    spatialreal_avatar_id: str
    console_endpoint: str
    ingress_endpoint: str
    session_ttl_seconds: int
    timeout_seconds: float
    failure_fallback_provider: str
    audio_sample_rate: int
    audio_channel_count: int

    @property
    def key_configured(self) -> bool:
        return bool(self.spatialreal_api_key and not self.spatialreal_api_key.startswith("replace-me"))

    @property
    def app_configured(self) -> bool:
        return bool(self.spatialreal_app_id and not self.spatialreal_app_id.startswith("replace-me"))

    @property
    def avatar_configured(self) -> bool:
        return bool(self.spatialreal_avatar_id and not self.spatialreal_avatar_id.startswith("replace-me"))


def load_tts_settings() -> TTSSettings:
    return TTSSettings(
        provider=os.getenv("VOICE_PROVIDER", "fake").strip().lower() or "fake",
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", "").strip(),
        elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID", "").strip(),
        elevenlabs_model=os.getenv("ELEVENLABS_TTS_MODEL", "eleven_flash_v2_5").strip() or "eleven_flash_v2_5",
        output_format=os.getenv("ELEVENLABS_OUTPUT_FORMAT", "mp3_22050_32").strip() or "mp3_22050_32",
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview").strip() or "gemini-3.1-flash-tts-preview",
        gemini_voice_name=os.getenv("GEMINI_TTS_VOICE", "Kore").strip() or "Kore",
        timeout_seconds=float(os.getenv("TTS_TIMEOUT_SECONDS", os.getenv("ELEVENLABS_TIMEOUT_SECONDS", os.getenv("GEMINI_TIMEOUT_SECONDS", "30")))),
        failure_fallback_provider=os.getenv("TTS_PROVIDER_FAILURE_FALLBACK", "").strip().lower(),
    )


def _spatialreal_console_endpoint() -> str:
    configured = os.getenv("SPATIALREAL_CONSOLE_ENDPOINT", "").strip().rstrip("/")
    if configured:
        return configured
    region = os.getenv("SPATIALREAL_REGION", "ap-northeast").strip().lower() or "ap-northeast"
    if region == "us-west":
        return "https://console.us-west.spatialwalk.cloud"
    return "https://console.ap-northeast.spatialwalk.cloud"


def load_avatar_settings() -> AvatarSettings:
    return AvatarSettings(
        provider=os.getenv("AVATAR_PROVIDER", "disabled").strip().lower() or "disabled",
        spatialreal_api_key=os.getenv("SPATIALREAL_API_KEY", "").strip(),
        spatialreal_app_id=os.getenv("SPATIALREAL_APP_ID", "").strip(),
        spatialreal_avatar_id=os.getenv("SPATIALREAL_AVATAR_ID", "").strip(),
        console_endpoint=_spatialreal_console_endpoint(),
        ingress_endpoint=os.getenv("SPATIALREAL_INGRESS_ENDPOINT", "").strip().rstrip("/"),
        session_ttl_seconds=min(23 * 60 * 60, max(60, int(os.getenv("SPATIALREAL_SESSION_TTL_SECONDS", "900")))),
        timeout_seconds=float(os.getenv("SPATIALREAL_TIMEOUT_SECONDS", os.getenv("GEMINI_TIMEOUT_SECONDS", "30"))),
        failure_fallback_provider=os.getenv("AVATAR_PROVIDER_FAILURE_FALLBACK", "").strip().lower(),
        audio_sample_rate=int(os.getenv("SPATIALREAL_AUDIO_SAMPLE_RATE", "16000")),
        audio_channel_count=int(os.getenv("SPATIALREAL_AUDIO_CHANNEL_COUNT", "1")),
    )


def load_llm_settings() -> LLMSettings:
    return LLMSettings(
        provider=os.getenv("LLM_PROVIDER", "fake").strip().lower() or "fake",
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip() or "gemini-3.5-flash",
        timeout_seconds=float(os.getenv("GEMINI_TIMEOUT_SECONDS", "30")),
    )


def _safe_str(value: object, max_len: int = 4_000) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def _candidate_context(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "interviewId": _safe_str(payload.get("interviewId") or "local-demo", 96),
        "candidateProfile": _safe_str(payload.get("candidateProfile") or "아직 후보자 CV가 입력되지 않았습니다.", 2_000),
        "job": _safe_str(payload.get("job") or "아직 직무 링크/공고가 입력되지 않았습니다.", 2_000),
        "persona": _safe_str(payload.get("persona") or "차분하고 명확한 한국어 면접관", 500),
        "lastAnswer": _safe_str(payload.get("lastAnswer") or "아직 이전 답변이 없습니다.", 2_000),
    }


def build_question_prompt(payload: dict[str, Any], turn_index: int) -> str:
    context = _candidate_context(payload)
    return f"""
너는 GilJob의 실시간 모의면접 InterviewController다.
목표는 후보자의 역량을 검증하는 한국어 면접 질문을 한 번에 하나씩 생성하는 것이다.

제약:
- 질문은 하나만 생성한다.
- 후보자가 답변 버튼을 눌러 말할 수 있도록 질문은 1~2문장으로 짧게 끝낸다.
- CV/직무 정보가 부족하면 일반적인 자기소개/경험 검증 질문으로 시작한다.
- 평가, 해설, 정답, 채점 기준은 출력하지 않는다.
- 출력은 면접관이 그대로 읽을 수 있는 질문 문장만 반환한다.

interviewId: {context['interviewId']}
turnIndex: {turn_index}
면접관 persona: {context['persona']}
후보자 정보: {context['candidateProfile']}
직무 정보: {context['job']}
이전 답변 요약: {context['lastAnswer']}
""".strip()


def _extract_gemini_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return ""
    texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
    return "\n".join(str(text) for text in texts if text).strip()


def generate_gemini_question(settings: LLMSettings, payload: dict[str, Any], turn_index: int) -> str:
    if not settings.key_configured:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    prompt = build_question_prompt(payload, turn_index)
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": settings.gemini_api_key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        error.read()  # consume upstream body without exposing provider diagnostics publicly
        raise RuntimeError(f"Gemini request failed: HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise RuntimeError("Gemini request failed") from error
    data = json.loads(response_body)
    text = _extract_gemini_text(data)
    if not text:
        raise RuntimeError("Gemini response did not include text")
    return text


def fake_question(payload: dict[str, Any], turn_index: int) -> str:
    context = _candidate_context(payload)
    if turn_index <= 1:
        return "먼저 본인의 핵심 경험 하나를 선택해서, 지원한 직무와 어떻게 연결되는지 설명해 주세요."
    return f"방금 답변을 바탕으로, {context['job']} 관점에서 가장 어려웠던 의사결정과 그 결과를 구체적으로 설명해 주세요."


def _parse_output_format(output_format: str) -> tuple[str, int | None]:
    parts = output_format.split("_")
    codec = parts[0] if parts else "unknown"
    sample_rate: int | None = None
    if len(parts) >= 2:
        try:
            sample_rate = int(parts[1])
        except ValueError:
            sample_rate = None
    return codec, sample_rate


def _fake_wav_bytes(text: str) -> bytes:
    sample_rate = 16_000
    duration_seconds = min(1.2, max(0.25, len(text) / 120.0))
    frame_count = int(sample_rate * duration_seconds)
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for index in range(frame_count):
            amplitude = int(1000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            wav.writeframesraw(struct.pack("<h", amplitude))
    return buffer.getvalue()


def _wav_container_bytes(pcm: bytes, *, channels: int = 1, rate: int = 24_000, sample_width: int = 2) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


def _extract_gemini_audio_base64(data: dict[str, Any]) -> str:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return ""
    for part in parts:
        if not isinstance(part, dict):
            continue
        inline_data = part.get("inlineData") or part.get("inline_data")
        if isinstance(inline_data, dict) and inline_data.get("data"):
            return str(inline_data.get("data"))
    return ""


def _tts_metadata(
    provider: str,
    content_type: str,
    codec: str,
    sample_rate: int | None,
    channels: int,
    data: bytes,
    request_id: str,
) -> dict[str, object]:
    return {
        "provider": provider,
        "contentType": content_type,
        "codec": codec,
        "sampleRate": sample_rate,
        "channels": channels,
        "byteLength": len(data),
        "requestId": request_id,
    }


def _safe_request_id(session_id: str, turn_id: str, provider: str) -> str:
    raw = f"{session_id}-{turn_id}-{provider}"
    return "tts_" + re.sub(r"[^A-Za-z0-9._-]+", "-", raw)[:120]


def synthesize_fake_tts(
    session_id: str,
    turn_id: str,
    text: str,
    *,
    fallback_from: str | None = None,
    fallback_reason: str | None = None,
) -> tuple[int, dict[str, object]]:
    # Fake is the required keyless contract provider and the optional fail-open room fallback.
    audio = _fake_wav_bytes(text)
    metadata = _tts_metadata(
        "fake",
        "audio/wav",
        "wav",
        16_000,
        1,
        audio,
        _safe_request_id(session_id, turn_id, "fake"),
    )
    audio_payload: dict[str, object] = {**metadata, "base64": base64.b64encode(audio).decode("ascii")}
    response: dict[str, object] = {
        "sessionId": session_id,
        "turnId": turn_id,
        "status": "ok",
        "audio": audio_payload,
    }
    if fallback_from:
        audio_payload["fallbackFrom"] = fallback_from
        audio_payload["fallbackReason"] = fallback_reason or "provider_failed"
        response["providerStatus"] = "fallback"
    return 200, response


def synthesize_elevenlabs_tts(settings: TTSSettings, session_id: str, turn_id: str, text: str) -> tuple[int, dict[str, object]]:
    if not settings.key_configured or not settings.voice_configured:
        return 503, {
            "error": "tts_provider_unavailable",
            "provider": "elevenlabs",
            "reason": "missing_api_key_or_voice_id",
        }
    codec, sample_rate = _parse_output_format(settings.output_format)
    body = json.dumps({"text": text, "model_id": settings.elevenlabs_model}).encode("utf-8")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}?output_format={settings.output_format}"
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "xi-api-key": settings.elevenlabs_api_key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.timeout_seconds) as response:
            audio = response.read()
            content_type = response.headers.get("Content-Type", "application/octet-stream")
    except urllib.error.HTTPError as error:
        error.read()  # consume upstream body without exposing provider diagnostics publicly
        return 502, {
            "error": "tts_provider_failed",
            "provider": "elevenlabs",
            "statusCode": error.code,
            "message": "provider request failed",
        }
    except urllib.error.URLError:
        return 502, {
            "error": "tts_provider_failed",
            "provider": "elevenlabs",
            "message": "provider request failed",
        }
    metadata = _tts_metadata(
        "elevenlabs",
        content_type,
        codec,
        sample_rate,
        1,
        audio,
        _safe_request_id(session_id, turn_id, "elevenlabs"),
    )
    return 200, {
        "sessionId": session_id,
        "turnId": turn_id,
        "status": "ok",
        "audio": {**metadata, "base64": base64.b64encode(audio).decode("ascii")},
    }


def synthesize_gemini_tts(settings: TTSSettings, session_id: str, turn_id: str, text: str) -> tuple[int, dict[str, object]]:
    if not settings.gemini_key_configured or not settings.gemini_voice_configured:
        return 503, {
            "error": "tts_provider_unavailable",
            "provider": "gemini",
            "reason": "missing_api_key_or_voice_name",
        }

    prompt = f"Say in a calm, professional Korean interviewer voice: {text}"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": settings.gemini_voice_name}
                }
            },
        },
        "model": settings.gemini_model,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": settings.gemini_api_key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        error.read()  # consume upstream body without exposing provider diagnostics publicly
        return 502, {
            "error": "tts_provider_failed",
            "provider": "gemini",
            "statusCode": error.code,
            "message": "provider request failed",
        }
    except urllib.error.URLError:
        return 502, {
            "error": "tts_provider_failed",
            "provider": "gemini",
            "message": "provider request failed",
        }

    try:
        data = json.loads(response_body)
        pcm_base64 = _extract_gemini_audio_base64(data)
        if not pcm_base64:
            raise ValueError("missing audio data")
        pcm = base64.b64decode(pcm_base64)
    except (ValueError, json.JSONDecodeError):
        return 502, {
            "error": "tts_provider_failed",
            "provider": "gemini",
            "message": "invalid audio response",
        }

    sample_rate = 24_000
    audio = _wav_container_bytes(pcm, channels=1, rate=sample_rate, sample_width=2)
    metadata = _tts_metadata(
        "gemini",
        "audio/wav",
        "wav",
        sample_rate,
        1,
        audio,
        _safe_request_id(session_id, turn_id, "gemini"),
    )
    return 200, {
        "sessionId": session_id,
        "turnId": turn_id,
        "status": "ok",
        "audio": {
            **metadata,
            "base64": base64.b64encode(audio).decode("ascii"),
            "model": settings.gemini_model,
            "voiceName": settings.gemini_voice_name,
            "sourceCodec": "pcm_s16le",
        },
    }


def tts_response(payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    settings = load_tts_settings()
    session_id = _safe_str(payload.get("sessionId") or payload.get("interviewId") or "local-demo", 96)
    turn_id = _safe_str(payload.get("turnId") or payload.get("questionId") or "turn-0001", 120)
    text = _safe_str(payload.get("text") or payload.get("question") or "", MAX_TTS_TEXT_CHARS)
    if not INTERVIEW_ID_PATTERN.fullmatch(session_id):
        return 400, {"error": "invalid_session_id"}
    if not text:
        return 400, {"error": "missing_text"}
    if settings.provider == "fake":
        return synthesize_fake_tts(session_id, turn_id, text)
    if settings.provider == "elevenlabs":
        status, response = synthesize_elevenlabs_tts(settings, session_id, turn_id, text)
        if status != 200 and settings.failure_fallback_provider == "fake":
            reason = _safe_str(response.get("error") or "provider_failed", 80)
            return synthesize_fake_tts(session_id, turn_id, text, fallback_from="elevenlabs", fallback_reason=reason)
        return status, response
    if settings.provider == "gemini":
        status, response = synthesize_gemini_tts(settings, session_id, turn_id, text)
        if status != 200 and settings.failure_fallback_provider == "fake":
            reason = _safe_str(response.get("error") or "provider_failed", 80)
            return synthesize_fake_tts(session_id, turn_id, text, fallback_from="gemini", fallback_reason=reason)
        return status, response
    return 400, {"error": "unsupported_tts_provider", "provider": settings.provider}


def _avatar_client_config(settings: AvatarSettings, *, include_session_token: str | None = None, expires_at: int | None = None) -> dict[str, object]:
    client: dict[str, object] = {
        "appId": settings.spatialreal_app_id if settings.app_configured else None,
        "avatarId": settings.spatialreal_avatar_id if settings.avatar_configured else None,
        "audioFormat": {
            "channelCount": settings.audio_channel_count,
            "sampleRate": settings.audio_sample_rate,
            "sampleEncoding": "pcm_s16le",
        },
        "drivingServiceMode": "sdk",
        "environment": "intl",
        "tokenSource": "server-mediated",
    }
    if settings.ingress_endpoint:
        client["ingressEndpoint"] = settings.ingress_endpoint
    if include_session_token is not None:
        client["sessionToken"] = include_session_token
        client["expiresAt"] = expires_at
    return client


def fetch_spatialreal_session_token(settings: AvatarSettings, expires_at: int) -> tuple[str | None, dict[str, object] | None]:
    body = json.dumps({"expireAt": expires_at}).encode("utf-8")
    request = urllib.request.Request(
        f"{settings.console_endpoint}/v1/console/session-tokens",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Api-Key": settings.spatialreal_api_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        error.read()  # consume upstream body without exposing provider diagnostics publicly
        return None, {"error": "avatar_provider_failed", "provider": "spatialreal", "statusCode": error.code, "message": "provider request failed"}
    except urllib.error.URLError:
        return None, {"error": "avatar_provider_failed", "provider": "spatialreal", "message": "provider request failed"}

    try:
        data = json.loads(response_body)
    except json.JSONDecodeError:
        return None, {"error": "avatar_provider_failed", "provider": "spatialreal", "message": "invalid session token response"}
    session_token = _safe_str(data.get("sessionToken") if isinstance(data, dict) else "", 4096)
    if not session_token:
        return None, {"error": "avatar_provider_failed", "provider": "spatialreal", "message": "missing sessionToken"}
    return session_token, None


def _disabled_avatar_payload(settings: AvatarSettings, interview_id: str, *, fallback_from: str | None = None, reason: str = "avatar_provider_disabled") -> dict[str, object]:
    payload: dict[str, object] = {
        "interviewId": interview_id,
        "provider": "disabled" if fallback_from else (settings.provider or "disabled"),
        "ready": False,
        "status": "disabled",
        "reason": reason,
        "client": _avatar_client_config(settings),
    }
    if fallback_from:
        payload["providerStatus"] = "fallback"
        payload["fallbackFrom"] = fallback_from
    return payload


def avatar_session_response(payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    settings = load_avatar_settings()
    interview_id = _safe_str(payload.get("interviewId") or payload.get("sessionId") or "local-demo", 96)
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        return 400, {"error": "invalid_interview_id"}
    if settings.provider in {"", "disabled", "none", "fake"}:
        return 200, _disabled_avatar_payload(settings, interview_id)
    if settings.provider != "spatialreal":
        return 400, {"error": "unsupported_avatar_provider", "provider": settings.provider}
    if not settings.key_configured or not settings.app_configured:
        return 503, {
            "error": "avatar_provider_unavailable",
            "provider": "spatialreal",
            "ready": False,
            "reason": "missing_api_key_or_app_id",
            "client": _avatar_client_config(settings),
        }

    expires_at = int(time.time()) + settings.session_ttl_seconds
    session_token, error_payload = fetch_spatialreal_session_token(settings, expires_at)
    if error_payload is not None:
        if settings.failure_fallback_provider in {"disabled", "none"}:
            return 200, _disabled_avatar_payload(settings, interview_id, fallback_from="spatialreal", reason="avatar_provider_failed")
        return 502, error_payload
    assert session_token is not None
    return 200, {
        "interviewId": interview_id,
        "provider": "spatialreal",
        "ready": True,
        "status": "session_issued",
        "client": _avatar_client_config(settings, include_session_token=session_token, expires_at=expires_at),
    }


def question_response(payload: dict[str, Any]) -> tuple[int, dict[str, object]]:
    settings = load_llm_settings()
    interview_id = _safe_str(payload.get("interviewId") or "local-demo", 96)
    if not INTERVIEW_ID_PATTERN.fullmatch(interview_id):
        return 400, {"error": "invalid_interview_id"}
    try:
        turn_index = int(payload.get("turnIndex") or 1)
    except (TypeError, ValueError):
        return 400, {"error": "invalid_turn_index"}
    if turn_index < 1:
        return 400, {"error": "invalid_turn_index"}

    if settings.provider == "gemini":
        try:
            question = generate_gemini_question(settings, payload, turn_index)
            provider_status = "ok"
        except Exception:  # fail closed into explicit generic error; do not leak provider diagnostics
            return 502, {
                "error": "llm_provider_failed",
                "provider": "gemini",
                "model": settings.gemini_model,
                "message": "provider request failed",
            }
    elif settings.provider == "fake":
        question = fake_question(payload, turn_index)
        provider_status = "fake"
    else:
        return 400, {"error": "unsupported_llm_provider", "provider": settings.provider}

    return 200, {
        "interviewId": interview_id,
        "turnIndex": turn_index,
        "questionId": f"q_{interview_id}_{turn_index:04d}",
        "question": question.strip(),
        "provider": settings.provider,
        "providerStatus": provider_status,
        "model": settings.gemini_model if settings.provider == "gemini" else "fake-interviewer",
        "answerTurn": {
            "boundary": "manual_button",
            "enableEvent": "giljob:interviewer-question-ended",
            "startLabel": "답변 시작",
            "endLabel": "답변 종료",
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "GilJobV2AIEngine/0.2"

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> tuple[dict[str, Any] | None, str | None]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None, "invalid_content_length"
        if length > MAX_REQUEST_BYTES:
            return None, "request_too_large"
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return None, "invalid_json"
        if not isinstance(payload, dict):
            return None, "invalid_json"
        return payload, None

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path in {"/healthz", "/readyz"}:
            settings = load_llm_settings()
            tts_settings = load_tts_settings()
            avatar_settings = load_avatar_settings()
            self._json(200, {
                "service": SERVICE_NAME,
                "status": "ok",
                "mode": "interview-controller-scaffold",
                "llmProvider": settings.provider,
                "geminiModel": settings.gemini_model,
                "geminiKeyConfigured": settings.key_configured,
                "voiceProvider": tts_settings.provider,
                "elevenLabsKeyConfigured": tts_settings.elevenlabs_key_configured,
                "elevenLabsVoiceConfigured": tts_settings.elevenlabs_voice_configured,
                "elevenLabsModel": tts_settings.elevenlabs_model,
                "geminiTtsKeyConfigured": tts_settings.gemini_key_configured,
                "geminiTtsModel": tts_settings.gemini_model,
                "geminiTtsVoice": tts_settings.gemini_voice_name,
                "avatarProvider": avatar_settings.provider,
                "spatialRealKeyConfigured": avatar_settings.key_configured,
                "spatialRealAppConfigured": avatar_settings.app_configured,
                "spatialRealAvatarConfigured": avatar_settings.avatar_configured,
                "spatialRealAudioFormat": {
                    "channelCount": avatar_settings.audio_channel_count,
                    "sampleRate": avatar_settings.audio_sample_rate,
                    "sampleEncoding": "pcm_s16le",
                },
            })
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path in {"/interview/next-question", "/ai/interview/next-question"}:
            payload, error = self._read_json()
            if error:
                status = 413 if error == "request_too_large" else 400
                self._json(status, {"error": error})
                return
            assert payload is not None
            status, response = question_response(payload)
            self._json(status, response)
            return
        if self.path == "/avatar/session":
            payload, error = self._read_json()
            if error:
                status = 413 if error == "request_too_large" else 400
                self._json(status, {"error": error})
                return
            assert payload is not None
            status, response = avatar_session_response(payload)
            self._json(status, response)
            return
        if self.path == "/tts/synthesize":
            payload, error = self._read_json()
            if error:
                status = 413 if error == "request_too_large" else 400
                self._json(status, {"error": error})
                return
            assert payload is not None
            status, response = tts_response(payload)
            self._json(status, response)
            return
        if self.path == "/turn-evaluations":
            self._json(501, {"error": "not_implemented", "service": SERVICE_NAME})
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
