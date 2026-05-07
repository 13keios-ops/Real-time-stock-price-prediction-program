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
  ops install-autopush-service --scan-root "$scan_root" --poll-seconds "$poll"
}

remove_git_autopush_service() {
  systemctl --user disable --now git-autopush-watcher.service >/dev/null 2>&1 || true
  rm -f "$HOME/.config/systemd/user/git-autopush-watcher.service"
  echo "Removed git autopush user service."
}

install_runtime_service() {
  ops install-runtime-service
}

get_runtime_service_status() {
  local service="$HOME/.config/systemd/user/stock-runtime-autoboot.service"
  "$PYTHON_BIN" - "$service" "$REPO_ROOT" <<'PY'
import json
import os
import sys

service, root = sys.argv[1:3]
content = open(service, encoding="utf-8").read() if os.path.exists(service) else ""
print(json.dumps({
    "installed": os.path.exists(service),
    "ok": root in content,
    "launcher_path": service,
    "workspace_root": root,
}, indent=2))
PY
}

remove_runtime_service() {
  systemctl --user disable --now stock-runtime-autoboot.service >/dev/null 2>&1 || true
  rm -f "$HOME/.config/systemd/user/stock-runtime-autoboot.service"
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
  local mode="paper" include="false" workspace="$REPO_ROOT"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --trading-mode|-TradingMode) mode="$2"; shift 2 ;;
      --include-account-fields|-IncludeAccountFields) include="true"; shift ;;
      --workspace-root|-WorkspaceRoot) workspace="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  local env_path="$workspace/.env"
  [[ -f "$env_path" ]] || cp "$workspace/.env.example" "$env_path"
  local prefix="PAPER"
  [[ "$mode" == "live" ]] && prefix="LIVE"
  echo "KIS .env restore ($mode)"
  read -r -s -p "KIS_APP_KEY_$prefix: " app_key
  echo
  read -r -s -p "KIS_APP_SECRET_$prefix: " app_secret
  echo
  set_dotenv_value "$env_path" "TRADING_MODE" "$mode"
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
  [[ "$mode" == "paper" ]] && set_dotenv_value "$env_path" "ALLOW_LIVE_ORDERS" "false"
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

post_close_ml_maintenance() {
  local workspace="$REPO_ROOT" runtime="" horizon="15" use_snapshot="true" snapshot_dir="" run_dir=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --workspace-root|-WorkspaceRoot) workspace="$2"; shift 2 ;;
      --runtime-data-dir|-RuntimeDataDir) runtime="$2"; shift 2 ;;
      --horizon-min|-HorizonMin) horizon="$2"; shift 2 ;;
      --snapshot-dir|-SnapshotDir) snapshot_dir="$2"; shift 2 ;;
      --run-dir|-RunDir) run_dir="$2"; shift 2 ;;
      --live-db|-LiveDb|--no-snapshot|-NoSnapshot) use_snapshot="false"; shift ;;
      --use-snapshot|-UseSnapshot) use_snapshot="true"; shift ;;
      --restart-live-runtime|-RestartLiveRuntime) shift ;;
      *) shift ;;
    esac
  done
  [[ -n "$runtime" ]] || runtime="$workspace/runtime-data"
  local state_dir="$runtime/reports/ml-maintenance/state"
  mkdir -p "$state_dir"
  local snapshot_path="" snapshot_manifest="" snapshot_runtime="" database_url=""
  if [[ "$use_snapshot" == "true" ]]; then
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
  "$PYTHON_BIN" - "$state_dir/latest-post-close-ml.json" "$workspace" "$runtime" "$horizon" "$use_snapshot" "$snapshot_path" "$snapshot_manifest" "$snapshot_runtime" <<'PY'
import json
import sys
from datetime import datetime
path, root, runtime, horizon, use_snapshot, snapshot_path, snapshot_manifest, snapshot_runtime = sys.argv[1:9]
payload = {
    "status": "ok",
    "maintenance_date": datetime.now().strftime("%Y-%m-%d"),
    "completed_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z"),
    "workspace_root": root,
    "runtime_data_dir": runtime,
    "horizon_min": int(horizon),
    "mode": "snapshot" if use_snapshot == "true" else "live-db",
    "snapshot_path": snapshot_path,
    "snapshot_manifest_path": snapshot_manifest,
    "snapshot_runtime_data_dir": snapshot_runtime,
}
open(path, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(payload, ensure_ascii=False, indent=2))
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
  [[ "$skip_cleanup" == "true" ]] || run_app --cleanup-runtime-test-data >/dev/null || true
  if [[ "$skip_account" != "true" ]]; then
    run_app --kis-account-balance >/dev/null || true
    run_app --sync-broker-paper-orders >/dev/null || true
    run_app --reconcile-paper-accounts >/dev/null || true
  fi
  [[ "$skip_dashboard" == "true" ]] || "$SCRIPT_DIR/start_dashboard_background.sh" "${remaining[@]}" $force_dashboard >/dev/null || true
  local session
  session="$(market_session_status "$REPO_ROOT")"
  if [[ "$skip_live" != "true" ]]; then
    if [[ "$session" == "regular-session" || "$session" == "pre-open" ]]; then
      "$SCRIPT_DIR/start_live_runtime_background.sh" $force_live >/dev/null || true
    else
      "$SCRIPT_DIR/stop_live_runtime.sh" >/dev/null || true
    fi
  fi
  [[ "$skip_watchdog" == "true" ]] || "$SCRIPT_DIR/start_runtime_watchdog_background.sh" $force_watchdog >/dev/null || true
  [[ "$skip_build" == "true" ]] || { run_app --build-runtime-report >/dev/null; run_app --build-dashboard >/dev/null; }
  printf '{\n  "ok": true,\n  "market_session_status": "%s",\n  "completed_at": "%s"\n}\n' "$session" "$(now_text)"
}

direct_sequence() {
  case "$SCRIPT_NAME" in
    align_local_paper_to_broker.sh) run_app --align-local-paper-to-broker ;;
    build_runtime_report.sh) run_app --build-runtime-report ;;
    cleanup_runtime_test_data.sh) run_app --cleanup-runtime-test-data; run_app --build-dashboard ;;
    rebuild_actual_ml_state.sh) run_app --rebuild-actual-ml --horizon-min 15; run_app --build-runtime-report; run_app --build-dashboard ;;
    reconcile_paper_accounts.sh) run_app --reconcile-paper-accounts ;;
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
  start_runtime_autoboot.sh) runtime_autoboot "$@" ;;
  start_monday_runtime.sh) "$SCRIPT_DIR/run_ml_shadow_cycle.sh"; runtime_autoboot "$@" ;;
  common_process_helpers.sh) exit 0 ;;
  *) direct_sequence "$@" || { echo "No bash implementation registered for $SCRIPT_NAME" >&2; exit 2; } ;;
esac
