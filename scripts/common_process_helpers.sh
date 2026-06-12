#!/usr/bin/env bash
# Shared helpers for WSL/Linux operation scripts.

script_dir() {
  cd "$(dirname "${BASH_SOURCE[0]}")" && pwd
}

repo_root_from_script_dir() {
  local dir="$1"
  cd "$dir/.." && pwd
}

resolve_python() {
  if [[ -n "${PYTHON:-}" ]] && command -v "$PYTHON" >/dev/null 2>&1; then
    command -v "$PYTHON"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  echo "python executable not found" >&2
  return 1
}

now_text() {
  date '+%Y-%m-%d %H:%M:%S %z'
}

ensure_dir() {
  mkdir -p "$1"
}

json_get() {
  local path="$1"
  local dotted="$2"
  local default_value="${3:-}"
  "$PYTHON_BIN" - "$path" "$dotted" "$default_value" <<'PY'
import json
import sys

path, dotted, default = sys.argv[1:4]
try:
    with open(path, "r", encoding="utf-8-sig") as fh:
        obj = json.load(fh)
except Exception:
    print(default)
    raise SystemExit(0)

cur = obj
for part in dotted.split(".") if dotted else []:
    if isinstance(cur, dict) and part in cur:
        cur = cur[part]
    else:
        print(default)
        raise SystemExit(0)

if cur is None:
    print(default)
elif isinstance(cur, bool):
    print("true" if cur else "false")
elif isinstance(cur, (dict, list)):
    print(json.dumps(cur, ensure_ascii=False))
else:
    print(cur)
PY
}

pid_cmdline() {
  local pid="$1"
  if [[ -r "/proc/$pid/cmdline" ]]; then
    tr '\0' ' ' <"/proc/$pid/cmdline"
  fi
}

pid_running() {
  local pid="$1"
  [[ -n "$pid" ]] && [[ -d "/proc/$pid" ]]
}

pid_matches_all() {
  local pid="$1"
  shift
  pid_running "$pid" || return 1
  local cmd
  cmd="$(pid_cmdline "$pid")"
  [[ -n "$cmd" ]] || return 1
  local pattern
  for pattern in "$@"; do
    [[ "$cmd" == *"$pattern"* ]] || return 1
  done
}

find_pids_matching() {
  local pattern
  ps -eo pid=,args= | while read -r pid args; do
    [[ -n "${pid:-}" ]] || continue
    local ok=1
    for pattern in "$@"; do
      if [[ "$args" != *"$pattern"* ]]; then
        ok=0
        break
      fi
    done
    [[ "$ok" -eq 1 ]] && printf '%s\n' "$pid"
  done
}

kill_pids() {
  local pid
  for pid in "$@"; do
    if pid_running "$pid"; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  sleep 1
  for pid in "$@"; do
    if pid_running "$pid"; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
}

http_contains() {
  local url="$1"
  local needle="$2"
  local timeout="${3:-5}"
  "$PYTHON_BIN" - "$url" "$needle" "$timeout" <<'PY'
import sys
import urllib.request

url, needle, timeout = sys.argv[1], sys.argv[2], float(sys.argv[3])
try:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
        if response.status >= 400:
            raise RuntimeError(response.status)
        if needle and needle not in body:
            raise RuntimeError("needle not found")
except Exception:
    raise SystemExit(1)
PY
}

set_dotenv_value() {
  local path="$1"
  local key="$2"
  local value="$3"
  "$PYTHON_BIN" - "$path" "$key" "$value" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
out = []
updated = False
for line in lines:
    if line.startswith(key + "="):
        out.append(f"{key}={value}")
        updated = True
    else:
        out.append(line)
if not updated:
    out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
}

market_session_status() {
  local workspace_root="$1"
  "$PYTHON_BIN" - "$workspace_root" <<'PY'
from datetime import datetime, timedelta
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
calendar = root / "config" / "market_calendar.toml"
settings = {"session_open": "09:00", "session_close": "15:30"}
holidays = set()
if calendar.exists():
    text = calendar.read_text(encoding="utf-8")
    for key in ["session_open", "session_close"]:
        match = re.search(r"^\s*" + re.escape(key) + r"\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
        if match:
            settings[key] = match.group(1)
    match = re.search(r"^\s*holidays\s*=\s*\[(.*?)\]", text, re.M | re.S)
    if match:
        holidays = {item.strip().strip("'\"") for item in match.group(1).split(",") if item.strip().strip("'\"")}

now = datetime.now()
if now.strftime("%Y-%m-%d") in holidays:
    print("holiday")
elif now.weekday() >= 5:
    print("weekend")
else:
    open_h, open_m = [int(x) for x in settings["session_open"].split(":")[:2]]
    close_h, close_m = [int(x) for x in settings["session_close"].split(":")[:2]]
    opened = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    closed = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
    if now < opened:
        warmup_start = opened - timedelta(minutes=60)
        print("pre-open" if warmup_start <= now < opened else "overnight")
    elif now > closed:
        print("post-close")
    else:
        print("regular-session")
PY
}
