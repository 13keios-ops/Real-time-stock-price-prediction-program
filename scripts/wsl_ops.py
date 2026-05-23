#!/usr/bin/env python3
"""WSL/Linux operation helpers used by the bash scripts.

The public entry points remain shell scripts. This module handles JSON, process
state, and git plumbing that is safer to express with structured Python APIs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"


def now_text() -> str:
    return dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json(path: Path, payload: Any, echo: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if echo:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=check)


def python_bin() -> str:
    return sys.executable


def runtime_dir(workspace_root: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else workspace_root / "runtime-data"


def cmdline(pid: int | str | None) -> str:
    if not pid:
        return ""
    path = Path("/proc") / str(pid) / "cmdline"
    try:
        return path.read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except Exception:
        return ""


def pid_matches(pid: int | str | None, *needles: str) -> bool:
    text = cmdline(pid)
    return bool(text) and all(needle in text for needle in needles)


def pid_matches_any(pid: int | str | None, *needle_groups: tuple[str, ...]) -> bool:
    return any(pid_matches(pid, *needles) for needles in needle_groups)


def find_pids(*needles: str) -> list[int]:
    found: list[int] = []
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        text = cmdline(entry.name)
        if text and all(needle in text for needle in needles):
            found.append(int(entry.name))
    return found


def find_pids_any(*needle_groups: tuple[str, ...]) -> list[int]:
    found: set[int] = set()
    for needles in needle_groups:
        found.update(find_pids(*needles))
    return sorted(found)


def stop_pids(pids: list[int]) -> None:
    own_pid = os.getpid()
    for pid in pids:
        if pid == own_pid:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(1)
    for pid in pids:
        if pid == own_pid:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def tail_text(path: Path, count: int = 20) -> str:
    if not path.exists():
        return ""
    lines = [line.rstrip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines()]
    return "\n".join([line for line in lines if line][-count:])


def http_ok(url: str, needle: str | None = None, timeout: int = 5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status < 400 and (needle is None or needle in body)
    except Exception:
        return False


def dashboard_health(url: str) -> tuple[bool, bool]:
    base = url.rstrip("/")
    health = http_ok(f"{base}/health", "dashboard", 3)
    api = http_ok(f"{base}/api/dashboard.json", None, 5)
    return health, api


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def set_env_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    output: list[str] = []
    updated = False
    for line in lines:
        if line.startswith(key + "="):
            output.append(f"{key}={value}")
            updated = True
        else:
            output.append(line)
    if not updated:
        output.append(f"{key}={value}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def number_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_env_number(value: float) -> str:
    rounded = round(value)
    if abs(value - rounded) < 1e-9:
        return str(int(rounded))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def account_position_count(account_snapshot: dict[str, Any]) -> int:
    raw_count = account_snapshot.get("position_row_count")
    if raw_count is not None:
        try:
            return int(raw_count)
        except (TypeError, ValueError):
            pass
    positions = account_snapshot.get("positions")
    if isinstance(positions, list):
        return len(positions)
    return 0


def market_settings(root: Path, *, pre_open_warmup_minutes: int = 60) -> tuple[str, bool, bool]:
    open_text, close_text, holidays = market_schedule(root)
    now = dt.datetime.now()
    if now.weekday() >= 5:
        return "weekend", False, False
    if now.strftime("%Y-%m-%d") in holidays:
        return "holiday", False, False
    open_h, open_m = [int(x) for x in open_text.split(":")[:2]]
    close_h, close_m = [int(x) for x in close_text.split(":")[:2]]
    opened = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    closed = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
    if now < opened:
        in_warmup = opened - dt.timedelta(minutes=max(0, int(pre_open_warmup_minutes))) <= now < opened
        return ("pre-open" if in_warmup else "overnight"), False, in_warmup
    if now > closed:
        return "post-close", False, False
    return "regular-session", True, True


def market_schedule(root: Path) -> tuple[str, str, set[str]]:
    calendar = root / "config" / "market_calendar.toml"
    open_text = "09:00"
    close_text = "15:30"
    holidays: set[str] = set()
    if calendar.exists():
        text = calendar.read_text(encoding="utf-8")
        for key in ("session_open", "session_close"):
            match = re.search(r"^\s*" + re.escape(key) + r"\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
            if match and key == "session_open":
                open_text = match.group(1)
            elif match:
                close_text = match.group(1)
        match = re.search(r"^\s*holidays\s*=\s*\[(.*?)\]", text, re.M | re.S)
        if match:
            holidays = {item.strip().strip("'\"") for item in match.group(1).split(",") if item.strip().strip("'\"")}
    return open_text, close_text, holidays


def market_close_datetime(root: Path) -> dt.datetime:
    _, close_text, _ = market_schedule(root)
    close_h, close_m = [int(x) for x in close_text.split(":")[:2]]
    now = dt.datetime.now()
    return now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)


def maybe_start_post_close_ml(
    *,
    root: Path,
    runtime: Path,
    session: str,
    args: argparse.Namespace,
    errors: list[str],
) -> str:
    if getattr(args, "disable_post_close_ml", False):
        return "disabled"
    if session != "post-close":
        return "none"
    delay_minutes = max(int(getattr(args, "post_close_ml_delay_minutes", 30)), 0)
    now = dt.datetime.now()
    if now < market_close_datetime(root) + dt.timedelta(minutes=delay_minutes):
        return f"waiting_delay_{delay_minutes}m"

    state_path = runtime / "reports/ml-maintenance/state/latest-post-close-ml.json"
    today = now.strftime("%Y-%m-%d")
    state = read_json(state_path, {})
    if state.get("maintenance_date") == today:
        if state.get("status"):
            return f"already_{state.get('status')}"

    horizon = str(getattr(args, "post_close_ml_horizon_min", 15))
    heavy_research = bool(getattr(args, "post_close_ml_heavy_research", False))
    use_snapshot = heavy_research and not bool(getattr(args, "post_close_ml_live_db", False))
    maintenance_mode = post_close_ml_mode_name(args)
    cmd = [
        str(SCRIPT_DIR / "run_post_close_ml_maintenance.sh"),
        "--workspace-root",
        str(root),
        "--runtime-data-dir",
        str(runtime),
        "--horizon-min",
        horizon,
    ]
    if heavy_research:
        cmd.append("--heavy-research")
    else:
        cmd.append("--quick")
    if use_snapshot:
        cmd.append("--use-snapshot")
    elif heavy_research:
        cmd.append("--live-db")

    log_dir = runtime / "logs/app"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "post-close-ml-maintenance.stdout.log"
    stderr_path = log_dir / "post-close-ml-maintenance.stderr.log"
    try:
        with stdout_path.open("ab") as out, stderr_path.open("ab") as err:
            process = subprocess.Popen(cmd, cwd=root, stdout=out, stderr=err, start_new_session=True)
        payload = {
            "status": "starting",
            "maintenance_date": today,
            "started_at": now_text(),
            "pid": process.pid,
            "workspace_root": str(root),
            "runtime_data_dir": str(runtime),
            "horizon_min": int(horizon),
            "mode": maintenance_mode,
            "maintenance_scope": "heavy" if heavy_research else "quick",
            "stdout_log_path": str(stdout_path),
            "stderr_log_path": str(stderr_path),
        }
        write_json(state_path, payload, echo=False)
        if heavy_research:
            return "start_heavy_snapshot_ml" if use_snapshot else "start_heavy_live_db_ml"
        return "start_quick_post_close"
    except Exception as exc:
        errors.append(f"post_close_ml_start: {exc}")
        return "start_failed"


def post_close_ml_mode_name(args: argparse.Namespace) -> str:
    if not bool(getattr(args, "post_close_ml_heavy_research", False)):
        return "quick-live-train"
    if bool(getattr(args, "post_close_ml_live_db", False)):
        return "heavy-live-db"
    return "heavy-snapshot"


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace-root", "-WorkspaceRoot", default=str(REPO_ROOT))
    parser.add_argument("--runtime-data-dir", "-RuntimeDataDir", default="")


def start_dashboard(args: argparse.Namespace) -> None:
    root = Path(args.workspace_root).expanduser().resolve()
    runtime = runtime_dir(root, args.runtime_data_dir)
    log_dir = runtime / "logs/app"
    state_path = runtime / "reports/dashboard/state/server-state.json"
    stdout_path = log_dir / "dashboard-server.stdout.log"
    stderr_path = log_dir / "dashboard-server.stderr.log"
    log_dir.mkdir(parents=True, exist_ok=True)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"http://{args.dashboard_host}:{args.port}"

    if args.force_restart:
        stop_pids(find_pids("-m", "app", "--serve-dashboard"))
    else:
        state = read_json(state_path, {})
        if pid_matches(state.get("pid"), "-m", "app", "--serve-dashboard"):
            health, api = dashboard_health(url)
            state.update({"status": "running" if health and api else "starting", "process_running": True})
            write_json(state_path, state)
            return

    with stdout_path.open("ab") as out, stderr_path.open("ab") as err:
        process = subprocess.Popen(
            [
                python_bin(),
                "-m",
                "app",
                "--serve-dashboard",
                "--dashboard-host",
                args.dashboard_host,
                "--dashboard-port",
                str(args.port),
                "--dashboard-refresh-seconds",
                str(args.refresh_seconds),
                "--dashboard-recent-limit",
                str(args.recent_limit),
            ],
            cwd=root,
            stdout=out,
            stderr=err,
            start_new_session=True,
        )

    status = "starting"
    health = api = False
    for _ in range(10):
        if process.poll() is not None:
            status = "failed"
            break
        health, api = dashboard_health(url)
        if health and api:
            status = "running"
            break
        time.sleep(1)

    payload = {
        "status": status,
        "pid": process.pid,
        "process_running": process.poll() is None,
        "port_bound": health,
        "host": args.dashboard_host,
        "port": args.port,
        "url": url,
        "refresh_seconds": args.refresh_seconds,
        "recent_limit": args.recent_limit,
        "workspace_root": str(root),
        "runtime_data_dir": str(runtime),
        "stdout_log_path": str(stdout_path),
        "stderr_log_path": str(stderr_path),
        "started_at": now_text(),
        "snapshot_html_path": str(runtime / "reports/dashboard/latest-dashboard.html"),
        "snapshot_json_path": str(runtime / "reports/dashboard/latest-dashboard.json"),
    }
    write_json(state_path, payload)


def get_dashboard_status(args: argparse.Namespace) -> None:
    root = Path(args.workspace_root).expanduser().resolve()
    runtime = runtime_dir(root, args.runtime_data_dir)
    state_path = runtime / "reports/dashboard/state/server-state.json"
    state = read_json(state_path, None)
    if not state:
        write_json(
            Path(os.devnull),
            {"status": "stopped", "process_running": False, "raw_status": "missing", "message": "Dashboard server state not found."},
        )
        return
    process_running = pid_matches(state.get("pid"), "-m", "app", "--serve-dashboard")
    url = state.get("url") or f"http://{state.get('host', '127.0.0.1')}:{state.get('port', 8765)}"
    health, api = dashboard_health(url)
    status = state.get("status", "stopped")
    if health and api:
        status = "running"
        process_running = True
    elif status in {"running", "starting"} and not process_running:
        status = "stale"
    elif status == "running":
        status = "warning"
    payload = {
        "status": status,
        "pid": state.get("pid"),
        "process_running": process_running,
        "port_bound": health,
        "host": state.get("host"),
        "port": state.get("port"),
        "url": url,
        "started_at": state.get("started_at"),
        "stdout_log_path": state.get("stdout_log_path"),
        "stderr_log_path": state.get("stderr_log_path"),
        "snapshot_html_path": state.get("snapshot_html_path"),
        "snapshot_json_path": state.get("snapshot_json_path"),
        "dashboard_responding": health,
        "dashboard_api_responding": api,
        "raw_status": state.get("status"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def stop_dashboard(args: argparse.Namespace) -> None:
    root = Path(args.workspace_root).expanduser().resolve()
    runtime = runtime_dir(root, args.runtime_data_dir)
    state_path = runtime / "reports/dashboard/state/server-state.json"
    pids = find_pids("-m", "app", "--serve-dashboard")
    stop_pids(pids)
    state = read_json(state_path, {})
    payload = {
        "status": "stopped",
        "pid": state.get("pid"),
        "stopped_pids": pids,
        "process_running": False,
        "stopped_at": now_text(),
        "workspace_root": str(root),
        "runtime_data_dir": str(runtime),
    }
    write_json(state_path, payload, echo=False)
    print(f"Stopped dashboard server pid(s) {', '.join(map(str, pids)) if pids else 'none'}.")


def start_live_runtime(args: argparse.Namespace) -> None:
    root = Path(args.workspace_root).expanduser().resolve()
    runtime = runtime_dir(root, args.runtime_data_dir)
    log_dir = runtime / "logs/app"
    state_path = runtime / "reports/live-runtime/state/listener-state.json"
    stdout_path = log_dir / "live-runtime.stdout.log"
    stderr_path = log_dir / "live-runtime.stderr.log"
    log_dir.mkdir(parents=True, exist_ok=True)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    if args.force_restart:
        stop_pids(find_pids("-m", "app", "--kis-ws-listen"))
    else:
        state = read_json(state_path, {})
        if pid_matches(state.get("pid"), "-m", "app", "--kis-ws-listen"):
            state.update({"status": "running", "process_running": True})
            write_json(state_path, state)
            return
    command = [
        python_bin(),
        "-m",
        "app",
        "--kis-ws-listen",
        "--max-frames",
        str(args.max_frames),
        "--max-reconnects",
        str(args.max_reconnects),
        "--watchlist-file",
        args.watchlist_file,
    ]
    if args.symbols:
        command.extend(["--symbols", args.symbols])
    with stdout_path.open("ab") as out, stderr_path.open("ab") as err:
        process = subprocess.Popen(command, cwd=root, stdout=out, stderr=err, start_new_session=True)
    time.sleep(3)
    running = process.poll() is None
    failure = ""
    blocked = ""
    if not running:
        failure = (tail_text(stderr_path) + "\n" + tail_text(stdout_path)).strip().splitlines()[-1:] or ["Live runtime exited immediately after launch."]
        failure = failure[0]
        if "KIS credentials are not configured" in failure:
            blocked = "missing_kis_credentials"
    payload = {
        "status": "running" if running else "failed",
        "pid": process.pid,
        "process_running": running,
        "workspace_root": str(root),
        "runtime_data_dir": str(runtime),
        "symbols": args.symbols,
        "watchlist_file": args.watchlist_file,
        "max_frames": args.max_frames,
        "max_reconnects": args.max_reconnects,
        "prediction_horizons": ["15", "60"],
        "trading_signal_horizon": "15",
        "stdout_log_path": str(stdout_path),
        "stderr_log_path": str(stderr_path),
        "started_at": now_text(),
        "env_file_path": str(root / ".env"),
        "env_file_exists": (root / ".env").exists(),
    }
    if failure:
        payload["failure_reason"] = failure
    if blocked:
        payload["blocked_reason"] = blocked
    write_json(state_path, payload)


def get_live_runtime_status(args: argparse.Namespace) -> None:
    root = Path(args.workspace_root).expanduser().resolve()
    runtime = runtime_dir(root, args.runtime_data_dir)
    state_path = runtime / "reports/live-runtime/state/listener-state.json"
    state = read_json(state_path, None)
    session, _, _ = market_settings(root)
    if not state:
        print(json.dumps({"status": "stopped", "process_running": False, "raw_status": "missing", "current_session_status": session, "session_status": session}, ensure_ascii=False, indent=2))
        return
    running = pid_matches(state.get("pid"), "-m", "app", "--kis-ws-listen")
    env = parse_env(root / ".env")
    mode = (env.get("TRADING_MODE") or "paper").lower()
    prefix = "LIVE" if mode == "live" else "PAPER"
    ready = bool(env.get(f"KIS_APP_KEY_{prefix}") and env.get(f"KIS_APP_SECRET_{prefix}"))
    status = "running" if running else ("failed" if state.get("blocked_reason") or state.get("status") == "failed" else "stopped")
    state.update(
        {
            "status": status,
            "process_running": running,
            "env_file_exists": (root / ".env").exists(),
            "trading_mode": mode,
            "credentials_ready_for_quotes": ready,
            "current_session_status": session,
            "session_status": session,
            "raw_status": state.get("status"),
        }
    )
    print(json.dumps(state, ensure_ascii=False, indent=2))


def stop_live_runtime(args: argparse.Namespace) -> None:
    root = Path(args.workspace_root).expanduser().resolve()
    runtime = runtime_dir(root, args.runtime_data_dir)
    state_path = runtime / "reports/live-runtime/state/listener-state.json"
    pids = find_pids("-m", "app", "--kis-ws-listen")
    stop_pids(pids)
    payload = {
        "status": "stopped",
        "stopped_pids": pids,
        "process_running": False,
        "stopped_at": now_text(),
        "workspace_root": str(root),
        "runtime_data_dir": str(runtime),
    }
    write_json(state_path, payload, echo=False)
    print(f"Stopped live runtime pid(s) {', '.join(map(str, pids)) if pids else 'none'}.")


def run_watchdog_loop(args: argparse.Namespace) -> None:
    root = Path(args.workspace_root).expanduser().resolve()
    runtime = runtime_dir(root, args.runtime_data_dir)
    state_path = runtime / "reports/runtime-watchdog/state/watchdog-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    started = now_text()
    while True:
        errors: list[str] = []
        session, regular, should_run = market_settings(root, pre_open_warmup_minutes=args.pre_open_warmup_minutes)
        dashboard_action = "none"
        live_action = "none"
        try:
            dashboard = subprocess.run(
                [str(SCRIPT_DIR / "get_dashboard_status.sh"), "--workspace-root", str(root), "--runtime-data-dir", str(runtime)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
            )
            dash_state = json.loads(dashboard.stdout) if dashboard.stdout.strip().startswith("{") else {}
        except Exception as exc:
            dash_state = {}
            errors.append(f"dashboard_status: {exc}")
        if dash_state.get("status") != "running":
            subprocess.run(
                [
                    str(SCRIPT_DIR / "start_dashboard_background.sh"),
                    "--workspace-root",
                    str(root),
                    "--runtime-data-dir",
                    str(runtime),
                    "--dashboard-host",
                    args.dashboard_host,
                    "--port",
                    str(args.dashboard_port),
                    "--force-restart",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            dashboard_action = "restart"
        try:
            live = subprocess.run(
                [str(SCRIPT_DIR / "get_live_runtime_status.sh"), "--workspace-root", str(root), "--runtime-data-dir", str(runtime)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
            )
            live_state = json.loads(live.stdout) if live.stdout.strip().startswith("{") else {}
        except Exception as exc:
            live_state = {}
            errors.append(f"live_runtime_status: {exc}")
        if should_run and live_state.get("status") != "running":
            subprocess.run(
                [str(SCRIPT_DIR / "start_live_runtime_background.sh"), "--workspace-root", str(root), "--runtime-data-dir", str(runtime), "--force-restart"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            live_action = "restart"
        elif not should_run and live_state.get("status") == "running":
            subprocess.run([str(SCRIPT_DIR / "stop_live_runtime.sh"), "--workspace-root", str(root), "--runtime-data-dir", str(runtime)], stdout=subprocess.DEVNULL)
            live_action = f"off_session_stop_{session}"
        elif not should_run:
            live_action = f"off_session_hold_{session}"
        ml_action = maybe_start_post_close_ml(root=root, runtime=runtime, session=session, args=args, errors=errors)
        payload = {
            "status": "running" if not errors else "warning",
            "pid": os.getpid(),
            "process_running": True,
            "workspace_root": str(root),
            "runtime_data_dir": str(runtime),
            "dashboard_host": args.dashboard_host,
            "dashboard_port": args.dashboard_port,
            "interval_seconds": args.interval_seconds,
            "dashboard_refresh_interval_seconds": args.dashboard_refresh_interval_seconds,
            "pre_open_warmup_minutes": args.pre_open_warmup_minutes,
            "post_close_ml_enabled": not args.disable_post_close_ml,
            "post_close_ml_delay_minutes": args.post_close_ml_delay_minutes,
            "post_close_ml_horizon_min": args.post_close_ml_horizon_min,
            "post_close_ml_mode": post_close_ml_mode_name(args),
            "market_session_status": session,
            "live_runtime_should_run": should_run,
            "started_at": started,
            "last_checked_at": now_text(),
            "dashboard_action": dashboard_action,
            "dashboard_snapshot_action": "client_refresh",
            "live_runtime_action": live_action,
            "ml_maintenance_action": ml_action,
            "errors": errors,
        }
        write_json(state_path, payload, echo=False)
        if args.single_pass:
            break
        time.sleep(args.interval_seconds)


def start_watchdog(args: argparse.Namespace) -> None:
    root = Path(args.workspace_root).expanduser().resolve()
    runtime = runtime_dir(root, args.runtime_data_dir)
    log_dir = runtime / "logs/app"
    state_path = runtime / "reports/runtime-watchdog/state/watchdog-state.json"
    stdout_path = log_dir / "runtime-watchdog.stdout.log"
    stderr_path = log_dir / "runtime-watchdog.stderr.log"
    log_dir.mkdir(parents=True, exist_ok=True)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    if args.force_restart:
        stop_pids(find_pids_any(("run_runtime_watchdog_loop.sh",), ("wsl_ops.py", "run-watchdog-loop")))
    else:
        state = read_json(state_path, {})
        if pid_matches_any(state.get("pid"), ("run_runtime_watchdog_loop.sh",), ("wsl_ops.py", "run-watchdog-loop")):
            state.update({"status": "running", "process_running": True})
            write_json(state_path, state)
            return
    cmd = [
        str(SCRIPT_DIR / "run_runtime_watchdog_loop.sh"),
        "--workspace-root",
        str(root),
        "--runtime-data-dir",
        str(runtime),
        "--dashboard-host",
        args.dashboard_host,
        "--dashboard-port",
        str(args.dashboard_port),
        "--interval-seconds",
        str(args.interval_seconds),
        "--dashboard-refresh-interval-seconds",
        str(args.dashboard_refresh_interval_seconds),
        "--pre-open-warmup-minutes",
        str(args.pre_open_warmup_minutes),
        "--post-close-ml-delay-minutes",
        str(args.post_close_ml_delay_minutes),
        "--post-close-ml-horizon-min",
        str(args.post_close_ml_horizon_min),
    ]
    if args.disable_post_close_ml:
        cmd.append("--disable-post-close-ml")
    if args.post_close_ml_heavy_research:
        cmd.append("--post-close-ml-heavy-research")
    if args.post_close_ml_live_db:
        cmd.append("--post-close-ml-live-db")
    with stdout_path.open("ab") as out, stderr_path.open("ab") as err:
        process = subprocess.Popen(cmd, cwd=root, stdout=out, stderr=err, start_new_session=True)
    time.sleep(3)
    payload = {
        "status": "running" if process.poll() is None else "failed",
        "pid": process.pid,
        "process_running": process.poll() is None,
        "heartbeat_stale": False,
        "workspace_root": str(root),
        "runtime_data_dir": str(runtime),
        "dashboard_host": args.dashboard_host,
        "dashboard_port": args.dashboard_port,
        "interval_seconds": args.interval_seconds,
        "dashboard_refresh_interval_seconds": args.dashboard_refresh_interval_seconds,
        "pre_open_warmup_minutes": args.pre_open_warmup_minutes,
        "post_close_ml_enabled": not args.disable_post_close_ml,
        "post_close_ml_delay_minutes": args.post_close_ml_delay_minutes,
        "post_close_ml_horizon_min": args.post_close_ml_horizon_min,
        "post_close_ml_mode": post_close_ml_mode_name(args),
        "stdout_log_path": str(stdout_path),
        "stderr_log_path": str(stderr_path),
        "started_at": now_text(),
    }
    write_json(state_path, payload)


def get_watchdog_status(args: argparse.Namespace) -> None:
    root = Path(args.workspace_root).expanduser().resolve()
    runtime = runtime_dir(root, args.runtime_data_dir)
    state_path = runtime / "reports/runtime-watchdog/state/watchdog-state.json"
    state = read_json(state_path, None)
    if not state:
        print(json.dumps({"status": "stopped", "process_running": False, "raw_status": "missing", "message": "Runtime watchdog state not found."}, indent=2))
        return
    running = pid_matches_any(state.get("pid"), ("run_runtime_watchdog_loop.sh",), ("wsl_ops.py", "run-watchdog-loop"))
    interval = int(state.get("interval_seconds") or 60)
    stale_after = args.heartbeat_stale_after_seconds or max(interval * 10, 600)
    age = None
    stale = False
    stamp = state.get("last_checked_at") or state.get("started_at")
    if stamp:
        try:
            parsed = dt.datetime.strptime(stamp.rsplit(" ", 1)[0], "%Y-%m-%d %H:%M:%S")
            age = round((dt.datetime.now() - parsed).total_seconds(), 1)
            stale = running and age > stale_after
        except Exception:
            stale = running
    status = state.get("status", "stopped")
    if status in {"starting", "running", "warning"} and (not running or stale):
        status = "stale"
    state.update({"status": status, "process_running": running, "heartbeat_stale": stale, "heartbeat_age_seconds": age, "heartbeat_stale_after_seconds": stale_after, "raw_status": state.get("status")})
    print(json.dumps(state, ensure_ascii=False, indent=2))


def stop_watchdog(args: argparse.Namespace) -> None:
    root = Path(args.workspace_root).expanduser().resolve()
    runtime = runtime_dir(root, args.runtime_data_dir)
    state_path = runtime / "reports/runtime-watchdog/state/watchdog-state.json"
    pids = find_pids_any(("run_runtime_watchdog_loop.sh",), ("wsl_ops.py", "run-watchdog-loop"))
    stop_pids(pids)
    payload = {"status": "stopped", "stopped_pids": pids, "process_running": False, "stopped_at": now_text(), "workspace_root": str(root), "runtime_data_dir": str(runtime)}
    write_json(state_path, payload, echo=False)
    print(f"Stopped runtime watchdog pid(s) {', '.join(map(str, pids)) if pids else 'none'}.")


def git(repo: Path, *args: str, check: bool = True) -> tuple[int, str]:
    proc = subprocess.run(["git", "-C", str(repo), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check and proc.returncode:
        raise RuntimeError(f"git -C {repo} {' '.join(args)} failed\n{proc.stdout.strip()}")
    return proc.returncode, proc.stdout.strip()


def _running_under_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
    except Exception:
        return False


def _windows_path_from_wsl(path: Path) -> str:
    proc = subprocess.run(["wslpath", "-w", str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode:
        raise RuntimeError(f"wslpath failed for {path}\n{proc.stdout.strip()}")
    return proc.stdout.strip()


def _windows_git(repo: Path, *args: str) -> tuple[int, str]:
    def ps_quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    repo_path = _windows_path_from_wsl(repo)
    git_args = ", ".join(ps_quote(arg) for arg in args)
    script = r"""
$ErrorActionPreference = 'Stop'
$repoPath = __REPO_PATH__
$gitArgs = @(__GIT_ARGS__)
$gitPath = $null
$desktopRoot = Join-Path $env:LOCALAPPDATA 'GitHubDesktop'
if (Test-Path -LiteralPath $desktopRoot) {
    $candidate = Get-ChildItem -LiteralPath $desktopRoot -Recurse -Filter git.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -like '*resources*app*git*cmd*git.exe' } |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if ($candidate) {
        $gitPath = $candidate.FullName
    }
}
if (-not $gitPath) {
    $command = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($command) {
        $gitPath = $command.Source
    }
}
if (-not $gitPath) {
    Write-Error 'Windows git.exe not found.'
    exit 127
}
& $gitPath -c "safe.directory=$repoPath" -C $repoPath @gitArgs
exit $LASTEXITCODE
""".replace("__REPO_PATH__", ps_quote(repo_path)).replace("__GIT_ARGS__", git_args)
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc.returncode, proc.stdout.strip()


def git_push(repo: Path, remote: str, refspec: str, *, set_upstream: bool = False) -> None:
    args = ["push"]
    if set_upstream:
        args.append("-u")
    args.extend([remote, refspec])
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    if proc.returncode == 0:
        return
    if _running_under_wsl():
        win_code, win_output = _windows_git(repo, *args)
        if win_code == 0:
            return
        raise RuntimeError(
            f"git -C {repo} {' '.join(args)} failed\n{proc.stdout.strip()}\n"
            f"Windows git fallback failed\n{win_output.strip()}"
        )
    raise RuntimeError(f"git -C {repo} {' '.join(args)} failed\n{proc.stdout.strip()}")


def update_autopush_state(state: dict[str, Any], repo: Path, observed: str, pushed: str, commit: str, result: str) -> None:
    state.setdefault("repos", {})[str(repo)] = {
        "last_observed_version": observed,
        "last_pushed_version": pushed,
        "last_commit": commit,
        "last_result": result,
        "updated_at": now_text(),
    }


def managed_repos(scan_root: Path, config_name: str, recurse: bool) -> list[Path]:
    found: list[Path] = []
    if (scan_root / ".git").exists() and (scan_root / config_name).exists():
        found.append(scan_root)
    if not scan_root.exists():
        return found
    iterator = (path.parent for path in scan_root.rglob(".git") if path.is_dir()) if recurse else (path for path in scan_root.iterdir() if path.is_dir())
    for repo in iterator:
        if (repo / ".git").exists() and (repo / config_name).exists() and repo.resolve() not in found:
            found.append(repo.resolve())
    return sorted(found, key=lambda item: str(item))


def remote_status(repo: Path, remote: str, branch: str) -> tuple[bool, int, int]:
    code, _ = git(repo, "show-ref", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}", check=False)
    if code:
        return False, 0, 0
    _, output = git(repo, "rev-list", "--left-right", "--count", f"{remote}/{branch}...HEAD")
    behind, ahead = [int(part) for part in output.split()[:2]]
    return True, behind, ahead


def expand_template(template: str, version: str, repo: Path, branch: str) -> str:
    return template.replace("{version}", version).replace("{repo}", repo.name).replace("{branch}", branch)


def process_autopush_repo(repo: Path, config_name: str, state: dict[str, Any], log_path: Path) -> None:
    def log(message: str) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{now_text()}] {message}\n")

    cfg = read_json(repo / config_name, {})
    if not cfg.get("enabled", False):
        log(f"[{repo.name}] disabled in {config_name}")
        return
    branch = cfg.get("branch") or "main"
    remote = cfg.get("remote") or "origin"
    if (cfg.get("trigger") or "version-change") != "version-change":
        log(f"[{repo.name}] unsupported trigger; skipped")
        return
    _, current_branch = git(repo, "branch", "--show-current")
    if current_branch != branch:
        log(f"[{repo.name}] current branch '{current_branch}' does not match '{branch}'; skipped")
        return
    version_file = cfg.get("version_file") or "VERSION"
    version_path = repo / version_file
    if not version_path.exists():
        log(f"[{repo.name}] missing version file '{version_file}'; skipped")
        return
    version = version_path.read_text(encoding="utf-8-sig").strip()
    if not version:
        log(f"[{repo.name}] version file is empty; skipped")
        return
    _, git_dir_text = git(repo, "rev-parse", "--git-dir")
    git_dir = Path(git_dir_text) if Path(git_dir_text).is_absolute() else repo / git_dir_text
    for marker in ["MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG"]:
        if (git_dir / marker).exists():
            raise RuntimeError(f"repository has an active git operation ({marker})")
    repo_state = state.setdefault("repos", {}).get(str(repo), {})
    last_pushed = repo_state.get("last_pushed_version", "")
    _, status = git(repo, "status", "--porcelain")
    has_changes = bool(status)
    has_remote, behind, ahead = remote_status(repo, remote, branch)
    _, head = git(repo, "rev-parse", "HEAD")
    _, head_version = git(repo, "show", f"HEAD:{version_file}", check=False)
    if has_remote and behind > 0:
        update_autopush_state(state, repo, version, last_pushed, head, "branch-behind-remote")
        log(f"[{repo.name}] branch behind remote; skipped")
        return
    if version == last_pushed:
        update_autopush_state(state, repo, version, version, head, "no-version-change")
        log(f"[{repo.name}] version '{version}' unchanged; skipped")
        return

    def push_current() -> None:
        if has_remote:
            git_push(repo, remote, branch)
        else:
            git_push(repo, remote, branch, set_upstream=True)
        if cfg.get("push_tag", False):
            tag = expand_template(cfg.get("tag_name") or "v{version}", version, repo, branch)
            _, tags = git(repo, "tag", "--list", tag)
            if not tags:
                git(repo, "tag", tag)
            git_push(repo, remote, tag)

    if head_version.strip() == version:
        if ahead > 0 or not has_remote:
            push_current()
            result = "pushed-existing-version-commit"
        else:
            result = "synced-head-version"
        update_autopush_state(state, repo, version, version, head, result)
        log(f"[{repo.name}] {result} for version '{version}'")
        return
    if not has_changes:
        if ahead > 0 or not has_remote:
            push_current()
            result = "pushed-clean-head"
        else:
            result = "synced-clean-state"
        update_autopush_state(state, repo, version, version, head, result)
        log(f"[{repo.name}] {result} for version '{version}'")
        return
    stage_mode = cfg.get("stage_mode") or "all"
    if stage_mode == "all":
        git(repo, "add", "-A")
    elif stage_mode == "tracked":
        git(repo, "add", "-u")
        git(repo, "add", "--", version_file)
    elif stage_mode == "version-only":
        git(repo, "add", "--", version_file)
    else:
        raise RuntimeError(f"Unsupported stage_mode: {stage_mode}")
    _, staged = git(repo, "diff", "--cached", "--name-only")
    if not staged:
        update_autopush_state(state, repo, version, last_pushed, head, "no-staged-diff")
        log(f"[{repo.name}] no staged changes; skipped")
        return
    message = expand_template(cfg.get("commit_message") or "chore(release): v{version}", version, repo, branch)
    body = ""
    if (cfg.get("commit_body_mode") or "staged-summary") == "staged-summary":
        _, changed = git(repo, "diff", "--cached", "--name-status", "--find-renames")
        _, stat = git(repo, "diff", "--cached", "--stat")
        lines = ["Version: " + version, "", expand_template(cfg.get("commit_body_header") or "Auto-generated change summary", version, repo, branch) + ":"]
        lines += ["- " + line for line in changed.splitlines()] or ["- no staged file list available"]
        if stat:
            lines += ["", "Diffstat:"] + stat.splitlines()
        body = "\n".join(lines)
    if body:
        git(repo, "commit", "-m", message, "-m", body)
    else:
        git(repo, "commit", "-m", message)
    push_current()
    _, new_head = git(repo, "rev-parse", "HEAD")
    update_autopush_state(state, repo, version, version, new_head, "committed-and-pushed")
    log(f"[{repo.name}] committed and pushed version '{version}'")


def autopush_cycle(args: argparse.Namespace) -> None:
    scan_root = Path(args.scan_root).expanduser().resolve()
    state_path = Path(args.state_path or REPO_ROOT / "runtime-data/autopush/git-autopush-state.json")
    log_path = Path(args.log_path or REPO_ROOT / "runtime-data/autopush/git-autopush.log")
    state = read_json(state_path, {"scan_root": "", "updated_at": "", "repos": {}})
    state["scan_root"] = str(scan_root)
    active: list[str] = []
    for repo in managed_repos(scan_root, args.config_file_name, args.recurse):
        active.append(str(repo))
        try:
            process_autopush_repo(repo, args.config_file_name, state, log_path)
        except Exception as exc:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"[{now_text()}] [{repo.name}] error: {exc}\n")
    state["repos"] = {key: value for key, value in state.get("repos", {}).items() if key in active}
    state["updated_at"] = now_text()
    write_json(state_path, state, echo=False)


def autopush_status(args: argparse.Namespace) -> None:
    state_path = Path(args.state_path or REPO_ROOT / "runtime-data/autopush/git-autopush-state.json")
    log_path = Path(args.log_path or REPO_ROOT / "runtime-data/autopush/git-autopush.log")
    pid_path = REPO_ROOT / "runtime-data/autopush/git-autopush-watcher.pid"
    pid = pid_path.read_text().strip() if pid_path.exists() else ""
    running = pid_matches(pid, "watch_git_versions_and_push.sh")
    state = read_json(state_path, {})
    last_line = ""
    if log_path.exists():
        lines = [line.rstrip("\n") for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
        last_line = lines[-1] if lines else ""
    payload = {
        "task_name": "GitAutoPushWatcher",
        "task_exists": False,
        "task_state": "N/A",
        "launch_mode": "manual" if running else "inactive",
        "watcher_process_count": 1 if running else 0,
        "watcher_pids": [int(pid)] if running and str(pid).isdigit() else [],
        "log_path": str(log_path),
        "log_exists": log_path.exists(),
        "log_last_line": last_line,
        "state_path": str(state_path),
        "state_exists": bool(state),
        "managed_repo_count": len(state.get("repos", {})) if isinstance(state, dict) else 0,
        "last_state_updated_at": state.get("updated_at", "") if isinstance(state, dict) else "",
        "last_known_results": {key: value.get("last_result", "") for key, value in state.get("repos", {}).items()} if isinstance(state, dict) else {},
        "healthy": running,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def audit_autopush(args: argparse.Namespace) -> None:
    root = Path(args.scan_root).expanduser().resolve()
    targets = []
    for repo in managed_repos(root, args.config_file_name, False):
        cfg = read_json(repo / args.config_file_name, {})
        _, branch = git(repo, "branch", "--show-current", check=False)
        _, remotes = git(repo, "remote", check=False)
        _, dirty = git(repo, "status", "--porcelain", check=False)
        targets.append(
            {
                "path": str(repo),
                "has_config": True,
                "enabled": bool(cfg.get("enabled")),
                "has_version_file": (repo / args.version_file_name).exists(),
                "branch": branch,
                "has_remote": bool(remotes),
                "dirty": bool(dirty),
                "recommended": bool(cfg.get("enabled")) and (repo / args.version_file_name).exists() and branch == "main" and bool(remotes),
            }
        )
    print(json.dumps({"scan_root": str(root), "targets": targets}, ensure_ascii=False, indent=2))


def bootstrap_autopush(args: argparse.Namespace) -> None:
    root = Path(args.scan_root).expanduser().resolve()
    repos = [root] if (root / ".git").exists() else []
    if root.exists():
        repos += [path for path in root.iterdir() if path.is_dir() and (path / ".git").exists()]
    changed = []
    default_cfg = {
        "enabled": True,
        "branch": "main",
        "remote": "origin",
        "trigger": "version-change",
        "version_file": args.version_file_name,
        "stage_mode": "version-only",
        "commit_message": "chore(release): v{version}",
        "commit_body_mode": "staged-summary",
        "commit_body_header": "Auto-generated change summary",
        "push_tag": False,
        "tag_name": "v{version}",
    }
    for repo in repos:
        cfg = repo / args.config_file_name
        version = repo / args.version_file_name
        if args.force or not cfg.exists():
            cfg.write_text(json.dumps(default_cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.force or not version.exists():
            version.write_text(args.initial_version + "\n", encoding="utf-8")
        changed.append(str(repo.resolve()))
    print(json.dumps({"bootstrapped": changed}, ensure_ascii=False, indent=2))


def set_autopush_enabled(args: argparse.Namespace) -> None:
    path = Path(args.config_path or REPO_ROOT / "autopush.json")
    cfg = read_json(path, {})
    cfg["enabled"] = bool(args.enabled)
    write_json(path, cfg)


def check_local_setup(args: argparse.Namespace) -> None:
    root = Path(args.workspace_root).expanduser().resolve()
    runtime = runtime_dir(root, args.runtime_data_dir)
    report_dir = runtime / "reports/recovery"
    report_dir.mkdir(parents=True, exist_ok=True)
    env_path = root / ".env"
    values = parse_env(env_path)

    def script_status(name: str) -> dict[str, Any]:
        try:
            proc = run([str(SCRIPT_DIR / name), "--workspace-root", str(root), "--runtime-data-dir", str(runtime)], check=False)
            return json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {"status": "unknown", "message": proc.stdout.strip()}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    try:
        import websockets  # type: ignore  # noqa: F401
        websockets_ok = True
    except Exception:
        websockets_ok = False
    try:
        import lightgbm  # type: ignore  # noqa: F401
        lightgbm_ok = True
    except Exception:
        lightgbm_ok = False
    dashboard = script_status("get_dashboard_status.sh")
    live = script_status("get_live_runtime_status.sh")
    watchdog = script_status("get_runtime_watchdog_status.sh")
    launcher = script_status("get_runtime_startup_launcher_status.sh")
    blockers = []
    if not env_path.exists():
        blockers.append("missing_root_env")
    if dashboard.get("status") != "running":
        blockers.append("dashboard_not_running")
    if watchdog.get("status") not in {"running", "warning"}:
        blockers.append("watchdog_not_running")
    payload = {
        "ok": not blockers,
        "checked_at": now_text(),
        "workspace_root": str(root),
        "runtime_data_dir": str(runtime),
        "env_file_path": str(env_path),
        "env_file_exists": env_path.exists(),
        "trading_mode": values.get("TRADING_MODE", ""),
        "broker_paper_mirroring_enabled": values.get("ENABLE_BROKER_PAPER_MIRRORING") == "true",
        "python_executable": sys.executable,
        "websockets_available": websockets_ok,
        "lightgbm_available": lightgbm_ok,
        "dashboard_status": dashboard,
        "live_runtime_status": live,
        "watchdog_status": watchdog,
        "runtime_startup_launcher_status": launcher,
        "blockers": blockers,
        "next_actions": [],
    }
    write_json(report_dir / "latest-local-setup-check.json", payload, echo=False)
    (report_dir / "latest-local-setup-check.md").write_text(
        "# Local Setup Check\n\n"
        f"- checked at: {payload['checked_at']}\n"
        f"- ok: {payload['ok']}\n"
        f"- blockers: {', '.join(blockers) if blockers else 'none'}\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def verify_paper_dual_account_match(args: argparse.Namespace) -> None:
    root = Path(args.workspace_root).expanduser().resolve()
    runtime = runtime_dir(root, args.runtime_data_dir)
    env_path = root / ".env"
    if not env_path.exists():
        raise SystemExit("Missing root .env. Restore KIS paper credentials before comparing paper accounts.")

    env_before = parse_env(env_path)
    initial_cash_before = env_before.get("PAPER_INITIAL_CASH", "")
    subprocess.run([python_bin(), "-m", "app", "--kis-account-balance"], cwd=root, check=True, stdout=subprocess.DEVNULL)
    account = read_json(runtime / "reports/kis-account/latest-account-paper.json", {}) or read_json(runtime / "reports/kis-account/latest-account.json", {})
    account_snapshot = account.get("account_snapshot") if isinstance(account, dict) else None
    if not isinstance(account_snapshot, dict):
        raise SystemExit("KIS paper account report was not created. Check paper account credentials and KIS connectivity.")

    broker_cash_from_account = number_or_none(account_snapshot.get("cash_balance"))
    broker_position_count_from_account = account_position_count(account_snapshot)
    if args.sync_initial_cash:
        if broker_position_count_from_account > 0:
            raise SystemExit(
                "Broker paper account has open positions, so PAPER_INITIAL_CASH should not be synchronized to current cash. "
                "Run this only before the first submission or after closing/realigning positions."
            )
        if broker_cash_from_account is None or broker_cash_from_account <= 0:
            raise SystemExit("Broker paper cash is unavailable, so PAPER_INITIAL_CASH cannot be synchronized.")
        set_env_value(env_path, "PAPER_INITIAL_CASH", format_env_number(broker_cash_from_account))

    if args.align_to_broker:
        subprocess.run([python_bin(), "-m", "app", "--align-local-paper-to-broker"], cwd=root, check=True, stdout=subprocess.DEVNULL)

    for app_args in (["--sync-broker-paper-orders"], ["--reconcile-paper-accounts"]):
        subprocess.run([python_bin(), "-m", "app", *app_args], cwd=root, check=True, stdout=subprocess.DEVNULL)
    if args.refresh_dashboard:
        subprocess.run([python_bin(), "-m", "app", "--build-dashboard"], cwd=root, check=True, stdout=subprocess.DEVNULL)

    env_after = parse_env(env_path)
    initial_cash_after = env_after.get("PAPER_INITIAL_CASH", "")
    report_dir = runtime / "reports/reconciliation"
    report_dir.mkdir(parents=True, exist_ok=True)
    reconciliation = read_json(report_dir / "latest-paper-account-sync.json", {})
    comp = reconciliation.get("comparison") or {}
    local = reconciliation.get("local_account") or {}
    broker = reconciliation.get("broker_account") or {}
    mismatch = int(comp.get("mismatch_count") or 0)
    cash_gap = float(comp.get("cash_gap") or 0)
    total_gap = float(comp.get("total_asset_gap") or 0)
    mirrored = int(comp.get("mirrored_order_count") or 0)
    local_positions = local.get("positions") if isinstance(local.get("positions"), list) else []
    local_position_count = len(local_positions)
    initial_cash_check_required = broker_position_count_from_account == 0 and local_position_count == 0
    initial_cash_matches_broker = True
    if initial_cash_check_required:
        local_initial_cash = number_or_none(initial_cash_after)
        initial_cash_matches_broker = (
            local_initial_cash is not None
            and broker_cash_from_account is not None
            and abs(local_initial_cash - broker_cash_from_account) < 1
        )
    balance_match = bool(comp.get("balance_match")) if comp.get("balance_match") is not None else abs(cash_gap) < 1
    total_asset_match = bool(comp.get("total_asset_match")) if comp.get("total_asset_match") is not None else abs(total_gap) < 1
    accounts_match = bool(reconciliation.get("ok")) and mismatch == 0 and balance_match and total_asset_match
    ok = (
        bool(account.get("ok", True))
        and bool(reconciliation.get("ok"))
        and bool(comp.get("order_mirroring_enabled"))
        and initial_cash_matches_broker
        and accounts_match
    )
    if ok and mirrored == 0:
        status = "matched_waiting_first_submission"
    elif ok:
        status = "matched"
    elif initial_cash_check_required and not initial_cash_matches_broker:
        status = "initial_cash_mismatch"
    else:
        status = "needs_review"
    payload = {
        "ok": ok,
        "checked_at": now_text(),
        "status": status,
        "actions": {"sync_initial_cash": args.sync_initial_cash, "align_to_broker": args.align_to_broker, "refresh_dashboard": args.refresh_dashboard},
        "env": {
            "paper_initial_cash_before": initial_cash_before,
            "paper_initial_cash_after": initial_cash_after,
            "initial_cash_check_required": initial_cash_check_required,
            "initial_cash_matches_broker_cash": initial_cash_matches_broker,
            "trading_mode": env_after.get("TRADING_MODE", ""),
            "broker_paper_mirroring_enabled": bool(comp.get("order_mirroring_enabled")),
        },
        "broker_account": broker,
        "local_account": local,
        "comparison": comp,
        "report_json_path": str(report_dir / "latest-paper-dual-account-match.json"),
        "report_markdown_path": str(report_dir / "latest-paper-dual-account-match.md"),
    }
    write_json(report_dir / "latest-paper-dual-account-match.json", payload, echo=False)
    (report_dir / "latest-paper-dual-account-match.md").write_text(
        "# Paper Dual Account Match\n\n"
        f"- checked at: {payload['checked_at']}\n"
        f"- ok: {payload['ok']}\n"
        f"- status: {payload['status']}\n"
        f"- local initial cash before: {initial_cash_before}\n"
        f"- local initial cash after: {initial_cash_after}\n"
        f"- initial cash check required: {initial_cash_check_required}\n"
        f"- cash gap: {cash_gap}\n"
        f"- total asset gap: {total_gap}\n"
        f"- mismatch count: {mismatch}\n",
        encoding="utf-8",
    )
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Paper dual account match: {status}\nreport: {payload['report_json_path']}")
    if args.fail_on_mismatch and not ok:
        raise SystemExit(1)


def hourly_audit(args: argparse.Namespace) -> None:
    root = Path(args.workspace_root).expanduser().resolve()
    runtime = runtime_dir(root, args.runtime_data_dir)
    now = dt.datetime.now()
    date_text = now.strftime("%Y-%m-%d")
    time_label = now.strftime("%H%M")
    base = runtime / "reports/codex/automation"
    paths = {
        "history": base / "history" / date_text / f"{time_label}-review.md",
        "research": base / "research" / date_text / f"{time_label}-web-notes.md",
        "draft": base / "drafts/latest-improvement-draft.md",
        "context": base / "state/latest-context.md",
        "progress": base / "state/latest-progress.json",
        "backlog": base / "backlog/latest-priority-backlog.json",
        "runner": base / "state/runner-state.json",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    _, status = git(root, "status", "--short", check=False)
    text = (
        "# Hourly Repo Audit\n\n"
        "## Summary\n"
        f"- generated_at: {now_text()}\n"
        f"- git_status: {status or 'clean'}\n\n"
        "## Note\n"
        "- Bash WSL audit runner recorded a lightweight local inspection.\n"
    )
    for key in ("history", "research", "draft", "context"):
        paths[key].write_text(text, encoding="utf-8")
    progress = {
        "generated_at": now_text(),
        "run_label": now.strftime("%Y-%m-%d %H:%M"),
        "session_status": "local",
        "kis_verification_action": "not-run",
        "last_run_summary": "Lightweight bash audit completed.",
        "open_items": [],
        "resolved_items": [],
        "next_actions": [],
        "latest_source_links": [],
        "latest_artifacts": [str(paths["history"])],
        "error": None,
    }
    write_json(paths["progress"], progress, echo=False)
    write_json(paths["backlog"], {"date": date_text, "generated_at": now_text(), "items": [], "error": None}, echo=False)
    write_json(paths["runner"], {"automation_name": "Hourly Repo Audit", "status": "completed", "last_run_at": now_text(), "last_review_path": str(paths["history"])}, echo=False)
    print(paths["history"])


def export_recovery(args: argparse.Namespace) -> None:
    repo = Path(args.repo_root or REPO_ROOT).expanduser().resolve()
    dest = Path(args.destination_root or REPO_ROOT / ".codex-artifacts/recovery-exports").expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    prefix = args.package_prefix or "real-time-stock-price-prediction-program-recovery"
    archive = dest / f"{prefix}-{stamp}.tar.gz"
    if args.dry_run:
        print(f"Dry run: {archive}")
        return
    excluded_prefixes = {".env", "runtime-data/cache/kis", "runtime-data/logs"}
    private_key_prefixes = ("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519")
    with tarfile.open(archive, "w:gz") as tar:
        for path in repo.rglob("*"):
            rel = path.relative_to(repo).as_posix()
            if rel.startswith(".env"):
                continue
            if any(rel == item or rel.startswith(item + "/") for item in excluded_prefixes):
                continue
            if path.name.endswith((".pem", ".key")) or path.name.startswith(private_key_prefixes):
                continue
            tar.add(path, arcname=rel, recursive=False)
    if args.keep_count > 0:
        archives = sorted(dest.glob(f"{prefix}-*.tar.gz"), key=lambda item: item.stat().st_mtime, reverse=True)
        for old in archives[args.keep_count:]:
            old.unlink()
    print(archive)


def install_service(args: argparse.Namespace, kind: str) -> None:
    service_dir = Path.home() / ".config/systemd/user"
    service_dir.mkdir(parents=True, exist_ok=True)
    if kind == "autopush":
        service = service_dir / "git-autopush-watcher.service"
        command = f"{SCRIPT_DIR / 'watch_git_versions_and_push.sh'} --scan-root {args.scan_root} --poll-seconds {args.poll_seconds}"
        name = "Git autopush watcher"
    else:
        service = service_dir / "stock-runtime-autoboot.service"
        command = str(SCRIPT_DIR / "start_runtime_autoboot.sh")
        name = "Stock runtime autoboot"
    service.write_text(
        "[Unit]\n"
        f"Description={name}\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={REPO_ROOT}\n"
        f"ExecStart={command}\n"
        "Restart=on-failure\n\n"
        "[Install]\n"
        "WantedBy=default.target\n",
        encoding="utf-8",
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["systemctl", "--user", "enable", service.name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Installed user service: {service}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(name: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name)
        add_common_args(p)
        return p

    p = common("start-dashboard")
    p.add_argument("--dashboard-host", "-DashboardHost", default="127.0.0.1")
    p.add_argument("--port", "-Port", type=int, default=8765)
    p.add_argument("--refresh-seconds", "-RefreshSeconds", type=int, default=600)
    p.add_argument("--recent-limit", "-RecentLimit", type=int, default=100)
    p.add_argument("--force-restart", "-ForceRestart", action="store_true")
    common("get-dashboard-status")
    common("stop-dashboard")

    p = common("start-live-runtime")
    p.add_argument("--symbols", "-Symbols", default="")
    p.add_argument("--watchlist-file", "-WatchlistFile", default="config/watchlist.txt")
    p.add_argument("--max-frames", "-MaxFrames", type=int, default=0)
    p.add_argument("--max-reconnects", "-MaxReconnects", type=int, default=999999)
    p.add_argument("--force-restart", "-ForceRestart", action="store_true")
    common("get-live-runtime-status")
    common("stop-live-runtime")

    p = common("run-watchdog-loop")
    p.add_argument("--dashboard-host", "-DashboardHost", default="127.0.0.1")
    p.add_argument("--dashboard-port", "-DashboardPort", type=int, default=8765)
    p.add_argument("--interval-seconds", "-IntervalSeconds", type=int, default=60)
    p.add_argument("--dashboard-refresh-interval-seconds", "-DashboardRefreshIntervalSeconds", type=int, default=600)
    p.add_argument("--pre-open-warmup-minutes", "-PreOpenWarmupMinutes", type=int, default=60)
    p.add_argument("--post-close-ml-delay-minutes", "-PostCloseMlDelayMinutes", type=int, default=30)
    p.add_argument("--post-close-ml-horizon-min", "-PostCloseMlHorizonMin", type=int, default=15)
    p.add_argument("--disable-post-close-ml", "-DisablePostCloseMl", action="store_true")
    p.add_argument("--post-close-ml-heavy-research", "-PostCloseMlHeavyResearch", action="store_true")
    p.add_argument("--post-close-ml-live-db", "-PostCloseMlLiveDb", action="store_true")
    p.add_argument("--single-pass", "-SinglePass", action="store_true")

    p = common("start-watchdog")
    p.add_argument("--dashboard-host", "-DashboardHost", default="127.0.0.1")
    p.add_argument("--dashboard-port", "-DashboardPort", type=int, default=8765)
    p.add_argument("--interval-seconds", "-IntervalSeconds", type=int, default=60)
    p.add_argument("--dashboard-refresh-interval-seconds", "-DashboardRefreshIntervalSeconds", type=int, default=600)
    p.add_argument("--pre-open-warmup-minutes", "-PreOpenWarmupMinutes", type=int, default=60)
    p.add_argument("--post-close-ml-delay-minutes", "-PostCloseMlDelayMinutes", type=int, default=30)
    p.add_argument("--post-close-ml-horizon-min", "-PostCloseMlHorizonMin", type=int, default=15)
    p.add_argument("--disable-post-close-ml", "-DisablePostCloseMl", action="store_true")
    p.add_argument("--post-close-ml-heavy-research", "-PostCloseMlHeavyResearch", action="store_true")
    p.add_argument("--post-close-ml-live-db", "-PostCloseMlLiveDb", action="store_true")
    p.add_argument("--force-restart", "-ForceRestart", action="store_true")
    p = common("get-watchdog-status")
    p.add_argument("--heartbeat-stale-after-seconds", "-HeartbeatStaleAfterSeconds", type=int, default=0)
    common("stop-watchdog")

    p = sub.add_parser("autopush-cycle")
    p.add_argument("--scan-root", "-ScanRoot", default=str(REPO_ROOT))
    p.add_argument("--config-file-name", "-ConfigFileName", default="autopush.json")
    p.add_argument("--state-path", "-StatePath", default="")
    p.add_argument("--log-path", "-LogPath", default="")
    p.add_argument("--recurse", "-Recurse", action="store_true")
    p = sub.add_parser("autopush-status")
    p.add_argument("--state-path", "-StatePath", default="")
    p.add_argument("--log-path", "-LogPath", default="")
    p = sub.add_parser("audit-autopush")
    p.add_argument("--scan-root", "-ScanRoot", default=str(REPO_ROOT))
    p.add_argument("--config-file-name", "-ConfigFileName", default="autopush.json")
    p.add_argument("--version-file-name", "-VersionFileName", default="VERSION")
    p = sub.add_parser("bootstrap-autopush")
    p.add_argument("--scan-root", "-ScanRoot", default=str(REPO_ROOT))
    p.add_argument("--config-file-name", "-ConfigFileName", default="autopush.json")
    p.add_argument("--version-file-name", "-VersionFileName", default="VERSION")
    p.add_argument("--initial-version", "-InitialVersion", default="0.1.0")
    p.add_argument("--force", "-Force", action="store_true")
    p = sub.add_parser("set-autopush-enabled")
    p.add_argument("--config-path", "-ConfigPath", default="")
    p.add_argument("--enabled", "-Enabled", action="store_true")
    p.add_argument("--disabled", "-Disabled", action="store_true")

    p = common("check-local-setup")
    p.add_argument("--as-json", "-AsJson", action="store_true")
    p = common("verify-paper-dual-account-match")
    p.add_argument("--sync-initial-cash", "-SyncInitialCash", action="store_true")
    p.add_argument("--align-to-broker", "-AlignToBroker", action="store_true")
    p.add_argument("--refresh-dashboard", "-RefreshDashboard", action="store_true")
    p.add_argument("--fail-on-mismatch", "-FailOnMismatch", action="store_true")
    p.add_argument("--as-json", "-AsJson", action="store_true")
    common("hourly-audit")

    p = sub.add_parser("export-recovery")
    p.add_argument("--repo-root", "-RepoRoot", default="")
    p.add_argument("--destination-root", "-DestinationRoot", default="")
    p.add_argument("--package-prefix", "-PackagePrefix", default="")
    p.add_argument("--keep-count", "-KeepCount", type=int, default=0)
    p.add_argument("--dry-run", "-DryRun", action="store_true")
    p.add_argument("--include-artifacts", "-IncludeArtifacts", action="store_true")
    p.add_argument("--backup-mode", "-BackupMode", default="Manual")
    p.add_argument("--backup-reason", "-BackupReason", default="")

    p = sub.add_parser("install-autopush-service")
    p.add_argument("--scan-root", "-ScanRoot", default=str(REPO_ROOT))
    p.add_argument("--poll-seconds", "-PollSeconds", type=int, default=60)
    sub.add_parser("install-runtime-service")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dispatch = {
        "start-dashboard": start_dashboard,
        "get-dashboard-status": get_dashboard_status,
        "stop-dashboard": stop_dashboard,
        "start-live-runtime": start_live_runtime,
        "get-live-runtime-status": get_live_runtime_status,
        "stop-live-runtime": stop_live_runtime,
        "run-watchdog-loop": run_watchdog_loop,
        "start-watchdog": start_watchdog,
        "get-watchdog-status": get_watchdog_status,
        "stop-watchdog": stop_watchdog,
        "autopush-cycle": autopush_cycle,
        "autopush-status": autopush_status,
        "audit-autopush": audit_autopush,
        "bootstrap-autopush": bootstrap_autopush,
        "set-autopush-enabled": set_autopush_enabled,
        "check-local-setup": check_local_setup,
        "verify-paper-dual-account-match": verify_paper_dual_account_match,
        "hourly-audit": hourly_audit,
        "export-recovery": export_recovery,
    }
    if args.cmd == "install-autopush-service":
        install_service(args, "autopush")
    elif args.cmd == "install-runtime-service":
        install_service(args, "runtime")
    elif args.cmd == "set-autopush-enabled" and args.disabled:
        args.enabled = False
        set_autopush_enabled(args)
    else:
        dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
