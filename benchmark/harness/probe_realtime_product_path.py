#!/usr/bin/env python3
"""Probe PR #15 Realtime broker/MMM gate routes and emit FD latency timestamps.

The script is a command adapter for run_fdbench_v1_latency.py. It does not
perform browser WebRTC SDP attach or receive model deltas; use it to measure the
API-mediated Realtime session broker and MMM readiness gate against a running
PR #15-or-newer service.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1")
    parser.add_argument("--interview-prefix", default="fdbench-pr15")
    parser.add_argument("--turn-index", type=int, default=1)
    parser.add_argument("--timeout-s", type=float, default=10.0)
    parser.add_argument(
        "--assume-response-create-after-gate",
        action="store_true",
        help="Emit t_response_create_s at gate pass time. Use only for dry-run plumbing, not product evidence.",
    )
    return parser.parse_args()


def safe_interview_id(prefix: str, example_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{prefix}-{example_id}").strip("-")
    if not value or not value[0].isalnum():
        value = f"bench-{value}"
    return value[:96]


def call_json(method: str, url: str, body: dict[str, Any] | None, timeout_s: float) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body or {}).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return int(response.status), payload if isinstance(payload, dict) else {}
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {}
        return int(exc.code), payload if isinstance(payload, dict) else {}


def timeline(base_wall_s: float, user_end_s: float) -> float:
    return user_end_s + (time.perf_counter() - base_wall_s)


def main() -> int:
    args = parse_args()
    payload = json.loads(sys.stdin.read() or "{}")
    example_id = str(payload.get("example_id") or "example")
    user_end_s = float(payload["t_user_audio_end_s"])
    interview_id = safe_interview_id(args.interview_prefix, example_id)
    base_url = args.base_url.rstrip("/")
    base_wall_s = time.perf_counter()

    row: dict[str, Any] = {
        "adapter": "realtime-api-sideband-probe",
        "adapter_boundary": "realtime-mmm-gate",
        "example_id": example_id,
        "full_product_path_observed": False,
        "interview_id": interview_id,
        "raw_media_included": False,
        "t_user_audio_end_s": user_end_s,
    }
    statuses: dict[str, int] = {}

    status, session = call_json(
        "POST",
        f"{base_url}/api/interviews/{interview_id}/realtime/session",
        {"benchmark": "fdbench-v1-latency", "exampleId": example_id},
        args.timeout_s,
    )
    statuses["realtime_session"] = status
    if status < 500:
        row["t_realtime_session_ready_s"] = timeline(base_wall_s, user_end_s)
    client_secret = session.get("client_secret")
    row["client_secret_shape_observed"] = isinstance(client_secret, dict) and bool(client_secret.get("value"))
    row["realtime_session_contract_observed"] = bool(
        status < 500
        and (
            row["client_secret_shape_observed"]
            or isinstance(session.get("webrtc"), dict)
            or isinstance(session.get("delivery"), dict)
        )
    )
    row["standard_openai_key_observed"] = False
    row["sdp_body_observed"] = False

    event_base = f"{base_url}/api/interviews/{interview_id}/turns/{args.turn_index}"
    events = [
        (
            "transcript_completed",
            "/events",
            {
                "type": "transcript.completed",
                "transcript": "benchmark answer transcript",
                "rawMediaIncluded": False,
            },
        ),
        (
            "answer_end",
            "/events",
            {
                "type": "turn.answer.end",
                "detail": {"transcriptAvailable": True},
                "rawMediaIncluded": False,
            },
        ),
        (
            "prosody",
            "/events",
            {
                "type": "prosody.window_metrics",
                "rawMediaIncluded": False,
            },
        ),
        (
            "vision",
            "/vision-events",
            {
                "type": "vision.frame_metrics",
                "rawFrameIncluded": False,
                "rawMediaIncluded": False,
            },
        ),
    ]
    for name, suffix, event in events:
        status, _ = call_json("POST", f"{event_base}{suffix}", event, args.timeout_s)
        statuses[name] = status
        if name == "answer_end":
            row["t_realtime_input_commit_s"] = timeline(base_wall_s, user_end_s)
        if name == "transcript_completed":
            row["t_transcript_ready_s"] = timeline(base_wall_s, user_end_s)

    status, readiness = call_json("GET", f"{event_base}/mmm-ready", None, args.timeout_s)
    statuses["mmm_ready"] = status
    row["full_mmm_ready"] = bool(readiness.get("full_mmm_ready"))
    row["mmm_ready_reason"] = str(readiness.get("reason") or "")
    if row["full_mmm_ready"]:
        row["t_mmm_ready_s"] = timeline(base_wall_s, user_end_s)
        if args.assume_response_create_after_gate:
            row["t_response_create_s"] = row["t_mmm_ready_s"]
            row["response_create_assumed_not_observed"] = True
    row["route_statuses"] = statuses

    print(json.dumps(row, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
