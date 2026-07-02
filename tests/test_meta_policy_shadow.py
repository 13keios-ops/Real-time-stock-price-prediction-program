from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from scripts.summarize_meta_policy_shadow import build_report, render_markdown


class MetaPolicyShadowTests(unittest.TestCase):
    def test_build_report_keeps_candidates_shadow_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay_path = root / "overlay.json"
            transfer_path = root / "transfer.json"
            rescue_path = root / "rescue.json"
            hold_path = root / "hold.json"
            overlay_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-07-03T00:00:00+09:00",
                        "status": "ok",
                        "models": [
                            {
                                "name": "LightGBM",
                                "model_version": "lightgbm-h15-v1",
                                "classification": {"three_class_accuracy": 0.35},
                                "buy_avoid": {"best": {"delta_net_return_pct": 12.3}},
                                "buy_rescue": {"best": {"policy_net_return_pct": -1.0}},
                                "hold_rescue": {"best": {"delta_cash_sum": -1000}},
                                "role_assessment": {
                                    "suggested_roles": ["defensive_buy_avoid"],
                                    "policy_status": "diagnostic_only_no_order_policy_change",
                                },
                            }
                        ],
                        "combination_policy_review": {
                            "policy_candidates": [
                                {
                                    "family": "buy_avoid",
                                    "policy": "either_model_down_veto_0.40",
                                    "baseline_rows": 100,
                                    "executed_rows": 60,
                                    "skipped_or_filtered_rows": 40,
                                    "coverage": 0.6,
                                    "baseline_net_return_pct": -20.0,
                                    "policy_net_return_pct": -5.0,
                                    "delta_net_return_pct": 15.0,
                                    "loss_share": 0.55,
                                }
                            ],
                            "best_policy": {
                                "family": "buy_avoid",
                                "policy": "either_model_down_veto_0.40",
                                "coverage": 0.6,
                                "delta_net_return_pct": 15.0,
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
                json.dumps({"decision": {"status": "diagnostic_only_no_hold_rescue_candidate"}}),
                encoding="utf-8",
            )

            report = build_report(
                repo_root=root,
                horizon_min=15,
                generated_at="2026-07-03T00:00:00+09:00",
                overlay_path=overlay_path,
                transfer_path=transfer_path,
                rescue_path=rescue_path,
                hold_path=hold_path,
            )

        self.assertEqual(report["status"], "ok")
        self.assertFalse(report["current_recommendation"]["active_model_change"])
        self.assertFalse(report["current_recommendation"]["paper_order_policy_change"])
        self.assertEqual(
            report["current_recommendation"]["primary_shadow_candidate"]["candidate"],
            "either_model_down_veto_0.40",
        )
        self.assertEqual(report["model_roles"][0]["suggested_roles"], ["defensive_buy_avoid"])
        markdown = render_markdown(report)
        self.assertIn("주문 정책", markdown)
        self.assertIn("either_model_down_veto_0.40", markdown)


if __name__ == "__main__":
    unittest.main()
