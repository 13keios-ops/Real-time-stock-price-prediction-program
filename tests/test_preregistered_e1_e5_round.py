import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.run_preregistered_e1_e5_round import (
    ResearchSnapshotError,
    _create_snapshot,
    evaluate_execution_gate,
    evaluate_label_refresh_gate,
    run_preregistered_round,
    write_round_outputs,
)


class PreregisteredE1E5RoundTests(unittest.TestCase):
    def test_snapshot_timeout_is_bounded_and_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts_dir = root / "scripts"
            scripts_dir.mkdir()
            snapshot_script = scripts_dir / "create_research_db_snapshot.sh"
            snapshot_script.write_text("#!/usr/bin/env bash\nexit 124\n", encoding="utf-8")
            with self.assertRaises(ResearchSnapshotError) as caught:
                _create_snapshot(root, timeout_seconds=1)

        self.assertEqual(caught.exception.code, "research_snapshot_timeout")

    def test_snapshot_script_cleans_partial_files_after_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "source.db"
            destination = tmp_path / "snapshot.db"
            lock_connection = sqlite3.connect(source)
            lock_connection.execute("create table sample (value integer)")
            lock_connection.commit()
            lock_connection.execute("begin exclusive")
            try:
                result = subprocess.run(
                    [
                        "bash",
                        str(Path(__file__).resolve().parents[1] / "scripts" / "create_research_db_snapshot.sh"),
                        "--src",
                        str(source),
                        "--dst",
                        str(destination),
                        "--timeout-seconds",
                        "1",
                        "--json",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            finally:
                lock_connection.rollback()
                lock_connection.close()

            self.assertEqual(result.returncode, 124)
            self.assertFalse(destination.exists())
            self.assertEqual(list(tmp_path.glob("*.partial*")), [])

    def test_execution_gate_enforces_not_before_and_protected_session(self) -> None:
        kst = ZoneInfo("Asia/Seoul")
        early = evaluate_execution_gate(
            current_time=datetime(2026, 7, 20, 15, 0, tzinfo=kst),
            session_status="post-close",
        )
        self.assertFalse(early["allowed"])
        self.assertIn("before_preregistered_not_before", early["blocking_reasons"])

        protected = evaluate_execution_gate(
            current_time=datetime(2026, 7, 21, 10, 0, tzinfo=kst),
            session_status="regular-session",
        )
        self.assertFalse(protected["allowed"])
        self.assertIn("protected_market_session", protected["blocking_reasons"])

        allowed = evaluate_execution_gate(
            current_time=datetime(2026, 7, 20, 16, 0, tzinfo=kst),
            session_status="post-close",
        )
        self.assertTrue(allowed["allowed"])

    def test_label_refresh_gate_requires_completed_2026_07_20_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "label-refresh.json"
            missing = evaluate_label_refresh_gate(state_path)
            self.assertFalse(missing["ready"])
            self.assertEqual(missing["blocking_reason"], "label_refresh_state_missing")

            state_path.write_text(
                '{"status":"ok","maintenance_date":"2026-07-19","completed_at":"2026-07-19 16:50:00 +0900"}\n',
                encoding="utf-8",
            )
            stale = evaluate_label_refresh_gate(state_path)
            self.assertFalse(stale["ready"])
            self.assertEqual(
                stale["blocking_reason"],
                "label_refresh_not_ready_for_2026_07_20",
            )

            state_path.write_text(
                '{"status":"ok","maintenance_date":"2026-07-20","completed_at":"2026-07-20 16:50:00 +0900"}\n',
                encoding="utf-8",
            )
            ready = evaluate_label_refresh_gate(state_path)
            self.assertTrue(ready["ready"])
            self.assertIsNone(ready["blocking_reason"])

    def test_round_uses_fixed_window_and_writes_timestamped_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "research.db"
            diagnostics_path = root / "diagnostics.json"
            diagnostics_path.write_text('{"trade_cost_pct": 0.108}\n', encoding="utf-8")
            connection = sqlite3.connect(db_path)
            self.addCleanup(connection.close)
            connection.executescript(
                """
                CREATE TABLE serving_trade_signals (
                    signal_id TEXT,
                    symbol TEXT,
                    event_time TEXT,
                    side TEXT,
                    confidence REAL,
                    reason TEXT,
                    allowed INTEGER
                );
                CREATE TABLE serving_predictions (
                    prediction_id TEXT,
                    symbol TEXT,
                    event_time TEXT,
                    horizon_min INTEGER,
                    model_version TEXT,
                    probability_up REAL,
                    probability_flat REAL,
                    probability_down REAL
                );
                CREATE TABLE feature_labels (
                    symbol TEXT,
                    event_time TEXT,
                    horizon_min INTEGER,
                    label TEXT,
                    threshold_pct REAL,
                    future_return_pct REAL
                );
                """
            )
            inside_days = ["2026-07-10", "2026-07-13", "2026-07-14"]
            idx = 0
            for day in ["2026-07-03", *inside_days]:
                for symbol in ("005380", "035420", "105560"):
                    for rank in range(4):
                        event_time = f"{day}T09:{10 + rank:02d}:00+09:00"
                        future_return = -1.5 + rank
                        if symbol == "005380":
                            probability_up = 0.10 + rank * 0.10
                            probability_down = 0.70 - rank * 0.10
                        elif symbol == "035420":
                            probability_up = 0.20 + rank * 0.05
                            probability_down = 0.40 - rank * 0.10
                        else:
                            probability_up = 0.20 + rank * 0.05
                            probability_down = 0.10 + rank * 0.10
                        probability_flat = 1.0 - probability_up - probability_down
                        connection.execute(
                            "INSERT INTO serving_trade_signals VALUES (?, ?, ?, 'buy', 0.5, 'baseline', 1)",
                            (f"sig-{idx}", symbol, event_time),
                        )
                        connection.execute(
                            "INSERT INTO serving_predictions VALUES (?, ?, ?, 15, 'lightgbm-h15-v1', ?, ?, ?)",
                            (
                                f"pred-{idx}",
                                symbol,
                                event_time,
                                probability_up,
                                probability_flat,
                                probability_down,
                            ),
                        )
                        connection.execute(
                            "INSERT INTO feature_labels VALUES (?, ?, 15, 'flat', 0.35, ?)",
                            (symbol, event_time, future_return),
                        )
                        idx += 1
            connection.commit()

            payload = run_preregistered_round(
                database_path=db_path,
                diagnostics_path=diagnostics_path,
                generated_at=datetime(2026, 7, 20, 16, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            )
            output_dir = root / "outputs" / "20260720-160000"
            paths = write_round_outputs(payload, output_dir)

            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["window"], {"start_date": "2026-07-04", "end_date": "2026-07-18"})
            self.assertEqual(payload["e1"]["joined_rows"], 36)
            self.assertEqual(
                payload["lineage_scope"]["e1"]["status"],
                "legacy_or_mixed_lineage_diagnostic_only",
            )
            self.assertEqual(payload["lineage_scope"]["e5"]["status"], "legacy_lineage_missing")
            self.assertFalse(payload["lineage_scope"]["candidate_or_policy_eligible"])
            self.assertEqual(
                payload["e1"]["preregistered_remeasurement"]["candidate_reproducibility"]["reproduced_count"],
                3,
            )
            self.assertFalse(payload["e5"]["automatic_policy_change"])
            self.assertFalse(payload["e5"]["policy_review_eligible"])
            self.assertTrue(all(Path(path).is_file() for path in paths.values()))


if __name__ == "__main__":
    unittest.main()
