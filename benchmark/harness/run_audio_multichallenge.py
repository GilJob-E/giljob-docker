#!/usr/bin/env python3
"""Run Audio MultiChallenge through a provisional rubric artifact contract."""

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


BENCHMARK_ID = "05-audio-multichallenge"


def parse_args() -> argparse.Namespace:
    repo_root = common.repo_root_from_file(__file__)
    default_root = repo_root / "benchmark/data/raw/mimo-audio-evalset/multi_challenge"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=default_root)
    parser.add_argument("--data-jsonl", type=Path, default=default_root / "data.jsonl")
    parser.add_argument("--run-root", type=Path, default=repo_root / "benchmark/runs")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--sample-seed", type=int, default=None)
    parser.add_argument("--axis", action="append", default=[])
    parser.add_argument(
        "--adapter",
        choices=("placeholder-empty", "constant-answer", "existing-jsonl", "command"),
        default="placeholder-empty",
    )
    parser.add_argument("--constant-answer", default="YES")
    parser.add_argument("--responses-jsonl", type=Path, default=None)
    parser.add_argument(
        "--command",
        default=None,
        help="Command adapter. JSON with conversation, target question, and audio paths is passed on stdin.",
    )
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--model-label", default=None)
    parser.add_argument("--notes", action="append", default=[])
    return parser.parse_args()


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows = common.read_jsonl(path)
    required = {"QUESTION_ID", "AXIS", "CONVERSATION", "TARGET_QUESTION", "PASS_CRITERIA", "speech_dialogue"}
    for index, row in enumerate(rows):
        missing = required - row.keys()
        if missing:
            raise ValueError(f"{path}:{index + 1}: missing fields {sorted(missing)}")
    return rows


def select_rows(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    selected = rows
    axes = set(args.axis)
    if axes:
        selected = [row for row in selected if row["AXIS"] in axes]
    if args.limit <= 0:
        raise ValueError("--limit must be positive")
    if args.offset < 0:
        raise ValueError("--offset must be non-negative")
    selected = selected[:]
    if args.sample_seed is not None:
        rng = random.Random(args.sample_seed)
        rng.shuffle(selected)
    return selected[args.offset : args.offset + args.limit]


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def resolve_audio_entries(row: dict[str, Any], data_root: Path, repo_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for turn_index, turn in enumerate(row.get("speech_dialogue") or []):
        content = str(turn.get("content", ""))
        if not content:
            continue
        audio_path = (data_root / content.replace("./", "", 1)).resolve()
        if not audio_path.exists():
            raise FileNotFoundError(f"Missing audio file for question={row['QUESTION_ID']}: {audio_path}")
        entries.append(
            {
                "audio_byte_count": audio_path.stat().st_size,
                "audio_path": common.relative_to_repo(audio_path, repo_root),
                "audio_sha256": file_sha256(audio_path),
                "role": turn.get("role"),
                "turn_index": turn_index,
            }
        )
    return entries


def load_response_mapping(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    by_question_id: dict[str, str] = {}
    by_target_question: dict[str, str] = {}
    for row in common.read_jsonl(path):
        response = str(row.get("response", row.get("answer", "")))
        if not response and "response" not in row and "answer" not in row:
            raise ValueError(f"{path}: every row must include response or answer")
        for key_field in ("question_id", "example_id", "QUESTION_ID"):
            if key_field in row:
                by_question_id[str(row[key_field])] = response
        if "target_question" in row:
            by_target_question[str(row["target_question"])] = response
    return by_question_id, by_target_question


def command_payload(row: dict[str, Any], audio_entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "benchmark_id": BENCHMARK_ID,
        "question_id": row["QUESTION_ID"],
        "axis": row["AXIS"],
        "conversation": row["CONVERSATION"],
        "target_question": row["TARGET_QUESTION"],
        "speech_dialogue_audio": [
            {
                "audio_path": entry["audio_path"],
                "role": entry["role"],
                "turn_index": entry["turn_index"],
            }
            for entry in audio_entries
        ],
    }


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


def make_responses(
    args: argparse.Namespace,
    selected: list[dict[str, Any]],
    audio_entries_by_id: dict[str, list[dict[str, Any]]],
    run_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    responses: list[dict[str, Any]] = []
    latencies: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    by_question_id: dict[str, str] = {}
    by_target_question: dict[str, str] = {}

    if args.adapter == "existing-jsonl":
        if args.responses_jsonl is None:
            raise ValueError("--responses-jsonl is required for existing-jsonl adapter")
        by_question_id, by_target_question = load_response_mapping(args.responses_jsonl)
    elif args.adapter == "command" and not args.command:
        raise ValueError("--command is required for command adapter")

    for ordinal, row in enumerate(selected):
        question_id = str(row["QUESTION_ID"])
        started_at = common.utc_now_iso()
        started = time.perf_counter()
        error: dict[str, Any] | None = None

        if args.adapter == "placeholder-empty":
            response = ""
        elif args.adapter == "constant-answer":
            response = args.constant_answer
        elif args.adapter == "existing-jsonl":
            if question_id in by_question_id:
                response = by_question_id[question_id]
            elif row["TARGET_QUESTION"] in by_target_question:
                response = by_target_question[row["TARGET_QUESTION"]]
            else:
                error = {"error": "missing_response_for_question"}
                response = ""
        elif args.adapter == "command":
            payload = command_payload(row, audio_entries_by_id[question_id])
            response, error = run_command_adapter(
                args.command,
                payload,
                args.timeout_s,
                {
                    "BENCHMARK_ID": BENCHMARK_ID,
                    "BENCHMARK_EXAMPLE_ID": question_id,
                    "BENCHMARK_ORDINAL": str(ordinal),
                    "BENCHMARK_RUN_DIR": str(run_dir),
                    "AUDIO_MULTICHALLENGE_AXIS": str(row["AXIS"]),
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
                "axis": row["AXIS"],
                "completed_at_utc": common.utc_now_iso(),
                "example_id": question_id,
                "model_label": args.model_label,
                "question_id": question_id,
                "response": response,
                "response_had_obvious_secret_redacted": contained_obvious_secret,
                "started_at_utc": started_at,
                "target_question": row["TARGET_QUESTION"],
            }
        )
        latencies.append(
            {
                "adapter": args.adapter,
                "adapter_wall_ms": round(wall_ms, 3),
                "example_id": question_id,
                "response_chars": len(response),
                "response_empty": not bool(response.strip()),
                "response_had_obvious_secret_redacted": contained_obvious_secret,
            }
        )
        if error:
            errors.append(
                {
                    "adapter": args.adapter,
                    "example_id": question_id,
                    **error,
                }
            )
    return responses, latencies, errors


def normalize_yes_no(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[^a-z]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    matches = re.findall(r"\b(?:yes|no)\b", normalized)
    if len(set(matches)) == 1:
        return matches[0].upper()
    if normalized in {"yes", "no"}:
        return normalized.upper()
    return normalized.upper()


def evaluate_responses(selected: list[dict[str, Any]], responses: list[dict[str, Any]], eval_path: Path) -> dict[str, Any]:
    by_id = {str(row["question_id"]): row for row in responses}
    eval_rows: list[dict[str, Any]] = []
    for row in selected:
        question_id = str(row["QUESTION_ID"])
        response_row = by_id[question_id]
        expected = normalize_yes_no(str(row["PASS_CRITERIA"]))
        extracted = normalize_yes_no(str(response_row["response"]))
        passed = extracted == expected
        eval_rows.append(
            {
                "axis": row["AXIS"],
                "example_id": question_id,
                "extracted_answer": extracted,
                "pass_criteria": expected,
                "passed": passed,
                "response_sha256": common.sha256_text(str(response_row["response"])),
            }
        )
    common.write_jsonl(eval_path, eval_rows)
    return summarize_eval(eval_rows)


def summarize_eval(eval_rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(eval_rows)
    passed = sum(1 for row in eval_rows if row["passed"])
    axis_total: collections.Counter[str] = collections.Counter()
    axis_passed: collections.Counter[str] = collections.Counter()
    for row in eval_rows:
        axis_total[row["axis"]] += 1
        if row["passed"]:
            axis_passed[row["axis"]] += 1

    def ratio(count: int, denominator: int) -> float:
        return float(count / denominator) if denominator else 0.0

    return {
        "evaluator": "binary-rubric-exact-v0",
        "limitations": [
            "This first runner answers TARGET_QUESTION directly; it is not yet a full multi-turn audio-agent simulation.",
            "Command adapters receive local audio paths and conversation text, not raw audio bytes.",
            "A judge-based rubric evaluator can replace this binary exact evaluator later.",
        ],
        "average_pass_rate": ratio(passed, total),
        "passed": passed,
        "total": total,
        "axis_pass_rate": {
            key: ratio(axis_passed[key], axis_total[key])
            for key in sorted(axis_total)
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
    eval_path = run_dir / "evaluation/rubric_eval.jsonl"

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
            "data_root": common.relative_to_repo(args.data_root, repo_root),
            "data_jsonl": common.relative_to_repo(args.data_jsonl, repo_root),
            "limit": args.limit,
            "offset": args.offset,
            "sample_seed": args.sample_seed,
            "axis": args.axis,
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
        rows = load_rows(args.data_jsonl)
        selected = select_rows(rows, args)
        if not selected:
            raise ValueError("No Audio MultiChallenge examples selected")

        audio_entries_by_id: dict[str, list[dict[str, Any]]] = {}
        input_rows = []
        label_rows = []
        audio_file_count = 0
        audio_byte_total = 0
        for row in selected:
            question_id = str(row["QUESTION_ID"])
            audio_entries = resolve_audio_entries(row, args.data_root, repo_root)
            audio_entries_by_id[question_id] = audio_entries
            audio_file_count += len(audio_entries)
            audio_byte_total += sum(int(entry["audio_byte_count"]) for entry in audio_entries)
            input_rows.append(
                {
                    "audio": audio_entries,
                    "axis": row["AXIS"],
                    "benchmark_id": BENCHMARK_ID,
                    "conversation": row["CONVERSATION"],
                    "example_id": question_id,
                    "question_id": question_id,
                    "source": common.relative_to_repo(args.data_jsonl, repo_root),
                    "target_question": row["TARGET_QUESTION"],
                    "turn_count": len(row["CONVERSATION"]),
                }
            )
            label_rows.append(
                {
                    "axis": row["AXIS"],
                    "example_id": question_id,
                    "pass_criteria": row["PASS_CRITERIA"],
                    "target_question": row["TARGET_QUESTION"],
                }
            )
        common.write_jsonl(inputs_path, input_rows)
        common.write_jsonl(labels_path, label_rows)

        responses, latencies, errors = make_responses(args, selected, audio_entries_by_id, run_dir)
        common.write_jsonl(responses_path, responses)
        common.write_jsonl(latency_path, latencies)
        common.write_jsonl(errors_path, errors)
        rubric_summary = evaluate_responses(selected, responses, eval_path)

        metrics = {
            "schema_version": "giljob-benchmark-metrics/v0",
            "benchmark_id": BENCHMARK_ID,
            "run_id": run_id,
            "adapter": args.adapter,
            "audio_byte_total": audio_byte_total,
            "audio_file_count": audio_file_count,
            "error_count": len(errors),
            "example_count": len(selected),
            "judge_model": "binary-rubric-exact-v0",
            "response_empty_count": sum(1 for row in latencies if row["response_empty"]),
            "secret_exposure_count": sum(1 for row in latencies if row["response_had_obvious_secret_redacted"]),
            "transcript_error_rate": None,
            "evaluation": {
                "rubric": rubric_summary,
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
                "stage": "run_audio_multichallenge",
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
