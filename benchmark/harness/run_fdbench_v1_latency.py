#!/usr/bin/env python3
"""Run FD-bench V1 turn-taking latency as a diagnostic/provisional benchmark."""

from __future__ import annotations

import argparse
import json
import os
import random
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_THIS_FILE = Path(__file__).resolve()
for _parent in _THIS_FILE.parents:
    if (_parent / "AGENTS.md").exists():
        sys.path.insert(0, str(_parent))
        break

from benchmark.harness import common


BENCHMARK_ID = "01-fd-bench-v1-turn-taking-latency"


def parse_args() -> argparse.Namespace:
    repo_root = common.repo_root_from_file(__file__)
    default_task_dir = repo_root / "benchmark/data/raw/fd-bench-v1-v1_5/v1.0/candor_turn_taking"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, default=default_task_dir)
    parser.add_argument("--run-root", type=Path, default=repo_root / "benchmark/runs")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--sample-seed", type=int, default=None)
    parser.add_argument(
        "--adapter",
        choices=("simulated-latency", "existing-jsonl", "command"),
        default="simulated-latency",
    )
    parser.add_argument("--simulated-latency-ms", type=float, default=750.0)
    parser.add_argument("--timestamps-jsonl", type=Path, default=None)
    parser.add_argument(
        "--command",
        default=None,
        help="Command adapter. JSON with audio path and user turn end timestamp is passed on stdin.",
    )
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--model-label", default=None)
    parser.add_argument("--notes", action="append", default=[])
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    import hashlib

    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_examples(task_dir: Path) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for folder in sorted(task_dir.iterdir(), key=lambda p: p.name):
        if not folder.is_dir():
            continue
        input_wav = folder / "input.wav"
        annotation_path = folder / "turn_taking.json"
        if not input_wav.exists() or not annotation_path.exists():
            continue
        annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
        if not annotation or "timestamp" not in annotation[0]:
            raise ValueError(f"{annotation_path}: missing timestamp annotation")
        timestamp = annotation[0]["timestamp"]
        user_turn_end_s = float(timestamp[0])
        examples.append(
            {
                "annotation": annotation,
                "annotation_path": annotation_path,
                "audio_byte_count": input_wav.stat().st_size,
                "audio_path": input_wav,
                "audio_sha256": file_sha256(input_wav),
                "example_id": folder.name,
                "user_turn_end_s": user_turn_end_s,
            }
        )
    return examples


def select_examples(examples: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.limit <= 0:
        raise ValueError("--limit must be positive")
    if args.offset < 0:
        raise ValueError("--offset must be non-negative")
    selected = examples[:]
    if args.sample_seed is not None:
        rng = random.Random(args.sample_seed)
        rng.shuffle(selected)
    return selected[args.offset : args.offset + args.limit]


def load_timestamp_mapping(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_audio_path: dict[str, dict[str, Any]] = {}
    for row in common.read_jsonl(path):
        for key_field in ("example_id", "sample_id", "id"):
            if key_field in row:
                by_id[str(row[key_field])] = row
        if "audio_path" in row:
            by_audio_path[str(row["audio_path"])] = row
    return by_id, by_audio_path


def run_command_adapter(command: str, payload: dict[str, Any], timeout_s: float, env_extra: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    argv = shlex.split(command)
    if not argv:
        raise ValueError("--command must not be empty for command adapter")
    env = os.environ.copy()
    env.update(env_extra)
    started = time.perf_counter()
    completed = subprocess.run(
        argv,
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
        env=env,
    )
    wall_ms = (time.perf_counter() - started) * 1000.0
    if completed.returncode != 0:
        stderr = completed.stderr or ""
        return {}, {
            "return_code": completed.returncode,
            "stderr_sha256": common.sha256_text(stderr),
            "stderr_preview_redacted": common.redact_obvious_secrets(stderr[:500]),
            "adapter_wall_ms": round(wall_ms, 3),
        }
    stdout = completed.stdout.strip()
    if not stdout:
        return {}, None
    try:
        value = json.loads(common.redact_obvious_secrets(stdout))
    except json.JSONDecodeError as exc:
        return {}, {
            "error": "invalid_json_from_command",
            "stdout_sha256": common.sha256_text(stdout),
            "message": str(exc),
            "adapter_wall_ms": round(wall_ms, 3),
        }
    if not isinstance(value, dict):
        return {}, {
            "error": "command_json_must_be_object",
            "adapter_wall_ms": round(wall_ms, 3),
        }
    value["adapter_wall_ms"] = round(wall_ms, 3)
    return value, None


def timestamp_value(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in row and row[key] is not None:
            return float(row[key])
    return None


def compute_latency_row(example: dict[str, Any], timestamp_row: dict[str, Any], adapter: str) -> dict[str, Any]:
    user_end = float(
        timestamp_value(timestamp_row, "t_user_audio_end_s", "t_user_audio_end", "user_turn_end_s")
        or example["user_turn_end_s"]
    )
    response_start = timestamp_value(
        timestamp_row,
        "t_tts_first_audio_s",
        "t_tts_first_audio",
        "model_response_start_s",
        "t_model_response_start_s",
    )
    no_response = response_start is None
    row: dict[str, Any] = {
        "adapter": adapter,
        "example_id": example["example_id"],
        "no_response": no_response,
        "t_user_audio_end_s": user_end,
    }
    if response_start is not None:
        row["t_model_response_start_s"] = response_start
        row["first_response_latency_ms"] = round((response_start - user_end) * 1000.0, 3)

    transcript_ready = timestamp_value(timestamp_row, "t_transcript_ready_s", "t_transcript_ready")
    llm_request = timestamp_value(timestamp_row, "t_llm_request_s", "t_llm_request")
    llm_done = timestamp_value(timestamp_row, "t_llm_done_s", "t_llm_done")
    response_done = timestamp_value(timestamp_row, "t_response_done_s", "t_response_done")
    if transcript_ready is not None:
        row["transcript_flush_latency_ms"] = round((transcript_ready - user_end) * 1000.0, 3)
    if llm_request is not None and llm_done is not None:
        row["llm_latency_ms"] = round((llm_done - llm_request) * 1000.0, 3)
    if llm_done is not None and response_start is not None:
        row["tts_first_audio_latency_ms"] = round((response_start - llm_done) * 1000.0, 3)
    if response_done is not None:
        row["end_to_end_latency_ms"] = round((response_done - user_end) * 1000.0, 3)
    return row


def make_timestamp_rows(
    args: argparse.Namespace,
    selected: list[dict[str, Any]],
    run_dir: Path,
    repo_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    timestamp_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    by_audio_path: dict[str, dict[str, Any]] = {}

    if args.adapter == "existing-jsonl":
        if args.timestamps_jsonl is None:
            raise ValueError("--timestamps-jsonl is required for existing-jsonl adapter")
        by_id, by_audio_path = load_timestamp_mapping(args.timestamps_jsonl)
    elif args.adapter == "command" and not args.command:
        raise ValueError("--command is required for command adapter")

    for ordinal, example in enumerate(selected):
        example_id = str(example["example_id"])
        relative_audio_path = common.relative_to_repo(Path(example["audio_path"]), repo_root)
        if args.adapter == "simulated-latency":
            response_start = example["user_turn_end_s"] + args.simulated_latency_ms / 1000.0
            timestamp_row = {
                "adapter": args.adapter,
                "example_id": example_id,
                "model_response_start_s": response_start,
                "t_user_audio_end_s": example["user_turn_end_s"],
            }
        elif args.adapter == "existing-jsonl":
            if example_id in by_id:
                timestamp_row = dict(by_id[example_id])
            elif relative_audio_path in by_audio_path:
                timestamp_row = dict(by_audio_path[relative_audio_path])
            else:
                timestamp_row = {"adapter": args.adapter, "example_id": example_id}
                errors.append(
                    {
                        "adapter": args.adapter,
                        "audio_sha256": example["audio_sha256"],
                        "error": "missing_timestamps_for_example",
                        "example_id": example_id,
                    }
                )
        elif args.adapter == "command":
            payload = {
                "benchmark_id": BENCHMARK_ID,
                "example_id": example_id,
                "audio_path": str(example["audio_path"]),
                "audio_path_relative": relative_audio_path,
                "annotation": example["annotation"],
                "t_user_audio_end_s": example["user_turn_end_s"],
            }
            timestamp_row, error = run_command_adapter(
                args.command,
                payload,
                args.timeout_s,
                {
                    "BENCHMARK_ID": BENCHMARK_ID,
                    "BENCHMARK_EXAMPLE_ID": example_id,
                    "BENCHMARK_ORDINAL": str(ordinal),
                    "BENCHMARK_RUN_DIR": str(run_dir),
                    "FDBENCH_AUDIO_PATH": str(example["audio_path"]),
                    "FDBENCH_USER_TURN_END_S": str(example["user_turn_end_s"]),
                },
            )
            timestamp_row.setdefault("adapter", args.adapter)
            timestamp_row.setdefault("example_id", example_id)
            if error:
                errors.append({"adapter": args.adapter, "example_id": example_id, **error})
        else:
            raise ValueError(f"Unsupported adapter: {args.adapter}")
        timestamp_rows.append(timestamp_row)
    return timestamp_rows, errors


def summarize_latencies(latency_rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [row["first_response_latency_ms"] for row in latency_rows if not row["no_response"]]
    no_response_count = sum(1 for row in latency_rows if row["no_response"])

    def percentile(sorted_values: list[float], pct: float) -> float | None:
        if not sorted_values:
            return None
        index = min(len(sorted_values) - 1, int(round((len(sorted_values) - 1) * pct)))
        return sorted_values[index]

    sorted_values = sorted(values)
    mean = sum(values) / len(values) if values else None
    median = percentile(sorted_values, 0.5)
    p95 = percentile(sorted_values, 0.95)
    total = len(latency_rows)
    return {
        "evaluator": "fixed-timestamp-latency-v0",
        "limitations": [
            "This is a diagnostic turn-based latency row, not an official full-duplex score.",
            "Adapter timestamps must use the same monotonic clock convention per run.",
            "simulated-latency adapter only verifies artifact plumbing.",
        ],
        "latency_mean_ms": round(mean, 3) if mean is not None else None,
        "latency_median_ms": median,
        "latency_p95_ms": p95,
        "no_response_count": no_response_count,
        "no_response_rate": float(no_response_count / total) if total else 0.0,
        "response_count": len(values),
        "total": total,
    }


def main() -> int:
    args = parse_args()
    repo_root = common.repo_root_from_file(__file__)
    run_id = args.run_id or common.default_run_id(args.adapter)
    run_dir = common.ensure_run_dir(args.run_root, BENCHMARK_ID, run_id)

    manifest_path = run_dir / "manifest.json"
    inputs_path = run_dir / "inputs.jsonl"
    timestamp_path = run_dir / "responses.jsonl"
    latency_path = run_dir / "latency.jsonl"
    errors_path = run_dir / "errors.jsonl"
    metrics_path = run_dir / "metrics.json"

    manifest = {
        "schema_version": common.SCHEMA_VERSION,
        "benchmark_id": BENCHMARK_ID,
        "run_id": run_id,
        "created_at_utc": common.utc_now_iso(),
        "status": "running",
        "pipeline_status": "provisional",
        "adapter": {
            "type": args.adapter,
            "model_label": args.model_label,
            "command": "[provided]" if args.command else None,
        },
        "dataset": {
            "task_dir": common.relative_to_repo(args.task_dir, repo_root),
            "limit": args.limit,
            "offset": args.offset,
            "sample_seed": args.sample_seed,
        },
        "artifacts": {
            "inputs": "inputs.jsonl",
            "responses": "responses.jsonl",
            "latency": "latency.jsonl",
            "errors": "errors.jsonl",
            "metrics": "metrics.json",
            "evaluation_dir": "evaluation",
        },
        "notes": args.notes,
    }
    common.write_json(manifest_path, manifest)

    try:
        examples = load_examples(args.task_dir)
        selected = select_examples(examples, args)
        if not selected:
            raise ValueError("No FD-bench V1 turn-taking examples selected")
        input_rows = []
        audio_byte_total = 0
        for example in selected:
            audio_byte_total += int(example["audio_byte_count"])
            input_rows.append(
                {
                    "annotation": example["annotation"],
                    "annotation_path": common.relative_to_repo(Path(example["annotation_path"]), repo_root),
                    "audio_byte_count": example["audio_byte_count"],
                    "audio_path": common.relative_to_repo(Path(example["audio_path"]), repo_root),
                    "audio_sha256": example["audio_sha256"],
                    "benchmark_id": BENCHMARK_ID,
                    "example_id": example["example_id"],
                    "t_user_audio_end_s": example["user_turn_end_s"],
                }
            )
        common.write_jsonl(inputs_path, input_rows)

        timestamp_rows, errors = make_timestamp_rows(args, selected, run_dir, repo_root)
        common.write_jsonl(timestamp_path, timestamp_rows)
        latency_rows = [
            compute_latency_row(example, timestamp_row, args.adapter)
            for example, timestamp_row in zip(selected, timestamp_rows)
        ]
        common.write_jsonl(latency_path, latency_rows)
        common.write_jsonl(errors_path, errors)

        metrics = {
            "schema_version": "giljob-benchmark-metrics/v0",
            "benchmark_id": BENCHMARK_ID,
            "run_id": run_id,
            "adapter": args.adapter,
            "audio_byte_total": audio_byte_total,
            "error_count": len(errors),
            "example_count": len(selected),
            "measurement_label": "GilJob v2 cascaded/turn-based adapter",
            "response_empty_count": sum(1 for row in latency_rows if row["no_response"]),
            "evaluation": {
                "latency": summarize_latencies(latency_rows),
            },
        }
        common.write_json(metrics_path, metrics)

        manifest["completed_at_utc"] = common.utc_now_iso()
        manifest["status"] = "completed_with_errors" if errors else "completed"
        manifest["summary"] = {
            "example_count": len(selected),
            "error_count": len(errors),
            "metrics_path": "metrics.json",
        }
        common.write_json(manifest_path, manifest)
    except Exception as exc:
        common.append_jsonl(
            errors_path,
            {
                "error": type(exc).__name__,
                "message": common.redact_obvious_secrets(str(exc)),
                "stage": "run_fdbench_v1_latency",
            },
        )
        manifest["completed_at_utc"] = common.utc_now_iso()
        manifest["status"] = "failed"
        manifest["failure"] = {
            "type": type(exc).__name__,
            "message": common.redact_obvious_secrets(str(exc)),
        }
        common.write_json(manifest_path, manifest)
        print(f"failed: {run_dir}", file=sys.stderr)
        raise

    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
