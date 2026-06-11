"""Shared helpers for provisional benchmark runs."""

from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "giljob-benchmark-run/v0"


_TOKEN_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|jwt|secret|password)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
)


def utc_now_iso() -> str:
    return _datetime.datetime.now(_datetime.UTC).replace(microsecond=0).isoformat()


def default_run_id(prefix: str | None = None) -> str:
    stamp = _datetime.datetime.now(_datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    if prefix:
        safe_prefix = re.sub(r"[^A-Za-z0-9_.-]+", "-", prefix).strip("-")
        if safe_prefix:
            return f"{stamp}-{safe_prefix}"
    return stamp


def repo_root_from_file(file_path: str | Path) -> Path:
    path = Path(file_path).resolve()
    for parent in path.parents:
        if (parent / ".git").exists() or (parent / "AGENTS.md").exists():
            return parent
    return path.parents[2]


def ensure_run_dir(run_root: Path, benchmark_id: str, run_id: str) -> Path:
    run_dir = run_root / benchmark_id / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "evaluation").mkdir()
    return run_dir


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSONL") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: JSONL row must be an object")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def _redact_match(match: re.Match[str]) -> str:
    if match.lastindex and match.lastindex >= 2:
        return match.group(0).replace(match.group(2), "[REDACTED]")
    return "[REDACTED]"


def redact_obvious_secrets(text: str) -> str:
    redacted = text
    for pattern in _TOKEN_PATTERNS:
        redacted = pattern.sub(_redact_match, redacted)
    return redacted


def contains_obvious_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in _TOKEN_PATTERNS)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def relative_to_repo(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path)
