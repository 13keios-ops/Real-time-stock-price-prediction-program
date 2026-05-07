#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
  cat <<'USAGE'
Run a research command against a copied SQLite DB snapshot.

Usage:
  scripts/run_research_on_snapshot.sh [options] -- COMMAND [ARGS...]

Options:
  --src PATH           Source SQLite DB. Default: runtime-data/dev.db
  --snapshot-dir DIR   Snapshot directory.
  --run-dir DIR        Runtime output directory for reports/models.
  --prefix NAME        Snapshot filename prefix. Default: dev
  -h, --help           Show this help.

Example:
  scripts/run_research_on_snapshot.sh -- \
    python -m app --run-cybos-rule-challengers --cybos-profitability-cost-pct 0.13
USAGE
}

default_data_root() {
  if [[ -d /mnt/d ]]; then
    printf '%s\n' "/mnt/d/CodexData/Real-time-stock-price-prediction-program"
  else
    printf '%s\n' "$REPO_ROOT/runtime-data"
  fi
}

src="$REPO_ROOT/runtime-data/dev.db"
snapshot_dir="$(default_data_root)/research-snapshots"
run_dir=""
prefix="dev"
command_args=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --src) src="$2"; shift 2 ;;
    --snapshot-dir) snapshot_dir="$2"; shift 2 ;;
    --run-dir) run_dir="$2"; shift 2 ;;
    --prefix) prefix="$2"; shift 2 ;;
    --) shift; command_args=("$@"); break ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ ${#command_args[@]} -eq 0 ]]; then
  echo "missing research command after --" >&2
  usage >&2
  exit 2
fi

snapshot_json="$("$SCRIPT_DIR/create_research_db_snapshot.sh" --src "$src" --snapshot-dir "$snapshot_dir" --prefix "$prefix" --json)"

read -r database_url snapshot_path created_at <<<"$(python - "$snapshot_json" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
print(payload["database_url"], payload["snapshot_path"], payload["created_at"])
PY
)"

if [[ -z "$run_dir" ]]; then
  safe_stamp="${created_at//:/}"
  safe_stamp="${safe_stamp//+/}"
  safe_stamp="${safe_stamp// /-}"
  run_dir="$(default_data_root)/research-runs/$safe_stamp"
fi
mkdir -p "$run_dir"
run_dir="$(cd "$run_dir" && pwd)"
runtime_dir="$run_dir/runtime-data"
mkdir -p "$runtime_dir"

export DATABASE_URL="$database_url"
export RUNTIME_DATA_DIR="$runtime_dir"

echo "research_run_status=starting"
echo "snapshot_path=$snapshot_path"
echo "database_url=$DATABASE_URL"
echo "runtime_data_dir=$RUNTIME_DATA_DIR"
echo "command=${command_args[*]}"

cd "$REPO_ROOT"
"${command_args[@]}"
