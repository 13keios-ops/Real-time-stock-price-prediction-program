#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common_process_helpers.sh
source "$SCRIPT_DIR/common_process_helpers.sh"
PYTHON_BIN="$(resolve_python)"
REPO_ROOT="$(repo_root_from_script_dir "$SCRIPT_DIR")"

profile_root=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile-root|-ProfileRoot) profile_root="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$profile_root" ]]; then
  if [[ -d /mnt/d ]]; then
    profile_root="/mnt/d/CodexData/Real-time-stock-price-prediction-program/profiles/dashboard"
  else
    profile_root="$REPO_ROOT/runtime-data/reports/profiles/dashboard"
  fi
fi

profile_dir="$profile_root/dashboard-build-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$profile_dir"

printf '%s\n' \
  "cwd=$REPO_ROOT" \
  "python=$PYTHON_BIN" \
  "command=python -m cProfile -o dashboard-build.cprofile -m app --build-dashboard" \
  > "$profile_dir/command.txt"

set +e
(
  cd "$REPO_ROOT"
  /usr/bin/time -v "$PYTHON_BIN" -m cProfile -o "$profile_dir/dashboard-build.cprofile" -m app --build-dashboard
) >"$profile_dir/stdout.log" 2>"$profile_dir/stderr.log"
status=$?
set -e

"$PYTHON_BIN" - "$profile_dir/dashboard-build.cprofile" "$profile_dir/dashboard-build-top.txt" <<'PY'
import pstats
import sys
from pathlib import Path

profile_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
with out_path.open("w", encoding="utf-8") as fh:
    stats = pstats.Stats(str(profile_path), stream=fh)
    stats.strip_dirs().sort_stats("cumulative").print_stats(40)
    fh.write("\n--- top by internal time ---\n")
    stats.sort_stats("tottime").print_stats(40)
PY

"$PYTHON_BIN" - "$profile_dir/stderr.log" "$profile_dir/summary.json" "$profile_dir" "$status" <<'PY'
import json
import re
import sys
from datetime import datetime
from pathlib import Path

stderr_path = Path(sys.argv[1])
summary_path = Path(sys.argv[2])
profile_dir = Path(sys.argv[3])
status = int(sys.argv[4])
text = stderr_path.read_text(encoding="utf-8", errors="replace")

def find(pattern: str):
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None

payload = {
    "status": "ok" if status == 0 else "failed",
    "exit_code": status,
    "completed_at": datetime.now().astimezone().isoformat(),
    "profile_dir": str(profile_dir),
    "elapsed_wall_clock": find(r"Elapsed \(wall clock\) time.*: (.+)"),
    "max_resident_set_kb": int(find(r"Maximum resident set size \(kbytes\): (\d+)") or 0),
    "user_time_seconds": float(find(r"User time \(seconds\): ([0-9.]+)") or 0.0),
    "system_time_seconds": float(find(r"System time \(seconds\): ([0-9.]+)") or 0.0),
    "cprofile_path": str(profile_dir / "dashboard-build.cprofile"),
    "top_stats_path": str(profile_dir / "dashboard-build-top.txt"),
    "stdout_log_path": str(profile_dir / "stdout.log"),
    "stderr_log_path": str(profile_dir / "stderr.log"),
}
summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY

exit "$status"
