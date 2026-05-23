import json
import os
from datetime import datetime
from pathlib import Path
import unittest
import uuid
from unittest.mock import MagicMock, patch

from app.config.settings import load_settings
from app.services.orchestrator import run_synthetic_dev_cycle
from app.services.paper_reconciliation import reconcile_paper_accounts
from app.services.reporting import build_runtime_report
from app.storage.contracts import LiveOrder
from app.storage.runtime_writer import get_sqlite_store


class ReportingTests(unittest.TestCase):
    def _mock_account_report(self) -> MagicMock:
        report = MagicMock()
        report.to_dict.return_value = {
            "ok": True,
            "trading_mode": "paper",
            "fetched_at": "2026-04-17T09:31:00+09:00",
            "cache_used": False,
            "cache_age_seconds": 0,
            "error": None,
            "source": "kis-broker",
            "account_snapshot": {
                "account_no_masked": "1234****",
                "product_code": "01",
                "cash_balance": 1000000,
                "stock_evaluation_amount": 0,
                "total_evaluation_amount": 1000000,
                "total_purchase_amount": 0,
                "total_profit_loss_amount": 0,
                "total_asset_amount": 1000000,
                "positions": [],
            },
        }
        return report

    def _seed_live_fill_mismatch(self, root: Path, *, trading_day: str = "2026-04-13") -> None:
        store = get_sqlite_store(load_settings(project_root=root))
        created_at = datetime.fromisoformat(f"{trading_day}T10:05:00+09:00")
        store.insert_live_order(
            LiveOrder(
                order_id="live-order-report-mismatch",
                idempotency_key="live-idem-report-mismatch",
                trading_day=trading_day,
                phase="phase2_canary",
                symbol="005930",
                side="buy",
                qty=3,
                filled_qty=3,
                remaining_qty=0,
                order_type="limit",
                limit_price=70000.0,
                avg_fill_price=70000.0,
                status="filled",
                prediction_id="pred-report-live-001",
                signal_id="signal-report-live-001",
                target_id="target-report-live-001",
                gate_decision_id="gate-report-live-001",
                market_status_snapshot_id="market-report-live-001",
                model_version="baseline-h15-v1",
                rule_version="live-rule-v1",
                broker_order_no="0000000002",
                broker_branch_no="001",
                reject_reason=None,
                cancel_reason=None,
                parent_order_id=None,
                created_at=created_at,
                submitted_at=created_at,
                last_synced_at=created_at,
                detail_json={
                    "order_policy": {},
                    "blocking_reasons": [],
                    "raw_broker_response": {},
                },
            )
        )

    def _seed_live_order_attention(self, root: Path, *, trading_day: str = "2026-04-13") -> None:
        store = get_sqlite_store(load_settings(project_root=root))
        created_at = datetime.fromisoformat(f"{trading_day}T10:15:00+09:00")
        store.insert_live_order(
            LiveOrder(
                order_id="live-order-report-unknown",
                idempotency_key="live-idem-report-unknown",
                trading_day=trading_day,
                phase="phase2_canary",
                symbol="005930",
                side="buy",
                qty=3,
                filled_qty=0,
                remaining_qty=3,
                order_type="limit",
                limit_price=70000.0,
                avg_fill_price=0.0,
                status="unknown",
                prediction_id="pred-report-live-unknown",
                signal_id="signal-report-live-unknown",
                target_id="target-report-live-unknown",
                gate_decision_id="gate-report-live-unknown",
                market_status_snapshot_id="market-report-live-unknown",
                model_version="baseline-h15-v1",
                rule_version="live-rule-v1",
                broker_order_no="0000000004",
                broker_branch_no="001",
                reject_reason=None,
                cancel_reason=None,
                parent_order_id=None,
                created_at=created_at,
                submitted_at=created_at,
                last_synced_at=created_at,
                detail_json={
                    "order_policy": {},
                    "blocking_reasons": [],
                    "raw_broker_response": {},
                },
            )
        )

    def test_build_runtime_report_after_synthetic_cycle(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "reporting" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{runtime_root / 'dev.db'}",
        }

        with patch.dict(os.environ, env, clear=False):
            run_synthetic_dev_cycle(project_root=root, symbol="005930", minutes=70, train_horizon_min=15)
            with patch("app.services.paper_reconciliation.refresh_kis_account_report", return_value=self._mock_account_report()):
                reconcile_paper_accounts(project_root=root)
            self._seed_live_fill_mismatch(root)
            self._seed_live_order_attention(root)
            report = build_runtime_report(project_root=root)

            self.assertTrue(report.report_markdown_path.exists())
            self.assertTrue(report.report_json_path.exists())
            self.assertGreater(report.summary["minute_bars"], 0)
            self.assertGreater(report.summary["training_runs"], 0)
            self.assertGreater(report.summary["backtests"], 0)
            self.assertGreater(report.summary["walk_forward_runs"], 0)
            self.assertGreater(report.summary["challenger_runs"], 0)
            self.assertEqual(report.summary["live_fill_mismatches"], 1)
            self.assertEqual(report.summary["live_order_attention"], 1)
            self.assertEqual(report.summary["live_open_orders"], 1)
            self.assertEqual(report.summary["live_phase2_parent_orders"], 2)
            self.assertTrue(report.summary["live_phase2_parent_order_limit_blocked"])
            self.assertEqual(report.summary["live_audit_integrity_issues"], 0)
            self.assertEqual(report.summary["live_alerts"], 2)
            report_text = report.report_markdown_path.read_text(encoding="utf-8")
            self.assertIn("Latest Backtest", report_text)
            self.assertIn("Latest Walk-Forward", report_text)
            self.assertIn("Latest Challenger", report_text)
            self.assertIn("Latest Paper Reconciliation", report_text)
            self.assertIn("Live Fill Consistency", report_text)
            self.assertIn("live-order-report-mismatch", report_text)
            self.assertIn("Live Order Attention", report_text)
            self.assertIn("live-order-report-unknown", report_text)
            self.assertIn("Live Phase 2 Parent Order Limit", report_text)
            self.assertIn("Live Audit Integrity", report_text)
            self.assertIn("Live Alert Outbox", report_text)
            report_payload = json.loads(report.report_json_path.read_text(encoding="utf-8"))
            self.assertEqual(report_payload["live_fill_consistency"]["status"], "mismatch")
            self.assertEqual(report_payload["live_fill_consistency"]["mismatch_count"], 1)
            self.assertEqual(report_payload["live_order_attention"]["status"], "attention")
            self.assertEqual(report_payload["live_order_attention"]["attention_count"], 1)
            self.assertEqual(report_payload["live_phase2_parent_order_limit"]["status"], "blocked")
            self.assertEqual(report_payload["live_phase2_parent_order_limit"]["parent_order_count"], 2)
            self.assertTrue(report_payload["live_phase2_parent_order_limit"]["blocked_by_limit"])
            self.assertEqual(report_payload["live_audit_integrity"]["status"], "empty")
            self.assertEqual(report_payload["live_audit_integrity"]["issue_count"], 0)
            self.assertEqual(report_payload["live_alert_outbox"]["status"], "queued")
            self.assertEqual(report_payload["live_alert_outbox"]["alert_count"], 2)
            self.assertEqual(
                [route["event_type"] for route in report_payload["live_alert_outbox"]["routes"]],
                ["live_fill_mismatch", "live_order_attention"],
            )
            for channel in ("local", "telegram", "email"):
                files = list((runtime_root / "reports" / "alerts" / channel).glob("alerts-*.jsonl"))
                self.assertEqual(len(files), 1)
                records = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
                self.assertEqual(len(records), 2)
                self.assertTrue(all(record["delivery_mode"] == "outbox_only" for record in records))


if __name__ == "__main__":
    unittest.main()
