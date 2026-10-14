#!/usr/bin/env python3
"""Arm approved candidate paper collection offline; never starts the runtime."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.config.settings import load_settings
from app.services.candidate_runtime import initialize_candidate_runtime, SUBDIRECTORY
from scripts.run_daily_profit_mission import _assert_runtime_not_protected


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--initialize',action='store_true')
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--status',action='store_true')
    parser.add_argument('--start-date',default='2026-10-15')
    args=parser.parse_args(argv)
    settings=load_settings(project_root=ROOT)
    if args.status:
        path=settings.runtime_data_dir/SUBDIRECTORY/'latest-runtime.json'
        result=json.loads(path.read_text()) if path.exists() else {'status':'not_armed'}
    elif args.initialize and args.execute:
        _assert_runtime_not_protected()
        result=initialize_candidate_runtime(settings,start_date=args.start_date)
    else:
        result={'status':'dry_run_no_activation','network_calls':0,'order_calls':0}
    print(json.dumps(result,ensure_ascii=True,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
