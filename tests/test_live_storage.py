from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import uuid
import unittest

from app.storage.contracts import (
    LiveAuditEvent,
    LiveFill,
    LiveOrder,
    LiveOrderEvent,
    LivePhaseApproval,
    LivePortfolioSnapshot,
    LivePosition,
    LiveReadinessRun,
    MarketStatusSnapshot,
)
from app.storage.jsonl_store import JsonlArtifactStore
from app.storage.runtime_writer import RuntimeWriter
from app.storage.sqlite_store import SQLiteRuntimeStore


class LiveStorageTests(unittest.TestCase):
    def _tmp_root(self) -> Path:
        return Path(__file__).resolve().parents[1] / ".tmp-tests" / "live-storage" / str(uuid.uuid4())

    def _store(self) -> SQLiteRuntimeStore:
        return SQLiteRuntimeStore(self._tmp_root() / "dev.db")

    def _now(self) -> datetime:
        return datetime(2026, 5, 14, 9, 5, tzinfo=timezone.utc)

    def _market_status_snapshot(self) -> MarketStatusSnapshot:
        return MarketStatusSnapshot(
            snapshot_id="market-status-1",
            trading_day="2026-05-14",
            created_at=self._now(),
            source="manual_fixture",
            symbol_set_hash="hash-1",
            status_json={
                "symbols": {"005930": {"tradable": True}},
                "market_session": "regular",
                "source_generated_at": self._now().isoformat(),
            },
            stale_after=datetime(2026, 5, 14, 9, 10, tzinfo=timezone.utc),
        )

    def _live_order(
        self,
        *,
        order_id: str = "live-order-1",
        idempotency_key: str = "idem-1",
        status: str = "intent_created",
        signal_id: str = "signal-1",
        detail_json: dict[str, object] | None = None,
    ) -> LiveOrder:
        return LiveOrder(
            order_id=order_id,
            idempotency_key=idempotency_key,
            trading_day="2026-05-14",
            phase="phase2_conservative",
            symbol="005930",
            side="buy",
            qty=1,
            filled_qty=0,
            remaining_qty=1,
            order_type="limit",
            limit_price=70000.0,
            avg_fill_price=0.0,
            status=status,
            prediction_id="prediction-1",
            signal_id=signal_id,
            target_id="target-1",
            gate_decision_id="gate-1",
            market_status_snapshot_id="market-status-1",
            model_version="model-1",
            rule_version="rule-1",
            broker_order_no="",
            broker_branch_no="",
            reject_reason=None,
            cancel_reason=None,
            parent_order_id=None,
            created_at=self._now(),
            submitted_at=None,
            last_synced_at=None,
            detail_json=detail_json or {
                "order_policy": {"type": "limit_only"},
                "blocking_reasons": [],
                "raw_broker_response": {},
            },
        )

    def _live_order_event(self) -> LiveOrderEvent:
        return LiveOrderEvent(
            order_event_id="live-order-event-1",
            order_id="live-order-1",
            event_time=self._now(),
            from_status="none",
            to_status="intent_created",
            event_type="created",
            actor="system",
            detail_json={
                "reason": "fixture",
                "source": "unit_test",
                "raw_broker_response": {},
            },
        )

    def _live_fill(self) -> LiveFill:
        return LiveFill(
            fill_id="live-fill-1",
            order_id="live-order-1",
            broker_order_no="broker-order-1",
            broker_branch_no="01",
            symbol="005930",
            trading_day="2026-05-14",
            event_time=self._now(),
            side="buy",
            fill_qty=1,
            fill_price=70000.0,
            commission=10.0,
            tax=0.0,
            fee=2.0,
            settlement_day="2026-05-18",
            detail_json={
                "raw_broker_fill": {},
                "fees": {"commission": 10.0, "tax": 0.0, "fee": 2.0},
                "settlement": {"cycle": "T+2"},
            },
        )

    def _live_position(self) -> LivePosition:
        return LivePosition(
            symbol="005930",
            trading_day="2026-05-14",
            opened_at=self._now(),
            updated_at=self._now(),
            qty=1,
            avg_price=70000.0,
            last_price=70100.0,
            market_value=70100.0,
            cost_basis=70000.0,
            realized_pnl=0.0,
            unrealized_pnl=100.0,
            day_realized_pnl=0.0,
            broker_qty=1,
            detail_json={"source": "unit_test", "raw_broker_position": {}},
        )

    def _live_portfolio_snapshot(self) -> LivePortfolioSnapshot:
        return LivePortfolioSnapshot(
            snapshot_id="live-portfolio-1",
            trading_day="2026-05-14",
            event_time=self._now(),
            cash_balance=1_000_000.0,
            available_cash=900_000.0,
            unsettled_cash=100_000.0,
            gross_market_value=70_100.0,
            net_liquidation_value=1_070_100.0,
            realized_pnl=0.0,
            unrealized_pnl=100.0,
            daily_pnl=100.0,
            open_positions=1,
            margin_requirement=0.0,
            detail_json={"source": "unit_test", "raw_broker_account": {}},
        )

    def _live_audit_event(self) -> LiveAuditEvent:
        return LiveAuditEvent(
            audit_event_id="live-audit-1",
            event_time=self._now(),
            trading_day="2026-05-14",
            event_type="order_intent_created",
            actor="system",
            symbol="005930",
            order_id="live-order-1",
            prediction_id="prediction-1",
            signal_id="signal-1",
            gate_decision_id="gate-1",
            rule_version="rule-1",
            model_version="model-1",
            data_snapshot_id="market-status-1",
            previous_hash="",
            event_hash="hash-1",
            detail_json={"reason": "fixture", "source": "unit_test", "gate_decision": {}},
        )

    def _live_phase_approval(self) -> LivePhaseApproval:
        return LivePhaseApproval(
            approval_id="live-approval-1",
            phase="phase2_conservative",
            trading_day="2026-05-14",
            approved_at=self._now(),
            approved_by="account_owner",
            expires_at=self._now(),
            scope="one_symbol_small",
            max_symbols=1,
            max_parent_orders=1,
            max_notional=100_000.0,
            daily_loss_limit_pct=2.0,
            per_symbol_loss_limit_pct=2.0,
            slippage_budget_bps=20.0,
            approval_hash="approval-hash-1",
            detail_json={
                "approval_basis": "unit_test",
                "limits": {"max_symbols": 1},
                "operator_decision_ref": "docs/cowork-reports/operator-decision.md",
            },
        )

    def _live_readiness_run(self) -> LiveReadinessRun:
        return LiveReadinessRun(
            readiness_id="live-readiness-1",
            trading_day="2026-05-14",
            checked_at=self._now(),
            phase="phase2_conservative",
            status="ok",
            passed=True,
            token_refresh_ok=True,
            ws_recovery_ok=True,
            account_snapshot_ok=True,
            market_status_ok=True,
            kill_switch_ok=True,
            database_ok=True,
            checks_json={"checks": {"database": "ok"}, "blocking_reasons": []},
            report_path="runtime-data/reports/live-readiness/example.json",
        )

    def test_live_dataclasses_serialize_datetimes(self) -> None:
        snapshot = self._market_status_snapshot()
        order = self._live_order()
        event = self._live_order_event()
        fill = self._live_fill()
        position = self._live_position()
        portfolio = self._live_portfolio_snapshot()
        audit = self._live_audit_event()
        approval = self._live_phase_approval()
        readiness = self._live_readiness_run()

        self.assertEqual(snapshot.to_record()["created_at"], "2026-05-14T09:05:00+00:00")
        self.assertEqual(order.to_record()["created_at"], "2026-05-14T09:05:00+00:00")
        self.assertEqual(event.to_record()["event_time"], "2026-05-14T09:05:00+00:00")
        self.assertEqual(fill.to_record()["event_time"], "2026-05-14T09:05:00+00:00")
        self.assertEqual(position.to_record()["updated_at"], "2026-05-14T09:05:00+00:00")
        self.assertEqual(portfolio.to_record()["event_time"], "2026-05-14T09:05:00+00:00")
        self.assertEqual(audit.to_record()["event_time"], "2026-05-14T09:05:00+00:00")
        self.assertEqual(approval.to_record()["approved_at"], "2026-05-14T09:05:00+00:00")
        self.assertEqual(readiness.to_record()["checked_at"], "2026-05-14T09:05:00+00:00")

    def test_live_dataclasses_require_minimum_json_keys_and_actor(self) -> None:
        with self.assertRaises(ValueError):
            MarketStatusSnapshot(
                snapshot_id="market-status-bad",
                trading_day="2026-05-14",
                created_at=self._now(),
                source="manual_fixture",
                symbol_set_hash="hash-1",
                status_json={"symbols": {}},
                stale_after=self._now(),
            )

        with self.assertRaises(ValueError):
            MarketStatusSnapshot(
                snapshot_id="market-status-bad-types",
                trading_day="2026-05-14",
                created_at=self._now(),
                source="manual_fixture",
                symbol_set_hash="hash-1",
                status_json={
                    "symbols": [],
                    "market_session": "regular",
                    "source_generated_at": self._now().isoformat(),
                },
                stale_after=self._now(),
            )

        with self.assertRaises(ValueError):
            self._live_order(
                detail_json={
                    "order_policy": {"type": "limit_only"},
                    "blocking_reasons": [],
                }
            )

        with self.assertRaises(ValueError):
            self._live_order(idempotency_key="")

        with self.assertRaises(ValueError):
            self._live_order(order_id=" ")

        with self.assertRaises(ValueError):
            self._live_order(signal_id="")

        with self.assertRaises(ValueError):
            self._live_order(
                detail_json={
                    "order_policy": {"type": "limit_only"},
                    "blocking_reasons": {"reason": "bad-type"},
                    "raw_broker_response": {},
                }
            )

        with self.assertRaises(ValueError):
            LiveOrderEvent(
                order_event_id="event-bad",
                order_id="live-order-1",
                event_time=self._now(),
                from_status="none",
                to_status="intent_created",
                event_type="created",
                actor="unknown_actor",
                detail_json={
                    "reason": "fixture",
                    "source": "unit_test",
                    "raw_broker_response": {},
                },
            )

        with self.assertRaises(ValueError):
            LiveOrderEvent(
                order_event_id="event-codex",
                order_id="live-order-1",
                event_time=self._now(),
                from_status="none",
                to_status="intent_created",
                event_type="created",
                actor="codex",
                detail_json={
                    "reason": "fixture",
                    "source": "unit_test",
                    "raw_broker_response": {},
                },
            )

        LiveOrderEvent(
            order_event_id="event-test",
            order_id="live-order-1",
            event_time=self._now(),
            from_status="none",
            to_status="intent_created",
            event_type="created",
            actor="test",
            detail_json={
                "reason": "fixture",
                "source": "unit_test",
                "raw_broker_response": {},
            },
        )

        with self.assertRaises(ValueError):
            LiveOrderEvent(
                order_event_id="event-bad-detail",
                order_id="live-order-1",
                event_time=self._now(),
                from_status="none",
                to_status="intent_created",
                event_type="created",
                actor="system",
                detail_json={
                    "reason": "fixture",
                    "source": "unit_test",
                    "raw_broker_response": [],
                },
            )

        with self.assertRaises(ValueError):
            LiveFill(
                fill_id="",
                order_id="live-order-1",
                broker_order_no="broker-order-1",
                broker_branch_no="01",
                symbol="005930",
                trading_day="2026-05-14",
                event_time=self._now(),
                side="buy",
                fill_qty=1,
                fill_price=70000.0,
                commission=0.0,
                tax=0.0,
                fee=0.0,
                settlement_day="2026-05-18",
                detail_json={"raw_broker_fill": {}, "fees": {}, "settlement": {}},
            )

        with self.assertRaises(ValueError):
            LiveFill(
                fill_id="fill-bad-detail",
                order_id="live-order-1",
                broker_order_no="broker-order-1",
                broker_branch_no="01",
                symbol="005930",
                trading_day="2026-05-14",
                event_time=self._now(),
                side="buy",
                fill_qty=1,
                fill_price=70000.0,
                commission=0.0,
                tax=0.0,
                fee=0.0,
                settlement_day="2026-05-18",
                detail_json={"raw_broker_fill": {}},
            )

        with self.assertRaises(ValueError):
            LiveAuditEvent(
                audit_event_id="audit-bad",
                event_time=self._now(),
                trading_day="2026-05-14",
                event_type="created",
                actor="codex",
                symbol="005930",
                order_id="live-order-1",
                prediction_id="prediction-1",
                signal_id="signal-1",
                gate_decision_id="gate-1",
                rule_version="rule-1",
                model_version="model-1",
                data_snapshot_id="market-status-1",
                previous_hash="",
                event_hash="hash-bad",
                detail_json={"reason": "fixture", "source": "unit_test", "gate_decision": {}},
            )

        with self.assertRaises(ValueError):
            LivePhaseApproval(
                approval_id="approval-bad",
                phase="phase2_conservative",
                trading_day="2026-05-14",
                approved_at=self._now(),
                approved_by="account_owner",
                expires_at=self._now(),
                scope="one_symbol_small",
                max_symbols=1,
                max_parent_orders=1,
                max_notional=100_000.0,
                daily_loss_limit_pct=2.0,
                per_symbol_loss_limit_pct=2.0,
                slippage_budget_bps=20.0,
                approval_hash="approval-hash-bad",
                detail_json={"approval_basis": "unit_test", "limits": {}},
            )

        with self.assertRaises(ValueError):
            LiveReadinessRun(
                readiness_id="readiness-bad",
                trading_day="2026-05-14",
                checked_at=self._now(),
                phase="phase2_conservative",
                status="ok",
                passed=True,
                token_refresh_ok=True,
                ws_recovery_ok=True,
                account_snapshot_ok=True,
                market_status_ok=True,
                kill_switch_ok=True,
                database_ok=True,
                checks_json={"checks": {}},
                report_path="runtime-data/reports/live-readiness/example.json",
            )

    def test_live_schema_tables_indexes_and_contract_fields_exist(self) -> None:
        store = self._store()
        table_rows = store._run_read_query(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN (
                'market_status_snapshots',
                'live_orders',
                'live_order_events',
                'live_fills',
                'live_positions',
                'live_portfolio_snapshots',
                'ops_live_audit_events',
                'live_phase_approvals',
                'live_readiness_runs'
              )
            ORDER BY name
            """
        )
        index_rows = store._run_read_query(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'index'
              AND name IN (
                'idx_market_status_day_hash',
                'idx_live_orders_status_symbol_day',
                'idx_live_orders_broker',
                'idx_live_orders_parent',
                'idx_live_order_events_order_time',
                'idx_live_fills_order_time',
                'idx_live_fills_broker',
                'idx_live_fills_symbol_day',
                'idx_live_positions_updated_at',
                'idx_live_portfolio_snapshots_time',
                'idx_ops_live_audit_order_time',
                'idx_ops_live_audit_hash',
                'idx_live_phase_approvals_day_phase',
                'idx_live_phase_approvals_expires',
                'idx_live_readiness_runs_day_phase'
              )
            ORDER BY name
            """
        )

        self.assertEqual(
            {row["name"] for row in table_rows},
            {
                "market_status_snapshots",
                "live_orders",
                "live_order_events",
                "live_fills",
                "live_positions",
                "live_portfolio_snapshots",
                "ops_live_audit_events",
                "live_phase_approvals",
                "live_readiness_runs",
            },
        )
        self.assertEqual(
            {row["name"] for row in index_rows},
            {
                "idx_market_status_day_hash",
                "idx_live_orders_status_symbol_day",
                "idx_live_orders_broker",
                "idx_live_orders_parent",
                "idx_live_order_events_order_time",
                "idx_live_fills_order_time",
                "idx_live_fills_broker",
                "idx_live_fills_symbol_day",
                "idx_live_positions_updated_at",
                "idx_live_portfolio_snapshots_time",
                "idx_ops_live_audit_order_time",
                "idx_ops_live_audit_hash",
                "idx_live_phase_approvals_day_phase",
                "idx_live_phase_approvals_expires",
                "idx_live_readiness_runs_day_phase",
            },
        )
        for table_name, contract in (
            ("market_status_snapshots", MarketStatusSnapshot),
            ("live_orders", LiveOrder),
            ("live_order_events", LiveOrderEvent),
            ("live_fills", LiveFill),
            ("live_positions", LivePosition),
            ("live_portfolio_snapshots", LivePortfolioSnapshot),
            ("ops_live_audit_events", LiveAuditEvent),
            ("live_phase_approvals", LivePhaseApproval),
            ("live_readiness_runs", LiveReadinessRun),
        ):
            with self.subTest(table_name=table_name):
                schema_rows = store._run_read_query(f"PRAGMA table_info({table_name})")
                self.assertEqual({row["name"] for row in schema_rows}, {field.name for field in fields(contract)})

    def test_live_order_insert_unique_idempotency_and_open_lookup(self) -> None:
        store = self._store()
        store.insert_market_status_snapshot(self._market_status_snapshot())
        store.insert_live_order(self._live_order(order_id="open-order", idempotency_key="idem-open", status="open"))
        store.insert_live_order(self._live_order(order_id="filled-order", idempotency_key="idem-filled", status="filled"))
        store.insert_live_order_event(self._live_order_event())

        open_rows = store.fetch_open_live_orders("2026-05-14")

        self.assertEqual([row["order_id"] for row in open_rows], ["open-order"])
        self.assertEqual(store.count_rows("market_status_snapshots"), 1)
        self.assertEqual(store.count_rows("live_order_events"), 1)
        with self.assertRaises(sqlite3.IntegrityError):
            store.insert_live_order(
                self._live_order(order_id="duplicate-idem", idempotency_key="idem-open", status="intent_created")
            )

    def test_live_execution_audit_approval_and_readiness_records_are_stored(self) -> None:
        store = self._store()

        store.insert_market_status_snapshot(self._market_status_snapshot())
        store.insert_live_order(self._live_order())
        store.insert_live_fill(self._live_fill())
        store.upsert_live_position(self._live_position())
        store.insert_live_portfolio_snapshot(self._live_portfolio_snapshot())
        store.insert_live_audit_event(self._live_audit_event())
        store.insert_live_phase_approval(self._live_phase_approval())
        store.insert_live_readiness_run(self._live_readiness_run())

        self.assertEqual(store.count_rows("live_fills"), 1)
        self.assertEqual(store.count_rows("live_positions"), 1)
        self.assertEqual(store.count_rows("live_portfolio_snapshots"), 1)
        self.assertEqual(store.count_rows("ops_live_audit_events"), 1)
        self.assertEqual(store.count_rows("live_phase_approvals"), 1)
        self.assertEqual(store.count_rows("live_readiness_runs"), 1)
        with self.assertRaises(sqlite3.IntegrityError):
            store.insert_live_audit_event(
                LiveAuditEvent(
                    audit_event_id="live-audit-duplicate",
                    event_time=self._now(),
                    trading_day="2026-05-14",
                    event_type="order_intent_created",
                    actor="system",
                    symbol="005930",
                    order_id="live-order-1",
                    prediction_id="prediction-1",
                    signal_id="signal-1",
                    gate_decision_id="gate-1",
                    rule_version="rule-1",
                    model_version="model-1",
                    data_snapshot_id="market-status-1",
                    previous_hash="",
                    event_hash="hash-1",
                    detail_json={"reason": "fixture", "source": "unit_test", "gate_decision": {}},
                )
            )

    def test_runtime_writer_writes_live_records_to_jsonl_and_sqlite(self) -> None:
        tmp_root = self._tmp_root()
        writer = RuntimeWriter(
            jsonl_store=JsonlArtifactStore(tmp_root / "runtime-data"),
            sqlite_store=SQLiteRuntimeStore(tmp_root / "dev.db"),
        )

        writer.write_market_status_snapshot(self._market_status_snapshot())
        writer.write_live_order(self._live_order())
        writer.write_live_order_event(self._live_order_event())
        writer.write_live_fill(self._live_fill())
        writer.write_live_position(self._live_position())
        writer.write_live_portfolio_snapshot(self._live_portfolio_snapshot())
        writer.write_live_audit_event(self._live_audit_event())
        writer.write_live_phase_approval(self._live_phase_approval())
        writer.write_live_readiness_run(self._live_readiness_run())

        self.assertTrue((tmp_root / "runtime-data" / "live" / "2026-05-14" / "market_status_snapshots.jsonl").exists())
        self.assertTrue((tmp_root / "runtime-data" / "live" / "2026-05-14" / "orders.jsonl").exists())
        self.assertTrue((tmp_root / "runtime-data" / "live" / "2026-05-14" / "order_events.jsonl").exists())
        self.assertTrue((tmp_root / "runtime-data" / "live" / "2026-05-14" / "fills.jsonl").exists())
        self.assertTrue((tmp_root / "runtime-data" / "live" / "2026-05-14" / "positions.jsonl").exists())
        self.assertTrue((tmp_root / "runtime-data" / "live" / "2026-05-14" / "portfolio_snapshots.jsonl").exists())
        self.assertTrue((tmp_root / "runtime-data" / "ops" / "2026-05-14" / "live_audit_events.jsonl").exists())
        self.assertTrue((tmp_root / "runtime-data" / "live" / "2026-05-14" / "phase_approvals.jsonl").exists())
        self.assertTrue((tmp_root / "runtime-data" / "live" / "2026-05-14" / "readiness_runs.jsonl").exists())
        self.assertEqual(writer.sqlite_store.count_rows("live_orders"), 1)
        self.assertEqual(writer.sqlite_store.count_rows("live_fills"), 1)
        self.assertEqual(writer.sqlite_store.count_rows("ops_live_audit_events"), 1)


if __name__ == "__main__":
    unittest.main()
