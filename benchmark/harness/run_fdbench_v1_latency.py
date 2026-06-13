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
    parser.add_argument(
        "--measurement-level",
        choices=("evaluator-smoke", "component", "product-path", "full-service-e2e"),
        default=None,
        help="What level of the GilJob system this run claims to measure.",
    )
    parser.add_argument(
        "--adapter-boundary",
        default=None,
        help="Human-readable boundary label, e.g. realtime-product-path or mmm-only.",
    )
    parser.add_argument("--notes", action="append", default=[])
    args = parser.parse_args()
    if args.measurement_level is None:
        args.measurement_level = "evaluator-smoke" if args.adapter == "simulated-latency" else "product-path"
    if args.adapter_boundary is None:
        if args.adapter == "simulated-latency":
            args.adapter_boundary = "offline-simulated"
        elif args.adapter == "command":
            args.adapter_boundary = "realtime-product-path-command"
        else:
            args.adapter_boundary = "external-timestamp-jsonl"
    return args


def measurement_contract(args: argparse.Namespace) -> dict[str, Any]:
    level = args.measurement_level
    required_evidence: list[str] = []
    excluded_boundaries: list[str] = []
    includes = {
        "browser_webrtc_or_equivalent": False,
        "realtime_session_broker": False,
        "mmm_readiness_gate": False,
        "realtime_response_create": False,
        "first_model_delta": False,
        "spatialreal_avatar": False,
        "public_turn_or_external_media_path": False,
    }
    if level == "product-path":
        includes.update(
            {
                "browser_webrtc_or_equivalent": True,
                "realtime_session_broker": True,
                "mmm_readiness_gate": True,
                "realtime_response_create": True,
                "first_model_delta": True,
            }
        )
        required_evidence = [
            "/api/interviews/:id/realtime/session returned a browser-safe Realtime session contract without exposing a standard provider key",
            "Realtime SDP attach or equivalent adapter path completed without exposing SDP body",
            "/api/interviews/:id/turns/:turnIndex/mmm-ready returned full_mmm_ready=true",
            "Realtime response create was accepted after full_mmm_ready",
            "first Realtime text/audio delta timestamp was recorded",
        ]
        excluded_boundaries = [
            "SpatialReal avatar RTC/egress",
            "public TURN/external media path",
            "final report generation",
        ]
    elif level == "component":
        boundary = args.adapter_boundary or ""
        includes["realtime_session_broker"] = "realtime" in boundary
        includes["mmm_readiness_gate"] = "mmm" in boundary
        includes["first_model_delta"] = "first-delta" in boundary
        required_evidence = [
            "component input timestamp recorded",
            "component output timestamp recorded",
            "component adapter label recorded",
        ]
        excluded_boundaries = [
            "browser WebRTC",
            "full product room UX",
            "SpatialReal avatar RTC/egress",
        ]
        if not includes["realtime_session_broker"]:
            excluded_boundaries.append("Realtime session broker")
        if not includes["mmm_readiness_gate"]:
            excluded_boundaries.append("MMM readiness gate")
    elif level == "full-service-e2e":
        includes.update(
            {
                "browser_webrtc_or_equivalent": True,
                "realtime_session_broker": True,
                "mmm_readiness_gate": True,
                "realtime_response_create": True,
                "first_model_delta": True,
                "spatialreal_avatar": True,
                "public_turn_or_external_media_path": True,
            }
        )
        required_evidence = [
            "browser route created/joined interview room",
            "Realtime session broker returned a browser-safe Realtime session contract",
            "browser performed SDP attach through the configured Realtime call path",
            "full_mmm_ready gate passed before realtime.response.create",
            "first model text/audio delta timestamp was recorded",
            "avatar/media/public path evidence was recorded",
        ]
    else:
        required_evidence = [
            "dataset examples selected",
            "runner artifacts written",
            "fixed timestamp evaluator executed",
        ]
        excluded_boundaries = [
            "GilJob API",
            "browser WebRTC",
            "Realtime provider",
            "MMM analysis",
            "SpatialReal avatar RTC/egress",
        ]
    return {
        "adapter_boundary": args.adapter_boundary,
        "level": level,
        "includes": includes,
        "required_evidence": required_evidence,
        "excluded_boundaries": excluded_boundaries,
    }


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
    first_audio_delta = timestamp_value(
        timestamp_row,
        "t_realtime_first_audio_delta_s",
        "t_realtime_first_audio_delta",
        "t_model_first_audio_delta_s",
        "t_model_first_audio_delta",
        # Compatibility with an earlier planned adapter name.
        "t_gemini_live_first_audio_delta_s",
        "t_gemini_live_first_audio_delta",
        # Legacy split-TTS diagnostic artifacts can still be evaluated.
        "t_tts_first_audio_s",
        "t_tts_first_audio",
    )
    first_text_delta = timestamp_value(
        timestamp_row,
        "t_realtime_first_text_delta_s",
        "t_realtime_first_text_delta",
        "t_model_first_text_delta_s",
        "t_model_first_text_delta",
        # Compatibility with an earlier planned adapter name.
        "t_gemini_live_first_text_delta_s",
        "t_gemini_live_first_text_delta",
    )
    legacy_response_start = timestamp_value(
        timestamp_row,
        "model_response_start_s",
        "t_model_response_start_s",
    )
    response_candidates = [
        value
        for value in (first_audio_delta, first_text_delta, legacy_response_start)
        if value is not None
    ]
    response_start = min(response_candidates) if response_candidates else None
    no_response = response_start is None
    row: dict[str, Any] = {
        "adapter": adapter,
        "example_id": example["example_id"],
        "no_response": no_response,
        "t_user_audio_end_s": user_end,
    }
    for key in (
        "analysis_inline_fixture_used",
        "api_call_broker_observed",
        "api_response_create_observed",
        "browser_webrtc_observed",
        "client_secret_shape_observed",
        "full_product_path_observed",
        "realtime_session_contract_observed",
        "response_command_forwarded_by_probe",
        "technical_realtime_first_delta_observed",
    ):
        if key in timestamp_row:
            row[key] = bool(timestamp_row[key])
    if response_start is not None:
        row["t_model_response_start_s"] = response_start
        row["first_response_latency_ms"] = round((response_start - user_end) * 1000.0, 3)
    if first_text_delta is not None:
        row["t_model_first_text_delta_s"] = first_text_delta
        row["first_text_delta_latency_ms"] = round((first_text_delta - user_end) * 1000.0, 3)
    if first_audio_delta is not None:
        row["t_model_first_audio_delta_s"] = first_audio_delta
        row["first_audio_delta_latency_ms"] = round((first_audio_delta - user_end) * 1000.0, 3)

    input_commit = timestamp_value(
        timestamp_row,
        "t_realtime_input_commit_s",
        "t_realtime_input_commit",
        "t_model_input_commit_s",
        "t_model_input_commit",
        "t_gemini_live_input_commit_s",
        "t_gemini_live_input_commit",
    )
    mmm_ready = timestamp_value(
        timestamp_row,
        "t_mmm_ready_s",
        "t_mmm_ready",
        "t_full_mmm_ready_s",
        "t_full_mmm_ready",
        "full_mmm_ready_s",
    )
    response_create = timestamp_value(
        timestamp_row,
        "t_response_create_s",
        "t_response_create",
        "t_realtime_response_create_s",
        "t_realtime_response_create",
    )
    transcript_ready = timestamp_value(timestamp_row, "t_transcript_ready_s", "t_transcript_ready")
    llm_request = timestamp_value(timestamp_row, "t_llm_request_s", "t_llm_request")
    llm_done = timestamp_value(timestamp_row, "t_llm_done_s", "t_llm_done")
    response_done = timestamp_value(
        timestamp_row,
        "t_realtime_response_done_s",
        "t_realtime_response_done",
        "t_model_response_done_s",
        "t_model_response_done",
        # Compatibility with an earlier planned adapter name.
        "t_gemini_live_response_done_s",
        "t_gemini_live_response_done",
        "t_response_done_s",
        "t_response_done",
    )
    if input_commit is not None:
        row["t_model_input_commit_s"] = input_commit
        row["input_commit_overhead_ms"] = round((input_commit - user_end) * 1000.0, 3)
    if mmm_ready is not None:
        row["t_mmm_ready_s"] = mmm_ready
        row["mmm_ready_latency_ms"] = round((mmm_ready - user_end) * 1000.0, 3)
    if response_create is not None:
        row["t_response_create_s"] = response_create
        reference = mmm_ready if mmm_ready is not None else user_end
        row["response_create_overhead_ms"] = round((response_create - reference) * 1000.0, 3)
    if transcript_ready is not None:
        row["transcript_flush_latency_ms"] = round((transcript_ready - user_end) * 1000.0, 3)
    if llm_request is not None and llm_done is not None:
        row["llm_latency_ms"] = round((llm_done - llm_request) * 1000.0, 3)
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
                "t_realtime_first_audio_delta_s": response_start,
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
                "adapter_boundary": args.adapter_boundary,
                "measurement_contract": measurement_contract(args),
                "measurement_level": args.measurement_level,
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
                    "GILJOB_BENCHMARK_ADAPTER_BOUNDARY": args.adapter_boundary,
                    "GILJOB_BENCHMARK_MEASUREMENT_LEVEL": args.measurement_level,
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
    mmm_ready_count = sum(1 for row in latency_rows if "mmm_ready_latency_ms" in row)
    response_create_count = sum(1 for row in latency_rows if "response_create_overhead_ms" in row)
    first_text_count = sum(1 for row in latency_rows if "first_text_delta_latency_ms" in row)
    first_audio_count = sum(1 for row in latency_rows if "first_audio_delta_latency_ms" in row)
    end_to_end_count = sum(1 for row in latency_rows if "end_to_end_latency_ms" in row)
    product_path_complete_count = sum(
        1
        for row in latency_rows
        if not row["no_response"]
        and not row.get("analysis_inline_fixture_used", False)
        and not row.get("response_command_forwarded_by_probe", False)
        and "mmm_ready_latency_ms" in row
        and "response_create_overhead_ms" in row
        and (
            "first_text_delta_latency_ms" in row
            or "first_audio_delta_latency_ms" in row
        )
    )

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
    limitations = [
        "This is a Realtime first-response latency diagnostic row, not an official full-duplex score.",
        "Adapter timestamps must use the same monotonic clock convention per run.",
    ]
    if any(row.get("adapter") == "simulated-latency" for row in latency_rows):
        limitations.append("simulated-latency adapter only verifies artifact plumbing.")
    if any(row.get("analysis_inline_fixture_used") for row in latency_rows):
        limitations.append(
            "Rows with analysis_inline_fixture_used rely on a candidate-safe inline analysis result instead of a live analysis-engine result and are excluded from product_path_complete."
        )
    if any(row.get("response_command_forwarded_by_probe") for row in latency_rows):
        limitations.append(
            "Rows with response_command_forwarded_by_probe use the benchmark probe to forward the API command on the browser data channel and are excluded from product_path_complete."
        )
    return {
        "evaluator": "fixed-timestamp-latency-v0",
        "limitations": limitations,
        "latency_mean_ms": round(mean, 3) if mean is not None else None,
        "latency_median_ms": median,
        "latency_p95_ms": p95,
        "no_response_count": no_response_count,
        "no_response_rate": float(no_response_count / total) if total else 0.0,
        "evidence_counts": {
            "end_to_end": end_to_end_count,
            "first_audio_delta": first_audio_count,
            "first_text_delta": first_text_count,
            "mmm_ready": mmm_ready_count,
            "product_path_complete": product_path_complete_count,
            "response_create": response_create_count,
        },
        "product_path_complete_rate": float(product_path_complete_count / total) if total else 0.0,
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
        "measurement": measurement_contract(args),
        "adapter": {
            "type": args.adapter,
            "boundary": args.adapter_boundary,
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
            "measurement_label": "GilJob v2 Realtime adapter",
            "measurement": measurement_contract(args),
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
