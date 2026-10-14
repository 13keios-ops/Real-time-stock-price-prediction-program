#!/usr/bin/env python3
"""Validate or explicitly replay isolated KR comparison events; never calls KIS."""
import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from app.config.settings import load_settings
from app.paper_trading.daily_mission import MissionContract
from app.services.candidate_pipeline import replay_comparison
from scripts.run_daily_profit_mission import _assert_runtime_not_protected


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events-file',type=Path,required=True)
    parser.add_argument('--symbols',required=True)
    parser.add_argument('--start-date',required=True)
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--execute-paper',action='store_true')
    args=parser.parse_args(argv)
    if args.events_file.stat().st_size>10_000_000:
        raise ValueError('Event file size limit exceeded')
    symbols=tuple(s.strip() for s in args.symbols.split(','))
    if not 1<=len(symbols)<=5:
        raise ValueError('One to five frozen symbols required')
    settings=load_settings(project_root=REPO_ROOT)
    if settings.trading_mode!='paper':
        raise ValueError('Local paper mode required')
    if args.execute_paper:
        if args.output_dir is None:
            raise ValueError('Explicit isolated output directory required')
        _assert_runtime_not_protected()
    contract=MissionContract(start_date=args.start_date,symbols=symbols,
        holidays=tuple(settings.market_calendar.holidays))
    events=json.loads(args.events_file.read_text(encoding='utf-8'))
    folder=args.output_dir.resolve() if args.output_dir else REPO_ROOT/'.tmp-tests/candidate-validation-no-write'
    report=replay_comparison(events,folder,contract,execute_paper=args.execute_paper)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,KeyError,TypeError,OSError) as exc:
        print(json.dumps({'status':'blocked','error_type':type(exc).__name__}),file=sys.stderr)
        raise SystemExit(1)
