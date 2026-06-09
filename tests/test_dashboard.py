import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import threading
import unittest
import urllib.request
import uuid
from unittest.mock import MagicMock, patch

from app.config.settings import load_settings

from app.services.dashboard import (
    _apply_current_challenger_dashboard_guards,
    _build_account_sync_status,
    _challenger_decision_label,
    build_dashboard_snapshot,
    collect_dashboard_payload,
    prepare_dashboard_server,
)
from app.services.orchestrator import run_synthetic_dev_cycle
from app.services.runtime import run_demo_pipeline
from app.services.streaming import build_sample_ws_frames, replay_ws_frames
from app.storage.contracts import LiveOrder, MarketTickEvent, MinuteBar, PaperPosition, PortfolioSnapshot, Prediction
from app.storage.runtime_writer import RuntimeWriter, get_sqlite_store


class DashboardTests(unittest.TestCase):
    def test_challenger_decision_label_distinguishes_eligibility_from_promotion(self) -> None:
        report = {
            "recommended_action": "keep_active",
            "recommended_model_version": "baseline-h15-v1",
            "promotion_applied": False,
            "promoted_model_version": None,
        }

        self.assertEqual(
            _challenger_decision_label({"candidate_name": "active_model", "model_version": "baseline-h15-v1"}, report),
            "유지 권장",
        )
        self.assertEqual(
            _challenger_decision_label({"candidate_name": "fresh_centroid", "model_version": "centroid-challenger-h15-v1"}, report),
            "관찰",
        )
        self.assertEqual(
            _challenger_decision_label(
                {"candidate_name": "latest_lightgbm", "model_version": "lightgbm-h15-v1"},
                {**report, "recommended_action": "promote", "recommended_model_version": "lightgbm-h15-v1"},
            ),
            "승격 권장",
        )

    def test_challenger_dashboard_guard_marks_legacy_lightgbm_not_promotable(self) -> None:
        report = {
            "candidates": [
                {
                    "candidate_name": "latest_lightgbm",
                    "model_kind": "lightgbm_artifact",
                    "model_version": "lightgbm-h15-v1",
                    "promotable": True,
                    "evaluation_independence_status": "independent_challenger_holdout",
                }
            ]
        }
        lightgbm_status = {
            "artifact_lineage_status": "artifact_missing_training_run_id",
            "artifact_training_run_id": None,
        }

        guarded = _apply_current_challenger_dashboard_guards(report, lightgbm_status)

        self.assertIsInstance(guarded, dict)
        candidate = guarded["candidates"][0]
        self.assertFalse(candidate["promotable"])
        self.assertTrue(candidate["report_promotable"])
        self.assertEqual(candidate["artifact_training_status"], "artifact_missing_training_run_id")
        self.assertEqual(guarded["current_guard_status"], "artifact_lineage_guard_applied")

    def _mock_account_report(self) -> MagicMock:
        report = MagicMock()
        report.to_dict.return_value = {
            "ok": True,
            "trading_mode": "paper",
            "fetched_at": "2026-04-13T10:50:00+09:00",
            "cache_used": False,
            "cache_age_seconds": 0,
            "error": None,
            "source": "kis-broker",
            "account_snapshot": {
                "account_no_masked": "1234****",
                "product_code": "01",
                "cash_balance": 1000000,
                "stock_evaluation_amount": 214500,
                "total_evaluation_amount": 1214500,
                "total_purchase_amount": 210000,
                "total_profit_loss_amount": 4500,
                "total_asset_amount": 1214500,
                "positions": [
                    {
                        "symbol": "005930",
                        "name": "삼성전자",
                        "holding_qty": 3,
                        "current_price": 71500,
                        "evaluation_amount": 214500,
                        "evaluation_profit_loss_amount": 4500,
                    }
                ],
            },
        }
        return report

    def _prepare_runtime_root(self) -> tuple[Path, dict[str, str]]:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "dashboard" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{runtime_root / 'dev.db'}",
        }
        return runtime_root, env

    def _mock_account_report_without_positions(self) -> MagicMock:
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

    def _full_local_account_state(self) -> dict[str, object]:
        return {
            "cash_balance": 1200000.0,
            "net_liquidation_value": 1214500.0,
            "gross_market_value": 214500.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 4500.0,
            "latest_snapshot_time": "2026-04-17T09:31:00+09:00",
            "positions": [
                {
                    "symbol": "005930",
                    "qty": 3,
                    "avg_price": 70000.0,
                    "last_price": 71500.0,
                    "market_value": 214500.0,
                    "realized_pnl": 0.0,
                    "unrealized_pnl": 4500.0,
                }
            ],
            "orders_total": 2,
            "fills_total": 2,
            "broker_order_submissions": 0,
            "latest_broker_submission_time": None,
        }

    def _seed_dashboard_inputs(self, runtime_root: Path) -> None:
        reports_root = runtime_root / "reports"
        (reports_root / "kis-ws").mkdir(parents=True, exist_ok=True)
        (reports_root / "data-quality").mkdir(parents=True, exist_ok=True)
        (reports_root / "recovery").mkdir(parents=True, exist_ok=True)
        (reports_root / "ml-maintenance" / "state").mkdir(parents=True, exist_ok=True)
        (reports_root / "codex" / "automation" / "state").mkdir(parents=True, exist_ok=True)
        (reports_root / "codex" / "automation" / "backlog").mkdir(parents=True, exist_ok=True)
        (reports_root / "codex" / "ops" / "premarket-readiness").mkdir(parents=True, exist_ok=True)
        (reports_root / "live-readiness").mkdir(parents=True, exist_ok=True)

        (reports_root / "recovery" / "latest-local-setup-check.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "checked_at": "2026-05-10 15:34:30 +0900",
                    "blockers": [],
                    "dashboard_status": {
                        "status": "running",
                        "dashboard_api_responding": True,
                    },
                    "live_runtime_status": {
                        "status": "stopped",
                        "session_status": "weekend",
                    },
                    "watchdog_status": {
                        "status": "running",
                        "market_session_status": "weekend",
                        "live_runtime_should_run": False,
                    },
                    "runtime_startup_launcher_status": {"ok": True},
                    "websockets_available": True,
                    "lightgbm_available": True,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        (reports_root / "codex" / "ops" / "premarket-readiness" / "latest-premarket-readiness.json").write_text(
            json.dumps(
                {
                    "job_type": "premarket-readiness",
                    "status": "ok",
                    "generated_at": "2026-05-16 00:18:28 +0900",
                    "report_path": "runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json",
                    "blockers": [],
                    "warnings": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (reports_root / "live-readiness" / "latest-readiness.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "job_type": "live-readiness-fault-dry-run",
                    "status": "blocked",
                    "generated_at": "2026-05-16T02:04:17+09:00",
                    "phase": "phase1_readonly",
                    "trading_day": "2026-05-16",
                    "dry_run": True,
                    "recorded": False,
                    "database_path": None,
                    "blocking_reasons": ["ws_recovery_not_verified_by_fault_dry_run"],
                    "fixture_checks": [
                        {
                            "key": "ws_recovery",
                            "status": "failed",
                            "passed": False,
                            "summary": "synthetic WS recovery evidence is not enough for live submit",
                            "details": {
                                "checked_at": "2026-05-16T02:03:37+09:00",
                                "evidence_type": "synthetic_fault_injection",
                                "evidence_age_seconds": 42.123,
                                "max_evidence_age_seconds": 1800.0,
                                "stable": {
                                    "state": "stable",
                                    "frames_since_connect": 2,
                                    "frames_seen_total": 2,
                                    "cumulative_reconnects": 1,
                                    "consecutive_reconnects": 0,
                                    "reconnect_storm": False,
                                    "observed_at": "2026-05-16T02:04:17+09:00",
                                },
                            },
                        }
                    ],
                    "readiness_run": {
                        "phase": "phase1_readonly",
                        "trading_day": "2026-05-16",
                        "status": "blocked",
                        "passed": False,
                        "checked_at": "2026-05-16T02:04:17+09:00",
                        "checks_json": {
                            "checks": {
                                "token_refresh": False,
                                "ws_recovery": False,
                                "account_snapshot": False,
                                "market_status": False,
                                "kill_switch": False,
                                "database": False,
                                "disk_space": False,
                                "dashboard": False,
                                "storage_migration_state": False,
                            }
                        },
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (reports_root / "kis-ws" / "latest-verification.json").write_text(
            json.dumps(
                {
                    "connection_ready": True,
                    "market_data_flow_ok": False,
                    "approval_key_issued": True,
                    "session_status": "weekend",
                    "status_note": "weekend test",
                    "frames_received": 4,
                    "control_frames": 4,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (reports_root / "ml-maintenance" / "state" / "latest-post-close-ml.json").write_text(
            json.dumps(
                {
                    "status": "ok",
                    "maintenance_date": "2026-05-13",
                    "completed_at": "2026-05-13 16:03:08 +0900",
                    "mode": "quick-live-report",
                    "horizon_min": 15,
                    "snapshot_path": "",
                    "snapshot_runtime_data_dir": "",
                    "stdout_log_path": "",
                    "stderr_log_path": "",
                    "error": None,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (reports_root / "ml-maintenance" / "state" / "latest-post-close-label-refresh.json").write_text(
            json.dumps(
                {
                    "status": "ok",
                    "maintenance_date": "2026-05-13",
                    "completed_at": "2026-05-13 23:15:10 +0900",
                    "mode": "post-close-label-refresh-live-db",
                    "tasks": [
                        "build-feature-dataset",
                        "summarize-kis-live-data-quality",
                        "build-dashboard",
                    ],
                    "recent_days": 10,
                    "skipped_feature_label_build": False,
                    "exit_code": 0,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (reports_root / "data-quality" / "latest-feature-source-drift.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-05-10T07:17:34+09:00",
                    "kis_date_selection": "post_cybos_overlap",
                    "kis_trade_dates": ["2026-05-08"],
                    "samples": {
                        "kis_live": {
                            "rows": 3790,
                            "symbols": 10,
                            "first_event_time": "2026-05-08T09:00:00+09:00",
                            "last_event_time": "2026-05-08T15:19:00+09:00",
                            "label_distribution_h15": {"down": 614, "flat": 2208, "up": 818},
                        },
                        "cybos_historical": {
                            "rows": 100000,
                            "symbols": 199,
                            "first_event_time": "2026-04-06T13:15:00+09:00",
                            "last_event_time": "2026-05-04T15:30:00+09:00",
                            "label_distribution_h15": {"down": 14059, "flat": 67467, "up": 14497},
                        },
                    },
                    "drift_findings": [
                        {
                            "feature": "spread_bps",
                            "flags": ["orderbook_feature_source_mismatch"],
                        }
                    ],
                    "assessment": {
                        "posture": "source_drift_detected",
                        "conclusion": "Cybos historical rows do not carry live orderbook feature distributions.",
                        "orderbook_mismatch_features": ["spread_bps", "bid_ask_imbalance"],
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (reports_root / "data-quality" / "latest-kis-live-feature-diagnostics.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-05-10T08:30:57+09:00",
                    "date_selection": "post_cybos_overlap",
                    "trade_dates": ["2026-05-08"],
                    "sample": {
                        "rows": 3640,
                        "symbols": 10,
                        "trade_dates": 1,
                        "first_event_time": "2026-05-08T09:00:00+09:00",
                        "last_event_time": "2026-05-08T15:04:00+09:00",
                        "label_distribution": {"down": 614, "flat": 2208, "up": 818},
                        "avg_future_return_pct": 0.048176,
                    },
                    "feature_diagnostics": [
                        {
                            "feature": "return_1m_pct",
                            "rows": 3640,
                            "pearson_future_return": -0.039879,
                            "top_bottom_future_return_delta_pct": -0.068962,
                            "top_bottom_up_ratio_delta": -0.04595,
                        },
                        {
                            "feature": "hl_range_pct",
                            "rows": 3640,
                            "pearson_future_return": 0.01536,
                            "top_bottom_future_return_delta_pct": 0.048852,
                            "top_bottom_up_ratio_delta": 0.21729,
                        },
                    ],
                    "assessment": {
                        "posture": "sample_too_small",
                        "conclusion": "KIS live sample is still small; use diagnostics only as directional feature triage.",
                        "strongest_feature": "return_1m_pct",
                        "strongest_feature_pearson": -0.039879,
                        "strongest_feature_top_bottom_delta_pct": -0.068962,
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (reports_root / "codex" / "automation" / "state" / "latest-progress.json").write_text(
            json.dumps(
                {
                    "last_run_summary": "dashboard test progress",
                    "open_items": [{"id": "AUD-004"}],
                    "next_actions": ["check live KIS session"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (reports_root / "codex" / "automation" / "backlog" / "latest-priority-backlog.json").write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "AUD-004",
                            "priority": "P0",
                            "status": "open",
                            "problem": "walk-forward gate needs review",
                            "recommended_change": "tighten weakest fold gate",
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _seed_live_fill_mismatch(self, root: Path, *, trading_day: str = "2026-04-13") -> None:
        store = get_sqlite_store(load_settings(project_root=root))
        created_at = datetime.fromisoformat(f"{trading_day}T10:05:00+09:00")
        store.insert_live_order(
            LiveOrder(
                order_id="live-order-dashboard-mismatch",
                idempotency_key="live-idem-dashboard-mismatch",
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
                prediction_id="pred-dashboard-live-001",
                signal_id="signal-dashboard-live-001",
                target_id="target-dashboard-live-001",
                gate_decision_id="gate-dashboard-live-001",
                market_status_snapshot_id="market-dashboard-live-001",
                model_version="baseline-h15-v1",
                rule_version="live-rule-v1",
                broker_order_no="0000000001",
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
                order_id="live-order-dashboard-unknown",
                idempotency_key="live-idem-dashboard-unknown",
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
                prediction_id="pred-dashboard-live-unknown",
                signal_id="signal-dashboard-live-unknown",
                target_id="target-dashboard-live-unknown",
                gate_decision_id="gate-dashboard-live-unknown",
                market_status_snapshot_id="market-dashboard-live-unknown",
                model_version="baseline-h15-v1",
                rule_version="live-rule-v1",
                broker_order_no="0000000003",
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

    def _seed_actual_prediction_runtime(self, root: Path) -> None:
        settings = load_settings(project_root=root)
        writer = RuntimeWriter.from_settings(settings)
        base_time = datetime.fromisoformat("2026-04-13T10:00:00+09:00")
        future_time = base_time + timedelta(minutes=15)
        writer.write_market_tick(
            MarketTickEvent(symbol="005930", event_time=base_time, price=70000, volume=100, source="kis-ws")
        )
        writer.write_market_tick(
            MarketTickEvent(symbol="005930", event_time=future_time, price=70700, volume=120, source="kis-ws")
        )
        writer.write_minute_bar(
            MinuteBar(
                symbol="005930",
                bar_time=base_time,
                open=69900,
                high=70100,
                low=69850,
                close=70000,
                volume=100,
                trade_count=5,
            )
        )
        writer.write_minute_bar(
            MinuteBar(
                symbol="005930",
                bar_time=future_time,
                open=70500,
                high=70800,
                low=70450,
                close=70700,
                volume=120,
                trade_count=6,
            )
        )
        writer.write_prediction(
            Prediction(
                prediction_id="pred-h15-online-unit-001",
                symbol="005930",
                event_time=base_time,
                horizon_min=15,
                model_version="baseline-h15-v1",
                probability_up=0.8,
                probability_flat=0.1,
                probability_down=0.1,
            )
        )

    def _seed_sparse_actual_prediction_runtime(self, root: Path) -> None:
        settings = load_settings(project_root=root)
        writer = RuntimeWriter.from_settings(settings)
        base_time = datetime.fromisoformat("2026-04-13T10:00:00+09:00")
        later_time = base_time + timedelta(minutes=20)
        writer.write_market_tick(
            MarketTickEvent(symbol="005930", event_time=base_time, price=70000, volume=100, source="kis-ws")
        )
        writer.write_market_tick(
            MarketTickEvent(symbol="005930", event_time=later_time, price=70800, volume=120, source="kis-ws")
        )
        writer.write_minute_bar(
            MinuteBar(
                symbol="005930",
                bar_time=base_time,
                open=69900,
                high=70100,
                low=69850,
                close=70000,
                volume=100,
                trade_count=5,
            )
        )
        writer.write_minute_bar(
            MinuteBar(
                symbol="005930",
                bar_time=later_time,
                open=70700,
                high=70900,
                low=70650,
                close=70800,
                volume=120,
                trade_count=6,
            )
        )
        writer.write_prediction(
            Prediction(
                prediction_id="pred-h15-online-unit-gap-001",
                symbol="005930",
                event_time=base_time,
                horizon_min=15,
                model_version="baseline-h15-v1",
                probability_up=0.9,
                probability_flat=0.05,
                probability_down=0.05,
            )
        )

    def _seed_after_close_prediction_runtime(self, root: Path) -> None:
        settings = load_settings(project_root=root)
        writer = RuntimeWriter.from_settings(settings)
        base_time = datetime.fromisoformat("2026-04-13T15:30:00+09:00")
        writer.write_market_tick(
            MarketTickEvent(symbol="005930", event_time=base_time, price=70000, volume=100, source="kis-ws")
        )
        writer.write_minute_bar(
            MinuteBar(
                symbol="005930",
                bar_time=base_time,
                open=69900,
                high=70100,
                low=69850,
                close=70000,
                volume=100,
                trade_count=5,
            )
        )
        writer.write_prediction(
            Prediction(
                prediction_id="pred-h15-online-unit-close-001",
                symbol="005930",
                event_time=base_time,
                horizon_min=15,
                model_version="baseline-h15-v1",
                probability_up=0.8,
                probability_flat=0.1,
                probability_down=0.1,
            )
        )

    def _seed_many_actual_predictions_runtime(self, root: Path, count: int = 8) -> None:
        settings = load_settings(project_root=root)
        writer = RuntimeWriter.from_settings(settings)
        first_time = datetime.fromisoformat("2026-04-13T10:00:00+09:00")
        for index in range(count):
            base_time = first_time + timedelta(minutes=index)
            future_time = base_time + timedelta(minutes=15)
            base_price = 70000 + index * 10
            future_price = base_price + 700
            for event_time, price in ((base_time, base_price), (future_time, future_price)):
                writer.write_market_tick(
                    MarketTickEvent(symbol="005930", event_time=event_time, price=price, volume=100 + index, source="kis-ws")
                )
                writer.write_minute_bar(
                    MinuteBar(
                        symbol="005930",
                        bar_time=event_time,
                        open=price - 100,
                        high=price + 100,
                        low=price - 150,
                        close=price,
                        volume=100 + index,
                        trade_count=5,
                    )
                )
            writer.write_prediction(
                Prediction(
                    prediction_id=f"pred-h15-online-unit-many-{index:03d}",
                    symbol="005930",
                    event_time=base_time,
                    horizon_min=15,
                    model_version="baseline-h15-v1",
                    probability_up=0.8,
                    probability_flat=0.1,
                    probability_down=0.1,
                )
            )

    def test_build_dashboard_snapshot_creates_files(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            run_synthetic_dev_cycle(project_root=root, symbol="005930", minutes=70, train_horizon_min=15)
            self._seed_dashboard_inputs(runtime_root)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()):
                snapshot = build_dashboard_snapshot(project_root=root, recent_limit=5)

        self.assertTrue(snapshot.snapshot_html_path.exists())
        self.assertTrue(snapshot.snapshot_json_path.exists())
        self.assertIn("runtime_summary", snapshot.payload)
        self.assertIn("active_model", snapshot.payload)
        self.assertTrue(snapshot.payload["dashboard_scope"]["actual_runtime_only"])
        self.assertEqual(snapshot.payload["period_filter"]["range_key"], "today")
        self.assertIn("account_views", snapshot.payload)
        self.assertIn("latest_walk_forward_setup_status", snapshot.payload)
        html = snapshot.snapshot_html_path.read_text(encoding="utf-8")
        self.assertIn("실시간 주가 예측 대시보드", html)
        self.assertIn("운영 대시보드", html)
        self.assertIn("오늘 해야 할 일", html)
        self.assertIn("실전 전환 readiness dry-run", html)
        self.assertIn("계좌 정합성", html)
        self.assertIn("장후 ML", html)
        self.assertIn("데이터/모델", html)
        self.assertIn("예측/주문", html)
        self.assertIn("운영", html)
        self.assertIn("모의투자(가상)", html)
        self.assertIn("모의계좌(실제)", html)
        self.assertIn("실 운용계좌", html)
        self.assertIn("머신러닝 현황", html)
        self.assertIn("예측현황", html)
        self.assertIn("오늘의 리포트", html)
        self.assertIn("모의투자(가상)", html)
        self.assertIn("조회 범위", html)
        self.assertIn("기준 날짜", html)
        self.assertIn("상태 설명", html)
        self.assertIn("보유 종목", html)
        self.assertIn("매수/매도 및 체결현황", html)
        self.assertIn("최근 종료 포지션", html)
        self.assertIn("매수 주문", html)
        self.assertIn("매도 주문", html)
        self.assertIn("최근 신호", html)
        self.assertIn("현재 운용", html)
        self.assertIn("학습 및 평가", html)
        self.assertIn("챌린저 및 워크포워드", html)
        self.assertIn("게이트 기준 워크포워드", html)
        self.assertIn("KIS-Cybos feature drift", html)
        self.assertIn("source_drift_detected", html)
        self.assertIn("KIS live feature-label 진단", html)
        self.assertIn("sample_too_small", html)
        self.assertIn("장전 readiness", html)
        self.assertIn("점검 신선도", html)
        self.assertIn("check_local_setup.sh 최신 결과입니다.", html)
        self.assertIn("실전 전환 readiness dry-run", html)
        self.assertIn("DB 기록", html)
        self.assertIn("ws_recovery_not_verified_by_fault_dry_run", html)
        self.assertIn("WS evidence type", html)
        self.assertIn("synthetic_fault_injection", html)
        self.assertIn("42.123s / max 1800.0s", html)
        self.assertIn("누적 1, 연속 0, storm 아니오", html)
        self.assertEqual(snapshot.payload["latest_live_readiness"]["status"], "blocked")
        self.assertIn("최근 raw minute 지연", html)
        self.assertIn("분봉 coverage(닫힌 분)", html)
        self.assertIn("장전 호가나 REST snapshot 때문에 raw coverage는 100%를 넘을 수 있고", html)
        self.assertIn("장후 ML 유지보수 상태", html)
        self.assertIn("legacy quick-live-report는 학습/평가 row를 만들지 않습니다", html)
        self.assertIn("학습/평가 수행", html)
        self.assertIn("스냅샷 DB", html)
        self.assertIn("stdout 로그", html)
        self.assertIn("장후 label refresh 상태", html)
        self.assertIn("post-close-label-refresh-live-db", html)
        self.assertIn("latest-post-close-label-refresh.json", html)
        self.assertIn("연결 및 설정", html)
        self.assertIn("집계 현황", html)
        self.assertIn("요약", html)
        self.assertIn("주문 및 체결", html)
        self.assertIn("최근 체결", html)
        self.assertIn("분석과 고찰", html)
        self.assertIn("우선순위 backlog", html)
        self.assertIn("data-scroll", html)
        self.assertIn("localStorage.setItem", html)
        self.assertIn("realtime-stock-dashboard-subtab-", html)
        self.assertIn("운용 방식:", html)
        self.assertIn("브로커 주문 자동 연동", html)
        self.assertIn("최근 브로커 제출 주문", html)
        self.assertIn("최근 동기화 점검", html)

    def test_collect_dashboard_payload_uses_read_only_sqlite_path(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            run_synthetic_dev_cycle(project_root=root, symbol="005930", minutes=70, train_horizon_min=15)
            self._seed_dashboard_inputs(runtime_root)
            with (
                patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()),
                patch("app.services.dashboard.get_sqlite_store", wraps=get_sqlite_store) as mocked_get_store,
            ):
                payload = collect_dashboard_payload(project_root=root, recent_limit=5)

        self.assertIn("runtime_summary", payload)
        self.assertTrue(mocked_get_store.called)
        self.assertTrue(any(call.kwargs.get("initialize_schema") is False for call in mocked_get_store.call_args_list))
        self.assertEqual(payload["runtime_summary"]["broker_order_submissions"], 0)
        self.assertIn("order_mirroring_enabled", payload["account_sync"])
        self.assertIn("paper_account_reconciliation", payload)

    def test_dashboard_shows_live_fill_consistency(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            run_synthetic_dev_cycle(project_root=root, symbol="005930", minutes=70, train_horizon_min=15)
            self._seed_dashboard_inputs(runtime_root)
            self._seed_live_fill_mismatch(root)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()):
                snapshot = build_dashboard_snapshot(project_root=root, recent_limit=5, selected_date="2026-04-13")

        self.assertEqual(snapshot.payload["live_fill_consistency"]["status"], "mismatch")
        self.assertEqual(snapshot.payload["live_fill_consistency"]["mismatch_count"], 1)
        self.assertEqual(snapshot.payload["status_alerts"][0]["title"], "실전 fill 정합성 불일치")
        html = snapshot.snapshot_html_path.read_text(encoding="utf-8")
        self.assertIn("실전 fill 정합성", html)
        self.assertIn("실전 fill 불일치 상세", html)
        self.assertIn("live-order-dashboard-mismatch", html)

    def test_dashboard_shows_live_order_attention(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            run_synthetic_dev_cycle(project_root=root, symbol="005930", minutes=70, train_horizon_min=15)
            self._seed_dashboard_inputs(runtime_root)
            self._seed_live_order_attention(root)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()):
                snapshot = build_dashboard_snapshot(project_root=root, recent_limit=5, selected_date="2026-04-13")

        self.assertEqual(snapshot.payload["live_order_attention"]["status"], "attention")
        self.assertEqual(snapshot.payload["live_order_attention"]["attention_count"], 1)
        self.assertEqual(snapshot.payload["status_alerts"][0]["title"], "실전 주문 상태 확인 필요")
        html = snapshot.snapshot_html_path.read_text(encoding="utf-8")
        self.assertIn("실전 미해결 주문", html)
        self.assertIn("실전 미해결 주문 상세", html)
        self.assertIn("live-order-dashboard-unknown", html)

    def test_dashboard_shows_phase2_parent_order_limit(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            run_synthetic_dev_cycle(project_root=root, symbol="005930", minutes=70, train_horizon_min=15)
            self._seed_dashboard_inputs(runtime_root)
            self._seed_live_order_attention(root)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()):
                snapshot = build_dashboard_snapshot(project_root=root, recent_limit=5, selected_date="2026-04-13")

        phase2_limit = snapshot.payload["live_phase2_parent_order_limit"]
        self.assertEqual(phase2_limit["status"], "blocked")
        self.assertEqual(phase2_limit["parent_order_count"], 1)
        self.assertEqual(phase2_limit["max_parent_orders_per_day"], 1)
        self.assertTrue(phase2_limit["blocked_by_limit"])
        html = snapshot.snapshot_html_path.read_text(encoding="utf-8")
        self.assertIn("Phase 2 부모 주문 한도", html)
        self.assertIn("Phase 2 부모 주문 상세", html)
        self.assertIn("live-order-dashboard-unknown", html)

    def test_account_sync_uses_broker_effective_cash(self) -> None:
        account_sync = _build_account_sync_status(
            {
                "cash_balance": 1_000_000,
                "positions": [
                    {"symbol": "005930", "qty": 3},
                ],
            },
            {
                "cash_balance": 900_000,
                "stock_evaluation_amount": 214_500,
                "total_asset_amount": 1_214_500,
                "positions": [
                    {"symbol": "005930", "holding_qty": 3},
                ],
            },
            order_mirroring_enabled=True,
            mirrored_order_count=1,
        )

        self.assertTrue(account_sync["positions_match"])
        self.assertTrue(account_sync["balance_match"])
        self.assertEqual(account_sync["cash_gap"], 0)
        self.assertEqual(account_sync["raw_cash_gap"], 100_000)
        self.assertEqual(account_sync["status"], "일치")

    def test_dashboard_server_serves_health_and_json(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            run_synthetic_dev_cycle(project_root=root, symbol="005930", minutes=70, train_horizon_min=15)
            self._seed_dashboard_inputs(runtime_root)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()):
                server, info = prepare_dashboard_server(
                    project_root=root,
                    host="127.0.0.1",
                    port=0,
                    recent_limit=4,
                )
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    health = urllib.request.urlopen(f"{info.url}/health", timeout=5).read().decode("utf-8")
                    payload = urllib.request.urlopen(f"{info.url}/api/dashboard.json", timeout=5).read().decode("utf-8")
                    html = urllib.request.urlopen(info.url, timeout=5).read().decode("utf-8")
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

        self.assertIn('"ok": true', health.lower())
        self.assertIn('"runtime_summary"', payload)
        self.assertIn("실시간 주가 예측 대시보드", html)
        self.assertIn("모의계좌(실제)", html)
        self.assertIn("fetch('/api/refresh'", html)
        self.assertIn("refreshIntervalMs = 600000", html)
        self.assertIn("data-tab-id=\"tab-ops\"", html)
        self.assertIn("const fallbackId = 'tab-ops'", html)
        self.assertIn("data-subtab-group", html)
        self.assertIn("실전 전환 readiness dry-run", html)
        self.assertIn("ws_recovery_not_verified_by_fault_dry_run", html)
        self.assertIn("synthetic_fault_injection", html)
        self.assertEqual(json.loads(payload)["latest_live_readiness"]["status"], "blocked")

    def test_dashboard_reconciliation_uses_full_local_account_state(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        full_local_account = self._full_local_account_state()
        with patch.dict(os.environ, env, clear=False):
            self._seed_dashboard_inputs(runtime_root)
            with patch(
                "app.services.dashboard.refresh_kis_account_report",
                return_value=self._mock_account_report_without_positions(),
            ), patch(
                "app.services.dashboard.load_local_paper_account_state",
                return_value=full_local_account,
            ):
                snapshot = build_dashboard_snapshot(project_root=root, recent_limit=5)

        reconciliation = snapshot.payload["paper_account_reconciliation"]
        self.assertEqual(reconciliation["mismatch_count"], 1)
        self.assertEqual(reconciliation["local_positions_count"], 1)
        self.assertEqual(reconciliation["broker_positions_count"], 0)
        self.assertEqual(reconciliation["mismatch_rows"][0]["symbol"], "005930")
        self.assertEqual(reconciliation["mismatch_rows"][0]["status"], "only_local")

    def test_dashboard_uses_broker_alignment_for_virtual_account_state(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            writer = RuntimeWriter.from_settings(settings)
            stale_time = datetime.fromisoformat("2026-04-17T09:15:00+09:00")
            writer.write_portfolio_snapshot(
                PortfolioSnapshot(
                    snapshot_id="stale-local-snapshot",
                    event_time=stale_time,
                    cash_balance=25494367.59,
                    gross_market_value=2034090.04,
                    net_liquidation_value=25494367.59,
                    open_positions=1,
                    realized_pnl=3938436.33,
                    unrealized_pnl=-671.24,
                )
            )
            writer.write_paper_position(
                PaperPosition(
                    symbol="005930",
                    opened_at=stale_time,
                    updated_at=stale_time,
                    qty=29,
                    avg_price=70164.18,
                    last_price=70141.03,
                    market_value=2034090.04,
                    cost_basis=2034761.29,
                    realized_pnl=0.0,
                    unrealized_pnl=-671.24,
                )
            )
            alignment_dir = runtime_root / "reports" / "broker-paper"
            alignment_dir.mkdir(parents=True, exist_ok=True)
            aligned_at = datetime.fromisoformat("2026-04-17T18:46:04.542863+09:00")
            (alignment_dir / "latest-alignment.json").write_text(
                json.dumps(
                    {
                        "ok": True,
                        "aligned_at": aligned_at.isoformat(),
                        "status": "aligned_to_broker_marker",
                        "broker_account_snapshot": {
                            "cash_balance": 10000000,
                            "positions": [],
                        },
                        "baseline_positions": [],
                        "baseline_snapshot": {
                            "snapshot_id": "portfolio-broker-aligned-20260417184604",
                            "event_time": aligned_at.isoformat(),
                            "cash_balance": 10000000.0,
                            "gross_market_value": 0.0,
                            "net_liquidation_value": 10000000.0,
                            "open_positions": 0,
                            "realized_pnl": 0.0,
                            "unrealized_pnl": 0.0,
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            self._seed_dashboard_inputs(runtime_root)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report_without_positions()):
                payload = collect_dashboard_payload(project_root=root, recent_limit=5)

        local_account = payload["local_account_state"]
        self.assertEqual(local_account["open_positions"], 0)
        self.assertEqual(local_account["positions"], [])
        self.assertEqual(local_account["cash_balance"], 10000000.0)
        self.assertEqual(local_account["net_liquidation_value"], 10000000.0)

        with patch.dict(os.environ, env, clear=False):
            self._seed_dashboard_inputs(runtime_root)
            with patch(
                "app.services.dashboard.refresh_kis_account_report",
                return_value=self._mock_account_report_without_positions(),
            ), patch(
                "app.services.dashboard.load_local_paper_account_state",
                return_value=self._full_local_account_state(),
            ):
                snapshot = build_dashboard_snapshot(project_root=root, recent_limit=5)

        reconciliation = snapshot.payload["paper_account_reconciliation"]
        self.assertEqual(reconciliation["mismatch_count"], 1)
        self.assertEqual(reconciliation["local_positions_count"], 1)
        self.assertEqual(reconciliation["broker_positions_count"], 0)
        self.assertEqual(reconciliation["mismatch_rows"][0]["status"], "only_local")

    def test_dashboard_hides_demo_runtime_rows(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            run_demo_pipeline(project_root=root, symbol="005930")
            self._seed_dashboard_inputs(runtime_root)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()):
                snapshot = build_dashboard_snapshot(project_root=root, refresh_seconds=5, recent_limit=5)

        self.assertEqual(snapshot.payload["runtime_summary"]["predictions"], 0)
        self.assertEqual(snapshot.payload["runtime_summary"]["orders"], 0)
        self.assertIsNone(snapshot.payload["latest_portfolio_snapshot"])
        self.assertEqual(snapshot.payload["recent_predictions"], [])
        self.assertEqual(snapshot.payload["recent_orders"], [])
        self.assertEqual(snapshot.payload["learning_context"]["mode"], "actual_runtime_pending")

    def test_dashboard_hides_replay_runtime_rows(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            replay_ws_frames(project_root=root, frames=build_sample_ws_frames("005930"))
            self._seed_dashboard_inputs(runtime_root)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()):
                snapshot = build_dashboard_snapshot(project_root=root, refresh_seconds=5, recent_limit=5)

        self.assertEqual(snapshot.payload["runtime_summary"]["predictions"], 0)
        self.assertEqual(snapshot.payload["runtime_summary"]["orders"], 0)
        self.assertEqual(snapshot.payload["recent_predictions"], [])
        self.assertEqual(snapshot.payload["recent_orders"], [])

    def test_dashboard_includes_broker_account_section(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            self._seed_dashboard_inputs(runtime_root)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()):
                snapshot = build_dashboard_snapshot(project_root=root, refresh_seconds=5, recent_limit=5)

        self.assertIn("broker_account_report", snapshot.payload)
        self.assertEqual(snapshot.payload["broker_account_report"]["account_snapshot"]["account_no_masked"], "1234****")
        self.assertIn("paper_account_report", snapshot.payload)
        self.assertIn("live_account_report", snapshot.payload)
        html = snapshot.snapshot_html_path.read_text(encoding="utf-8")
        self.assertIn("모의계좌(실제)", html)
        self.assertIn("실 운용계좌", html)

    def test_dashboard_prediction_view_includes_expected_and_actual_changes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            self._seed_dashboard_inputs(runtime_root)
            self._seed_actual_prediction_runtime(root)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()):
                snapshot = build_dashboard_snapshot(project_root=root, recent_limit=5, range_key="all")

        recent_predictions = snapshot.payload["recent_predictions"]
        self.assertEqual(len(recent_predictions), 1)
        row = recent_predictions[0]
        self.assertEqual(row["symbol_name"], "삼성전자")
        self.assertTrue(str(row["predicted_change_text"]).startswith("상승 우세 /"))
        self.assertEqual(row["actual_change_text"], "+700원 (+1.00%)")
        self.assertEqual(row["success_text"], "성공")

    def test_dashboard_prediction_view_uses_nearest_same_day_future_bar(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            self._seed_dashboard_inputs(runtime_root)
            self._seed_sparse_actual_prediction_runtime(root)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()):
                snapshot = build_dashboard_snapshot(project_root=root, recent_limit=5, range_key="all")

        recent_predictions = snapshot.payload["recent_predictions"]
        self.assertEqual(len(recent_predictions), 1)
        row = recent_predictions[0]
        self.assertEqual(row["actual_change_text"], "+800원 (+1.14%)")
        self.assertEqual(row["success_text"], "성공")
        self.assertEqual(snapshot.payload["prediction_summary"]["evaluated"], 1)
        self.assertEqual(snapshot.payload["prediction_summary"]["pending"], 0)

    def test_dashboard_prediction_view_closes_after_market_without_future_bar(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            self._seed_dashboard_inputs(runtime_root)
            self._seed_after_close_prediction_runtime(root)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()):
                snapshot = build_dashboard_snapshot(project_root=root, recent_limit=5, range_key="all")

        recent_predictions = snapshot.payload["recent_predictions"]
        self.assertEqual(len(recent_predictions), 1)
        row = recent_predictions[0]
        self.assertEqual(row["actual_label_text"], "결과 없음")
        self.assertEqual(row["actual_change_text"], "결과 없음")
        self.assertEqual(row["success_text"], "결과 없음")
        self.assertEqual(row["result_status"], "no_result")
        self.assertEqual(snapshot.payload["prediction_summary"]["evaluated"], 0)
        self.assertEqual(snapshot.payload["prediction_summary"]["pending"], 0)
        self.assertEqual(snapshot.payload["prediction_summary"]["no_result"], 1)

    def test_dashboard_prediction_detail_shows_all_selected_predictions(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            self._seed_dashboard_inputs(runtime_root)
            self._seed_many_actual_predictions_runtime(root, count=8)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()):
                snapshot = build_dashboard_snapshot(project_root=root, recent_limit=5, range_key="all")

        self.assertEqual(len(snapshot.payload["recent_predictions"]), 5)
        self.assertEqual(len(snapshot.payload["prediction_details"]), 8)
        self.assertEqual(snapshot.payload["prediction_summary"]["total"], 8)


if __name__ == "__main__":
    unittest.main()
