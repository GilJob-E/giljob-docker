#!/usr/bin/env python3
"""Minimal dummy analysis-engine for smoke testing.

Accepts POST /realtime/turn-events (202) and returns a canned
GET /realtime/turn-results payload that satisfies the report pipeline.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(os.getenv("ANALYSIS_ENGINE_PORT", "8200"))

CANNED_RESULT = {
    "transcriptSignals": {
        "speech_rate_syllables_per_sec": 5.2,
        "pitch_hz": 215.0,
        "pause_count_long": 1,
    },
    "visionSignals": {
        "smile_ratio": 0.18,
        "gaze_off_ratio": 0.12,
        "blink_count": 3,
        "face_seen_ratio": 0.88,
    },
    "prosodySignals": {"speech_duration_ms": 4800},
    "candidateSafePromptFragment": {
        "text": "[smoke-test dummy] 답변이 명확하고 구조적으로 전달되었습니다."
    },
    "status": "ready",
    "source": "dummy-analysis-engine",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "DummyAnalysisEngine/1.0"

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: D102
        print(f"[dummy-ae] {fmt % args}")

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/realtime/turn-events":
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)  # drain body
            self._json(202, {"accepted": True, "source": "dummy-analysis-engine"})
        else:
            self._json(404, {"error": "not_found"})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/realtime/turn-results":
            qs = parse_qs(parsed.query)
            interview_id = qs.get("interviewId", [None])[0]
            turn_index_raw = qs.get("turnIndex", [None])[0]
            result = dict(CANNED_RESULT)
            if interview_id:
                result["interviewId"] = interview_id
            if turn_index_raw is not None:
                try:
                    result["turnIndex"] = int(turn_index_raw)
                except ValueError:
                    pass
            self._json(200, result)
        elif path == "/health":
            self._json(200, {"status": "ok", "engine": "dummy"})
        else:
            self._json(404, {"error": "not_found"})


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[dummy-ae] listening on :{PORT}")
    server.serve_forever()
