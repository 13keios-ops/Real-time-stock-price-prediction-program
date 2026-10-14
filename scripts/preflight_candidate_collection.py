#!/usr/bin/env python3
"""Print a conservative candidate GET budget; never activates collection."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.candidate_pipeline import candidate_budget_preflight


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbol-count', type=int, default=5)
    parser.add_argument('--market-count', type=int, default=2)
    parser.add_argument('--sector-count', type=int, default=5)
    args = parser.parse_args(argv)
    report = candidate_budget_preflight(symbol_count=args.symbol_count,
        market_count=args.market_count, sector_count=args.sector_count)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except ValueError:
        print(json.dumps({'status':'invalid_budget_plan'}), file=sys.stderr)
        raise SystemExit(1)
