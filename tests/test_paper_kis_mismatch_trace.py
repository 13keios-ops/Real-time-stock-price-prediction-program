import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.trace_paper_kis_mismatch import build_trace_report


class PaperKisMismatchTraceTests(unittest.TestCase):
    def test_account_sync_mismatches_override_stale_dual_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "trace.db"
            sqlite3.connect(db_path).close()
            dual_path = tmp_path / "dual.json"
            account_path = tmp_path / "account.json"
            broker_path = tmp_path / "broker.json"
            dual_path.write_text(
                json.dumps(
                    {
                        "comparison": {
                            "status": "needs_review",
                            "mismatch_rows": [
                                {"symbol": "005930", "status": "only_local", "local_qty": 2},
                                {"symbol": "373220", "status": "only_local", "local_qty": 1},
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            account_path.write_text(
                json.dumps(
                    {
                        "comparison": {
                            "status": "needs_review",
                            "mismatch_rows": [
                                {"symbol": "373220", "status": "only_local", "local_qty": 1},
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            broker_path.write_text(json.dumps({"status": "rate_limited"}), encoding="utf-8")

            report = build_trace_report(
                db_path=db_path,
                dual_match_path=dual_path,
                account_sync_path=account_path,
                broker_sync_path=broker_path,
                limit_per_table=3,
                include_auxiliary=False,
            )

        self.assertEqual(report["mismatch_source_report"], "paper_account_sync")
        self.assertEqual(report["symbols"], ["373220"])
        self.assertEqual(report["mismatch_count"], 1)

    def test_dual_report_is_fallback_when_account_sync_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "trace.db"
            sqlite3.connect(db_path).close()
            dual_path = tmp_path / "dual.json"
            account_path = tmp_path / "missing-account.json"
            broker_path = tmp_path / "broker.json"
            dual_path.write_text(
                json.dumps(
                    {
                        "comparison": {
                            "status": "needs_review",
                            "mismatch_rows": [
                                {"symbol": "005930", "status": "only_local", "local_qty": 2},
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            broker_path.write_text(json.dumps({"status": "rate_limited"}), encoding="utf-8")

            report = build_trace_report(
                db_path=db_path,
                dual_match_path=dual_path,
                account_sync_path=account_path,
                broker_sync_path=broker_path,
                limit_per_table=3,
                include_auxiliary=False,
            )

        self.assertEqual(report["mismatch_source_report"], "dual_account_match")
        self.assertEqual(report["symbols"], ["005930"])


if __name__ == "__main__":
    unittest.main()
