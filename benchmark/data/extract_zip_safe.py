#!/usr/bin/env python3
"""Safely extract zip archives into target directories."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def extract_one(archive: Path, dest: Path) -> None:
    archive = archive.resolve()
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            target = (dest / member.filename).resolve()
            if not is_relative_to(target, dest):
                raise RuntimeError(f"unsafe zip member path: {member.filename}")
        zf.extractall(dest)

    print(f"extracted {archive} -> {dest}")


def main(argv: list[str]) -> int:
    if len(argv) < 3 or len(argv) % 2 != 1:
        print("usage: extract_zip_safe.py ARCHIVE DEST [ARCHIVE DEST ...]", file=sys.stderr)
        return 2

    for index in range(1, len(argv), 2):
        extract_one(Path(argv[index]), Path(argv[index + 1]))

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
