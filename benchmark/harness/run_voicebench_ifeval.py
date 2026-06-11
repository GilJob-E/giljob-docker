#!/usr/bin/env python3
"""Run VoiceBench IFEval through the provisional benchmark artifact contract."""

from __future__ import annotations

import argparse
import hashlib
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
from benchmark.harness.run_ifeval_text import evaluate as evaluate_ifeval


BENCHMARK_ID = "07-ifeval-voicebench"


def parse_args() -> argparse.Namespace:
    repo_root = common.repo_root_from_file(__file__)
    default_parquet = repo_root / "benchmark/data/raw/voicebench-ifeval/test-00000-of-00001.parquet"
    default_google_root = repo_root / "benchmark/data/repos/google-research"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", type=Path, default=default_parquet)
    parser.add_argument("--google-research-root", type=Path, default=default_google_root)
    parser.add_argument("--run-root", type=Path, default=repo_root / "benchmark/runs")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--sample-seed", type=int, default=None)
    parser.add_argument(
        "--adapter",
        choices=("placeholder-empty", "echo-prompt", "existing-jsonl", "command"),
        default="placeholder-empty",
    )
    parser.add_argument("--responses-jsonl", type=Path, default=None)
    parser.add_argument("--command", default=None, help="Command adapter. Oracle transcript prompt is passed on stdin.")
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--model-label", default=None)
    parser.add_argument("--notes", action="append", default=[])
    return parser.parse_args()


def import_pyarrow() -> Any:
    try:
        import pyarrow.parquet as pq
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "pyarrow is required for VoiceBench parquet. Install with: "
            "benchmark/data/cache/data-tools/bin/pip install pyarrow"
        ) from exc
    return pq


def load_rows(path: Path) -> list[dict[str, Any]]:
    pq = import_pyarrow()
    table = pq.read_table(path)
    rows = table.to_pylist()
    required = {"audio", "key", "prompt", "instruction_id_list", "kwargs"}
    for index, row in enumerate(rows):
        missing = required - row.keys()
        if missing:
            raise ValueError(f"{path}:{index + 1}: missing fields {sorted(missing)}")
    return rows


def select_rows(rows: list[dict[str, Any]], limit: int, offset: int, sample_seed: int | None) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("--limit must be positive")
    if offset < 0:
        raise ValueError("--offset must be non-negative")
    selected = rows[:]
    if sample_seed is not None:
        rng = random.Random(sample_seed)
        rng.shuffle(selected)
    return selected[offset : offset + limit]


def audio_metadata(row: dict[str, Any]) -> dict[str, Any]:
    audio = row.get("audio") or {}
    audio_bytes = audio.get("bytes") if isinstance(audio, dict) else None
    audio_path = audio.get("path") if isinstance(audio, dict) else None
    if isinstance(audio_bytes, bytes):
        return {
            "audio_byte_count": len(audio_bytes),
            "audio_sha256": hashlib.sha256(audio_bytes).hexdigest(),
            "audio_path": audio_path,
        }
    return {
        "audio_byte_count": 0,
        "audio_sha256": None,
        "audio_path": audio_path,
    }


def drop_none_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: drop_none_values(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [drop_none_values(item) for item in value if item is not None]
    return value


def cleaned_kwargs(row: dict[str, Any]) -> list[dict[str, Any]]:
    kwargs = row.get("kwargs") or []
    cleaned = drop_none_values(kwargs)
    if not isinstance(cleaned, list):
        raise ValueError(f"Expected kwargs list for example {row.get('key')}")
    return cleaned


def load_response_mapping(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    by_example_id: dict[str, str] = {}
    by_prompt: dict[str, str] = {}
    for row in common.read_jsonl(path):
        if "response" not in row:
            raise ValueError(f"{path}: every row must include response")
        response = str(row["response"])
        for key_field in ("example_id", "key"):
            if key_field in row:
                by_example_id[str(row[key_field])] = response
        if "prompt" in row:
            by_prompt[str(row["prompt"])] = response
    return by_example_id, by_prompt


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
    by_example_id: dict[str, str] = {}
    by_prompt: dict[str, str] = {}

    if args.adapter == "existing-jsonl":
        if args.responses_jsonl is None:
            raise ValueError("--responses-jsonl is required for existing-jsonl adapter")
        by_example_id, by_prompt = load_response_mapping(args.responses_jsonl)
    elif args.adapter == "command" and not args.command:
        raise ValueError("--command is required for command adapter")

    for ordinal, row in enumerate(selected):
        example_id = str(row["key"])
        prompt = str(row["prompt"])
        started_at = common.utc_now_iso()
        started = time.perf_counter()
        error: dict[str, Any] | None = None

        if args.adapter == "placeholder-empty":
            response = ""
        elif args.adapter == "echo-prompt":
            response = prompt
        elif args.adapter == "existing-jsonl":
            if example_id in by_example_id:
                response = by_example_id[example_id]
            elif prompt in by_prompt:
                response = by_prompt[prompt]
            else:
                error = {"error": "missing_response_for_example"}
                response = ""
        elif args.adapter == "command":
            response, error = run_command_adapter(
                args.command,
                prompt,
                args.timeout_s,
                {
                    "BENCHMARK_ID": BENCHMARK_ID,
                    "BENCHMARK_EXAMPLE_ID": example_id,
                    "BENCHMARK_ORDINAL": str(ordinal),
                    "BENCHMARK_RUN_DIR": str(run_dir),
                    "VOICEBENCH_ADAPTER_INPUT": "oracle_transcript",
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
                "adapter_input": "oracle_transcript",
                "completed_at_utc": common.utc_now_iso(),
                "example_id": row["key"],
                "model_label": args.model_label,
                "prompt": prompt,
                "response": response,
                "response_had_obvious_secret_redacted": contained_obvious_secret,
                "started_at_utc": started_at,
            }
        )
        latencies.append(
            {
                "adapter": args.adapter,
                "adapter_wall_ms": round(wall_ms, 3),
                "example_id": row["key"],
                "response_chars": len(response),
                "response_empty": not bool(response.strip()),
                "response_had_obvious_secret_redacted": contained_obvious_secret,
            }
        )
        if error:
            errors.append(
                {
                    "adapter": args.adapter,
                    "example_id": row["key"],
                    "prompt_sha256": common.sha256_text(prompt),
                    **error,
                }
            )
    return responses, latencies, errors


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
            "adapter_input": "oracle_transcript",
            "model_label": args.model_label,
            "command": "[provided]" if args.command else None,
        },
        "dataset": {
            "parquet": common.relative_to_repo(args.parquet, repo_root),
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
        all_rows = load_rows(args.parquet)
        selected = select_rows(all_rows, args.limit, args.offset, args.sample_seed)
        if not selected:
            raise ValueError("No VoiceBench IFEval examples selected")

        input_rows = []
        official_rows = []
        audio_byte_total = 0
        for row in selected:
            metadata = audio_metadata(row)
            audio_byte_total += int(metadata["audio_byte_count"])
            input_rows.append(
                {
                    "benchmark_id": BENCHMARK_ID,
                    "example_id": row["key"],
                    "instruction_id_list": row["instruction_id_list"],
                    "kwargs": cleaned_kwargs(row),
                    "prompt": row["prompt"],
                    "source": common.relative_to_repo(args.parquet, repo_root),
                    **metadata,
                }
            )
            official_rows.append(
                {
                    "key": row["key"],
                    "instruction_id_list": row["instruction_id_list"],
                    "kwargs": cleaned_kwargs(row),
                    "prompt": row["prompt"],
                }
            )
        common.write_jsonl(inputs_path, input_rows)
        common.write_jsonl(official_subset_path, official_rows)

        responses, latencies, errors = make_responses(args, selected, run_dir)
        common.write_jsonl(responses_path, responses)
        common.write_jsonl(latency_path, latencies)
        common.write_jsonl(errors_path, errors)

        eval_args = argparse.Namespace(google_research_root=args.google_research_root)
        metrics = {
            "schema_version": "giljob-benchmark-metrics/v0",
            "benchmark_id": BENCHMARK_ID,
            "run_id": run_id,
            "adapter": args.adapter,
            "adapter_input": "oracle_transcript",
            "example_count": len(selected),
            "audio_byte_total": audio_byte_total,
            "error_count": len(errors),
            "response_empty_count": sum(1 for row in latencies if row["response_empty"]),
            "secret_exposure_count": sum(1 for row in latencies if row["response_had_obvious_secret_redacted"]),
            "transcript_error_rate": None,
            "transcript_source": "dataset_prompt_oracle",
            "official_evaluator": "google-research/instruction_following_eval",
            "evaluation": evaluate_ifeval(eval_args, official_subset_path, responses_path, eval_dir),
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
                "stage": "run_voicebench_ifeval",
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
