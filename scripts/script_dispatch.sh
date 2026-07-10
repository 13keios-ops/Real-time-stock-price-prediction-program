#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common_process_helpers.sh
source "$SCRIPT_DIR/common_process_helpers.sh"
PYTHON_BIN="$(resolve_python)"
REPO_ROOT="$(repo_root_from_script_dir "$SCRIPT_DIR")"

SCRIPT_NAME="${1:-}"
if [[ -z "$SCRIPT_NAME" ]]; then
  echo "missing script name" >&2
  exit 2
fi
shift || true

ops() {
  "$PYTHON_BIN" "$SCRIPT_DIR/wsl_ops.py" "$@"
}

run_app() {
  (cd "$REPO_ROOT" && "$PYTHON_BIN" -m app "$@")
}

run_dashboard_foreground() {
  local host="127.0.0.1" port="8765" refresh="600" recent="100"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dashboard-host|-DashboardHost) host="$2"; shift 2 ;;
      --port|-Port|--dashboard-port|-DashboardPort) port="$2"; shift 2 ;;
      --refresh-seconds|-RefreshSeconds) refresh="$2"; shift 2 ;;
      --recent-limit|-RecentLimit) recent="$2"; shift 2 ;;
      *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
  done
  run_app --serve-dashboard --dashboard-host "$host" --dashboard-port "$port" --dashboard-refresh-seconds "$refresh" --dashboard-recent-limit "$recent"
}

bump_version() {
  local version=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --version|-Version) version="$2"; shift 2 ;;
      *) [[ -z "$version" ]] && version="$1"; shift ;;
    esac
  done
  [[ -n "$version" ]] || { echo "Version must not be empty." >&2; exit 2; }
  printf '%s\n' "$version" > "$REPO_ROOT/VERSION"
  echo "VERSION updated to $version"
}

watch_git_versions_and_push() {
  local scan_root="$REPO_ROOT" config="autopush.json" state="" log="" poll="60" once="false" recurse="false"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --scan-root|-ScanRoot) scan_root="$2"; shift 2 ;;
      --config-file-name|-ConfigFileName) config="$2"; shift 2 ;;
      --state-path|-StatePath) state="$2"; shift 2 ;;
      --log-path|-LogPath) log="$2"; shift 2 ;;
      --poll-seconds|-PollSeconds) poll="$2"; shift 2 ;;
      --once|-Once) once="true"; shift ;;
      --recurse|-Recurse) recurse="true"; shift ;;
      *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
  done

  local cycle_args=(autopush-cycle --scan-root "$scan_root" --config-file-name "$config")
  [[ -z "$state" ]] || cycle_args+=(--state-path "$state")
  [[ -z "$log" ]] || cycle_args+=(--log-path "$log")
  [[ "$recurse" != "true" ]] || cycle_args+=(--recurse)

  while true; do
    ops "${cycle_args[@]}"
    [[ "$once" == "true" ]] && break
    if command -v inotifywait >/dev/null 2>&1; then
      inotifywait -q -e close_write,create,delete,move --timeout "$poll" "$scan_root" >/dev/null 2>&1 || true
    else
      sleep "$poll"
    fi
  done
}

start_git_autopush_watcher() {
  local scan_root="$REPO_ROOT" poll="60" recurse="false" as_json="false"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --scan-root|-ScanRoot) scan_root="$2"; shift 2 ;;
      --poll-seconds|-PollSeconds) poll="$2"; shift 2 ;;
      --recurse|-Recurse) recurse="true"; shift ;;
      --as-json|-AsJson) as_json="true"; shift ;;
      --task-name|-TaskName) shift 2 ;;
      --ensure-registered|-EnsureRegistered) shift ;;
      *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
  done
  local runtime="$REPO_ROOT/runtime-data/autopush"
  local pid_path="$runtime/git-autopush-watcher.pid"
  local log_path="$runtime/git-autopush.log"
  mkdir -p "$runtime"
  if [[ -f "$pid_path" ]] && pid_matches_all "$(cat "$pid_path")" "watch_git_versions_and_push.sh"; then
    ops autopush-status
    return
  fi
  local args=(--scan-root "$scan_root" --poll-seconds "$poll")
  [[ "$recurse" != "true" ]] || args+=(--recurse)
  nohup "$SCRIPT_DIR/watch_git_versions_and_push.sh" "${args[@]}" >>"$log_path" 2>&1 &
  echo $! > "$pid_path"
  sleep 2
  ops autopush-status
}

stop_git_autopush_watcher() {
  local pid_path="$REPO_ROOT/runtime-data/autopush/git-autopush-watcher.pid"
  if [[ -f "$pid_path" ]]; then
    kill_pids "$(cat "$pid_path")"
    rm -f "$pid_path"
  fi
  mapfile -t pids < <(find_pids_matching "watch_git_versions_and_push.sh") || true
  kill_pids "${pids[@]:-}"
  ops autopush-status
}

test_git_autopush_watcher() {
  local test_root="$REPO_ROOT/.tmp-tests/git-autopush"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --test-root|-TestRoot) test_root="$2"; shift 2 ;;
      *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
  done
  rm -rf "$test_root"
  mkdir -p "$test_root/origin.git" "$test_root/work"
  git init --bare "$test_root/origin.git" >/dev/null
  git init "$test_root/work" >/dev/null
  git -C "$test_root/work" config user.email test@example.invalid
  git -C "$test_root/work" config user.name "Autopush Test"
  git -C "$test_root/work" remote add origin "$test_root/origin.git"
  printf '0.1.0\n' > "$test_root/work/VERSION"
  cat > "$test_root/work/autopush.json" <<'JSON'
{
  "enabled": true,
  "branch": "main",
  "remote": "origin",
  "trigger": "version-change",
  "version_file": "VERSION",
  "stage_mode": "version-only",
  "commit_message": "chore(release): v{version}",
  "commit_body_mode": "none",
  "push_tag": false,
  "tag_name": "v{version}"
}
JSON
  git -C "$test_root/work" add VERSION autopush.json
  git -C "$test_root/work" commit -m init >/dev/null
  git -C "$test_root/work" branch -M main
  git -C "$test_root/work" push -u origin main >/dev/null
  printf '0.2.0\n' > "$test_root/work/VERSION"
  "$SCRIPT_DIR/watch_git_versions_and_push.sh" --scan-root "$test_root/work" --once >/dev/null
  local latest
  latest="$(git -C "$test_root/work" log --oneline -1)"
  [[ "$latest" == *"v0.2.0"* ]] || { echo "autopush test failed: $latest" >&2; exit 1; }
  echo "git autopush watcher test passed"
}

install_git_autopush_service() {
  local scan_root="$REPO_ROOT" poll="60"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --scan-root|-ScanRoot) scan_root="$2"; shift 2 ;;
      --poll-seconds|-PollSeconds) poll="$2"; shift 2 ;;
      --task-name|-TaskName) shift 2 ;;
      --recurse|-Recurse|--ensure-registered|-EnsureRegistered) shift ;;
      *) shift ;;
    esac
  done
  if windows_startup_dir >/dev/null 2>&1; then
    install_windows_startup_launcher \
      "GitAutoPushWatcher.cmd" \
      "GitAutoPushWatcher" \
      "./scripts/start_git_autopush_watcher.sh --scan-root '$scan_root' --poll-seconds $poll"
    return
  fi
  ops install-autopush-service --scan-root "$scan_root" --poll-seconds "$poll"
}

remove_git_autopush_service() {
  systemctl --user disable --now git-autopush-watcher.service >/dev/null 2>&1 || true
  rm -f "$HOME/.config/systemd/user/git-autopush-watcher.service"
  remove_windows_startup_launcher "GitAutoPushWatcher.cmd" || true
  echo "Removed git autopush user service."
}

windows_startup_dir() {
  command -v cmd.exe >/dev/null 2>&1 || return 1
  command -v wslpath >/dev/null 2>&1 || return 1

  local appdata
  appdata="$(cmd.exe /C echo %APPDATA% 2>/dev/null | tr -d '\r' | tail -n 1)"
  [[ -n "$appdata" && "$appdata" != "%APPDATA%" ]] || return 1

  wslpath -u "$appdata\\Microsoft\\Windows\\Start Menu\\Programs\\Startup"
}

install_windows_startup_launcher() {
  local launcher_name="$1" window_title="$2" wsl_command="$3"
  local startup_dir
  startup_dir="$(windows_startup_dir)" || {
    echo "Windows startup folder is not available; skipped $launcher_name"
    return 0
  }

  mkdir -p "$startup_dir"
  local launcher_path="$startup_dir/$launcher_name"
  local distro="${WSL_DISTRO_NAME:-Ubuntu}"
  local log_name="${launcher_name%.cmd}.log"
  cat >"$launcher_path" <<EOF
@echo off
timeout /t 20 /nobreak >nul
start "$window_title" /min "%SystemRoot%\System32\wsl.exe" -d "$distro" --cd "$REPO_ROOT" --exec bash -lc "mkdir -p runtime-data/logs/automation; echo '[windows-startup] start at '\$(date -Is) >> runtime-data/logs/automation/$log_name; $wsl_command >> runtime-data/logs/automation/$log_name 2>&1; rc=\$?; echo '[windows-startup] exit '\$rc' at '\$(date -Is) >> runtime-data/logs/automation/$log_name; exit \$rc"
EOF
  echo "Installed Windows startup launcher: $launcher_path"
}

remove_windows_startup_launcher() {
  local launcher_name="$1"
  local startup_dir
  startup_dir="$(windows_startup_dir)" || return 0
  rm -f "$startup_dir/$launcher_name"
}

install_runtime_service() {
  if windows_startup_dir >/dev/null 2>&1; then
    install_windows_startup_launcher \
      "RealTimeStockRuntime.cmd" \
      "RealTimeStockRuntime" \
      "./scripts/start_runtime_autoboot.sh --skip-runtime-cleanup --skip-dashboard-build"
    return
  fi
  ops install-runtime-service
}

get_runtime_service_status() {
  local service="$HOME/.config/systemd/user/stock-runtime-autoboot.service"
  local startup_dir="" windows_launcher=""
  if startup_dir="$(windows_startup_dir 2>/dev/null)"; then
    windows_launcher="$startup_dir/RealTimeStockRuntime.cmd"
  fi
  "$PYTHON_BIN" - "$service" "$REPO_ROOT" "$windows_launcher" <<'PY'
import json
import os
import sys

service, root, windows_launcher = sys.argv[1:4]
content = open(service, encoding="utf-8").read() if os.path.exists(service) else ""
windows_available = bool(windows_launcher)
windows_content = ""
if windows_launcher and os.path.exists(windows_launcher):
    windows_content = open(windows_launcher, encoding="utf-8", errors="replace").read()

systemd_installed = os.path.exists(service)
systemd_ok = systemd_installed and root in content and "start_runtime_autoboot.sh" in content
windows_installed = bool(windows_launcher) and os.path.exists(windows_launcher)
windows_ok = bool(
    windows_available
    and windows_installed
    and "wsl.exe" in windows_content
    and root in windows_content
    and "start_runtime_autoboot.sh" in windows_content
    and "D:\\GitHub" not in windows_content
)
installed = windows_installed if windows_available else systemd_installed
ok = windows_ok if windows_available else systemd_ok
print(json.dumps({
    "installed": installed,
    "ok": ok,
    "launcher_path": service,
    "workspace_root": root,
    "systemd_user_service": {
        "installed": systemd_installed,
        "ok": systemd_ok,
        "path": service,
    },
    "windows_startup_launcher": {
        "available": windows_available,
        "installed": windows_installed,
        "ok": windows_ok,
        "path": windows_launcher,
    },
}, indent=2))
PY
}

remove_runtime_service() {
  systemctl --user disable --now stock-runtime-autoboot.service >/dev/null 2>&1 || true
  rm -f "$HOME/.config/systemd/user/stock-runtime-autoboot.service"
  remove_windows_startup_launcher "RealTimeStockRuntime.cmd" || true
  echo "Removed runtime startup user service."
}

hourly_loop() {
  while true; do
    ops hourly-audit "$@" || true
    sleep 3600
  done
}

start_hourly_background() {
  local runtime="$REPO_ROOT/runtime-data"
  local workspace="$REPO_ROOT"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --workspace-root|-WorkspaceRoot) workspace="$2"; shift 2 ;;
      --runtime-data-dir|-RuntimeDataDir) runtime="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  local state_dir="$runtime/reports/codex/automation/state"
  local log_dir="$runtime/logs/app"
  mkdir -p "$state_dir" "$log_dir"
  nohup "$SCRIPT_DIR/start_hourly_repo_audit.sh" --workspace-root "$workspace" --runtime-data-dir "$runtime" >"$log_dir/hourly-repo-audit-runner.stdout.log" 2>"$log_dir/hourly-repo-audit-runner.stderr.log" &
  "$PYTHON_BIN" - "$state_dir/runner-state.json" "$!" "$workspace" "$runtime" <<'PY'
import json
import sys
from datetime import datetime
path, pid, root, runtime = sys.argv[1:5]
payload = {
    "automation_name": "Hourly Repo Audit",
    "status": "running",
    "pid": int(pid),
    "workspace_root": root,
    "runtime_data_dir": runtime,
    "started_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z"),
}
open(path, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
}

get_hourly_status() {
  local runtime="$REPO_ROOT/runtime-data"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --runtime-data-dir|-RuntimeDataDir) runtime="$2"; shift 2 ;;
      --workspace-root|-WorkspaceRoot) shift 2 ;;
      *) shift ;;
    esac
  done
  local state="$runtime/reports/codex/automation/state/runner-state.json"
  if [[ -f "$state" ]]; then
    cat "$state"
  else
    printf '{\n  "status": "stopped",\n  "process_running": false,\n  "raw_status": "missing"\n}\n'
  fi
}

stop_hourly() {
  mapfile -t pids < <(find_pids_matching "start_hourly_repo_audit.sh") || true
  kill_pids "${pids[@]:-}"
  echo "Stopped hourly repo audit pid(s) ${pids[*]:-none}."
}

export_to_nas() {
  local backup_root=""
  local passthrough=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --backup-share-root|-BackupShareRoot) backup_root="$2"; shift 2 ;;
      *) passthrough+=("$1"); shift ;;
    esac
  done
  [[ -n "$backup_root" ]] || { echo "BackupShareRoot is required" >&2; exit 2; }
  ops export-recovery --destination-root "$backup_root/repos/real-time-stock-price-prediction-program/recovery-exports" --package-prefix "real-time-stock-price-prediction-program-recovery" "${passthrough[@]}"
}

restore_kis_env_interactive() {
  local mode="paper" include="false" read_only_preparation="false" workspace="$REPO_ROOT"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --trading-mode|-TradingMode) mode="$2"; shift 2 ;;
      --include-account-fields|-IncludeAccountFields) include="true"; shift ;;
      --read-only-preparation|-ReadOnlyPreparation) read_only_preparation="true"; shift ;;
      --workspace-root|-WorkspaceRoot) workspace="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  [[ "$mode" == "paper" || "$mode" == "live" ]] || { echo "TradingMode must be paper or live" >&2; exit 2; }
  if [[ "$read_only_preparation" == "true" && "$mode" != "live" ]]; then
    echo "--read-only-preparation requires --trading-mode live" >&2
    exit 2
  fi
  local env_path="$workspace/.env"
  [[ -f "$env_path" ]] || cp "$workspace/.env.example" "$env_path"
  local prefix="PAPER"
  [[ "$mode" == "live" ]] && prefix="LIVE"
  if [[ "$read_only_preparation" == "true" ]]; then
    echo "KIS .env restore (live read-only preparation; trading mode preserved)"
  else
    echo "KIS .env restore ($mode)"
  fi
  read -r -s -p "KIS_APP_KEY_$prefix: " app_key
  echo
  read -r -s -p "KIS_APP_SECRET_$prefix: " app_secret
  echo
  if [[ "$read_only_preparation" != "true" ]]; then
    set_dotenv_value "$env_path" "TRADING_MODE" "$mode"
  fi
  set_dotenv_value "$env_path" "KIS_APP_KEY_$prefix" "$app_key"
  set_dotenv_value "$env_path" "KIS_APP_SECRET_$prefix" "$app_secret"
  if [[ "$include" == "true" ]]; then
    read -r -p "KIS_ACCOUNT_NO_$prefix: " account
    set_dotenv_value "$env_path" "KIS_ACCOUNT_NO_$prefix" "$account"
    if [[ "$prefix" == "PAPER" ]]; then
      set_dotenv_value "$env_path" "KIS_PRODUCT_CODE_PAPER" ""
    else
      read -r -p "KIS_PRODUCT_CODE_$prefix: " product_code
      set_dotenv_value "$env_path" "KIS_PRODUCT_CODE_$prefix" "$product_code"
    fi
  fi
  if [[ "$mode" == "paper" || "$read_only_preparation" == "true" ]]; then
    set_dotenv_value "$env_path" "ALLOW_LIVE_ORDERS" "false"
  fi
  echo ".env saved: $env_path"
}

connect_kis_paper_account_interactive() {
  local workspace="$REPO_ROOT"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --workspace-root|-WorkspaceRoot) workspace="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  local env_path="$workspace/.env"
  [[ -f "$env_path" ]] || { echo "Missing .env. Restore KIS app key and secret first." >&2; exit 1; }
  read -r -p "KIS_ACCOUNT_NO_PAPER (8 digits, or 8 digits-2 digits): " account
  [[ "$account" =~ ^[0-9]{8}(-[0-9]{2})?$ ]] || { echo "invalid account format" >&2; exit 2; }
  set_dotenv_value "$env_path" TRADING_MODE paper
  set_dotenv_value "$env_path" ALLOW_LIVE_ORDERS false
  set_dotenv_value "$env_path" ENABLE_PAPER_EXECUTION true
  set_dotenv_value "$env_path" ENABLE_BROKER_PAPER_MIRRORING true
  set_dotenv_value "$env_path" KIS_ACCOUNT_NO_PAPER "$account"
  set_dotenv_value "$env_path" KIS_PRODUCT_CODE_PAPER ""
  echo ".env saved; paper account connected."
}

post_close_data_root() {
  if [[ -d /mnt/d ]]; then
    printf '%s\n' "/mnt/d/CodexData/Real-time-stock-price-prediction-program"
  else
    printf '%s\n' "$REPO_ROOT/runtime-data"
  fi
}

write_post_close_skip_state() {
  local state_path="$1" workspace="$2" runtime="$3" reason="$4" mode="$5" horizon="${6:-15}" recent_days="${7:-10}" skip_build="${8:-false}"
  "$PYTHON_BIN" - "$state_path" "$workspace" "$runtime" "$reason" "$mode" "$horizon" "$recent_days" "$skip_build" <<'PY'
import json
import sys
from datetime import datetime

path, root, runtime, reason, mode, horizon, recent_days, skip_build = sys.argv[1:9]
payload = {
    "status": "skipped",
    "maintenance_date": datetime.now().strftime("%Y-%m-%d"),
    "completed_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z"),
    "workspace_root": root,
    "runtime_data_dir": runtime,
    "mode": mode,
    "skip_reason": reason,
}
if mode in {"quick-live-train", "heavy-snapshot", "heavy-live-db"}:
    maintenance_scope = "quick" if mode == "quick-live-train" else "heavy"
    payload.update(
        {
            "horizon_min": int(horizon),
            "maintenance_scope": maintenance_scope,
            "tasks": [],
            "time_cap_target_minutes": 10 if maintenance_scope == "quick" else None,
            "snapshot_path": "",
            "snapshot_manifest_path": "",
            "snapshot_runtime_data_dir": "",
        }
    )
else:
    payload.update(
        {
            "tasks": [],
            "recent_days": int(recent_days),
            "skipped_feature_label_build": skip_build == "true",
            "time_cap_target_minutes": None,
            "exit_code": 0,
        }
    )
open(path, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
}

post_close_ml_maintenance() {
  local workspace="$REPO_ROOT" runtime="" horizon="15" use_snapshot="false" snapshot_dir="" run_dir="" maintenance_mode="quick" force_run="false"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --workspace-root|-WorkspaceRoot) workspace="$2"; shift 2 ;;
      --runtime-data-dir|-RuntimeDataDir) runtime="$2"; shift 2 ;;
      --horizon-min|-HorizonMin) horizon="$2"; shift 2 ;;
      --snapshot-dir|-SnapshotDir) snapshot_dir="$2"; shift 2 ;;
      --run-dir|-RunDir) run_dir="$2"; shift 2 ;;
      --quick|-Quick) maintenance_mode="quick"; use_snapshot="false"; shift ;;
      --heavy-research|-HeavyResearch) maintenance_mode="heavy"; use_snapshot="true"; shift ;;
      --mode|-Mode)
        case "$2" in
          quick) maintenance_mode="quick"; use_snapshot="false" ;;
          heavy|heavy-research|snapshot) maintenance_mode="heavy"; use_snapshot="true" ;;
          *) echo "unknown post-close maintenance mode: $2" >&2; exit 2 ;;
        esac
        shift 2
        ;;
      --live-db|-LiveDb|--no-snapshot|-NoSnapshot) use_snapshot="false"; shift ;;
      --use-snapshot|-UseSnapshot) maintenance_mode="heavy"; use_snapshot="true"; shift ;;
      --force|-Force) force_run="true"; shift ;;
      --restart-live-runtime|-RestartLiveRuntime) shift ;;
      *) shift ;;
    esac
  done
  [[ -n "$runtime" ]] || runtime="$workspace/runtime-data"
  local state_dir="$runtime/reports/ml-maintenance/state"
  local state_path="$state_dir/latest-post-close-ml.json"
  mkdir -p "$state_dir"
  if [[ "$force_run" != "true" ]]; then
    if "$PYTHON_BIN" - "$state_path" "$horizon" "$maintenance_mode" <<'PY'
import json
import sys
from datetime import datetime

path, horizon, maintenance_mode = sys.argv[1:4]
try:
    payload = json.load(open(path, encoding="utf-8"))
except Exception:
    raise SystemExit(1)
if (
    payload.get("status") == "ok"
    and payload.get("maintenance_date") == datetime.now().strftime("%Y-%m-%d")
    and int(payload.get("horizon_min", -1)) == int(horizon)
    and str(payload.get("maintenance_scope") or "") == maintenance_mode
):
    raise SystemExit(0)
raise SystemExit(1)
PY
    then
      echo "post-close ML maintenance already ok for today; skipping. Use --force to rerun." >&2
      cat "$state_path"
      return 0
    fi
  fi
  local session_status
  session_status="$(market_session_status "$workspace")"
  if [[ "$force_run" != "true" && "$session_status" =~ ^(weekend|holiday)$ ]]; then
    local skip_mode="quick-live-train"
    [[ "$maintenance_mode" != "quick" && "$use_snapshot" == "true" ]] && skip_mode="heavy-snapshot"
    [[ "$maintenance_mode" != "quick" && "$use_snapshot" != "true" ]] && skip_mode="heavy-live-db"
    write_post_close_skip_state "$state_path" "$workspace" "$runtime" "market_session_${session_status}_no_post_close_maintenance" "$skip_mode" "$horizon"
    return 0
  fi
  local snapshot_path="" snapshot_manifest="" snapshot_runtime="" database_url=""
  if [[ "$maintenance_mode" == "quick" ]]; then
    run_app --build-runtime-report >/dev/null
    (
      cd "$workspace"
      "$SCRIPT_DIR/check_local_setup.sh" >/dev/null
    ) || echo "warning: local setup readiness check failed during quick post-close maintenance" >&2
    (
      cd "$workspace"
      "$PYTHON_BIN" scripts/summarize_kis_live_data_quality.py --recent-days 10 >/dev/null
    ) || echo "warning: KIS live data quality summary failed during quick post-close maintenance" >&2
    (
      cd "$workspace"
      "$PYTHON_BIN" scripts/summarize_feature_source_drift.py >/dev/null
    ) || echo "warning: feature source drift summary failed during quick post-close maintenance" >&2
    (
      cd "$workspace"
      "$PYTHON_BIN" scripts/summarize_kis_live_feature_diagnostics.py >/dev/null
    ) || echo "warning: KIS live feature diagnostics summary failed during quick post-close maintenance" >&2
    run_app --train-lightgbm --horizon-min "$horizon" >/dev/null
    run_app --run-challengers --horizon-min "$horizon" >/dev/null
    run_app --build-dashboard >/dev/null
  elif [[ "$use_snapshot" == "true" ]]; then
    local data_root
    data_root="$(post_close_data_root)"
    [[ -n "$snapshot_dir" ]] || snapshot_dir="$data_root/research-snapshots"
    [[ -n "$run_dir" ]] || run_dir="$data_root/research-runs/post-close-$(date +%Y%m%d)-h${horizon}"
    mkdir -p "$run_dir"
    local snapshot_json
    snapshot_json="$("$SCRIPT_DIR/create_research_db_snapshot.sh" --src "$workspace/runtime-data/dev.db" --snapshot-dir "$snapshot_dir" --prefix "post-close-h${horizon}" --json)"
    read -r database_url snapshot_path snapshot_manifest <<<"$("$PYTHON_BIN" - "$snapshot_json" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
print(payload["database_url"], payload["snapshot_path"], payload["manifest_path"])
PY
)"
    snapshot_runtime="$run_dir/runtime-data"
    mkdir -p "$snapshot_runtime"
    (
      export DATABASE_URL="$database_url"
      export RUNTIME_DATA_DIR="$snapshot_runtime"
      run_app --rebuild-actual-ml --horizon-min "$horizon" >/dev/null
      run_app --build-runtime-report >/dev/null
      run_app --build-dashboard >/dev/null
    )
  else
    run_app --rebuild-actual-ml --horizon-min "$horizon" >/dev/null
    run_app --build-runtime-report >/dev/null
    run_app --build-dashboard >/dev/null
  fi
  "$PYTHON_BIN" - "$state_path" "$workspace" "$runtime" "$horizon" "$maintenance_mode" "$use_snapshot" "$snapshot_path" "$snapshot_manifest" "$snapshot_runtime" <<'PY'
import json
import sys
from datetime import datetime
path, root, runtime, horizon, maintenance_mode, use_snapshot, snapshot_path, snapshot_manifest, snapshot_runtime = sys.argv[1:10]
if maintenance_mode == "quick":
    mode = "quick-live-train"
    tasks = [
        "build-runtime-report",
        "check-local-setup",
        "summarize-kis-live-data-quality",
        "summarize-feature-source-drift",
        "summarize-kis-live-feature-diagnostics",
        "train-lightgbm-bounded",
        "run-challengers-bounded",
        "build-dashboard",
    ]
elif use_snapshot == "true":
    mode = "heavy-snapshot"
    tasks = ["create-research-db-snapshot", "rebuild-actual-ml", "build-runtime-report", "build-dashboard"]
else:
    mode = "heavy-live-db"
    tasks = ["rebuild-actual-ml", "build-runtime-report", "build-dashboard"]
payload = {
    "status": "ok",
    "maintenance_date": datetime.now().strftime("%Y-%m-%d"),
    "completed_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z"),
    "workspace_root": root,
    "runtime_data_dir": runtime,
    "horizon_min": int(horizon),
    "mode": mode,
    "maintenance_scope": maintenance_mode,
    "tasks": tasks,
    "time_cap_target_minutes": 10 if maintenance_mode == "quick" else None,
    "snapshot_path": snapshot_path,
    "snapshot_manifest_path": snapshot_manifest,
    "snapshot_runtime_data_dir": snapshot_runtime,
}
open(path, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
  run_app --build-dashboard >/dev/null
}

post_close_label_refresh() {
  local workspace="$REPO_ROOT" runtime="" recent_days="10" skip_build="false" dry_run="false" force_run="false"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --workspace-root|-WorkspaceRoot) workspace="$2"; shift 2 ;;
      --runtime-data-dir|-RuntimeDataDir) runtime="$2"; shift 2 ;;
      --recent-days|-RecentDays) recent_days="$2"; shift 2 ;;
      --skip-build|-SkipBuild) skip_build="true"; shift ;;
      --dry-run|-DryRun) dry_run="true"; shift ;;
      --force|-Force) force_run="true"; shift ;;
      *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
  done
  [[ -n "$runtime" ]] || runtime="$workspace/runtime-data"
  local state_dir="$runtime/reports/ml-maintenance/state"
  local state_path="$state_dir/latest-post-close-label-refresh.json"
  mkdir -p "$state_dir"
  if [[ "$force_run" != "true" && "$dry_run" != "true" ]]; then
    if "$PYTHON_BIN" - "$state_path" "$recent_days" "$skip_build" <<'PY'
import json
import sys
from datetime import datetime

path, recent_days, skip_build = sys.argv[1:4]
try:
    payload = json.load(open(path, encoding="utf-8"))
except Exception:
    raise SystemExit(1)
if (
    payload.get("status") == "ok"
    and payload.get("maintenance_date") == datetime.now().strftime("%Y-%m-%d")
    and int(payload.get("recent_days", -1)) == int(recent_days)
    and bool(payload.get("skipped_feature_label_build")) == (skip_build == "true")
):
    raise SystemExit(0)
raise SystemExit(1)
PY
    then
      echo "post-close label refresh already ok for today; skipping. Use --force to rerun." >&2
      cat "$state_path"
      return 0
    fi
  fi
  local session_status
  session_status="$(market_session_status "$workspace")"
  if [[ "$force_run" != "true" && "$dry_run" != "true" && "$session_status" =~ ^(weekend|holiday)$ ]]; then
    write_post_close_skip_state "$state_path" "$workspace" "$runtime" "market_session_${session_status}_no_post_close_label_refresh" "post-close-label-refresh-live-db" "15" "$recent_days" "$skip_build"
    return 0
  fi

  local tasks=()
  [[ "$skip_build" == "true" ]] || tasks+=("build-feature-dataset")
  tasks+=(
    "summarize-kis-live-data-quality"
    "summarize-feature-source-drift"
    "summarize-kis-live-feature-diagnostics"
    "build-runtime-report"
    "build-dashboard"
  )

  write_label_refresh_state() {
    local status="$1" exit_code="${2:-0}"
    "$PYTHON_BIN" - "$state_path" "$workspace" "$runtime" "$recent_days" "$skip_build" "$status" "$exit_code" "${tasks[@]}" <<'PY'
import json
import sys
from datetime import datetime

path, root, runtime, recent_days, skip_build, status, exit_code, *tasks = sys.argv[1:]
payload = {
    "status": status,
    "maintenance_date": datetime.now().strftime("%Y-%m-%d"),
    "completed_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z"),
    "workspace_root": root,
    "runtime_data_dir": runtime,
    "mode": "post-close-label-refresh-live-db",
    "tasks": tasks,
    "recent_days": int(recent_days),
    "skipped_feature_label_build": skip_build == "true",
    "time_cap_target_minutes": None,
    "exit_code": int(exit_code),
}
open(path, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
  }

  run_label_app_step() {
    printf '+ python -m app'
    printf ' %q' "$@"
    printf '\n'
    [[ "$dry_run" == "true" ]] || run_app "$@"
  }

  run_label_python_step() {
    printf '+ python'
    printf ' %q' "$@"
    printf '\n'
    [[ "$dry_run" == "true" ]] || (cd "$workspace" && "$PYTHON_BIN" "$@")
  }

  if [[ "$dry_run" == "true" ]]; then
    [[ "$skip_build" == "true" ]] || run_label_app_step --build-feature-dataset --feature-dataset-recent-days "$recent_days"
    run_label_python_step scripts/summarize_kis_live_data_quality.py --recent-days "$recent_days"
    run_label_python_step scripts/summarize_feature_source_drift.py
    run_label_python_step scripts/summarize_kis_live_feature_diagnostics.py
    run_label_app_step --build-runtime-report
    run_label_app_step --build-dashboard
    return 0
  fi

  write_label_refresh_state "running" 0 >/dev/null
  trap 'code=$?; if [[ $code -ne 0 ]]; then write_label_refresh_state "failed" "$code" >/dev/null || true; fi' EXIT

  [[ "$skip_build" == "true" ]] || run_label_app_step --build-feature-dataset --feature-dataset-recent-days "$recent_days"
  run_label_python_step scripts/summarize_kis_live_data_quality.py --recent-days "$recent_days"
  run_label_python_step scripts/summarize_feature_source_drift.py
  run_label_python_step scripts/summarize_kis_live_feature_diagnostics.py
  run_label_app_step --build-runtime-report
  write_label_refresh_state "ok" 0
  run_label_app_step --build-dashboard
  trap - EXIT
}

storage_migration_dry_run() {
  local source_db="$REPO_ROOT/runtime-data/dev.db"
  local work_dir="$REPO_ROOT/.tmp-tests/storage-migration-dry-run"
  local report_path=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --source-db|-SourceDb) source_db="$2"; shift 2 ;;
      --work-dir|-WorkDir) work_dir="$2"; shift 2 ;;
      --report-path|-ReportPath) report_path="$2"; shift 2 ;;
      *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
  done
  [[ -n "$report_path" ]] || report_path="$work_dir/latest-storage-migration-dry-run.json"
  "$PYTHON_BIN" - "$REPO_ROOT" "$source_db" "$work_dir" "$report_path" <<'PY'
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from app.storage.sqlite_store import SQLiteRuntimeStore


def is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


root = Path(sys.argv[1]).resolve()
source_db = Path(sys.argv[2]).expanduser().resolve()
work_dir = Path(sys.argv[3]).expanduser().resolve()
report_path = Path(sys.argv[4]).expanduser().resolve()

if not is_relative_to(work_dir, root):
    raise SystemExit(f"work_dir must stay inside repository root: {work_dir}")
if not is_relative_to(report_path, root):
    raise SystemExit(f"report_path must stay inside repository root: {report_path}")

work_dir.mkdir(parents=True, exist_ok=True)
report_path.parent.mkdir(parents=True, exist_ok=True)
dry_db = work_dir / "storage-migration-dry-run.sqlite3"
if dry_db.exists():
    dry_db.unlink()

source_exists = source_db.exists()
if source_exists:
    shutil.copy2(source_db, dry_db)

SQLiteRuntimeStore(dry_db, initialize_schema=True)

required_tables = [
    "market_status_snapshots",
    "live_orders",
    "live_order_events",
    "live_fills",
    "live_positions",
    "live_portfolio_snapshots",
    "ops_live_audit_events",
    "live_phase_approvals",
    "live_readiness_runs",
]
required_indexes = [
    "idx_market_status_day_hash",
    "idx_live_orders_status_symbol_day",
    "idx_live_orders_broker",
    "idx_live_orders_parent",
    "idx_live_order_events_order_time",
    "idx_live_fills_order_time",
    "idx_live_fills_broker",
    "idx_live_fills_symbol_day",
    "idx_live_positions_updated_at",
    "idx_live_portfolio_snapshots_time",
    "idx_ops_live_audit_order_time",
    "idx_ops_live_audit_hash",
    "idx_live_phase_approvals_day_phase",
    "idx_live_phase_approvals_expires",
    "idx_live_readiness_runs_day_phase",
]
with sqlite3.connect(dry_db) as connection:
    table_rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    index_rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index'"
    ).fetchall()

tables = sorted(row[0] for row in table_rows)
indexes = sorted(row[0] for row in index_rows)
missing_tables = [name for name in required_tables if name not in tables]
missing_indexes = [name for name in required_indexes if name not in indexes]
status = "ok" if not missing_tables and not missing_indexes else "failed"

payload = {
    "status": status,
    "completed_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z"),
    "workspace_root": str(root),
    "source_db": str(source_db),
    "source_db_exists": source_exists,
    "dry_run_db": str(dry_db),
    "report_path": str(report_path),
    "required_tables": required_tables,
    "required_indexes": required_indexes,
    "missing_tables": missing_tables,
    "missing_indexes": missing_indexes,
}
report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, indent=2))
if status != "ok":
    raise SystemExit(1)
PY
}

storage_migration_apply() {
  local database_path="$REPO_ROOT/runtime-data/dev.db"
  local backup_dir="$REPO_ROOT/runtime-data/backups/storage-migrations"
  local report_path="$REPO_ROOT/runtime-data/reports/storage-migration/latest-storage-migration-apply.json"
  local apply="false" skip_service_check="false"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --database-path|-DatabasePath) database_path="$2"; shift 2 ;;
      --backup-dir|-BackupDir) backup_dir="$2"; shift 2 ;;
      --report-path|-ReportPath) report_path="$2"; shift 2 ;;
      --apply|-Apply) apply="true"; shift ;;
      --skip-service-check|-SkipServiceCheck) skip_service_check="true"; shift ;;
      *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
  done
  "$PYTHON_BIN" - "$REPO_ROOT" "$database_path" "$backup_dir" "$report_path" "$apply" "$skip_service_check" <<'PY'
import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from app.storage.sqlite_store import SQLiteRuntimeStore


REQUIRED_TABLES = [
    "market_status_snapshots",
    "live_orders",
    "live_order_events",
    "live_fills",
    "live_positions",
    "live_portfolio_snapshots",
    "ops_live_audit_events",
    "live_phase_approvals",
    "live_readiness_runs",
]
REQUIRED_INDEXES = [
    "idx_market_status_day_hash",
    "idx_live_orders_status_symbol_day",
    "idx_live_orders_broker",
    "idx_live_orders_parent",
    "idx_live_order_events_order_time",
    "idx_live_fills_order_time",
    "idx_live_fills_broker",
    "idx_live_fills_symbol_day",
    "idx_live_positions_updated_at",
    "idx_live_portfolio_snapshots_time",
    "idx_ops_live_audit_order_time",
    "idx_ops_live_audit_hash",
    "idx_live_phase_approvals_day_phase",
    "idx_live_phase_approvals_expires",
    "idx_live_readiness_runs_day_phase",
]


def is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def status_payload(root: Path, script_name: str) -> dict:
    script_path = root / "scripts" / script_name
    result = subprocess.run(
        ["bash", str(script_path)],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {
            "status": "status_check_failed",
            "script": script_name,
            "returncode": result.returncode,
            "stderr": result.stderr.strip(),
        }
    try:
        payload = json.loads(result.stdout)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    return {
        "status": "status_check_invalid_json",
        "script": script_name,
        "stdout": result.stdout.strip(),
    }


def services_are_stopped(root: Path) -> tuple[bool, dict]:
    live_status = status_payload(root, "get_live_runtime_status.sh")
    dashboard_status = status_payload(root, "get_dashboard_status.sh")
    watchdog_status = status_payload(root, "get_runtime_watchdog_status.sh")
    live_running = bool(live_status.get("process_running")) or live_status.get("status") == "running"
    dashboard_running = bool(dashboard_status.get("process_running")) or dashboard_status.get("status") == "running"
    watchdog_running = bool(watchdog_status.get("process_running")) or watchdog_status.get("status") == "running"
    checks = {
        "live_runtime": live_status,
        "dashboard": dashboard_status,
        "runtime_watchdog": watchdog_status,
        "live_runtime_running": live_running,
        "dashboard_running": dashboard_running,
        "runtime_watchdog_running": watchdog_running,
    }
    return not live_running and not dashboard_running and not watchdog_running, checks


def restore_sqlite_backup(backup_path: Path, database_path: Path) -> None:
    with sqlite3.connect(backup_path) as source, sqlite3.connect(database_path) as target:
        source.backup(target)


def run_sample_smoke_check(database_path: Path) -> list[str]:
    smoke_id = "__storage_migration_smoke__"
    now = datetime.now().astimezone().isoformat()
    errors: list[str] = []
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("BEGIN")
        connection.execute("DELETE FROM live_order_events WHERE order_id = ?", (smoke_id,))
        connection.execute("DELETE FROM live_fills WHERE order_id = ?", (smoke_id,))
        connection.execute("DELETE FROM live_orders WHERE order_id = ?", (smoke_id,))
        connection.execute("DELETE FROM live_positions WHERE symbol = ?", ("__SMOKE__",))
        connection.execute("DELETE FROM live_portfolio_snapshots WHERE snapshot_id = ?", (smoke_id,))
        connection.execute("DELETE FROM ops_live_audit_events WHERE audit_event_id = ?", (smoke_id,))
        connection.execute("DELETE FROM live_phase_approvals WHERE approval_id = ?", (smoke_id,))
        connection.execute("DELETE FROM live_readiness_runs WHERE readiness_id = ?", (smoke_id,))
        connection.execute("DELETE FROM market_status_snapshots WHERE snapshot_id = ?", (smoke_id,))
        connection.execute(
            """
            INSERT INTO market_status_snapshots(
                snapshot_id,
                trading_day,
                created_at,
                source,
                symbol_set_hash,
                status_json,
                stale_after
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                smoke_id,
                "2099-12-31",
                now,
                "migration_smoke",
                smoke_id,
                json.dumps({"smoke": True}, ensure_ascii=False, sort_keys=True),
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO live_orders(
                order_id,
                idempotency_key,
                trading_day,
                phase,
                symbol,
                side,
                qty,
                filled_qty,
                remaining_qty,
                order_type,
                limit_price,
                avg_fill_price,
                status,
                prediction_id,
                signal_id,
                target_id,
                gate_decision_id,
                market_status_snapshot_id,
                model_version,
                rule_version,
                broker_order_no,
                broker_branch_no,
                reject_reason,
                cancel_reason,
                parent_order_id,
                created_at,
                submitted_at,
                last_synced_at,
                detail_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                smoke_id,
                smoke_id,
                "2099-12-31",
                "phase2_conservative",
                "005930",
                "buy",
                1,
                0,
                1,
                "limit",
                70000.0,
                0.0,
                "intent_created",
                smoke_id,
                smoke_id,
                smoke_id,
                smoke_id,
                smoke_id,
                "migration-smoke-model",
                "migration-smoke-rule",
                "",
                "",
                None,
                None,
                None,
                now,
                None,
                None,
                json.dumps({"smoke": True}, ensure_ascii=False, sort_keys=True),
            ),
        )
        connection.execute(
            """
            INSERT INTO live_order_events(
                order_event_id,
                order_id,
                event_time,
                from_status,
                to_status,
                event_type,
                actor,
                detail_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{smoke_id}_event",
                smoke_id,
                now,
                "none",
                "intent_created",
                "migration_smoke",
                "system",
                json.dumps({"smoke": True}, ensure_ascii=False, sort_keys=True),
            ),
        )
        connection.execute(
            """
            INSERT INTO live_fills(
                fill_id,
                order_id,
                broker_order_no,
                broker_branch_no,
                symbol,
                trading_day,
                event_time,
                side,
                fill_qty,
                fill_price,
                commission,
                tax,
                fee,
                settlement_day,
                detail_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                smoke_id,
                smoke_id,
                "smoke-broker-order",
                "smoke-branch",
                "005930",
                "2099-12-31",
                now,
                "buy",
                1,
                70000.0,
                0.0,
                0.0,
                0.0,
                "2100-01-02",
                json.dumps({"smoke": True}, ensure_ascii=False, sort_keys=True),
            ),
        )
        connection.execute(
            """
            INSERT INTO live_positions(
                symbol,
                trading_day,
                opened_at,
                updated_at,
                qty,
                avg_price,
                last_price,
                market_value,
                cost_basis,
                realized_pnl,
                unrealized_pnl,
                day_realized_pnl,
                broker_qty,
                detail_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "__SMOKE__",
                "2099-12-31",
                now,
                now,
                1,
                70000.0,
                70000.0,
                70000.0,
                70000.0,
                0.0,
                0.0,
                0.0,
                1,
                json.dumps({"smoke": True}, ensure_ascii=False, sort_keys=True),
            ),
        )
        connection.execute(
            """
            INSERT INTO live_portfolio_snapshots(
                snapshot_id,
                trading_day,
                event_time,
                cash_balance,
                available_cash,
                unsettled_cash,
                gross_market_value,
                net_liquidation_value,
                realized_pnl,
                unrealized_pnl,
                daily_pnl,
                open_positions,
                margin_requirement,
                detail_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                smoke_id,
                "2099-12-31",
                now,
                100000.0,
                100000.0,
                0.0,
                70000.0,
                170000.0,
                0.0,
                0.0,
                0.0,
                1,
                0.0,
                json.dumps({"smoke": True}, ensure_ascii=False, sort_keys=True),
            ),
        )
        connection.execute(
            """
            INSERT INTO ops_live_audit_events(
                audit_event_id,
                event_time,
                trading_day,
                event_type,
                actor,
                symbol,
                order_id,
                prediction_id,
                signal_id,
                gate_decision_id,
                rule_version,
                model_version,
                data_snapshot_id,
                previous_hash,
                event_hash,
                detail_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                smoke_id,
                now,
                "2099-12-31",
                "migration_smoke",
                "system",
                "005930",
                smoke_id,
                smoke_id,
                smoke_id,
                smoke_id,
                "migration-smoke-rule",
                "migration-smoke-model",
                smoke_id,
                "",
                f"{smoke_id}_hash",
                json.dumps({"smoke": True}, ensure_ascii=False, sort_keys=True),
            ),
        )
        connection.execute(
            """
            INSERT INTO live_phase_approvals(
                approval_id,
                phase,
                trading_day,
                approved_at,
                approved_by,
                expires_at,
                scope,
                max_symbols,
                max_parent_orders,
                max_notional,
                daily_loss_limit_pct,
                per_symbol_loss_limit_pct,
                slippage_budget_bps,
                approval_hash,
                detail_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                smoke_id,
                "phase2_conservative",
                "2099-12-31",
                now,
                "system",
                now,
                "migration_smoke",
                1,
                1,
                100000.0,
                2.0,
                2.0,
                20.0,
                f"{smoke_id}_approval_hash",
                json.dumps({"smoke": True}, ensure_ascii=False, sort_keys=True),
            ),
        )
        connection.execute(
            """
            INSERT INTO live_readiness_runs(
                readiness_id,
                trading_day,
                checked_at,
                phase,
                status,
                passed,
                token_refresh_ok,
                ws_recovery_ok,
                account_snapshot_ok,
                market_status_ok,
                kill_switch_ok,
                database_ok,
                checks_json,
                report_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                smoke_id,
                "2099-12-31",
                now,
                "phase2_conservative",
                "ok",
                1,
                1,
                1,
                1,
                1,
                1,
                1,
                json.dumps({"smoke": True}, ensure_ascii=False, sort_keys=True),
                "runtime-data/reports/storage-migration/smoke.json",
            ),
        )
        rows = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM market_status_snapshots WHERE snapshot_id = ?) AS market_rows,
                (SELECT COUNT(*) FROM live_orders WHERE order_id = ?) AS order_rows,
                (SELECT COUNT(*) FROM live_order_events WHERE order_id = ?) AS event_rows,
                (SELECT COUNT(*) FROM live_fills WHERE order_id = ?) AS fill_rows,
                (SELECT COUNT(*) FROM live_positions WHERE symbol = '__SMOKE__') AS position_rows,
                (SELECT COUNT(*) FROM live_portfolio_snapshots WHERE snapshot_id = ?) AS portfolio_rows,
                (SELECT COUNT(*) FROM ops_live_audit_events WHERE audit_event_id = ?) AS audit_rows,
                (SELECT COUNT(*) FROM live_phase_approvals WHERE approval_id = ?) AS approval_rows,
                (SELECT COUNT(*) FROM live_readiness_runs WHERE readiness_id = ?) AS readiness_rows
            """,
            (smoke_id, smoke_id, smoke_id, smoke_id, smoke_id, smoke_id, smoke_id, smoke_id),
        ).fetchone()
        if rows != (1, 1, 1, 1, 1, 1, 1, 1, 1):
            errors.append(f"sample smoke read mismatch: {rows!r}")
        connection.execute("DELETE FROM live_order_events WHERE order_id = ?", (smoke_id,))
        connection.execute("DELETE FROM live_fills WHERE order_id = ?", (smoke_id,))
        connection.execute("DELETE FROM live_orders WHERE order_id = ?", (smoke_id,))
        connection.execute("DELETE FROM live_positions WHERE symbol = ?", ("__SMOKE__",))
        connection.execute("DELETE FROM live_portfolio_snapshots WHERE snapshot_id = ?", (smoke_id,))
        connection.execute("DELETE FROM ops_live_audit_events WHERE audit_event_id = ?", (smoke_id,))
        connection.execute("DELETE FROM live_phase_approvals WHERE approval_id = ?", (smoke_id,))
        connection.execute("DELETE FROM live_readiness_runs WHERE readiness_id = ?", (smoke_id,))
        connection.execute("DELETE FROM market_status_snapshots WHERE snapshot_id = ?", (smoke_id,))
        connection.commit()
    except Exception as exc:
        connection.rollback()
        errors.append(str(exc))
        try:
            connection.execute("DELETE FROM live_order_events WHERE order_id = ?", (smoke_id,))
            connection.execute("DELETE FROM live_fills WHERE order_id = ?", (smoke_id,))
            connection.execute("DELETE FROM live_orders WHERE order_id = ?", (smoke_id,))
            connection.execute("DELETE FROM live_positions WHERE symbol = ?", ("__SMOKE__",))
            connection.execute("DELETE FROM live_portfolio_snapshots WHERE snapshot_id = ?", (smoke_id,))
            connection.execute("DELETE FROM ops_live_audit_events WHERE audit_event_id = ?", (smoke_id,))
            connection.execute("DELETE FROM live_phase_approvals WHERE approval_id = ?", (smoke_id,))
            connection.execute("DELETE FROM live_readiness_runs WHERE readiness_id = ?", (smoke_id,))
            connection.execute("DELETE FROM market_status_snapshots WHERE snapshot_id = ?", (smoke_id,))
            connection.commit()
        except Exception as cleanup_exc:
            errors.append(f"sample smoke cleanup failed: {cleanup_exc}")
    finally:
        connection.close()
    return errors


def smoke_check(database_path: Path) -> tuple[list[str], list[str], list[str]]:
    store = SQLiteRuntimeStore(database_path, initialize_schema=False)
    table_rows = store._run_read_query(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )
    index_rows = store._run_read_query(
        "SELECT name FROM sqlite_master WHERE type = 'index'"
    )
    tables = {row["name"] for row in table_rows}
    indexes = {row["name"] for row in index_rows}
    missing_tables = [name for name in REQUIRED_TABLES if name not in tables]
    missing_indexes = [name for name in REQUIRED_INDEXES if name not in indexes]
    smoke_errors = []
    if not missing_tables and not missing_indexes:
        smoke_errors = run_sample_smoke_check(database_path)
    return missing_tables, missing_indexes, smoke_errors


root = Path(sys.argv[1]).resolve()
database_path = Path(sys.argv[2]).expanduser().resolve()
backup_dir = Path(sys.argv[3]).expanduser().resolve()
report_path = Path(sys.argv[4]).expanduser().resolve()
apply = sys.argv[5] == "true"
skip_service_check = sys.argv[6] == "true"
default_runtime_db = (root / "runtime-data" / "dev.db").resolve()

for name, path in (
    ("database_path", database_path),
    ("backup_dir", backup_dir),
    ("report_path", report_path),
):
    if not is_relative_to(path, root):
        raise SystemExit(f"{name} must stay inside repository root: {path}")

if database_path == default_runtime_db and skip_service_check:
    raise SystemExit("skip_service_check is not allowed for runtime-data/dev.db")

completed_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
report_path.parent.mkdir(parents=True, exist_ok=True)
backup_dir.mkdir(parents=True, exist_ok=True)
service_ok = True
service_checks: dict = {}
if not skip_service_check:
    service_ok, service_checks = services_are_stopped(root)

backup_path = backup_dir / f"{database_path.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
payload = {
    "status": "planned",
    "completed_at": completed_at,
    "workspace_root": str(root),
    "database_path": str(database_path),
    "database_exists": database_path.exists(),
    "backup_dir": str(backup_dir),
    "backup_path": str(backup_path),
    "report_path": str(report_path),
    "apply": apply,
    "skip_service_check": skip_service_check,
    "service_ok": service_ok,
    "service_checks": service_checks,
    "required_tables": REQUIRED_TABLES,
    "required_indexes": REQUIRED_INDEXES,
    "missing_tables": [],
    "missing_indexes": [],
    "smoke_errors": [],
    "rollback_status": "not_needed",
}

def write_report() -> None:
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if not apply:
    write_report()
    raise SystemExit(0)

if not service_ok:
    payload["status"] = "blocked_services_running"
    write_report()
    raise SystemExit(1)
if not database_path.exists():
    payload["status"] = "blocked_database_missing"
    write_report()
    raise SystemExit(1)

try:
    backup_store = SQLiteRuntimeStore(database_path, initialize_schema=False)
    backup_store.backup_database(backup_path)
    SQLiteRuntimeStore(database_path, initialize_schema=True)
    missing_tables, missing_indexes, smoke_errors = smoke_check(database_path)
    payload["missing_tables"] = missing_tables
    payload["missing_indexes"] = missing_indexes
    payload["smoke_errors"] = smoke_errors
    if missing_tables or missing_indexes or smoke_errors:
        raise RuntimeError("storage migration smoke check failed")
    payload["status"] = "ok"
except Exception as exc:
    payload["status"] = "failed"
    payload["error"] = str(exc)
    if backup_path.exists():
        restore_sqlite_backup(backup_path, database_path)
        payload["rollback_status"] = "restored_from_backup"
    else:
        payload["rollback_status"] = "no_backup_available"
    write_report()
    raise SystemExit(1)

write_report()
PY
}

codex_ops_job() {
  local job_type="premarket-readiness"
  local dry_run="true"
  local report_path="$REPO_ROOT/runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json"
  local live_status_path=""
  local watchdog_status_path=""
  local dashboard_status_path=""
  local database_path="$REPO_ROOT/runtime-data/dev.db"
  local database_timeout_seconds="2.0"
  local storage_state_path="$REPO_ROOT/runtime-data/reports/storage-migration/latest-storage-migration-apply.json"
  local disk_free_bytes=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --job-type|-JobType) job_type="$2"; shift 2 ;;
      --report-path|-ReportPath) report_path="$2"; shift 2 ;;
      --live-status-path|-LiveStatusPath) live_status_path="$2"; shift 2 ;;
      --watchdog-status-path|-WatchdogStatusPath) watchdog_status_path="$2"; shift 2 ;;
      --dashboard-status-path|-DashboardStatusPath) dashboard_status_path="$2"; shift 2 ;;
      --database-path|-DatabasePath) database_path="$2"; shift 2 ;;
      --database-timeout-seconds|-DatabaseTimeoutSeconds) database_timeout_seconds="$2"; shift 2 ;;
      --storage-state-path|-StorageStatePath) storage_state_path="$2"; shift 2 ;;
      --disk-free-bytes|-DiskFreeBytes) disk_free_bytes="$2"; shift 2 ;;
      --dry-run|-DryRun) dry_run="true"; shift ;;
      --execute|--apply|-Execute|-Apply) echo "run_codex_ops_job.sh supports dry-run only" >&2; exit 2 ;;
      *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
  done
  "$PYTHON_BIN" - "$REPO_ROOT" "$job_type" "$dry_run" "$report_path" "$live_status_path" "$watchdog_status_path" "$dashboard_status_path" "$database_path" "$database_timeout_seconds" "$storage_state_path" "$disk_free_bytes" <<'PY'
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from app.services.codex_ops import (
    ACTION_WRITE_REPORT,
    JOB_PREMARKET_READINESS,
    CodexOpsContext,
    build_premarket_readiness_report,
    evaluate_action,
)


def is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def load_json_file(path_text: str) -> dict:
    if not path_text:
        return {}
    path = Path(path_text).expanduser().resolve()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": "invalid_json", "path": str(path), "error": str(exc)}
    return payload if isinstance(payload, dict) else {"status": "invalid_json", "path": str(path)}


def status_payload(root: Path, script_name: str) -> dict:
    result = subprocess.run(
        ["bash", str(root / "scripts" / script_name)],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {
            "status": "status_check_failed",
            "script": script_name,
            "returncode": result.returncode,
            "stderr": result.stderr.strip(),
        }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "status_check_invalid_json", "script": script_name, "stdout": result.stdout.strip()}
    return payload if isinstance(payload, dict) else {"status": "status_check_invalid_json", "script": script_name}


def sqlite_readonly_smoke(root: Path, path_text: str, timeout_seconds: float) -> dict:
    path = Path(path_text).expanduser().resolve()
    if not is_relative_to(path, root):
        return {"status": "blocked", "database_path": str(path), "reason": "database_path_outside_root"}
    if not path.exists():
        return {"status": "missing", "database_path": str(path), "reason": "database_path_missing"}
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=timeout_seconds) as conn:
            journal_row = conn.execute("PRAGMA journal_mode").fetchone()
            journal_mode = journal_row[0] if journal_row else "unknown"
            schema_version_row = conn.execute("PRAGMA schema_version").fetchone()
            schema_version = schema_version_row[0] if schema_version_row else None
            table_row = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' LIMIT 1").fetchone()
            conn.execute("SELECT 1").fetchone()
    except sqlite3.OperationalError as exc:
        message = str(exc)
        if "locked" in message.lower() or "busy" in message.lower():
            return {
                "status": "unknown",
                "database_path": str(path),
                "reason": "database_locked_or_busy",
                "timeout_seconds": timeout_seconds,
                "error": message,
            }
        return {
            "status": "blocked",
            "database_path": str(path),
            "timeout_seconds": timeout_seconds,
            "error": message,
        }
    except sqlite3.Error as exc:
        return {"status": "blocked", "database_path": str(path), "error": str(exc)}
    return {
        "status": "ok",
        "database_path": str(path),
        "timeout_seconds": timeout_seconds,
        "journal_mode": journal_mode,
        "schema_version": schema_version,
        "has_table": table_row is not None,
    }


root = Path(sys.argv[1]).resolve()
job_type = sys.argv[2]
dry_run = sys.argv[3] == "true"
report_path = Path(sys.argv[4]).expanduser().resolve()
live_status_path = sys.argv[5]
watchdog_status_path = sys.argv[6]
dashboard_status_path = sys.argv[7]
database_path = sys.argv[8]
database_timeout_seconds = max(float(sys.argv[9]), 0.1)
storage_state_path = sys.argv[10]
disk_free_arg = sys.argv[11]

if not dry_run:
    raise SystemExit("run_codex_ops_job.sh supports dry-run only")
if job_type != JOB_PREMARKET_READINESS:
    raise SystemExit(f"unsupported codex ops job type for dry-run wrapper: {job_type}")
if not is_relative_to(report_path, root):
    raise SystemExit(f"report_path must stay inside repository root: {report_path}")

live_status = load_json_file(live_status_path) or status_payload(root, "get_live_runtime_status.sh")
watchdog_status = load_json_file(watchdog_status_path) or status_payload(root, "get_runtime_watchdog_status.sh")
dashboard_status = load_json_file(dashboard_status_path) or status_payload(root, "get_dashboard_status.sh")
database_smoke = sqlite_readonly_smoke(root, database_path, database_timeout_seconds)
storage_state = load_json_file(storage_state_path)
disk_free_bytes = int(disk_free_arg) if disk_free_arg else shutil.disk_usage(root).free

session_status = (
    live_status.get("session_status")
    or live_status.get("current_session_status")
    or watchdog_status.get("market_session_status")
    or "unknown"
)
live_running = bool(live_status.get("process_running")) or live_status.get("status") == "running"
session_requires_live_runtime = str(session_status) in {"pre-open", "regular-session"}
context = CodexOpsContext(
    session_status=str(session_status),
    live_runtime_should_run=bool(watchdog_status.get("live_runtime_should_run")) or session_requires_live_runtime,
    live_runtime_running=live_running,
)
policy_path = Path(os.path.relpath(report_path, root))
decision = evaluate_action(job_type, ACTION_WRITE_REPORT, context, target_path=policy_path)
if not decision.allowed:
    raise SystemExit("write_report is blocked by codex ops manifest: " + ",".join(decision.blocking_reasons))

generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
payload = build_premarket_readiness_report(
    context=context,
    live_runtime_status=live_status,
    watchdog_status=watchdog_status,
    dashboard_status=dashboard_status,
    database_smoke=database_smoke,
    storage_migration_state=storage_state,
    disk_free_bytes=disk_free_bytes,
    generated_at=generated_at,
    workspace_root=str(root),
    report_path=str(report_path),
)
payload["dry_run"] = True
payload["write_report_decision"] = {
    "allowed": decision.allowed,
    "blocking_reasons": list(decision.blocking_reasons),
}
report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
}

live_readiness_dry_run() {
  local phase="phase1_readonly"
  local trading_day=""
  local premarket_report_path="$REPO_ROOT/runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json"
  local fixture_path=""
  local system_clock_check_path=""
  local report_path="$REPO_ROOT/runtime-data/reports/live-readiness/latest-readiness.json"
  local record_db="false"
  local database_path=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --phase|-Phase) phase="$2"; shift 2 ;;
      --trading-day|-TradingDay) trading_day="$2"; shift 2 ;;
      --premarket-report-path|-PremarketReportPath) premarket_report_path="$2"; shift 2 ;;
      --fixture-path|-FixturePath) fixture_path="$2"; shift 2 ;;
      --system-clock-check-path|-SystemClockCheckPath) system_clock_check_path="$2"; shift 2 ;;
      --report-path|-ReportPath) report_path="$2"; shift 2 ;;
      --record|-Record) record_db="true"; shift ;;
      --database-path|-DatabasePath) database_path="$2"; shift 2 ;;
      --dry-run|-DryRun) shift ;;
      --execute|--apply|-Execute|-Apply) echo "run_live_readiness_dry_run.sh supports dry-run only" >&2; exit 2 ;;
      *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
  done
  "$PYTHON_BIN" - "$REPO_ROOT" "$phase" "$trading_day" "$premarket_report_path" "$fixture_path" "$system_clock_check_path" "$report_path" "$record_db" "$database_path" <<'PY'
import json
import sys
from datetime import datetime
from pathlib import Path

from app.services.live_phase_readiness import build_fault_injection_dry_run_report
from app.storage.contracts import LiveReadinessRun
from app.storage.sqlite_store import SQLiteRuntimeStore


def is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": "invalid_json", "path": str(path), "error": str(exc)}
    return payload if isinstance(payload, dict) else {"status": "invalid_json", "path": str(path)}


root = Path(sys.argv[1]).resolve()
phase = sys.argv[2]
trading_day = sys.argv[3]
premarket_report_path = Path(sys.argv[4]).expanduser().resolve()
fixture_path_text = sys.argv[5]
system_clock_check_path_text = sys.argv[6]
report_path = Path(sys.argv[7]).expanduser().resolve()
record_db = sys.argv[8] == "true"
database_path_text = sys.argv[9]

if not is_relative_to(report_path, root):
    raise SystemExit(f"report_path must stay inside repository root: {report_path}")
if not is_relative_to(premarket_report_path, root):
    raise SystemExit(f"premarket_report_path must stay inside repository root: {premarket_report_path}")
fixture_path = Path(fixture_path_text).expanduser().resolve() if fixture_path_text else None
if fixture_path is not None and not is_relative_to(fixture_path, root):
    raise SystemExit(f"fixture_path must stay inside repository root: {fixture_path}")
system_clock_check_path = Path(system_clock_check_path_text).expanduser().resolve() if system_clock_check_path_text else None
if system_clock_check_path is not None and not is_relative_to(system_clock_check_path, root):
    raise SystemExit(f"system_clock_check_path must stay inside repository root: {system_clock_check_path}")
database_path = Path(database_path_text).expanduser().resolve() if database_path_text else None
if record_db and database_path is None:
    raise SystemExit("--record requires --database-path")
if database_path is not None and not is_relative_to(database_path, root):
    raise SystemExit(f"database_path must stay inside repository root: {database_path}")
if record_db and database_path is not None and not database_path.exists():
    raise SystemExit(f"database_path must already exist for --record: {database_path}")

checked_at = datetime.now().astimezone()
trading_day = trading_day or checked_at.strftime("%Y-%m-%d")
premarket_report = load_json(premarket_report_path)
if not premarket_report:
    premarket_report = {
        "status": "blocked",
        "report_path": str(premarket_report_path),
        "blockers": ["premarket_report_missing"],
        "warnings": [],
        "checks": [],
    }
fixture_results = load_json(fixture_path) if fixture_path is not None else {}
if system_clock_check_path is not None:
    system_clock_payload = load_json(system_clock_check_path)
    fixture_results = dict(fixture_results)
    if isinstance(system_clock_payload.get("system_clock"), dict):
        fixture_results["system_clock"] = system_clock_payload["system_clock"]
    elif system_clock_payload.get("key") == "system_clock":
        fixture_results["system_clock"] = system_clock_payload
    else:
        fixture_results["system_clock"] = {
            "key": "system_clock",
            "status": "invalid_fixture",
            "passed": False,
            "summary": "system clock check file must contain a system_clock check payload",
            "details": {"path": str(system_clock_check_path)},
        }

payload = build_fault_injection_dry_run_report(
    phase=phase,
    trading_day=trading_day,
    checked_at=checked_at,
    premarket_report=premarket_report,
    fixture_results=fixture_results,
    report_path=str(report_path),
)
payload["dry_run"] = True
payload["fixture_path"] = str(fixture_path) if fixture_path is not None else None
payload["system_clock_check_path"] = str(system_clock_check_path) if system_clock_check_path is not None else None
payload["recorded"] = False
payload["database_path"] = str(database_path) if database_path is not None else None
if record_db:
    record = payload["readiness_run"]
    checks_json = record.get("checks_json", {})
    if not isinstance(checks_json, dict):
        raise SystemExit("readiness_run.checks_json must be a JSON object")
    run = LiveReadinessRun(
        readiness_id=str(record["readiness_id"]),
        trading_day=str(record["trading_day"]),
        checked_at=datetime.fromisoformat(str(record["checked_at"])),
        phase=str(record["phase"]),
        status=str(record["status"]),
        passed=bool(record["passed"]),
        token_refresh_ok=bool(record["token_refresh_ok"]),
        ws_recovery_ok=bool(record["ws_recovery_ok"]),
        account_snapshot_ok=bool(record["account_snapshot_ok"]),
        market_status_ok=bool(record["market_status_ok"]),
        kill_switch_ok=bool(record["kill_switch_ok"]),
        database_ok=bool(record["database_ok"]),
        checks_json=checks_json,
        report_path=str(record["report_path"]),
    )
    store = SQLiteRuntimeStore(database_path, initialize_schema=False)
    store.insert_live_readiness_run(run)
    payload["recorded"] = True
report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
}

probe_kis_clock_reference() {
  "$PYTHON_BIN" "$REPO_ROOT/scripts/probe_kis_clock_reference.py" --project-root "$REPO_ROOT" "$@"
}

probe_kis_token_refresh() {
  "$PYTHON_BIN" "$REPO_ROOT/scripts/probe_kis_token_refresh.py" --project-root "$REPO_ROOT" "$@"
}

probe_kis_account_snapshot() {
  "$PYTHON_BIN" "$REPO_ROOT/scripts/probe_kis_account_snapshot.py" --project-root "$REPO_ROOT" "$@"
}

compare_kis_account_snapshot_checks() {
  "$PYTHON_BIN" "$REPO_ROOT/scripts/compare_kis_account_snapshot_checks.py" --project-root "$REPO_ROOT" "$@"
}

probe_kis_ws_recovery() {
  "$PYTHON_BIN" "$REPO_ROOT/scripts/probe_kis_ws_recovery.py" --project-root "$REPO_ROOT" "$@"
}

probe_market_status_snapshot() {
  "$PYTHON_BIN" "$REPO_ROOT/scripts/probe_market_status_snapshot.py" --project-root "$REPO_ROOT" "$@"
}

prepare_market_status_snapshot_template() {
  "$PYTHON_BIN" "$REPO_ROOT/scripts/prepare_market_status_snapshot_template.py" --project-root "$REPO_ROOT" "$@"
}

build_live_readiness_fixture_snapshot() {
  "$PYTHON_BIN" "$REPO_ROOT/scripts/build_live_readiness_fixture_snapshot.py" --project-root "$REPO_ROOT" "$@"
}

live_kill_switch_cli() {
  local action="status"
  local reason=""
  local actor="account_owner"
  local scope="global"
  local symbol=""
  local stale_after_minutes="1440"
  local state_path="$REPO_ROOT/runtime-data/reports/live-risk/kill-switch.json"
  local apply="false"
  local confirm_disable="false"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --status|-Status) action="status"; shift ;;
      --enable|-Enable) action="enable"; shift ;;
      --disable|-Disable) action="disable"; shift ;;
      --reason|-Reason) reason="$2"; shift 2 ;;
      --actor|-Actor) actor="$2"; shift 2 ;;
      --scope|-Scope) scope="$2"; shift 2 ;;
      --symbol|-Symbol) symbol="$2"; shift 2 ;;
      --stale-after-minutes|-StaleAfterMinutes) stale_after_minutes="$2"; shift 2 ;;
      --path|-Path) state_path="$2"; shift 2 ;;
      --apply|-Apply) apply="true"; shift ;;
      --dry-run|-DryRun) apply="false"; shift ;;
      --confirm-disable|-ConfirmDisable) confirm_disable="true"; shift ;;
      *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
  done
  "$PYTHON_BIN" - "$REPO_ROOT" "$action" "$reason" "$actor" "$scope" "$symbol" "$stale_after_minutes" "$state_path" "$apply" "$confirm_disable" <<'PY'
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from app.services.live_kill_switch import LiveKillSwitch
from app.storage.contracts import LIVE_ORDER_EVENT_ACTORS


def is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def state_payload(state, *, action: str, applied: bool, dry_run: bool) -> dict:
    return {
        "status": "ok" if state.status == "ok" else state.status,
        "action": action,
        "applied": applied,
        "dry_run": dry_run,
        "enabled": state.enabled,
        "reason": state.reason,
        "actor": state.actor,
        "scope": state.scope,
        "symbol": state.symbol,
        "updated_at": state.updated_at.isoformat() if state.updated_at else None,
        "stale_after": state.stale_after.isoformat() if state.stale_after else None,
        "path": state.path,
        "submit_blocking_reason": state.submit_blocking_reason,
        "cancel_only_allowed": state.cancel_only_allowed,
    }


root = Path(sys.argv[1]).resolve()
action = sys.argv[2]
reason = sys.argv[3].strip()
actor = sys.argv[4].strip()
scope = sys.argv[5].strip()
symbol = sys.argv[6].strip()
stale_after_minutes = float(sys.argv[7])
state_path = Path(sys.argv[8]).expanduser().resolve()
apply = sys.argv[9] == "true"
confirm_disable = sys.argv[10] == "true"

if not is_relative_to(state_path, root):
    raise SystemExit(f"kill switch path must stay inside repository root: {state_path}")
switch = LiveKillSwitch(state_path)

if action == "status":
    print(json.dumps(state_payload(switch.read_state(), action=action, applied=False, dry_run=True), ensure_ascii=False, indent=2))
    raise SystemExit(0)
if action not in {"enable", "disable"}:
    raise SystemExit(f"unsupported kill switch action: {action}")
if actor not in LIVE_ORDER_EVENT_ACTORS:
    allowed = ", ".join(sorted(LIVE_ORDER_EVENT_ACTORS))
    raise SystemExit(f"actor must be one of: {allowed}")
if not reason:
    raise SystemExit("--reason is required for --enable/--disable")
if action == "disable" and apply and not confirm_disable:
    raise SystemExit("--disable --apply requires --confirm-disable")
if stale_after_minutes <= 0:
    raise SystemExit("--stale-after-minutes must be positive")

enabled = action == "enable"
now = datetime.now().astimezone()
stale_after = now + timedelta(minutes=stale_after_minutes)
if not apply:
    payload = {
        "status": "dry_run",
        "action": action,
        "applied": False,
        "dry_run": True,
        "would_write": True,
        "enabled": enabled,
        "reason": reason,
        "actor": actor,
        "scope": scope,
        "symbol": symbol or None,
        "updated_at": now.isoformat(),
        "stale_after": stale_after.isoformat(),
        "path": str(state_path),
        "requires_confirm_disable": action == "disable",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(0)

state = switch.write_state(
    enabled=enabled,
    reason=reason,
    actor=actor,
    scope=scope,
    symbol=symbol or None,
    now=now,
    stale_after=stale_after,
)
print(json.dumps(state_payload(state, action=action, applied=True, dry_run=False), ensure_ascii=False, indent=2))
PY
}

runtime_autoboot() {
  local skip_dashboard="false" skip_live="false" skip_account="false" skip_cleanup="false" skip_build="false" skip_watchdog="false"
  local force_dashboard="" force_live="" force_watchdog=""
  local remaining=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --skip-dashboard|-SkipDashboard) skip_dashboard="true"; shift ;;
      --skip-live-runtime|-SkipLiveRuntime) skip_live="true"; shift ;;
      --skip-account-refresh|-SkipAccountRefresh) skip_account="true"; shift ;;
      --skip-runtime-cleanup|-SkipRuntimeCleanup) skip_cleanup="true"; shift ;;
      --skip-dashboard-build|-SkipDashboardBuild) skip_build="true"; shift ;;
      --skip-watchdog|-SkipWatchdog) skip_watchdog="true"; shift ;;
      --force-dashboard-restart|-ForceDashboardRestart) force_dashboard="--force-restart"; shift ;;
      --force-live-runtime-restart|-ForceLiveRuntimeRestart) force_live="--force-restart"; shift ;;
      --force-watchdog-restart|-ForceWatchdogRestart) force_watchdog="--force-restart"; shift ;;
      *) remaining+=("$1"); shift ;;
    esac
  done
  local session live_window_fast_start="false"
  session="$(market_session_status "$REPO_ROOT")"
  if [[ "$session" == "regular-session" || "$session" == "pre-open" ]]; then
    live_window_fast_start="true"
    skip_account="true"
    skip_cleanup="true"
    skip_build="true"
  fi
  [[ "$skip_cleanup" == "true" ]] || run_app --cleanup-runtime-test-data >/dev/null || true
  if [[ "$skip_account" != "true" ]]; then
    run_app --kis-account-balance >/dev/null || true
    run_app --sync-broker-paper-orders >/dev/null || true
    run_app --reconcile-paper-accounts >/dev/null || true
  fi
  [[ "$skip_dashboard" == "true" ]] || "$SCRIPT_DIR/start_dashboard_background.sh" "${remaining[@]}" $force_dashboard >/dev/null || true
  if [[ "$skip_live" != "true" ]]; then
    if [[ "$session" == "regular-session" || "$session" == "pre-open" ]]; then
      "$SCRIPT_DIR/start_live_runtime_background.sh" $force_live >/dev/null || true
    else
      "$SCRIPT_DIR/stop_live_runtime.sh" >/dev/null || true
    fi
  fi
  [[ "$skip_watchdog" == "true" ]] || "$SCRIPT_DIR/start_runtime_watchdog_background.sh" $force_watchdog >/dev/null || true
  [[ "$skip_build" == "true" ]] || { run_app --build-runtime-report >/dev/null; run_app --build-dashboard >/dev/null; }
  printf '{\n  "ok": true,\n  "market_session_status": "%s",\n  "live_window_fast_start": %s,\n  "completed_at": "%s"\n}\n' "$session" "$live_window_fast_start" "$(now_text)"
}

direct_sequence() {
  case "$SCRIPT_NAME" in
    align_local_paper_to_broker.sh) run_app --align-local-paper-to-broker ;;
    build_runtime_report.sh) run_app --build-runtime-report ;;
    cleanup_repo_generated_artifacts.sh) ops cleanup-repo-generated-artifacts "$@" ;;
    cleanup_runtime_test_data.sh) run_app --cleanup-runtime-test-data; run_app --build-dashboard ;;
    rebuild_actual_ml_state.sh) run_app --rebuild-actual-ml --horizon-min 15; run_app --build-runtime-report; run_app --build-dashboard ;;
    reconcile_paper_accounts.sh) run_app --reconcile-paper-accounts ;;
    recheck_paper_kis_mismatch.sh) "$PYTHON_BIN" "$REPO_ROOT/scripts/recheck_paper_kis_mismatch.py" --project-root "$REPO_ROOT" "$@" ;;
    refresh_kis_account.sh) run_app --kis-account-balance ;;
    run_backtest.sh) run_app --run-backtest --horizon-min 15 ;;
    run_challenger_review.sh) run_app --run-challengers --horizon-min 15 ;;
    run_foundation_demo.sh) run_app --demo ;;
    run_full_kis_cycle.sh) run_app --run-kis-dev-cycle --iterations 5 --interval-seconds 5 --horizon-min 15; run_app --build-runtime-report ;;
    run_full_synthetic_cycle.sh) run_app --run-synthetic-dev-cycle --symbol 005930 --minutes 90 --horizon-min 15; run_app --build-runtime-report ;;
    run_kis_watchlist_poll.sh) run_app --kis-watchlist-poll --iterations 5 --interval-seconds 5 ;;
    run_kis_ws_listener.sh) run_app --kis-ws-listen --max-frames 50 --max-reconnects 2 ;;
    run_lightgbm_training.sh) run_app --train-lightgbm --horizon-min 15 ;;
    run_ml_shadow_cycle.sh) run_app --rebuild-actual-ml --horizon-min 15; run_app --build-runtime-report ;;
    run_research_pipeline.sh) run_app --build-minute-bars; run_app --build-feature-dataset; run_app --train-baseline --horizon-min 15 ;;
    run_streaming_replay_demo.sh) run_app --replay-sample-ws --symbol 005930 ;;
    run_synthetic_research_loop.sh) run_app --seed-synthetic-data --symbol 005930 --minutes 90; run_app --build-minute-bars; run_app --build-feature-dataset; run_app --train-baseline --horizon-min 15 ;;
    run_walk_forward_backtest.sh) run_app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 ;;
    run_gate_walk_forward_backtest.sh) run_app --run-gate-walk-forward --horizon-min 15 ;;
    sync_broker_paper_orders.sh) run_app --sync-broker-paper-orders ;;
    verify_kis_ws.sh) run_app --verify-kis-ws --max-frames 20 --max-reconnects 1 ;;
    *) return 1 ;;
  esac
}

case "$SCRIPT_NAME" in
  bump_version.sh) bump_version "$@" ;;
  run_dashboard.sh) run_dashboard_foreground "$@" ;;
  start_dashboard_background.sh) ops start-dashboard "$@" ;;
  get_dashboard_status.sh) ops get-dashboard-status "$@" ;;
  stop_dashboard.sh) ops stop-dashboard "$@" ;;
  start_live_runtime_background.sh) ops start-live-runtime "$@" ;;
  get_live_runtime_status.sh) ops get-live-runtime-status "$@" ;;
  stop_live_runtime.sh) ops stop-live-runtime "$@" ;;
  run_runtime_watchdog_loop.sh) ops run-watchdog-loop "$@" ;;
  start_runtime_watchdog_background.sh) ops start-watchdog "$@" ;;
  get_runtime_watchdog_status.sh) ops get-watchdog-status "$@" ;;
  stop_runtime_watchdog.sh) ops stop-watchdog "$@" ;;
  watch_git_versions_and_push.sh) watch_git_versions_and_push "$@" ;;
  start_git_autopush_watcher.sh) start_git_autopush_watcher "$@" ;;
  get_git_autopush_watcher_status.sh) ops autopush-status "$@" ;;
  stop_git_autopush_watcher.sh) stop_git_autopush_watcher "$@" ;;
  set_git_autopush_enabled.sh) ops set-autopush-enabled "$@" ;;
  audit_git_autopush_targets.sh) ops audit-autopush "$@" ;;
  bootstrap_git_autopush_targets.sh) ops bootstrap-autopush "$@" ;;
  test_git_autopush_watcher.sh) test_git_autopush_watcher "$@" ;;
  register_git_autopush_task.sh|install_git_autopush_startup_launcher.sh) install_git_autopush_service "$@" ;;
  remove_git_autopush_startup_launcher.sh) remove_git_autopush_service "$@" ;;
  install_runtime_startup_launcher.sh) install_runtime_service "$@" ;;
  get_runtime_startup_launcher_status.sh) get_runtime_service_status "$@" ;;
  remove_runtime_startup_launcher.sh) remove_runtime_service "$@" ;;
  run_hourly_repo_audit_iteration.sh) ops hourly-audit "$@" ;;
  start_hourly_repo_audit.sh) hourly_loop "$@" ;;
  start_hourly_repo_audit_background.sh) start_hourly_background "$@" ;;
  get_hourly_repo_audit_status.sh) get_hourly_status "$@" ;;
  stop_hourly_repo_audit.sh) stop_hourly "$@" ;;
  run_repo_review_until_deadline.sh|start_midday_codex_review.sh|run_codex_review_iteration_v4.sh) ops hourly-audit "$@" ;;
  start_repo_review_until_deadline_background.sh) start_hourly_background "$@" ;;
  get_repo_review_until_deadline_status.sh) get_hourly_status "$@" ;;
  stop_repo_review_until_deadline.sh) stop_hourly "$@" ;;
  export_recovery_snapshot.sh) ops export-recovery "$@" ;;
  export_recovery_snapshot_to_nas.sh) export_to_nas "$@" ;;
  run_weekly_nas_backup.sh) export_to_nas "$@" --keep-count 3 ;;
  run_forced_nas_backup.sh) export_to_nas "$@" --keep-count 3 ;;
  verify_paper_dual_account_match.sh) ops verify-paper-dual-account-match "$@" ;;
  check_local_setup.sh) ops check-local-setup "$@" ;;
  restore_kis_env_interactive.sh) restore_kis_env_interactive "$@" ;;
  connect_kis_paper_account_interactive.sh) connect_kis_paper_account_interactive "$@" ;;
  run_post_close_ml_maintenance.sh) post_close_ml_maintenance "$@" ;;
  run_post_close_label_refresh.sh) post_close_label_refresh "$@" ;;
  run_codex_ops_job.sh) codex_ops_job "$@" ;;
  probe_kis_clock_reference.sh) probe_kis_clock_reference "$@" ;;
  probe_kis_token_refresh.sh) probe_kis_token_refresh "$@" ;;
  probe_kis_account_snapshot.sh) probe_kis_account_snapshot "$@" ;;
  compare_kis_account_snapshot_checks.sh) compare_kis_account_snapshot_checks "$@" ;;
  probe_kis_ws_recovery.sh) probe_kis_ws_recovery "$@" ;;
  probe_market_status_snapshot.sh) probe_market_status_snapshot "$@" ;;
  prepare_market_status_snapshot_template.sh) prepare_market_status_snapshot_template "$@" ;;
  build_live_readiness_fixture_snapshot.sh) build_live_readiness_fixture_snapshot "$@" ;;
  run_live_readiness_dry_run.sh) live_readiness_dry_run "$@" ;;
  set_live_kill_switch.sh) live_kill_switch_cli "$@" ;;
  run_storage_migration_dry_run.sh) storage_migration_dry_run "$@" ;;
  apply_storage_migration.sh) storage_migration_apply "$@" ;;
  start_runtime_autoboot.sh) runtime_autoboot "$@" ;;
  start_monday_runtime.sh) "$SCRIPT_DIR/run_ml_shadow_cycle.sh"; runtime_autoboot "$@" ;;
  common_process_helpers.sh) exit 0 ;;
  *) direct_sequence "$@" || { echo "No bash implementation registered for $SCRIPT_NAME" >&2; exit 2; } ;;
esac
