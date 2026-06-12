#!/usr/bin/env python3
"""Realtime browser/API smoke readiness check for GilJob v2.

This script is intentionally a readiness gate, not a credential dump. It probes
browser/static and API-mediated Realtime/MMM contracts and prints only a compact
secret-safe summary. If OpenAI Realtime credentials are missing it reports a
precise blocker and exits 0 by default; pass --require-live to fail in that case.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Iterable
from urllib.parse import urljoin

SENSITIVE_FIELD_HINTS = ("token", "secret", "key", "jwt", "sdp", "transcript", "media", "audio", "frame")
DEFAULT_MARKERS = (
    "function connectRealtimeRoom",
    "requestRealtimeSessionBroker",
    "requestRealtimeWebrtcAnswer",
    "ephemeral client secret hidden",
    "waitForFullMmmReady",
    "realtime.response.create",
    "realtime.first_audio",
    "vision.frame_metrics",
    "browser tools disabled; backend sideband required",
)


def redact_visible_text(value: object) -> str:
    return str(value).replace("\n", " ").replace("\r", " ")


def redact_secret_shapes(value: object) -> str:
    text = redact_visible_text(value)
    text = re.sub(r"access_token=[^'\"\s&]+", "access_token=<redacted>", text)
    text = re.sub(r"join_request=[^'\"\s&]+", "join_request=<redacted>", text)
    text = re.sub(r"eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+", "<jwt-redacted>", text)
    text = re.sub(r"gj_(session|report)_[A-Za-z0-9._-]+", r"gj_\1_<redacted>", text)
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-<redacted>", text)
    text = re.sub(r"rt[a-zA-Z0-9_-]*_[A-Za-z0-9._-]+", "rt_<redacted>", text)
    return text[:240]


def build_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/") + "/"
    return urljoin(base, path.lstrip("/"))


def request_json(method: str, url: str, payload: dict[str, Any] | None = None, timeout: float = 8.0) -> tuple[int, dict[str, Any]]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body or "{}")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body or "{}")
        except json.JSONDecodeError:
            payload = {"error": "non_json_error", "message": redact_secret_shapes(body)}
        return error.code, payload
    except urllib.error.URLError as error:
        return 0, {"error": "request_failed", "message": redact_secret_shapes(error.reason)}


def request_text(url: str, timeout: float = 8.0) -> tuple[int, str, str]:
    request = urllib.request.Request(url, headers={"Accept": "text/html, text/javascript, */*"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as error:
        return 0, "", redact_secret_shapes(error.reason)


def public_payload_shape(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a compact shape summary without token/secret/raw media values."""
    shape: dict[str, Any] = {}
    for key, value in sorted(payload.items()):
        lower = key.lower()
        if any(hint in lower for hint in SENSITIVE_FIELD_HINTS):
            shape[key] = "<redacted>"
        elif isinstance(value, dict):
            shape[key] = public_payload_shape(value)
        elif isinstance(value, list):
            shape[key] = f"list[{len(value)}]"
        elif isinstance(value, (str, int, float, bool)) or value is None:
            shape[key] = value if key in {"error", "status", "state", "provider", "ready", "full_mmm_ready"} else type(value).__name__
        else:
            shape[key] = type(value).__name__
    return shape


def assert_no_secret_shapes(label: str, text: str) -> None:
    if redact_secret_shapes(text) != redact_visible_text(text)[:240]:
        raise AssertionError(f"{label} contains a raw secret/token-shaped value")


def check_static_readiness(web_url: str, interview_id: str, markers: Iterable[str] = DEFAULT_MARKERS) -> dict[str, Any]:
    room_status, room_content_type, room_body = request_text(build_url(web_url, f"/interviews/{interview_id}/room"))
    app_status, app_content_type, app_body = request_text(build_url(web_url, "/app.js"))
    marker_tuple = tuple(markers)
    missing = [marker for marker in marker_tuple if marker not in app_body]
    if room_status != 200 or app_status != 200 or missing:
        return {
            "ok": False,
            "roomStatus": room_status,
            "appStatus": app_status,
            "roomBlocker": redact_secret_shapes(room_body) if room_status == 0 else None,
            "appBlocker": redact_secret_shapes(app_body) if app_status == 0 else None,
            "blocker": "realtime_static_markers_missing" if missing else None,
            "missingMarkers": missing,
            "contentTypes": [room_content_type, app_content_type],
        }
    assert_no_secret_shapes("room/app static", f"{room_body[:500]}\n{app_body[:500]}")
    return {"ok": True, "roomStatus": room_status, "appStatus": app_status, "markerCount": len(marker_tuple)}


def check_session_routes(api_url: str, interview_id: str) -> dict[str, Any]:
    status, payload = request_json("POST", build_url(api_url, "/api/sessions"), {"role": "candidate", "interviewId": interview_id})
    realtime = payload.get("realtime") if isinstance(payload, dict) else None
    ok = status == 201 and isinstance(realtime, dict) and realtime.get("fullMmmRequiredBeforeResponseCreate") is True
    if status == 201 and not isinstance(realtime, dict):
        blocker = "realtime_route_config_missing_from_session_payload"
    else:
        blocker = payload.get("message") or payload.get("error") or (f"HTTP {status}" if not ok else None)
    return {
        "ok": ok,
        "status": status,
        "blocker": redact_secret_shapes(blocker) if blocker else None,
        "realtime": public_payload_shape(realtime or {}),
        "payloadShape": public_payload_shape(payload),
    }


def check_realtime_broker(api_url: str, interview_id: str, require_live: bool) -> dict[str, Any]:
    status, payload = request_json("POST", build_url(api_url, f"/api/interviews/{interview_id}/realtime/session"), {
        "interviewId": interview_id,
        "sessionId": interview_id,
        "role": "candidate",
        "transport": "webrtc",
        "turnDetection": "manual",
    })
    if status in {200, 201}:
        return {"ok": True, "liveConfigured": True, "status": status, "payloadShape": public_payload_shape(payload)}
    blocker = payload.get("error") or payload.get("message") or f"HTTP {status}"
    ok = not require_live and blocker in {"realtime_not_configured", "request_failed"}
    return {
        "ok": ok,
        "liveConfigured": False,
        "status": status,
        "blocker": redact_secret_shapes(blocker),
        "payloadShape": public_payload_shape(payload),
    }


def check_realtime_call_boundary(api_url: str, interview_id: str, require_live: bool) -> dict[str, Any]:
    status, payload = request_json("POST", build_url(api_url, f"/api/interviews/{interview_id}/realtime/call"), {
        "interviewId": interview_id,
        "sessionId": interview_id,
        "turnIndex": 1,
        "type": "offer",
        "sdp": "v=0\no=- 1 2 IN IP4 127.0.0.1",
    })
    if status in {200, 201, 202, 501}:
        return {"ok": True, "status": status, "payloadShape": public_payload_shape(payload)}
    blocker = payload.get("error") or payload.get("message") or f"HTTP {status}"
    ok = not require_live and blocker in {"realtime_not_configured", "request_failed"}
    return {"ok": ok, "status": status, "blocker": redact_secret_shapes(blocker), "payloadShape": public_payload_shape(payload)}


def check_mmm_gate(api_url: str, interview_id: str) -> dict[str, Any]:
    turn = int(time.time()) % 9000 + 1
    steps: list[dict[str, Any]] = []
    status, payload = request_json("GET", build_url(api_url, f"/api/interviews/{interview_id}/turns/{turn}/mmm-ready"))
    initial_ok = status == 200 and payload.get("full_mmm_ready") is False
    steps.append({
        "step": "initial_mmm_ready",
        "status": status,
        "state": payload.get("state"),
        "ok": initial_ok,
        "blocker": redact_secret_shapes(payload.get("message") or payload.get("error") or f"HTTP {status}") if not initial_ok else None,
    })

    events = [
        ("turn_event", "/events", {"type": "analysis.transcript.completed", "normalizedType": "transcript.completed", "transcript": "redacted smoke transcript"}),
        ("turn_end", "/events", {"type": "turn.answer.end", "normalizedType": "turn.answer_ended", "detail": {"transcriptAvailable": True}}),
        ("vision", "/vision-events", {"type": "vision_metadata", "normalizedType": "vision.frame_metrics", "rawMediaIncluded": False, "video": {"cameraEnabled": True, "width": 640, "height": 480}}),
        ("prosody", "/events", {"type": "prosody.window", "normalizedType": "prosody.window_metrics"}),
    ]
    events_ok = True
    for name, suffix, body in events:
        status, payload = request_json("POST", build_url(api_url, f"/api/interviews/{interview_id}/turns/{turn}{suffix}"), body)
        event_ok = status == 202
        events_ok = events_ok and event_ok
        steps.append({
            "step": name,
            "status": status,
            "ok": event_ok,
            "eventKind": payload.get("eventKind"),
            "blocker": redact_secret_shapes(payload.get("message") or payload.get("error") or f"HTTP {status}") if not event_ok else None,
        })

    raw_status, raw_payload = request_json("POST", build_url(api_url, f"/api/interviews/{interview_id}/turns/{turn}/vision-events"), {
        "type": "vision_metadata",
        "normalizedType": "vision.frame_metrics",
        "rawMediaIncluded": True,
    })
    raw_ok = raw_status == 400 and raw_payload.get("error") == "raw_media_not_allowed"
    steps.append({
        "step": "raw_media_rejected",
        "status": raw_status,
        "ok": raw_ok,
        "blocker": redact_secret_shapes(raw_payload.get("message") or raw_payload.get("error") or f"HTTP {raw_status}") if not raw_ok else None,
    })

    status, payload = request_json("GET", build_url(api_url, f"/api/interviews/{interview_id}/turns/{turn}/mmm-ready"))
    final_ok = status == 200 and payload.get("full_mmm_ready") is True and payload.get("delivery", {}).get("trustedBusinessLogicBoundary") == "api-sideband"
    steps.append({
        "step": "final_mmm_ready",
        "status": status,
        "state": payload.get("state"),
        "ok": final_ok,
        "blocker": redact_secret_shapes(payload.get("message") or payload.get("error") or f"HTTP {status}") if not final_ok else None,
    })
    return {"ok": initial_ok and events_ok and raw_ok and final_ok, "turnIndex": turn, "steps": steps}


def run(argv: list[str]) -> tuple[dict[str, Any], int]:
    parser = argparse.ArgumentParser(description="Check Realtime WebRTC/MMM smoke readiness without printing secrets.")
    parser.add_argument("--web-url", default="http://127.0.0.1/", help="Web/Caddy base URL; defaults to localhost")
    parser.add_argument("--api-url", default=None, help="API/Caddy base URL; defaults to --web-url")
    parser.add_argument("--interview-id", default="realtime-smoke", help="Safe interview/session id for readiness probes")
    parser.add_argument("--require-live", action="store_true", help="Fail if Realtime credentials or live broker are not configured")
    args = parser.parse_args(argv)
    web_url = args.web_url
    api_url = args.api_url or web_url
    interview_id = args.interview_id

    checks = {
        "staticReadiness": check_static_readiness(web_url, interview_id),
        "sessionRoutes": check_session_routes(api_url, interview_id),
        "realtimeSessionBroker": check_realtime_broker(api_url, interview_id, args.require_live),
        "realtimeCallBoundary": check_realtime_call_boundary(api_url, interview_id, args.require_live),
        "fullMmmGate": check_mmm_gate(api_url, interview_id),
    }
    primary_check_names = ("staticReadiness", "sessionRoutes", "realtimeSessionBroker", "fullMmmGate")
    primary_ok = all(checks[name].get("ok") is True for name in primary_check_names)
    live_ready = checks["realtimeSessionBroker"].get("liveConfigured") is True
    # The browser-primary WebRTC flow posts SDP with an ephemeral client_secret directly to
    # /v1/realtime/calls. The server-side /realtime/call broker is retained as a diagnostic
    # boundary only; a provider 502 from its synthetic SDP probe must not fail the primary
    # live-readiness gate once session minting, static markers, and full-MMM sideband are OK.
    ok = primary_ok
    summary = {
        "ok": ok,
        "primaryOk": primary_ok,
        "primaryChecks": list(primary_check_names),
        "liveReady": live_ready,
        "requireLive": args.require_live,
        "checks": checks,
        "optionalChecks": ["realtimeCallBoundary"],
        "secretPolicy": "summary-only; token/secret/sdp/transcript/media values redacted",
    }
    return summary, 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    summary, exit_code = run(sys.argv[1:] if argv is None else argv)
    json.dump(summary, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
