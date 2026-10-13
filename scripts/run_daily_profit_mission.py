#!/usr/bin/env python3
"""Initialize or inspect the independent cash-only KR paper mission; no broker calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config.settings import load_settings
from app.paper_trading.daily_mission import DailyProfitMission, MissionContract, MISSION_SUBDIRECTORY
from app.universe.watchlist import load_watchlist


def initialize(folder: Path, contract: MissionContract):
    folder = Path(folder)
    path = folder / "contract.json"
    if folder.is_symlink() or path.is_symlink():
        raise ValueError("Mission contract storage must be isolated.")
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("enabled") is not True or MissionContract.from_dict(payload["contract"]).sha256 != contract.sha256:
            raise ValueError("Existing mission contract differs; never reset the wallet automatically.")
    mission = DailyProfitMission(folder, contract)
    try:
        if not path.exists():
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps({"enabled": True, "contract": contract.to_dict()},
                                            ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
            temporary.replace(path)
        return mission.write_report()
    finally:
        mission.close()


def _assert_runtime_not_protected():
    for name in ("get_live_runtime_status.sh", "get_runtime_watchdog_status.sh"):
        result = subprocess.run([str(REPO_ROOT / "scripts" / name)], cwd=REPO_ROOT,
                                capture_output=True, text=True, timeout=15, check=True)
        status = json.loads(result.stdout)
        if (status.get("process_running") and name == "get_live_runtime_status.sh"
                or status.get("live_runtime_should_run")
                or status.get("current_session_status", status.get("market_session_status")) in {"pre-open", "regular-session"}):
            raise RuntimeError("Protected runtime session: do not initialize the mission now.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--initialize", action="store_true")
    actions.add_argument("--status", action="store_true")
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--start-date", default="2026-10-14")
    args = parser.parse_args(argv)
    settings = load_settings(project_root=REPO_ROOT)
    runtime = (args.runtime_root or settings.runtime_data_dir).resolve()
    folder = runtime / MISSION_SUBDIRECTORY
    if args.status:
        path = folder / "latest.json"
        if not path.exists():
            raise ValueError("Mission report is not available; initialize explicitly first.")
        report = json.loads(path.read_text(encoding="utf-8"))
    else:
        if settings.trading_mode != "paper":
            raise ValueError("The independent mission only supports local paper mode.")
        if runtime == settings.runtime_data_dir.resolve():
            _assert_runtime_not_protected()
        contract = MissionContract(start_date=args.start_date,
                                   symbols=tuple(load_watchlist(REPO_ROOT)),
                                   holidays=tuple(settings.market_calendar.holidays))
        report = initialize(folder, contract)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
