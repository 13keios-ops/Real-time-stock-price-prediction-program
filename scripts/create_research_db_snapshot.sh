#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
  cat <<'USAGE'
Create a consistent SQLite snapshot for offline research without writing to the live DB.

Usage:
  scripts/create_research_db_snapshot.sh [options]

Options:
  --src PATH           Source SQLite DB. Default: runtime-data/dev.db
  --dst PATH           Exact snapshot DB path.
  --snapshot-dir DIR   Snapshot directory when --dst is omitted.
  --prefix NAME        Snapshot filename prefix. Default: dev
  --timeout-seconds N  Maximum snapshot duration. Default: 180.
  --json               Print machine-readable JSON.
  --print-env          Print DATABASE_URL and RUNTIME_DATA_DIR exports.
  -h, --help           Show this help.
USAGE
}

default_snapshot_dir() {
  if [[ -d /mnt/d ]]; then
    printf '%s\n' "/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-snapshots"
  else
    printf '%s\n' "$REPO_ROOT/runtime-data/research-snapshots"
  fi
}

src="$REPO_ROOT/runtime-data/dev.db"
dst=""
snapshot_dir="$(default_snapshot_dir)"
prefix="dev"
as_json="false"
print_env="false"
timeout_seconds="180"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --src) src="$2"; shift 2 ;;
    --dst) dst="$2"; shift 2 ;;
    --snapshot-dir) snapshot_dir="$2"; shift 2 ;;
    --prefix) prefix="$2"; shift 2 ;;
    --timeout-seconds) timeout_seconds="$2"; shift 2 ;;
    --json) as_json="true"; shift ;;
    --print-env) print_env="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if ! [[ "$timeout_seconds" =~ ^[1-9][0-9]*$ ]]; then
  echo "--timeout-seconds must be a positive integer" >&2
  exit 2
fi

if [[ ! -f "$src" ]]; then
  echo "source DB not found: $src" >&2
  exit 1
fi

timestamp="$(date +%Y%m%d-%H%M%S)"
if [[ -z "$dst" ]]; then
  mkdir -p "$snapshot_dir"
  dst="$snapshot_dir/${prefix}-${timestamp}.db"
else
  mkdir -p "$(dirname "$dst")"
fi

set +e
snapshot_json="$(
  timeout --foreground --signal=TERM --kill-after=10s "${timeout_seconds}s" python - "$src" "$dst" <<'PY'
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

src = Path(sys.argv[1]).expanduser().resolve()
dst = Path(sys.argv[2]).expanduser().resolve()
manifest = dst.with_suffix(".manifest.json")
partial = dst.with_name(f".{dst.name}.{os.getpid()}.partial")
partial_manifest = manifest.with_name(f".{manifest.name}.{os.getpid()}.partial")

if not src.exists():
    raise SystemExit(f"source DB not found: {src}")

dst.parent.mkdir(parents=True, exist_ok=True)
partial.unlink(missing_ok=True)
partial_manifest.unlink(missing_ok=True)

try:
    src_uri = f"file:{src}?mode=ro"
    with sqlite3.connect(src_uri, uri=True, timeout=30.0) as src_conn:
        src_conn.execute("PRAGMA busy_timeout = 30000")
        with sqlite3.connect(partial, timeout=30.0) as dst_conn:
            src_conn.backup(dst_conn, pages=1000, sleep=0.05)
            quick_check = dst_conn.execute("PRAGMA quick_check").fetchone()[0]
    if quick_check != "ok":
        raise RuntimeError(f"research snapshot quick_check failed: {quick_check}")
    payload = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_path": str(src),
        "snapshot_path": str(dst),
        "manifest_path": str(manifest),
        "database_url": "sqlite:///" + str(dst),
        "source_size_bytes": src.stat().st_size,
        "snapshot_size_bytes": partial.stat().st_size,
        "quick_check": quick_check,
    }
    partial.replace(dst)
    partial_manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    partial_manifest.replace(manifest)
    print(json.dumps(payload, ensure_ascii=False))
finally:
    partial.unlink(missing_ok=True)
    partial_manifest.unlink(missing_ok=True)
PY
)"
snapshot_status=$?
set -e

if [[ "$snapshot_status" -ne 0 ]]; then
  if [[ "$snapshot_status" -eq 124 ]]; then
    echo "research snapshot timed out after ${timeout_seconds}s; final snapshot was not replaced" >&2
  else
    echo "research snapshot failed with status ${snapshot_status}; final snapshot was not replaced" >&2
  fi
  exit "$snapshot_status"
fi

if [[ "$as_json" == "true" ]]; then
  printf '%s\n' "$snapshot_json"
elif [[ "$print_env" == "true" ]]; then
  python - "$dst" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).expanduser().resolve().with_suffix(".manifest.json").read_text(encoding="utf-8"))
snapshot_path = payload["snapshot_path"]
runtime_dir = str(Path(snapshot_path).with_suffix("").parent / "runtime-data")
print(f"export DATABASE_URL='{payload['database_url']}'")
print(f"export RUNTIME_DATA_DIR='{runtime_dir}'")
PY
else
  python - "$dst" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).expanduser().resolve().with_suffix(".manifest.json").read_text(encoding="utf-8"))
print("research_snapshot_status=ok")
print(f"snapshot_path={payload['snapshot_path']}")
print(f"database_url={payload['database_url']}")
print(f"quick_check={payload['quick_check']}")
print(f"manifest_path={payload['manifest_path']}")
PY
fi
