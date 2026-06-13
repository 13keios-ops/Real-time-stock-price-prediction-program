from __future__ import annotations

import unittest

from scripts.summarize_paper_cash_gap import build_cash_gap_analysis


class PaperCashGapAnalysisTests(unittest.TestCase):
    def test_sync_initial_cash_does_not_rewrite_current_snapshot_gap(self) -> None:
        payload = build_cash_gap_analysis(
            env={"TRADING_MODE": "paper", "PAPER_INITIAL_CASH": "700000"},
            dual_match={
                "status": "initial_cash_mismatch",
                "env": {"paper_initial_cash_after": "700000", "trading_mode": "paper"},
                "broker_account": {
                    "cash_balance": 1_000_000,
                    "stock_evaluation_amount": 10_000,
                    "total_asset_amount": 990_000,
                    "positions": [],
                    "position_row_count": 0,
                },
                "local_account": {
                    "cash_balance": 800_000.0,
                    "net_liquidation_value": 800_000.0,
                    "positions": [],
                },
                "comparison": {
                    "mismatch_count": 0,
                    "positions_match": True,
                    "balance_match": False,
                    "total_asset_match": False,
                    "cash_gap": -180_000.0,
                    "total_asset_gap": -190_000.0,
                    "broker_raw_cash_balance": 1_000_000,
                    "broker_effective_cash_balance": 980_000.0,
                    "order_mirroring_enabled": True,
                    "mirrored_order_count": 3,
                },
            },
            account_sync={},
            broker_sync={"status": "ok", "open_order_count": 10, "pending_symbols": ["005930"]},
            alignment={"status": "aligned_to_broker_marker"},
            generated_at="2026-06-14T00:00:00+09:00",
        )

        sync = payload["dry_run"]["sync_initial_cash"]
        self.assertTrue(sync["allowed_by_current_shape"])
        self.assertEqual(sync["target_env_initial_cash"], 1_000_000.0)
        self.assertEqual(sync["env_delta"], 300_000.0)
        self.assertFalse(sync["would_fix_current_snapshot_cash_gap"])
        self.assertIn("initial_cash_only_does_not_fix_current_snapshot_gap", payload["warnings"])

    def test_align_to_broker_hypothetical_baseline_uses_effective_cash(self) -> None:
        payload = build_cash_gap_analysis(
            env={"PAPER_INITIAL_CASH": "700000"},
            dual_match={
                "broker_account": {
                    "cash_balance": 1_000_000,
                    "stock_evaluation_amount": 25_000,
                    "total_asset_amount": 975_000,
                    "total_profit_loss_amount": -5_000,
                    "positions": [{"symbol": "005930", "holding_qty": 2}],
                    "position_row_count": 1,
                },
                "local_account": {"cash_balance": 800_000.0, "net_liquidation_value": 800_000.0, "positions": []},
                "comparison": {
                    "cash_gap": -150_000.0,
                    "total_asset_gap": -175_000.0,
                    "broker_effective_cash_balance": 950_000.0,
                    "broker_raw_cash_balance": 1_000_000,
                    "order_mirroring_enabled": True,
                },
            },
            account_sync={},
            broker_sync={},
            alignment={},
            generated_at="2026-06-14T00:00:00+09:00",
        )

        align = payload["dry_run"]["align_to_broker"]
        baseline = align["hypothetical_baseline_snapshot"]
        self.assertTrue(align["allowed_by_current_shape"])
        self.assertEqual(baseline["cash_balance"], 950_000.0)
        self.assertEqual(baseline["gross_market_value"], 25_000.0)
        self.assertEqual(baseline["net_liquidation_value"], 975_000.0)
        self.assertEqual(baseline["open_positions"], 1)

    def test_sync_initial_cash_is_blocked_when_broker_has_positions(self) -> None:
        payload = build_cash_gap_analysis(
            env={"PAPER_INITIAL_CASH": "700000"},
            dual_match={
                "broker_account": {
                    "cash_balance": 1_000_000,
                    "stock_evaluation_amount": 25_000,
                    "total_asset_amount": 975_000,
                    "positions": [{"symbol": "005930", "holding_qty": 2}],
                },
                "local_account": {"cash_balance": 800_000.0, "net_liquidation_value": 800_000.0, "positions": []},
                "comparison": {
                    "cash_gap": -150_000.0,
                    "broker_raw_cash_balance": 1_000_000,
                    "broker_effective_cash_balance": 950_000.0,
                },
            },
            account_sync={},
            broker_sync={},
            alignment={},
            generated_at="2026-06-14T00:00:00+09:00",
        )

        sync = payload["dry_run"]["sync_initial_cash"]
        self.assertFalse(sync["allowed_by_current_shape"])
        self.assertEqual(sync["blocked_reason"], "broker_positions_or_cash_unavailable")

    def test_aligned_accounts_need_no_cash_gap_action(self) -> None:
        payload = build_cash_gap_analysis(
            env={"PAPER_INITIAL_CASH": "700000"},
            dual_match={
                "status": "matched_waiting_first_submission",
                "broker_account": {
                    "cash_balance": 1_030_000,
                    "stock_evaluation_amount": 0,
                    "total_asset_amount": 1_000_000,
                    "positions": [],
                    "position_row_count": 0,
                },
                "local_account": {
                    "cash_balance": 1_000_000.0,
                    "net_liquidation_value": 1_000_000.0,
                    "positions": [],
                },
                "comparison": {
                    "mismatch_count": 0,
                    "positions_match": True,
                    "balance_match": True,
                    "total_asset_match": True,
                    "cash_gap": 0.0,
                    "total_asset_gap": 0.0,
                    "broker_raw_cash_balance": 1_030_000,
                    "broker_effective_cash_balance": 1_000_000.0,
                    "order_mirroring_enabled": True,
                    "mirrored_order_count": 0,
                },
            },
            account_sync={},
            broker_sync={"status": "no_submissions", "open_order_count": 0},
            alignment={"status": "aligned_to_broker_marker"},
            generated_at="2026-06-14T00:00:00+09:00",
        )

        self.assertEqual(payload["recommendation"]["recommended_action"], "keep_current_alignment")
        self.assertEqual(payload["recommendation"]["next_action"], "no_cash_gap_action_required")
        self.assertFalse(payload["recommendation"]["operator_approval_required_for_mutation"])


if __name__ == "__main__":
    unittest.main()
