#!/usr/bin/env python3
"""Safely extract a tar archive into a target directory."""

from __future__ import annotations

import sys
import tarfile
from pathlib import Path


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: extract_tar_safe.py ARCHIVE DEST", file=sys.stderr)
        return 2

    archive = Path(argv[1]).resolve()
    dest = Path(argv[2]).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive, "r:*") as tar:
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            if not is_relative_to(target, dest):
                raise RuntimeError(f"unsafe tar member path: {member.name}")
        tar.extractall(dest)

    print(f"extracted {archive} -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
