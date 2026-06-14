#!/usr/bin/env python3
"""Summarize locally acquired benchmark data without reading secret files."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def count_files(path: Path, pattern: str = "*") -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.rglob(pattern) if item.is_file())


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle)


def size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def mib(value: int) -> float:
    return value / 1024 / 1024


def status_line(name: str, path: Path, detail: str = "") -> str:
    status = "ok" if path.exists() else "missing"
    suffix = f", {detail}" if detail else ""
    return f"{name}: {status}, path={path.relative_to(ROOT.parent.parent)}{suffix}"


def count_json_items(path: Path) -> int:
    if not path.exists():
        return 0
    value = json.loads(path.read_text())
    return len(value) if hasattr(value, "__len__") else 0


def main() -> int:
    checks = []

    fd_root = ROOT / "raw" / "fd-bench-v1-v1_5"
    checks.append(
        status_line(
            "FD-bench V1",
            fd_root / "v1.0",
            f"v1_0_files={count_files(fd_root / 'v1.0')}, v1_5_files={count_files(fd_root / 'v1.5')}, size_mib={mib(size_bytes(fd_root)):.1f}",
        )
    )

    qivd_root = ROOT / "raw" / "qivd"
    checks.append(
        status_line(
            "QIVD",
            qivd_root / "labels.json",
            f"labels={count_json_items(qivd_root / 'labels.json')}, mp4_files={count_files(qivd_root / 'videos', '*.mp4')}, size_mib={mib(size_bytes(qivd_root)):.1f}",
        )
    )

    multi_root = ROOT / "raw" / "mimo-audio-evalset" / "multi_challenge"
    checks.append(
        status_line(
            "Audio MultiChallenge",
            multi_root / "data.jsonl",
            f"examples={count_lines(multi_root / 'data.jsonl')}, media_files={count_files(multi_root, '*.mp3') + count_files(multi_root, '*.wav')}, size_mib={mib(size_bytes(multi_root)):.1f}",
        )
    )

    bigbench_root = ROOT / "raw" / "bigbench-audio"
    checks.append(
        status_line(
            "BigBench Audio",
            bigbench_root / "metadata.jsonl",
            f"examples={count_lines(bigbench_root / 'metadata.jsonl')}, mp3_files={count_files(bigbench_root / 'data', '*.mp3')}, size_mib={mib(size_bytes(bigbench_root)):.1f}",
        )
    )

    voicebench_root = ROOT / "raw" / "voicebench-ifeval"
    checks.append(
        status_line(
            "VoiceBench IFEval",
            voicebench_root / "test-00000-of-00001.parquet",
            f"files={count_files(voicebench_root)}, size_mib={mib(size_bytes(voicebench_root)):.1f}",
        )
    )

    ifeval_root = ROOT / "repos" / "google-research" / "instruction_following_eval"
    checks.append(
        status_line(
            "IFEval Text",
            ifeval_root / "data" / "input_data.jsonl",
            f"prompts={count_lines(ifeval_root / 'data' / 'input_data.jsonl')}, files={count_files(ifeval_root)}",
        )
    )

    harmbench_root = ROOT / "repos" / "harmbench"
    checks.append(
        status_line(
            "HarmBench",
            harmbench_root / "data" / "behavior_datasets" / "harmbench_behaviors_text_all.csv",
            f"text_behaviors_all_lines={count_lines(harmbench_root / 'data' / 'behavior_datasets' / 'harmbench_behaviors_text_all.csv')}, files={count_files(harmbench_root / 'data')}, size_mib={mib(size_bytes(harmbench_root / 'data')):.1f}",
        )
    )

    for line in checks:
        print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
