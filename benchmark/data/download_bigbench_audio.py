#!/usr/bin/env python3
"""Download BigBench Audio mp3 files from the public HF dataset.

This intentionally uses only the Python standard library because the project
environment does not include huggingface_hub or datasets by default.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


REPO_BASE = "https://huggingface.co/datasets/ArtificialAnalysis/big_bench_audio/resolve/main"
ROOT = Path(__file__).resolve().parent
DATASET_DIR = ROOT / "raw" / "bigbench-audio"
METADATA = DATASET_DIR / "metadata.jsonl"


def download(url: str, dest: Path, retries: int = 4) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                with tmp.open("wb") as out:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
            tmp.replace(dest)
            return
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == retries:
                raise RuntimeError(f"failed to download {url}") from exc
            time.sleep(2 * attempt)


def main() -> int:
    if not METADATA.exists():
        raise SystemExit(f"missing metadata: {METADATA}")

    rows = [json.loads(line) for line in METADATA.read_text().splitlines() if line.strip()]
    total = len(rows)

    for index, row in enumerate(rows, start=1):
        rel = row["file_name"]
        url = f"{REPO_BASE}/{urllib.parse.quote(rel)}"
        dest = DATASET_DIR / rel
        download(url, dest)
        if index == 1 or index % 50 == 0 or index == total:
            print(f"downloaded {index}/{total}: {rel}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
