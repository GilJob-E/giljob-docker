#!/usr/bin/env bash
set -euo pipefail

# Remote-only verification harness for OMX worker/leader lanes.
# It packages the committed HEAD tree, uploads it to kiostation, and runs the
# canonical syntax/contract checks only over SSH. Run it after committing the
# worker slice so disposable team overlays (for example generated AGENTS.md) do
# not replace repository contract files in the verification copy. It intentionally
# never sources or prints .env values.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_HOST="${KI_VERIFY_REMOTE_HOST:-hoddukzoa@kiostation}"
REMOTE_PARENT="${KI_VERIFY_REMOTE_PARENT:-/tmp}"
KEEP_REMOTE="${KI_VERIFY_KEEP_REMOTE:-0}"

usage() {
  cat <<USAGE
usage: $0 [--remote user@host] [--remote-parent /tmp] [--keep-remote]

Archives committed HEAD and runs verification on kiostation via ssh.
No tests/lint/build are run on the local machine. Commit changes before running.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote)
      REMOTE_HOST="${2:?missing remote host}"
      shift 2
      ;;
    --remote-parent)
      REMOTE_PARENT="${2:?missing remote parent}"
      shift 2
      ;;
    --keep-remote)
      KEEP_REMOTE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

local_tmp="$(mktemp -d)"
cleanup_local() {
  rm -rf "$local_tmp"
}
trap cleanup_local EXIT

archive="$local_tmp/giljob-v2-head.tgz"
remote_archive="giljob-v2-head-$(date +%Y%m%dT%H%M%S)-$$.tgz"

(
  cd "$ROOT_DIR"
  git archive --format=tar.gz --output="$archive" HEAD
)

remote_archive_path="$REMOTE_PARENT/$remote_archive"
scp -q "$archive" "$REMOTE_HOST:$remote_archive_path"

ssh "$REMOTE_HOST" \
  "REMOTE_ARCHIVE='$remote_archive_path' REMOTE_PARENT='$REMOTE_PARENT' KEEP_REMOTE='$KEEP_REMOTE' bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail
workdir="$(mktemp -d "${REMOTE_PARENT%/}/giljob-v2-verify.XXXXXX")"
cleanup_remote() {
  if [[ "${KEEP_REMOTE:-0}" != "1" ]]; then
    rm -rf "$workdir" "$REMOTE_ARCHIVE"
  else
    echo "Keeping remote verification workspace: $workdir" >&2
    echo "Keeping remote archive: $REMOTE_ARCHIVE" >&2
  fi
}
trap cleanup_remote EXIT

tar -xzf "$REMOTE_ARCHIVE" -C "$workdir"
cd "$workdir"

if [[ ! -f apps/web/node_modules/@spatialwalk/avatarkit-rtc/dist/index.js || ! -f apps/web/node_modules/@spatialwalk/avatarkit/dist/index.js ]]; then
  (cd apps/web && npm ci --ignore-scripts --no-audit --no-fund)
fi

node --check apps/web/static/app.js
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile services/api/server.py services/ai-engine/server.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -v

git init -q
git add -A
git diff --cached --check
REMOTE_SCRIPT
