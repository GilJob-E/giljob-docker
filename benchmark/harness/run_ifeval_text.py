#!/usr/bin/env python3
"""Run IFEval Text through a provisional benchmark artifact contract."""

from __future__ import annotations

import argparse
import collections
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


BENCHMARK_ID = "08-ifeval-text"


def parse_args() -> argparse.Namespace:
    repo_root = common.repo_root_from_file(__file__)
    default_google_root = repo_root / "benchmark/data/repos/google-research"
    default_input = default_google_root / "instruction_following_eval/data/input_data.jsonl"
    default_reference = (
        default_google_root
        / "instruction_following_eval/data/input_response_data_gpt4_20231107_145030.jsonl"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--google-research-root", type=Path, default=default_google_root)
    parser.add_argument("--input-data", type=Path, default=default_input)
    parser.add_argument("--run-root", type=Path, default=repo_root / "benchmark/runs")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--sample-seed", type=int, default=None)
    parser.add_argument(
        "--adapter",
        choices=("placeholder-empty", "echo-prompt", "reference-jsonl", "existing-jsonl", "command"),
        default="placeholder-empty",
    )
    parser.add_argument("--reference-jsonl", type=Path, default=default_reference)
    parser.add_argument("--responses-jsonl", type=Path, default=None)
    parser.add_argument("--command", default=None, help="Command adapter. Prompt is passed on stdin.")
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--model-label", default=None)
    parser.add_argument("--notes", action="append", default=[])
    return parser.parse_args()


def load_inputs(path: Path) -> list[dict[str, Any]]:
    rows = common.read_jsonl(path)
    required = {"key", "prompt", "instruction_id_list", "kwargs"}
    for index, row in enumerate(rows):
        missing = required - row.keys()
        if missing:
            raise ValueError(f"{path}:{index + 1}: missing fields {sorted(missing)}")
    return rows


def select_inputs(rows: list[dict[str, Any]], limit: int, offset: int, sample_seed: int | None) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("--limit must be positive")
    if offset < 0:
        raise ValueError("--offset must be non-negative")
    if sample_seed is None:
        return rows[offset : offset + limit]
    rng = random.Random(sample_seed)
    selected = rows[:]
    rng.shuffle(selected)
    return selected[offset : offset + limit]


def load_prompt_to_response(path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in common.read_jsonl(path):
        if "prompt" not in row or "response" not in row:
            raise ValueError(f"{path}: every row must include prompt and response")
        mapping[str(row["prompt"])] = str(row["response"])
    return mapping


def run_command_adapter(command: str, prompt: str, timeout_s: float, env_extra: dict[str, str]) -> tuple[str, dict[str, Any] | None]:
    argv = shlex.split(command)
    if not argv:
        raise ValueError("--command must not be empty for command adapter")
    env = os.environ.copy()
    env.update(env_extra)
    started = time.perf_counter()
    completed = subprocess.run(
        argv,
        input=prompt,
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


def make_responses(args: argparse.Namespace, selected: list[dict[str, Any]], run_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    responses: list[dict[str, Any]] = []
    latencies: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    reference_mapping: dict[str, str] = {}
    if args.adapter == "reference-jsonl":
        reference_mapping = load_prompt_to_response(args.reference_jsonl)
    elif args.adapter == "existing-jsonl":
        if args.responses_jsonl is None:
            raise ValueError("--responses-jsonl is required for existing-jsonl adapter")
        reference_mapping = load_prompt_to_response(args.responses_jsonl)
    elif args.adapter == "command" and not args.command:
        raise ValueError("--command is required for command adapter")

    for ordinal, row in enumerate(selected):
        prompt = str(row["prompt"])
        example_id = row["key"]
        started_at = common.utc_now_iso()
        started = time.perf_counter()
        error: dict[str, Any] | None = None

        if args.adapter == "placeholder-empty":
            response = ""
        elif args.adapter == "echo-prompt":
            response = prompt
        elif args.adapter in {"reference-jsonl", "existing-jsonl"}:
            if prompt not in reference_mapping:
                error = {"error": "missing_response_for_prompt"}
                response = ""
            else:
                response = reference_mapping[prompt]
        elif args.adapter == "command":
            response, error = run_command_adapter(
                args.command,
                prompt,
                args.timeout_s,
                {
                    "BENCHMARK_ID": BENCHMARK_ID,
                    "BENCHMARK_EXAMPLE_ID": str(example_id),
                    "BENCHMARK_ORDINAL": str(ordinal),
                    "BENCHMARK_RUN_DIR": str(run_dir),
                },
            )
        else:
            raise ValueError(f"Unsupported adapter: {args.adapter}")

        contained_obvious_secret = common.contains_obvious_secret(response)
        if contained_obvious_secret:
            response = common.redact_obvious_secrets(response)

        wall_ms = (time.perf_counter() - started) * 1000.0
        completed_at = common.utc_now_iso()
        response_row = {
            "adapter": args.adapter,
            "completed_at_utc": completed_at,
            "example_id": example_id,
            "prompt": prompt,
            "response": response,
            "response_had_obvious_secret_redacted": contained_obvious_secret,
            "started_at_utc": started_at,
        }
        if args.model_label:
            response_row["model_label"] = args.model_label
        responses.append(response_row)
        latencies.append(
            {
                "adapter": args.adapter,
                "adapter_wall_ms": round(wall_ms, 3),
                "example_id": example_id,
                "response_chars": len(response),
                "response_empty": not bool(response.strip()),
                "response_had_obvious_secret_redacted": contained_obvious_secret,
            }
        )
        if error:
            error_row = {
                "adapter": args.adapter,
                "example_id": example_id,
                "prompt_sha256": common.sha256_text(prompt),
                **error,
            }
            errors.append(error_row)
    return responses, latencies, errors


def import_official_eval(google_root: Path) -> Any:
    repo_root = common.repo_root_from_file(__file__)
    nltk_data_dir = repo_root / "benchmark/data/cache/nltk_data"
    existing_nltk_data = os.environ.get("NLTK_DATA")
    os.environ["NLTK_DATA"] = (
        f"{nltk_data_dir}{os.pathsep}{existing_nltk_data}"
        if existing_nltk_data
        else str(nltk_data_dir)
    )
    sys.path.insert(0, str(google_root.resolve()))
    try:
        import nltk

        if str(nltk_data_dir) not in nltk.data.path:
            nltk.data.path.insert(0, str(nltk_data_dir))
        from instruction_following_eval import evaluation_lib
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "IFEval dependencies are missing. Install with: "
            "benchmark/data/cache/data-tools/bin/pip install absl-py langdetect nltk immutabledict"
        ) from exc
    return evaluation_lib


def summarize_outputs(outputs: list[Any]) -> dict[str, Any]:
    prompt_total = len(outputs)
    prompt_correct = sum(1 for output in outputs if output.follow_all_instructions)
    instruction_total = 0
    instruction_correct = 0
    tier0_total: collections.Counter[str] = collections.Counter()
    tier0_correct: collections.Counter[str] = collections.Counter()
    tier1_total: collections.Counter[str] = collections.Counter()
    tier1_correct: collections.Counter[str] = collections.Counter()

    for output in outputs:
        instruction_total += len(output.instruction_id_list)
        instruction_correct += sum(output.follow_instruction_list)
        for instruction_id, followed in zip(output.instruction_id_list, output.follow_instruction_list):
            tier0 = instruction_id.split(":", 1)[0]
            tier0_total[tier0] += 1
            tier1_total[instruction_id] += 1
            if followed:
                tier0_correct[tier0] += 1
                tier1_correct[instruction_id] += 1

    def ratio(correct: int, total: int) -> float:
        return float(correct / total) if total else 0.0

    return {
        "instruction_level_accuracy": ratio(instruction_correct, instruction_total),
        "instruction_total": instruction_total,
        "instruction_correct": instruction_correct,
        "prompt_level_accuracy": ratio(prompt_correct, prompt_total),
        "prompt_total": prompt_total,
        "prompt_correct": prompt_correct,
        "tier0_accuracy": {
            key: ratio(tier0_correct[key], tier0_total[key])
            for key in sorted(tier0_total)
        },
        "tier1_accuracy": {
            key: ratio(tier1_correct[key], tier1_total[key])
            for key in sorted(tier1_total)
        },
    }


def evaluate(args: argparse.Namespace, selected_input_path: Path, responses_path: Path, eval_dir: Path) -> dict[str, Any]:
    evaluation_lib = import_official_eval(args.google_research_root)
    inputs = evaluation_lib.read_prompt_list(str(selected_input_path))
    prompt_to_response = evaluation_lib.read_prompt_to_response_dict(str(responses_path))

    metrics: dict[str, Any] = {}
    for label, func, output_name in (
        ("strict", evaluation_lib.test_instruction_following_strict, "eval_results_strict.jsonl"),
        ("loose", evaluation_lib.test_instruction_following_loose, "eval_results_loose.jsonl"),
    ):
        outputs = [func(inp, prompt_to_response) for inp in inputs]
        evaluation_lib.write_outputs(str(eval_dir / output_name), outputs)
        metrics[label] = summarize_outputs(outputs)
    return metrics


def main() -> int:
    args = parse_args()
    repo_root = common.repo_root_from_file(__file__)
    run_id = args.run_id or common.default_run_id(args.adapter)
    run_dir = common.ensure_run_dir(args.run_root, BENCHMARK_ID, run_id)

    manifest_path = run_dir / "manifest.json"
    inputs_path = run_dir / "inputs.jsonl"
    official_subset_path = run_dir / "official_input_subset.jsonl"
    responses_path = run_dir / "responses.jsonl"
    latency_path = run_dir / "latency.jsonl"
    errors_path = run_dir / "errors.jsonl"
    metrics_path = run_dir / "metrics.json"
    eval_dir = run_dir / "evaluation"

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
            "input_data": common.relative_to_repo(args.input_data, repo_root),
            "google_research_root": common.relative_to_repo(args.google_research_root, repo_root),
            "limit": args.limit,
            "offset": args.offset,
            "sample_seed": args.sample_seed,
        },
        "artifacts": {
            "inputs": "inputs.jsonl",
            "official_input_subset": "official_input_subset.jsonl",
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
        all_inputs = load_inputs(args.input_data)
        selected = select_inputs(all_inputs, args.limit, args.offset, args.sample_seed)
        if not selected:
            raise ValueError("No input examples selected")
        inputs_rows = [
            {
                "benchmark_id": BENCHMARK_ID,
                "example_id": row["key"],
                "instruction_id_list": row["instruction_id_list"],
                "kwargs": row["kwargs"],
                "prompt": row["prompt"],
                "source": common.relative_to_repo(args.input_data, repo_root),
            }
            for row in selected
        ]
        official_rows = [
            {
                "key": row["key"],
                "instruction_id_list": row["instruction_id_list"],
                "kwargs": row["kwargs"],
                "prompt": row["prompt"],
            }
            for row in selected
        ]
        common.write_jsonl(inputs_path, inputs_rows)
        common.write_jsonl(official_subset_path, official_rows)

        responses, latencies, errors = make_responses(args, selected, run_dir)
        common.write_jsonl(responses_path, responses)
        common.write_jsonl(latency_path, latencies)
        common.write_jsonl(errors_path, errors)

        metrics = {
            "schema_version": "giljob-benchmark-metrics/v0",
            "benchmark_id": BENCHMARK_ID,
            "run_id": run_id,
            "adapter": args.adapter,
            "example_count": len(selected),
            "error_count": len(errors),
            "response_empty_count": sum(1 for row in latencies if row["response_empty"]),
            "secret_exposure_count": sum(1 for row in latencies if row["response_had_obvious_secret_redacted"]),
            "official_evaluator": "google-research/instruction_following_eval",
            "evaluation": evaluate(args, official_subset_path, responses_path, eval_dir),
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
                "stage": "run_ifeval_text",
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
