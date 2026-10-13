#!/usr/bin/env python3
"""Inspect a supplied point-in-time snapshot, without API calls or orders."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.universe.intraday_candidates import scan_candidates
from app.universe.kis_candidate_snapshot import scan_kis_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--as-of", required=True, help="Timezone-aware evaluation timestamp")
    parser.add_argument("--format", choices=("normalized", "kis-capture"), default="normalized")
    args = parser.parse_args()
    try:
        path = args.snapshot
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 5_000_000:
            raise ValueError("A regular snapshot file below 5 MB is required")
        payload = json.loads(path.read_text(encoding="utf-8"))
        scanner = scan_kis_snapshot if args.format == "kis-capture" else scan_candidates
        report = scanner(payload, as_of=datetime.fromisoformat(args.as_of))
    except (OSError, ValueError, TypeError, KeyError):
        # Never echo provider payloads, paths or arbitrary exception text.
        print(json.dumps(dict(status="invalid_snapshot", execution_enabled=False,
                              network_calls=0, order_calls=0)), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
