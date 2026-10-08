from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from app.services.e7_portfolio_evaluator import (
    E7EvidenceAcceptanceContract,
    E7FutureInterval,
    E7_SOURCE_VALIDATOR_VERSION,
    E7_PORTFOLIO_REPLAY_MANIFEST,
    build_e7_interval_context,
    run_e7_portfolio_replay,
    run_e7_random_control,
    stamp_e7_result,
    validate_e7_official_result_set,
)
from app.services.portfolio_replay import ExecutableDecision, ReplayBar
from app.services.portfolio_replay_v2 import (
    ReplayCompatibilityError, replay_long_only_v2,
)
from tests.test_e7_portfolio_evaluator import (
    _complete_package, _contract_kwargs, _intervals, _proof,
)


def _rehash(proof):
    proof.pop("proof_hash", None)
    proof["proof_hash"] = hashlib.sha256(json.dumps(
        proof, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()
    return proof


def _case():
    interval = _intervals()[0]
    start = interval.start
    decisions = [ExecutableDecision(
        episode_id="A-1", symbol="A", signal_time=start,
        entry_time=start + timedelta(minutes=1), entry_price=100.0,
        exit_time=start + timedelta(minutes=3), exit_price=101.0,
        signal_rows=1, avoid=False,
    )]
    bars = {"A": [ReplayBar(
        "A", start + timedelta(minutes=index), 100.0, 100.0
    ) for index in range(1, 4)]}
    context = build_e7_interval_context(decisions, bars, future_interval=interval)
    return decisions, context, interval


def _run(decisions, context, interval, **overrides):
    kwargs = {
        "context": context, "future_interval": interval,
        "result_role": "baseline", "cost_scenario": "normal",
        "respect_decision_avoid": False,
        "source_acceptance": _proof(context, interval),
        **_contract_kwargs(),
    }
    kwargs.update(overrides)
    return run_e7_portfolio_replay(decisions, **kwargs)


class E7SourceAcceptanceTests(unittest.TestCase):
    def test_prepared_post_recovery_contract_is_frozen_and_not_activated(self):
        path = Path(__file__).resolve().parents[1] / "docs" / (
            "e7-post-recovery-acceptance-20261009.json"
        )
        record = json.loads(path.read_text(encoding="utf-8"))
        intervals = tuple(E7FutureInterval(
            item["interval_id"], datetime.fromisoformat(item["start"]),
            datetime.fromisoformat(item["end"]),
        ) for item in record["contract"]["future_intervals"])
        contract = E7EvidenceAcceptanceContract(intervals)
        self.assertEqual(contract.to_dict(), record["contract"])
        self.assertEqual(contract.sha256, record["contract_hash"])
        self.assertEqual(contract.sha256,
            "16a22ce5801cd1f38d21aee98bfe806fa809a3c4061d2f61e4bdb5b16b20e740")
        approval_date = datetime.fromisoformat(
            record["prepared_on_kst"] + "T00:00:00+09:00"
        )
        self.assertTrue(all(item.start > approval_date for item in intervals))
        self.assertEqual(record["activation_status"],
            "not_activated_trusted_producer_pending")
        policy = record["evaluation_policy"]
        self.assertFalse(policy["automatic_official_permission"])
        self.assertFalse(policy["merge_with_original_cumulative_results_permitted"])
        self.assertFalse(policy["historical_evidence_repair_permitted"])
        self.assertFalse(policy["strategy_costs_constraints_and_model_changes_permitted"])
        self.assertEqual(policy["threshold"], 0.55)
        self.assertEqual(policy["minimum_trading_days_per_interval"], 10)
        self.assertEqual(policy["minimum_policy_episodes_per_interval"], 100)
        self.assertEqual(policy["minimum_policy_symbols_per_interval"], 5)
        self.assertEqual(policy["random_control_simulations"], 1000)

    def test_validator_and_manifest_remain_canonical(self):
        from app.services.e7_daily_evidence import E7_EVIDENCE_VALIDATION_VERSION
        self.assertEqual(E7_SOURCE_VALIDATOR_VERSION, E7_EVIDENCE_VALIDATION_VERSION)
        self.assertEqual(
            E7_PORTFOLIO_REPLAY_MANIFEST.sha256,
            "1d61b288a715d3cde63f6ccf1e4dcc42d6affebd14fe9d4beaf3319a9e0dd3fa",
        )

    def test_legacy_package_without_approved_source_proof_is_rejected(self):
        with self.assertRaisesRegex(ReplayCompatibilityError, "acceptance"):
            validate_e7_official_result_set(
                _complete_package(), future_intervals=_intervals()
            )

    def test_diagnostic_failed_source_package_is_rejected(self):
        package = _complete_package()
        for result in package:
            result["official_evaluation_permitted"] = False
            result["source_evidence_health"] = {"passed": False}
            result["input_source_version"] = "diagnostic-price-view"
        with self.assertRaisesRegex(ReplayCompatibilityError, "acceptance"):
            validate_e7_official_result_set(
                package, future_intervals=_intervals(), **_contract_kwargs()
            )

    def test_no_operator_hash_blocks_compute_and_stamp(self):
        decisions, context, interval = _case()
        with patch("app.services.e7_portfolio_evaluator.replay_long_only_v2") as compute:
            with self.assertRaisesRegex(ReplayCompatibilityError, "approval"):
                _run(decisions, context, interval, approved_contract_hash=None)
            compute.assert_not_called()
        result = _complete_package()[0]
        with self.assertRaisesRegex(ReplayCompatibilityError, "approval"):
            stamp_e7_result(
                result, result_role="baseline", future_interval=interval,
                context=context, source_acceptance=_proof(context, interval),
                acceptance_contract=_contract_kwargs()["acceptance_contract"],
            )

    def test_failed_legacy_diagnostic_or_incomplete_proof_blocks_compute(self):
        decisions, context, interval = _case()
        mutations = (
            {"passed": False}, {"passed": 1},
            {"official_evaluation_permitted": False},
            {"reason_counts": {"duplicate_decision_minute": 4}},
            {"version": "legacy"}, {"validator_version": "v1"},
            {"price_input_version": "e7-captured-raw-price-view-v1"},
            {"source_scope": "whole_history"},
            {"future_interval_definition_hash": "f" * 64},
            {"contract_hash": "f" * 64},
            {"ledger_fingerprint": ""}, {"prediction_fingerprint": None},
            {"population_fingerprint": "f" * 64},
            {"price_input_fingerprint": "f" * 64},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                proof = _proof(context, interval, **mutation)
                with patch("app.services.e7_portfolio_evaluator.replay_long_only_v2") as compute:
                    with self.assertRaises(ReplayCompatibilityError):
                        _run(decisions, context, interval, source_acceptance=proof)
                    compute.assert_not_called()
        for proof in (None, [], {"passed": True}):
            with self.subTest(proof=proof):
                with self.assertRaises(ReplayCompatibilityError):
                    _run(decisions, context, interval, source_acceptance=proof)

    def test_tampered_proof_and_changed_actual_prices_are_rejected(self):
        decisions, context, interval = _case()
        proof = _proof(context, interval)
        proof["ledger_fingerprint"] = "f" * 64
        with self.assertRaisesRegex(ReplayCompatibilityError, "proof hash"):
            _run(decisions, context, interval, source_acceptance=proof)
        changed = build_e7_interval_context(decisions, {"A": [
            ReplayBar("A", interval.start + timedelta(minutes=index), 100, 102)
            for index in range(1, 4)
        ]}, future_interval=interval)
        with self.assertRaisesRegex(ReplayCompatibilityError, "input mismatch"):
            _run(decisions, changed, interval, source_acceptance=_proof(context, interval))

    def test_normal_and_double_replay_math_is_unchanged(self):
        decisions, context, interval = _case()
        for scenario in ("normal", "double"):
            with self.subTest(scenario=scenario):
                expected = replay_long_only_v2(
                    decisions, context=context, manifest=E7_PORTFOLIO_REPLAY_MANIFEST,
                    cost_scenario=scenario, respect_decision_avoid=False,
                    result_role="baseline", future_interval_id=interval.interval_id,
                )
                observed = _run(decisions, context, interval, cost_scenario=scenario)
                for key, value in expected.items():
                    self.assertEqual(observed[key], value, key)

    def test_package_rejects_missing_tampered_or_mixed_inputs(self):
        for field in ("ledger_fingerprint", "prediction_fingerprint",
                      "population_fingerprint", "price_input_fingerprint"):
            package = _complete_package()
            package[0]["source_acceptance"][field] = "f" * 64
            _rehash(package[0]["source_acceptance"])
            if field == "population_fingerprint":
                package[0]["lineage"]["decision_fingerprint"] = "f" * 64
            elif field == "price_input_fingerprint":
                package[0]["lineage"]["price_input_fingerprint"] = "f" * 64
            with self.subTest(field=field):
                with self.assertRaisesRegex(ReplayCompatibilityError, "mixed"):
                    validate_e7_official_result_set(
                        package, future_intervals=_intervals(), **_contract_kwargs()
                    )
        for proof in (None, {}, {"passed": True}):
            package = _complete_package()
            package[0]["source_acceptance"] = proof
            with self.assertRaises(ReplayCompatibilityError):
                validate_e7_official_result_set(
                    package, future_intervals=_intervals(), **_contract_kwargs()
                )

    def test_package_allows_role_selection_and_distinct_intervals(self):
        package = _complete_package()
        for index, result in enumerate(package):
            result["selected_episode_fingerprint"] = hashlib.sha256(str(index).encode()).hexdigest()
        report = validate_e7_official_result_set(
            package, future_intervals=_intervals(), **_contract_kwargs()
        )
        self.assertTrue(report["passed"])
        self.assertNotEqual(package[0]["source_acceptance"], package[-1]["source_acceptance"])

    def test_package_identity_changes_with_source_and_contract(self):
        package = _complete_package()
        old = validate_e7_official_result_set(
            package, future_intervals=_intervals(), **_contract_kwargs()
        )
        modified = deepcopy(package)
        for result in modified:
            if result["future_interval_id"] == "future_interval_1":
                result["source_acceptance"]["prediction_fingerprint"] = "f" * 64
                _rehash(result["source_acceptance"])
        new = validate_e7_official_result_set(
            modified, future_intervals=_intervals(), **_contract_kwargs()
        )
        self.assertNotEqual(old["package_identity_hash"], new["package_identity_hash"])
        intervals = (_intervals()[0], replace(_intervals()[1], end=_intervals()[1].end + timedelta(days=1)))
        contract = E7EvidenceAcceptanceContract(intervals)
        modified = deepcopy(package)
        for result in modified:
            interval = next(item for item in intervals if item.interval_id == result["future_interval_id"])
            result["future_interval_definition"] = interval.to_dict()
            result["future_interval_definition_hash"] = interval.sha256
            result["source_acceptance"]["contract_hash"] = contract.sha256
            result["source_acceptance"]["future_interval_definition_hash"] = interval.sha256
            _rehash(result["source_acceptance"])
        new = validate_e7_official_result_set(
            modified, future_intervals=intervals,
            acceptance_contract=contract, approved_contract_hash=contract.sha256,
        )
        self.assertNotEqual(old["package_identity_hash"], new["package_identity_hash"])

    def test_cannot_restamp_conflicting_existing_source(self):
        decisions, context, interval = _case()
        result = _run(decisions, context, interval)
        proof = _proof(context, interval, ledger_fingerprint="f" * 64)
        with self.assertRaisesRegex(ReplayCompatibilityError, "source acceptance"):
            stamp_e7_result(
                result, result_role="baseline", future_interval=interval,
                context=context, source_acceptance=proof, **_contract_kwargs()
            )

    def test_random_control_rejects_cross_source_before_simulation(self):
        decisions, context, interval = _case()
        actual = _run(decisions, context, interval, result_role="e7_policy")
        actual["source_acceptance"]["ledger_fingerprint"] = "f" * 64
        _rehash(actual["source_acceptance"])
        with patch("app.services.e7_portfolio_evaluator.portfolio_random_control_v2") as compute:
            with self.assertRaisesRegex(ReplayCompatibilityError, "source acceptance"):
                run_e7_random_control(
                    decisions, actual_policy_result=actual, actual_policy_veto_ids=[],
                    context=context, future_interval=interval, cost_scenario="normal",
                    source_acceptance=_proof(context, interval), **_contract_kwargs()
                )
            compute.assert_not_called()

    def test_random_control_normal_and_double_share_validated_inputs(self):
        decisions, context, interval = _case()
        decisions.append(replace(decisions[0], episode_id="A-2"))
        context = build_e7_interval_context(decisions, {"A": [
            ReplayBar("A", interval.start + timedelta(minutes=index), 100, 100)
            for index in range(1, 4)
        ]}, future_interval=interval)
        for scenario in ("normal", "double"):
            with self.subTest(scenario=scenario):
                actual = _run(decisions, context, interval, result_role="e7_policy", cost_scenario=scenario, policy_veto_ids=["A-1"])
                result = run_e7_random_control(
                    decisions, actual_policy_result=actual, actual_policy_veto_ids=["A-1"],
                    context=context, future_interval=interval, cost_scenario=scenario,
                    source_acceptance=_proof(context, interval), **_contract_kwargs()
                )
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["simulations"], 1000)
                self.assertEqual(result["source_acceptance"], actual["source_acceptance"])

    def test_insufficient_control_sample_is_not_officially_stamped(self):
        decisions, context, interval = _case()
        actual = _run(decisions, context, interval, result_role="e7_policy")
        result = run_e7_random_control(
            decisions, actual_policy_result=actual, actual_policy_veto_ids=[],
            context=context, future_interval=interval, cost_scenario="normal",
            source_acceptance=_proof(context, interval), **_contract_kwargs()
        )
        self.assertEqual(result["status"], "insufficient_control_sample")
        self.assertIs(result["official_evaluation_permitted"], False)
        self.assertNotIn("future_interval_definition_hash", result)

    def test_contract_drift_and_contextless_stamp_are_rejected(self):
        decisions, context, interval = _case()
        for field in ("version", "validator_version", "price_input_version"):
            contract = replace(_contract_kwargs()["acceptance_contract"], **{field: "legacy"})
            with self.subTest(field=field):
                with self.assertRaisesRegex(ReplayCompatibilityError, "unsupported"):
                    _run(decisions, context, interval, acceptance_contract=contract, approved_contract_hash=contract.sha256)
        with self.assertRaisesRegex(ReplayCompatibilityError, "context"):
            stamp_e7_result(
                _complete_package()[0], result_role="baseline", future_interval=interval,
                source_acceptance=_proof(context, interval), **_contract_kwargs()
            )

    def test_stamp_rejects_invalid_or_mislabeled_evaluator_result(self):
        decisions, context, interval = _case()
        result = _run(decisions, context, interval)
        for mutation in ({"status": "invalid"}, {"evaluator_version": "legacy"},
                         {"result_role": "e7_policy"}, {"mark_price_basis": "entry"}):
            with self.subTest(mutation=mutation):
                with self.assertRaises(ReplayCompatibilityError):
                    stamp_e7_result(
                        {**result, **mutation}, result_role="baseline", future_interval=interval,
                        context=context, source_acceptance=_proof(context, interval), **_contract_kwargs()
                    )

    def test_package_rejects_tampered_interval_contents_and_metadata(self):
        for mutation in (
            {"future_interval_definition": {"start": "different"}},
            {"source_acceptance": []},
            {"input_source_version": "e7-captured-raw-price-view-v1"},
            {"input_fingerprint": "f" * 64},
            {"source_evidence_health": {"passed": True, "reasons": ["duplicate"]}},
        ):
            package = _complete_package()
            package[0].update(mutation)
            with self.subTest(mutation=mutation):
                with self.assertRaises(ReplayCompatibilityError):
                    validate_e7_official_result_set(
                        package, future_intervals=_intervals(), **_contract_kwargs()
                    )

    def test_missing_or_invalid_marks_block_before_compute(self):
        decisions, _, interval = _case()
        for bars in ({}, {"A": [ReplayBar("A", interval.start + timedelta(minutes=1), 100, float("nan"))]}):
            context = build_e7_interval_context(decisions, bars, future_interval=interval)
            with patch("app.services.e7_portfolio_evaluator.replay_long_only_v2") as compute:
                with self.assertRaises(ReplayCompatibilityError):
                    _run(decisions, context, interval)
                compute.assert_not_called()

    def test_stamp_rejects_result_computed_from_different_population_or_prices(self):
        decisions, context, interval = _case()
        result = replay_long_only_v2(
            decisions, context=context, manifest=E7_PORTFOLIO_REPLAY_MANIFEST,
            respect_decision_avoid=False, result_role="baseline",
            future_interval_id=interval.interval_id,
        )
        other_contexts = [build_e7_interval_context([], {}, future_interval=interval)]
        other_contexts.append(build_e7_interval_context(decisions, {"A": [
            ReplayBar("A", interval.start + timedelta(minutes=index), 100, 50)
            for index in range(1, 4)
        ]}, future_interval=interval))
        for other in other_contexts:
            with self.subTest(fingerprint=other.decision_fingerprint):
                with self.assertRaisesRegex(ReplayCompatibilityError, "input lineage"):
                    stamp_e7_result(
                        result, result_role="baseline", future_interval=interval,
                        context=other, source_acceptance=_proof(other, interval),
                        **_contract_kwargs()
                    )

    def test_package_rejects_missing_or_mixed_computation_lineage(self):
        for lineage in (None, {}, {"decision_fingerprint": "f" * 64},
                        {"price_input_fingerprint": "f" * 64}):
            package = _complete_package()
            package[0]["lineage"] = lineage
            with self.subTest(lineage=lineage):
                with self.assertRaisesRegex(ReplayCompatibilityError, "input lineage"):
                    validate_e7_official_result_set(
                        package, future_intervals=_intervals(), **_contract_kwargs()
                    )


if __name__ == "__main__":
    unittest.main()
