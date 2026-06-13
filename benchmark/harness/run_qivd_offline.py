#!/usr/bin/env python3
"""Run QIVD as a provisional offline video-QA benchmark."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import random
import re
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


BENCHMARK_ID = "04-qivd"


def parse_args() -> argparse.Namespace:
    repo_root = common.repo_root_from_file(__file__)
    default_root = repo_root / "benchmark/data/raw/qivd"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=default_root)
    parser.add_argument("--labels", type=Path, default=default_root / "labels.json")
    parser.add_argument("--videos-dir", type=Path, default=default_root / "videos")
    parser.add_argument("--run-root", type=Path, default=repo_root / "benchmark/runs")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--sample-seed", type=int, default=None)
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument(
        "--adapter",
        choices=("placeholder-empty", "short-answer-oracle", "existing-jsonl", "command"),
        default="placeholder-empty",
    )
    parser.add_argument("--responses-jsonl", type=Path, default=None)
    parser.add_argument(
        "--command",
        default=None,
        help="Command adapter. JSON with video path, question, timestamp, and category is passed on stdin.",
    )
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--model-label", default=None)
    parser.add_argument("--notes", action="append", default=[])
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def parse_timestamp(value: str) -> float | None:
    if not value:
        return None
    parts = value.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(value)
    except ValueError:
        return None


def load_labels(labels_path: Path, videos_dir: Path) -> list[dict[str, Any]]:
    rows = json.loads(labels_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"{labels_path}: expected list")
    required = {"id", "video", "question", "answer", "short_answer", "timestamp", "category"}
    for index, row in enumerate(rows):
        missing = required - row.keys()
        if missing:
            raise ValueError(f"{labels_path}:{index + 1}: missing fields {sorted(missing)}")
        video_path = videos_dir / str(row["video"])
        if not video_path.exists():
            raise FileNotFoundError(f"Missing QIVD video for id={row['id']}: {video_path}")
        row["video_path"] = video_path
        row["video_byte_count"] = video_path.stat().st_size
        row["video_sha256"] = file_sha256(video_path)
        row["reference_timestamp_s"] = parse_timestamp(str(row["timestamp"]))
    return rows


def select_rows(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    selected = rows
    categories = set(args.category)
    if categories:
        selected = [row for row in selected if row["category"] in categories]
    if args.limit <= 0:
        raise ValueError("--limit must be positive")
    if args.offset < 0:
        raise ValueError("--offset must be non-negative")
    selected = selected[:]
    if args.sample_seed is not None:
        rng = random.Random(args.sample_seed)
        rng.shuffle(selected)
    return selected[args.offset : args.offset + args.limit]


def load_response_mapping(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_video: dict[str, dict[str, Any]] = {}
    for row in common.read_jsonl(path):
        if "response" not in row and "answer" not in row:
            raise ValueError(f"{path}: every row must include response or answer")
        for key_field in ("example_id", "id"):
            if key_field in row:
                by_id[str(row[key_field])] = row
        if "video" in row:
            by_video[str(row["video"])] = row
        if "video_path" in row:
            by_video[str(row["video_path"])] = row
    return by_id, by_video


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
        return {"response": ""}, None
    try:
        value = json.loads(common.redact_obvious_secrets(stdout))
        if isinstance(value, dict):
            value["adapter_wall_ms"] = round(wall_ms, 3)
            return value, None
    except json.JSONDecodeError:
        pass
    return {"response": common.redact_obvious_secrets(stdout), "adapter_wall_ms": round(wall_ms, 3)}, None


def response_text(row: dict[str, Any]) -> str:
    return str(row.get("response", row.get("answer", "")))


def make_responses(
    args: argparse.Namespace,
    selected: list[dict[str, Any]],
    run_dir: Path,
    repo_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    responses: list[dict[str, Any]] = []
    latencies: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    by_video: dict[str, dict[str, Any]] = {}

    if args.adapter == "existing-jsonl":
        if args.responses_jsonl is None:
            raise ValueError("--responses-jsonl is required for existing-jsonl adapter")
        by_id, by_video = load_response_mapping(args.responses_jsonl)
    elif args.adapter == "command" and not args.command:
        raise ValueError("--command is required for command adapter")

    for ordinal, row in enumerate(selected):
        example_id = str(row["id"])
        video_path = Path(row["video_path"])
        relative_video_path = common.relative_to_repo(video_path, repo_root)
        started_at = common.utc_now_iso()
        started = time.perf_counter()
        error: dict[str, Any] | None = None

        if args.adapter == "placeholder-empty":
            adapter_row: dict[str, Any] = {"response": ""}
        elif args.adapter == "short-answer-oracle":
            adapter_row = {"response": row["short_answer"], "answer_start_s": row["reference_timestamp_s"]}
        elif args.adapter == "existing-jsonl":
            if example_id in by_id:
                adapter_row = dict(by_id[example_id])
            elif row["video"] in by_video:
                adapter_row = dict(by_video[row["video"]])
            elif relative_video_path in by_video:
                adapter_row = dict(by_video[relative_video_path])
            else:
                adapter_row = {"response": ""}
                error = {"error": "missing_response_for_qivd_example"}
        elif args.adapter == "command":
            payload = {
                "benchmark_id": BENCHMARK_ID,
                "example_id": row["id"],
                "video": row["video"],
                "video_path": str(video_path),
                "video_path_relative": relative_video_path,
                "question": row["question"],
                "category": row["category"],
                "reference_timestamp_s": row["reference_timestamp_s"],
            }
            adapter_row, error = run_command_adapter(
                args.command,
                payload,
                args.timeout_s,
                {
                    "BENCHMARK_ID": BENCHMARK_ID,
                    "BENCHMARK_EXAMPLE_ID": example_id,
                    "BENCHMARK_ORDINAL": str(ordinal),
                    "BENCHMARK_RUN_DIR": str(run_dir),
                    "QIVD_VIDEO_PATH": str(video_path),
                    "QIVD_CATEGORY": str(row["category"]),
                },
            )
        else:
            raise ValueError(f"Unsupported adapter: {args.adapter}")

        response = response_text(adapter_row)
        contained_obvious_secret = common.contains_obvious_secret(response)
        if contained_obvious_secret:
            response = common.redact_obvious_secrets(response)

        wall_ms = (time.perf_counter() - started) * 1000.0
        responses.append(
            {
                "adapter": args.adapter,
                "answer_start_s": adapter_row.get("answer_start_s"),
                "category": row["category"],
                "completed_at_utc": common.utc_now_iso(),
                "example_id": row["id"],
                "model_label": args.model_label,
                "question": row["question"],
                "response": response,
                "response_had_obvious_secret_redacted": contained_obvious_secret,
                "started_at_utc": started_at,
                "video": row["video"],
                "video_path": relative_video_path,
            }
        )
        latencies.append(
            {
                "adapter": args.adapter,
                "adapter_wall_ms": round(wall_ms, 3),
                "example_id": row["id"],
                "response_chars": len(response),
                "response_empty": not bool(response.strip()),
                "response_had_obvious_secret_redacted": contained_obvious_secret,
            }
        )
        if error:
            errors.append(
                {
                    "adapter": args.adapter,
                    "example_id": row["id"],
                    "video_sha256": row["video_sha256"],
                    **error,
                }
            )
    return responses, latencies, errors


def normalize_answer(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def extract_answer(response: str, short_answer: str) -> str:
    target = normalize_answer(short_answer)
    normalized = normalize_answer(response)
    if target in {"yes", "no", "left", "right"}:
        matches = re.findall(r"\b(?:yes|no|left|right)\b", normalized)
        return matches[0] if target in matches else normalized
    if target.isdigit():
        matches = re.findall(r"\b\d+\b", normalized)
        return matches[0] if target in matches else normalized
    if len(target) >= 3 and re.search(rf"\b{re.escape(target)}\b", normalized):
        return target
    return normalized


def evaluate_responses(selected: list[dict[str, Any]], responses: list[dict[str, Any]], eval_path: Path) -> dict[str, Any]:
    by_id = {str(row["example_id"]): row for row in responses}
    eval_rows: list[dict[str, Any]] = []
    timing_errors: list[float] = []
    for row in selected:
        response_row = by_id[str(row["id"])]
        expected = normalize_answer(str(row["short_answer"]))
        extracted = extract_answer(str(response_row["response"]), str(row["short_answer"]))
        correct = extracted == expected
        answer_start = response_row.get("answer_start_s")
        timing_error_ms = None
        if answer_start is not None and row.get("reference_timestamp_s") is not None:
            timing_error_ms = abs(float(answer_start) - float(row["reference_timestamp_s"])) * 1000.0
            timing_errors.append(timing_error_ms)
        eval_rows.append(
            {
                "category": row["category"],
                "correct": correct,
                "example_id": row["id"],
                "extracted_answer": extracted,
                "official_short_answer_normalized": expected,
                "response_sha256": common.sha256_text(str(response_row["response"])),
                "timing_error_ms": round(timing_error_ms, 3) if timing_error_ms is not None else None,
            }
        )
    common.write_jsonl(eval_path, eval_rows)
    return summarize_eval(eval_rows, timing_errors)


def summarize_eval(eval_rows: list[dict[str, Any]], timing_errors: list[float]) -> dict[str, Any]:
    total = len(eval_rows)
    correct = sum(1 for row in eval_rows if row["correct"])
    category_total: collections.Counter[str] = collections.Counter()
    category_correct: collections.Counter[str] = collections.Counter()
    for row in eval_rows:
        category_total[row["category"]] += 1
        if row["correct"]:
            category_correct[row["category"]] += 1

    def ratio(count: int, denominator: int) -> float:
        return float(count / denominator) if denominator else 0.0

    timing_mae = sum(timing_errors) / len(timing_errors) if timing_errors else None
    return {
        "evaluator": "short-answer-normalized-v0",
        "limitations": [
            "This is an offline-adapted runner, not a Realtime sideband streaming runner.",
            "The short-answer evaluator is deterministic and provisional; a fixed LLM judge can replace it.",
            "Frame sampling and VLM prompting are adapter responsibilities in this runner.",
        ],
        "accuracy": ratio(correct, total),
        "answer_timing_mae_ms": round(timing_mae, 3) if timing_mae is not None else None,
        "correct": correct,
        "total": total,
        "category_accuracy": {
            key: ratio(category_correct[key], category_total[key])
            for key in sorted(category_total)
        },
    }


def main() -> int:
    args = parse_args()
    repo_root = common.repo_root_from_file(__file__)
    run_id = args.run_id or common.default_run_id(args.adapter)
    run_dir = common.ensure_run_dir(args.run_root, BENCHMARK_ID, run_id)

    manifest_path = run_dir / "manifest.json"
    inputs_path = run_dir / "inputs.jsonl"
    labels_path = run_dir / "labels.jsonl"
    responses_path = run_dir / "responses.jsonl"
    latency_path = run_dir / "latency.jsonl"
    errors_path = run_dir / "errors.jsonl"
    metrics_path = run_dir / "metrics.json"
    eval_path = run_dir / "evaluation/answer_eval.jsonl"

    manifest = {
        "schema_version": common.SCHEMA_VERSION,
        "benchmark_id": BENCHMARK_ID,
        "run_id": run_id,
        "created_at_utc": common.utc_now_iso(),
        "status": "running",
        "pipeline_status": "provisional",
        "adapter_type": "offline-adapted",
        "adapter": {
            "type": args.adapter,
            "model_label": args.model_label,
            "command": "[provided]" if args.command else None,
        },
        "dataset": {
            "labels": common.relative_to_repo(args.labels, repo_root),
            "videos_dir": common.relative_to_repo(args.videos_dir, repo_root),
            "limit": args.limit,
            "offset": args.offset,
            "sample_seed": args.sample_seed,
            "category": args.category,
        },
        "artifacts": {
            "inputs": "inputs.jsonl",
            "labels": "labels.jsonl",
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
        rows = load_labels(args.labels, args.videos_dir)
        selected = select_rows(rows, args)
        if not selected:
            raise ValueError("No QIVD examples selected")

        input_rows = []
        label_rows = []
        video_byte_total = 0
        for row in selected:
            video_path = Path(row["video_path"])
            relative_video_path = common.relative_to_repo(video_path, repo_root)
            video_byte_total += int(row["video_byte_count"])
            input_rows.append(
                {
                    "benchmark_id": BENCHMARK_ID,
                    "category": row["category"],
                    "example_id": row["id"],
                    "question": row["question"],
                    "reference_timestamp_s": row["reference_timestamp_s"],
                    "source": common.relative_to_repo(args.labels, repo_root),
                    "timestamp": row["timestamp"],
                    "video": row["video"],
                    "video_byte_count": row["video_byte_count"],
                    "video_path": relative_video_path,
                    "video_sha256": row["video_sha256"],
                }
            )
            label_rows.append(
                {
                    "answer": row["answer"],
                    "category": row["category"],
                    "example_id": row["id"],
                    "short_answer": row["short_answer"],
                    "timestamp": row["timestamp"],
                }
            )
        common.write_jsonl(inputs_path, input_rows)
        common.write_jsonl(labels_path, label_rows)

        responses, latencies, errors = make_responses(args, selected, run_dir, repo_root)
        common.write_jsonl(responses_path, responses)
        common.write_jsonl(latency_path, latencies)
        common.write_jsonl(errors_path, errors)
        answer_summary = evaluate_responses(selected, responses, eval_path)

        metrics = {
            "schema_version": "giljob-benchmark-metrics/v0",
            "benchmark_id": BENCHMARK_ID,
            "run_id": run_id,
            "adapter": args.adapter,
            "adapter_type": "offline-adapted",
            "error_count": len(errors),
            "example_count": len(selected),
            "judge_model": "short-answer-normalized-v0",
            "response_empty_count": sum(1 for row in latencies if row["response_empty"]),
            "secret_exposure_count": sum(1 for row in latencies if row["response_had_obvious_secret_redacted"]),
            "video_byte_total": video_byte_total,
            "video_frame_sampling_policy": "adapter-defined",
            "evaluation": {
                "answer": answer_summary,
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
                "stage": "run_qivd_offline",
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
