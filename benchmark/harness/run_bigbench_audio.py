#!/usr/bin/env python3
"""Run BigBench Audio as an internal adapted audio-QA benchmark."""

from __future__ import annotations

import argparse
import collections
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


BENCHMARK_ID = "06-bigbench-audio"


def parse_args() -> argparse.Namespace:
    repo_root = common.repo_root_from_file(__file__)
    default_root = repo_root / "benchmark/data/raw/bigbench-audio"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=default_root)
    parser.add_argument("--metadata", type=Path, default=default_root / "metadata.jsonl")
    parser.add_argument("--run-root", type=Path, default=repo_root / "benchmark/runs")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--sample-seed", type=int, default=None)
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument(
        "--adapter",
        choices=("placeholder-empty", "constant-answer", "existing-jsonl", "command"),
        default="placeholder-empty",
    )
    parser.add_argument("--constant-answer", default="No")
    parser.add_argument("--responses-jsonl", type=Path, default=None)
    parser.add_argument(
        "--command",
        default=None,
        help="Command adapter. JSON with audio path and metadata is passed on stdin.",
    )
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--model-label", default=None)
    parser.add_argument("--notes", action="append", default=[])
    return parser.parse_args()


def load_metadata(path: Path, data_root: Path) -> list[dict[str, Any]]:
    rows = common.read_jsonl(path)
    required = {"id", "category", "file_name", "official_answer"}
    for index, row in enumerate(rows):
        missing = required - row.keys()
        if missing:
            raise ValueError(f"{path}:{index + 1}: missing fields {sorted(missing)}")
        audio_path = data_root / str(row["file_name"])
        if not audio_path.exists():
            raise FileNotFoundError(f"Missing audio file for id={row['id']}: {audio_path}")
        row["audio_path"] = audio_path
        row["audio_byte_count"] = audio_path.stat().st_size
        row["audio_sha256"] = file_sha256(audio_path)
    return rows


def file_sha256(path: Path) -> str:
    import hashlib

    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


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


def load_response_mapping(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    by_id: dict[str, str] = {}
    by_audio_path: dict[str, str] = {}
    for row in common.read_jsonl(path):
        response = str(row.get("response", row.get("answer", "")))
        if not response and "response" not in row and "answer" not in row:
            raise ValueError(f"{path}: every row must include response or answer")
        for key_field in ("example_id", "id"):
            if key_field in row:
                by_id[str(row[key_field])] = response
        if "audio_path" in row:
            by_audio_path[str(row["audio_path"])] = response
    return by_id, by_audio_path


def run_command_adapter(command: str, payload: dict[str, Any], timeout_s: float, env_extra: dict[str, str]) -> tuple[str, dict[str, Any] | None]:
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
        return "", {
            "return_code": completed.returncode,
            "stderr_sha256": common.sha256_text(stderr),
            "stderr_preview_redacted": common.redact_obvious_secrets(stderr[:500]),
            "adapter_wall_ms": round(wall_ms, 3),
        }
    return completed.stdout.rstrip("\n"), None


def make_responses(args: argparse.Namespace, selected: list[dict[str, Any]], run_dir: Path, repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    responses: list[dict[str, Any]] = []
    latencies: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    by_id: dict[str, str] = {}
    by_audio_path: dict[str, str] = {}

    if args.adapter == "existing-jsonl":
        if args.responses_jsonl is None:
            raise ValueError("--responses-jsonl is required for existing-jsonl adapter")
        by_id, by_audio_path = load_response_mapping(args.responses_jsonl)
    elif args.adapter == "command" and not args.command:
        raise ValueError("--command is required for command adapter")

    for ordinal, row in enumerate(selected):
        example_id = str(row["id"])
        audio_path = Path(row["audio_path"])
        relative_audio_path = common.relative_to_repo(audio_path, repo_root)
        started_at = common.utc_now_iso()
        started = time.perf_counter()
        error: dict[str, Any] | None = None

        if args.adapter == "placeholder-empty":
            response = ""
        elif args.adapter == "constant-answer":
            response = args.constant_answer
        elif args.adapter == "existing-jsonl":
            if example_id in by_id:
                response = by_id[example_id]
            elif relative_audio_path in by_audio_path:
                response = by_audio_path[relative_audio_path]
            else:
                error = {"error": "missing_response_for_audio_example"}
                response = ""
        elif args.adapter == "command":
            payload = {
                "benchmark_id": BENCHMARK_ID,
                "example_id": row["id"],
                "audio_path": str(audio_path),
                "audio_path_relative": relative_audio_path,
                "category": row["category"],
            }
            response, error = run_command_adapter(
                args.command,
                payload,
                args.timeout_s,
                {
                    "BENCHMARK_ID": BENCHMARK_ID,
                    "BENCHMARK_EXAMPLE_ID": example_id,
                    "BENCHMARK_ORDINAL": str(ordinal),
                    "BENCHMARK_RUN_DIR": str(run_dir),
                    "BIGBENCH_AUDIO_PATH": str(audio_path),
                    "BIGBENCH_AUDIO_CATEGORY": str(row["category"]),
                },
            )
        else:
            raise ValueError(f"Unsupported adapter: {args.adapter}")

        contained_obvious_secret = common.contains_obvious_secret(response)
        if contained_obvious_secret:
            response = common.redact_obvious_secrets(response)

        wall_ms = (time.perf_counter() - started) * 1000.0
        responses.append(
            {
                "adapter": args.adapter,
                "audio_path": relative_audio_path,
                "category": row["category"],
                "completed_at_utc": common.utc_now_iso(),
                "example_id": row["id"],
                "model_label": args.model_label,
                "response": response,
                "response_had_obvious_secret_redacted": contained_obvious_secret,
                "started_at_utc": started_at,
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
                    "audio_sha256": row["audio_sha256"],
                    **error,
                }
            )
    return responses, latencies, errors


def normalize_answer(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def extract_answer(response: str, official_answer: str) -> str:
    target = normalize_answer(official_answer)
    normalized = normalize_answer(response)
    if target in {"yes", "no"}:
        matches = re.findall(r"\b(?:yes|no)\b", normalized)
        return matches[0] if len(set(matches)) == 1 else normalized
    if target in {"valid", "invalid"}:
        matches = re.findall(r"\b(?:valid|invalid)\b", normalized)
        return matches[0] if len(set(matches)) == 1 else normalized
    if target.isdigit():
        matches = re.findall(r"\b\d+\b", normalized)
        return matches[0] if len(set(matches)) == 1 else normalized
    return normalized


def evaluate_responses(selected: list[dict[str, Any]], responses: list[dict[str, Any]], eval_path: Path) -> dict[str, Any]:
    by_id = {str(row["example_id"]): row for row in responses}
    eval_rows: list[dict[str, Any]] = []
    for row in selected:
        example_id = str(row["id"])
        response_row = by_id[example_id]
        official = str(row["official_answer"])
        extracted = extract_answer(str(response_row["response"]), official)
        expected = normalize_answer(official)
        correct = extracted == expected
        eval_rows.append(
            {
                "category": row["category"],
                "correct": correct,
                "example_id": row["id"],
                "extracted_answer": extracted,
                "official_answer_normalized": expected,
                "response_sha256": common.sha256_text(str(response_row["response"])),
            }
        )
    common.write_jsonl(eval_path, eval_rows)
    return summarize_eval(eval_rows)


def summarize_eval(eval_rows: list[dict[str, Any]]) -> dict[str, Any]:
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

    return {
        "evaluator": "category-aware-token-exact-v0",
        "limitations": [
            "BigBench Audio public methodology is not fixed here; this is an internal adapted score.",
            "Command adapters receive local audio paths, not raw audio bytes.",
            "Answer extraction handles yes/no, valid/invalid, and integer answers with simple token rules.",
        ],
        "accuracy": ratio(correct, total),
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
        "reproducibility_status": "internal-adapted",
        "adapter": {
            "type": args.adapter,
            "model_label": args.model_label,
            "command": "[provided]" if args.command else None,
        },
        "dataset": {
            "data_root": common.relative_to_repo(args.data_root, repo_root),
            "metadata": common.relative_to_repo(args.metadata, repo_root),
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
        rows = load_metadata(args.metadata, args.data_root)
        selected = select_rows(rows, args)
        if not selected:
            raise ValueError("No BigBench Audio examples selected")

        input_rows = []
        label_rows = []
        audio_byte_total = 0
        for row in selected:
            audio_path = Path(row["audio_path"])
            relative_audio_path = common.relative_to_repo(audio_path, repo_root)
            audio_byte_total += int(row["audio_byte_count"])
            input_rows.append(
                {
                    "audio_byte_count": row["audio_byte_count"],
                    "audio_path": relative_audio_path,
                    "audio_sha256": row["audio_sha256"],
                    "benchmark_id": BENCHMARK_ID,
                    "category": row["category"],
                    "example_id": row["id"],
                    "source": common.relative_to_repo(args.metadata, repo_root),
                }
            )
            label_rows.append(
                {
                    "category": row["category"],
                    "example_id": row["id"],
                    "official_answer": row["official_answer"],
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
            "answer_extraction_policy": "category-aware-token-exact-v0",
            "audio_byte_total": audio_byte_total,
            "dataset_source": "ArtificialAnalysis/big_bench_audio local mirror",
            "error_count": len(errors),
            "example_count": len(selected),
            "reproducibility_status": "internal-adapted",
            "response_empty_count": sum(1 for row in latencies if row["response_empty"]),
            "secret_exposure_count": sum(1 for row in latencies if row["response_had_obvious_secret_redacted"]),
            "transcript_error_rate": None,
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
                "stage": "run_bigbench_audio",
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
