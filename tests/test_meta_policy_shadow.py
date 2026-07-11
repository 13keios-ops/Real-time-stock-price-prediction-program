from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from scripts.summarize_meta_policy_shadow import build_report, render_markdown


class MetaPolicyShadowTests(unittest.TestCase):
    def _write_inputs(self, root: Path, *, random_passed: bool) -> dict[str, Path]:
        generated_at = "2026-07-10T20:30:00+09:00"
        overlay_path = root / "overlay.json"
        transfer_path = root / "transfer.json"
        rescue_path = root / "rescue.json"
        hold_path = root / "hold.json"
        defensive_path = root / "defensive.json"
        overlay_path.write_text(
            json.dumps(
                {
                    "generated_at": generated_at,
                    "status": "ok",
                    "date_range": {"end": "2026-07-10T14:59:00+09:00"},
                    "models": [
                        {
                            "name": "LightGBM",
                            "model_version": "lightgbm-h15-v1",
                            "classification": {"three_class_accuracy": 0.35},
                            "buy_avoid": {"best": {"delta_net_return_pct_points": 12.3}},
                            "buy_rescue": {"best": {"rescued_net_return_pct_points": -1.0}},
                            "hold_rescue": {"best": {"delta_cash_sum": -1000}},
                            "role_assessment": {
                                "suggested_roles": ["observe_only"],
                                "policy_status": "diagnostic_only_no_order_policy_change",
                            },
                        }
                    ],
                    "combination_policy_review": {
                        "policy_candidates": [
                            {
                                "family": "buy_avoid",
                                "policy": "either_model_down_veto_0.40",
                                "baseline_rows": 1000,
                                "executed_rows": 600,
                                "skipped_or_filtered_rows": 400,
                                "coverage": 0.6,
                                "baseline_net_return_pct_points": -20.0,
                                "policy_net_return_pct_points": 5.0,
                                "delta_net_return_pct_points": 25.0,
                                "loss_share": 0.45,
                                "candidate_eligible": True,
                                "candidate_blockers": [],
                            }
                        ],
                        "best_policy": {
                            "family": "buy_avoid",
                            "policy": "either_model_down_veto_0.40",
                            "coverage": 0.6,
                            "policy_net_return_pct_points": 5.0,
                            "delta_net_return_pct_points": 25.0,
                            "candidate_eligible": True,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        transfer_path.write_text(
            json.dumps(
                {
                    "candidate_actions": [
                        {
                            "candidate": "kis_only_bid_ask_imbalance",
                            "type": "kis_live_shadow_only",
                            "role": "orderbook_filter_watch",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        rescue_path.write_text(
            json.dumps({"decision": {"status": "buy_avoid_candidate_only"}}),
            encoding="utf-8",
        )
        hold_path.write_text(
            json.dumps(
                {
                    "generated_at": generated_at,
                    "decision": {"status": "diagnostic_only_no_hold_rescue_candidate"},
                }
            ),
            encoding="utf-8",
        )
        defensive_path.write_text(
            json.dumps(
                {
                    "generated_at": generated_at,
                    "status": "portfolio_candidate_found" if random_passed else "rejected_random_control",
                    "date_range": {"end": "2026-07-10T14:59:00+09:00"},
                    "prediction_lineage": {
                        "candidate_eligible": True,
                        "selected_lineage": {
                            "training_run_id": "run-1",
                            "artifact_id": "artifact-1",
                            "artifact_sha256": "sha-1",
                        },
                    },
                    "buy_avoid_shadow": {
                        "candidate_thresholds": [0.4] if random_passed else [],
                        "random_control_gate": {
                            "passed": random_passed,
                            "verdict": (
                                "filter_better_than_random_p05"
                                if random_passed
                                else "filter_worse_than_random_p95"
                            ),
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        return {
            "overlay_path": overlay_path,
            "transfer_path": transfer_path,
            "rescue_path": rescue_path,
            "hold_path": hold_path,
            "defensive_path": defensive_path,
        }

    def test_build_report_requires_all_profitability_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._write_inputs(root, random_passed=True)
            report = build_report(
                repo_root=root,
                horizon_min=15,
                generated_at="2026-07-10T20:30:00+09:00",
                **paths,
            )

        self.assertEqual(report["status"], "ok")
        self.assertFalse(report["current_recommendation"]["active_model_change"])
        self.assertFalse(report["current_recommendation"]["paper_order_policy_change"])
        self.assertEqual(
            report["current_recommendation"]["primary_shadow_candidate"]["candidate"],
            "either_model_down_veto_0.40",
        )
        self.assertTrue(report["defensive_buy_avoid"]["signal_random_control_passed"])
        markdown = render_markdown(report)
        self.assertIn("주문 정책", markdown)
        self.assertIn("either_model_down_veto_0.40", markdown)

    def test_failed_random_control_removes_primary_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._write_inputs(root, random_passed=False)
            report = build_report(
                repo_root=root,
                horizon_min=15,
                generated_at="2026-07-10T20:30:00+09:00",
                **paths,
            )

        self.assertEqual(report["status"], "blocked_evidence")
        self.assertIsNone(report["current_recommendation"]["primary_shadow_candidate"])
        self.assertIn("defensive_random_control_failed", report["blockers"])
        self.assertIn("no_absolute_profit_portfolio_candidate", report["blockers"])


if __name__ == "__main__":
    unittest.main()