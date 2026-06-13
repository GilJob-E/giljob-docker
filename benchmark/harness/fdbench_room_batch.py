#!/usr/bin/env python3
"""Drive fdbench_room_minimal.mjs over a seeded random sample of FD-bench
turn-taking examples and summarize the latencies. Sequential on purpose:
parallel sessions would contaminate a latency benchmark."""

from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, default=Path("benchmark/data/raw/fd-bench-v1-v1_5/v1.0/candor_turn_taking"))
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-url", default="http://127.0.0.1:8081")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prefix", default="fdbench-min")
    parser.add_argument("--timeout-s", type=float, default=240.0)
    return parser.parse_args()


def stat(rows: list[dict], key: str) -> dict | None:
    values = sorted(r[key] for r in rows if isinstance(r.get(key), (int, float)))
    if not values:
        return None
    return {
        "n": len(values),
        "mean": round(statistics.mean(values)),
        "median": round(statistics.median(values)),
        "p95": values[min(len(values) - 1, round((len(values) - 1) * 0.95))],
        "min": values[0],
        "max": values[-1],
    }


def main() -> int:
    args = parse_args()
    harness = Path(__file__).resolve().parent / "fdbench_room_minimal.mjs"
    examples = sorted(
        (d for d in args.task_dir.iterdir() if (d / "input.wav").exists() and (d / "turn_taking.json").exists()),
        key=lambda d: d.name,
    )
    sample = random.Random(args.seed).sample(examples, args.count)
    run_dir = Path("benchmark/runs/01-fd-bench-v1-turn-taking-latency") / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for example in sample:
        turn_end = float(json.loads((example / "turn_taking.json").read_text())[0]["timestamp"][0])
        cmd = [
            "node", str(harness),
            "--audio", str(example / "input.wav"),
            "--turn-end-s", str(turn_end),
            "--base-url", args.base_url,
            "--interview-id", f"{args.prefix}-{example.name}",
        ]
        row: dict = {}
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout_s)
            row = json.loads(proc.stdout) if proc.returncode == 0 and proc.stdout.strip() else {"error": (proc.stderr or "no output")[:300]}
        except subprocess.TimeoutExpired:
            row = {"error": "timeout"}
        except json.JSONDecodeError:
            row = {"error": "invalid json from harness"}
        row["example_id"] = example.name
        row["turn_end_s"] = turn_end
        rows.append(row)
        with (run_dir / "rows.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{example.name}: first_audio={row.get('first_audio_ms')} gate={row.get('full_mmm_ready_ms')} err={row.get('error')}", flush=True)

    responded = [r for r in rows if isinstance(r.get("first_audio_ms"), (int, float))]
    summary = {
        "run_id": args.run_id,
        "seed": args.seed,
        "count": len(rows),
        "responded": len(responded),
        "no_response_examples": [r["example_id"] for r in rows if r not in responded],
        "first_audio_after_click_ms": stat(rows, "first_audio_after_click_ms"),
        "full_mmm_ready_after_click_ms": stat(rows, "full_mmm_ready_after_click_ms"),
        "response_create_after_click_ms": stat(rows, "response_create_after_click_ms"),
        "next_question_started_after_click_ms": stat(rows, "next_question_started_after_click_ms"),
        "first_audio_ms": stat(rows, "first_audio_ms"),
        "full_mmm_ready_ms": stat(rows, "full_mmm_ready_ms"),
        "response_create_ms": stat(rows, "response_create_ms"),
        "next_question_started_ms": stat(rows, "next_question_started_ms"),
        "measurement_note": (
            "Minimal room runner, product path through real room UI. Primary reference = 답변 종료 click "
            "(*_after_click_ms); speech-end-relative values (*_ms, includes the harness click pad) kept for "
            "reference. Avatar SDK blocked (excluded boundary); mic = WebAudio-injected clip + room-tone tail; "
            "답변 종료 click at turn end + pad (default 3s, VAD window for single-segment answers)."
        ),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
