"""Pinned post-recovery E7 source proof and progress, separate from cumulative E7."""

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from app.services.e7_daily_evidence import (
    _connect_readonly, _load_bars, _load_future_decisions, _requirement, _table_names,
)
from app.services.e7_portfolio_evaluator import (
    E7EvidenceAcceptanceContract, E7FutureInterval, E7_PORTFOLIO_REPLAY_MANIFEST,
    E7_SOURCE_ACCEPTANCE_VERSION, KST, build_e7_interval_context,
)
from app.services.portfolio_replay import (
    DecisionPoint, ExecutableDecision, build_executable_decisions, group_decision_episodes,
)
from app.services.portfolio_replay_v2 import PortfolioReplayV2Context


PINNED_CONTRACT_HASH = "16a22ce5801cd1f38d21aee98bfe806fa809a3c4061d2f61e4bdb5b16b20e740"
PROGRESS_VERSION = "e7-post-recovery-progress-v1"


def _digest(payload):
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _check_contract(contract):
    if not isinstance(contract, E7EvidenceAcceptanceContract) or contract.sha256 != PINNED_CONTRACT_HASH:
        raise ValueError("post-recovery acceptance contract drift")


def load_post_recovery_contract(path: Path) -> E7EvidenceAcceptanceContract:
    record = json.loads(path.read_text(encoding="utf-8"))
    body = record["contract"]
    contract = E7EvidenceAcceptanceContract(tuple(E7FutureInterval(
        item["interval_id"], datetime.fromisoformat(item["start"]),
        datetime.fromisoformat(item["end"]),
    ) for item in body["future_intervals"]))
    _check_contract(contract)
    manifest = E7_PORTFOLIO_REPLAY_MANIFEST
    policy = {
        "original_future_start_preserved": manifest.future_evaluation_start.isoformat(),
        "evaluator_version": manifest.evaluator_version,
        "threshold": manifest.threshold,
        "minimum_trading_days_per_interval": manifest.minimum_trading_days,
        "minimum_policy_episodes_per_interval": manifest.minimum_episodes,
        "minimum_policy_symbols_per_interval": manifest.minimum_symbols,
        "random_control_simulations": manifest.random_control_simulations,
        "cost_scenarios": ["normal", "double"],
        "strategy_costs_constraints_and_model_changes_permitted": False,
        "insufficient_sample": "observe_more_without_moving_fixed_boundaries",
        "merge_with_original_cumulative_results_permitted": False,
        "historical_evidence_repair_permitted": False,
        "automatic_official_permission": False,
    }
    if (body != contract.to_dict() or record.get("contract_hash") != contract.sha256
            or record.get("schema_version") != 1 or record.get("evaluation_policy") != policy):
        raise ValueError("post-recovery contract record/policy drift")
    return contract


@dataclass(frozen=True)
class E7IntervalEvidence:
    report: dict
    decisions: tuple[ExecutableDecision, ...] = ()
    context: PortfolioReplayV2Context | None = None


def produce_interval_evidence(
    database_path: Path, *, acceptance_contract: E7EvidenceAcceptanceContract,
    future_interval: E7FutureInterval, approved_contract_hash: str | None = None,
    generated_at: datetime | None = None, holidays: tuple[str, ...] = (),
) -> E7IntervalEvidence:
    _check_contract(acceptance_contract)
    if future_interval not in acceptance_contract.future_intervals:
        raise ValueError("post-recovery interval mismatch")
    if approved_contract_hash not in (None, acceptance_contract.sha256):
        raise ValueError("post-recovery approval hash mismatch")
    now = generated_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("observation time must be timezone-aware")
    now = now.astimezone(KST)
    report = {
        "future_interval": future_interval.to_dict(),
        "future_interval_definition_hash": future_interval.sha256,
        "contract_hash": acceptance_contract.sha256,
        "status": "not_started", "blocking_reasons": ["fixed_interval_not_started"],
        "database_access_started": False, "future_trading_days": 0,
        "episodes": 0, "symbols": 0, "source_acceptance": None,
        "mark_observation_count": 0, "missing_mark_count": 0,
        "stale_mark_count": 0, "invalid_mark_count": 0,
        "official_evaluation_permitted": False,
    }
    if now < future_interval.start:
        return E7IntervalEvidence(report)
    end = min(now, future_interval.end)
    report["database_access_started"] = True
    with closing(_connect_readonly(database_path)) as connection:
        required = {"serving_decision_ledger", "serving_predictions", "curated_minute_bars"}
        missing = required.difference(_table_names(connection))
        if missing:
            report.update(status="invalid_evidence", blocking_reasons=["required_tables_missing"],
                          source={"missing_tables": sorted(missing)})
            return E7IntervalEvidence(report)
        rows, source = _load_future_decisions(
            connection, through_trading_day=end.date(), future_interval=future_interval,
            observed_until=end,
        )
        eligible = [row for row in rows if row.eligible_population]
        points = [DecisionPoint(row.decision_id, row.symbol, row.event_time,
                                row.probability_up < E7_PORTFOLIO_REPLAY_MANIFEST.threshold)
                  for row in eligible]
        grouped = group_decision_episodes(points)
        bars = _load_bars(connection, symbols=(row.symbol for row in eligible),
                          start_day=future_interval.start.date(), end_day=end.date(),
                          start_at=future_interval.start, end_at=end)
    executable, diagnostics = build_executable_decisions(
        grouped, bars, horizon_min=E7_PORTFOLIO_REPLAY_MANIFEST.horizon_min,
        forced_flat_time=E7_PORTFOLIO_REPLAY_MANIFEST.forced_flat_time,
    )
    context = build_e7_interval_context(executable, bars, future_interval=future_interval)
    policy = [item for item in executable if not item.avoid]
    days = sorted({row.event_time.astimezone(KST).date().isoformat() for row in rows
                   if row.event_time.astimezone(KST).weekday() < 5
                   and row.event_time.astimezone(KST).date().isoformat() not in holidays})
    validation = source["shadow_lineage_validation"]
    reasons = set(validation["reason_counts"])
    if validation["version"] != acceptance_contract.validator_version:
        reasons.add("validator_version_drift")
    if any(row.event_time.astimezone(KST).weekday() >= 5
           or row.event_time.astimezone(KST).date().isoformat() in holidays for row in rows):
        reasons.add("non_trading_day_source_rows")
    reasons.update(context.coverage.invalid_reasons)
    reasons.update(key for key in (
        "missing_symbol_bars", "missing_next_entry_bar", "missing_exit_bar", "invalid_price",
        "cross_day_bar",
    ) if diagnostics.get(key, 0))
    manifest = E7_PORTFOLIO_REPLAY_MANIFEST
    requirements = {
        "trading_days": _requirement(len(days), manifest.minimum_trading_days),
        "episodes": _requirement(len(policy), manifest.minimum_episodes),
        "symbols": _requirement(len({item.symbol for item in policy}), manifest.minimum_symbols),
    }
    minimums = all(item["passed"] for item in requirements.values())
    status = "invalid_evidence" if reasons else (
        "collecting_future_sample" if now < future_interval.end else
        "observe_more" if not minimums else
        "waiting_explicit_activation" if approved_contract_hash is None else
        "ready_for_official_evaluation"
    )
    blockers = sorted(reasons)
    if now < future_interval.end:
        blockers.append("fixed_interval_not_closed")
    if not minimums:
        blockers.append("minimum_sample_not_met")
    if approved_contract_hash is None:
        blockers.append("explicit_activation_not_supplied")
    report.update(
        status=status, blocking_reasons=blockers, source=source,
        future_trading_days=len(days), future_trading_day_list=days,
        episodes=len(policy), symbols=len({item.symbol for item in policy}),
        eligible_population_episodes=len(executable), execution_diagnostics=diagnostics,
        minimum_requirements=requirements, source_health_passed=not reasons,
        mark_observation_count=context.coverage.mark_observation_count,
        missing_mark_count=context.coverage.missing_mark_count,
        stale_mark_count=context.coverage.stale_mark_count,
        invalid_mark_count=context.coverage.invalid_mark_count,
        population_fingerprint=context.decision_fingerprint,
        price_input_fingerprint=context.price_input_fingerprint,
    )
    if status == "ready_for_official_evaluation":
        proof = {
            "version": E7_SOURCE_ACCEPTANCE_VERSION,
            "contract_hash": acceptance_contract.sha256, "manifest_hash": manifest.sha256,
            "source_scope": "fixed_e7_future_interval",
            "future_interval_definition_hash": future_interval.sha256,
            "validator_version": acceptance_contract.validator_version,
            "price_input_version": acceptance_contract.price_input_version,
            "passed": True, "reason_counts": {}, "official_evaluation_permitted": True,
            "ledger_fingerprint": source["ledger_fingerprint"],
            "prediction_fingerprint": source["prediction_fingerprint"],
            "population_fingerprint": context.decision_fingerprint,
            "price_input_fingerprint": context.price_input_fingerprint,
        }
        proof["proof_hash"] = _digest(proof)
        report.update(source_acceptance=proof, official_evaluation_permitted=True)
    return E7IntervalEvidence(report, tuple(executable), context)


def build_post_recovery_progress(
    database_path: Path, *, acceptance_contract: E7EvidenceAcceptanceContract,
    generated_at: datetime | None = None, holidays: tuple[str, ...] = (),
) -> dict:
    now = generated_at or datetime.now(timezone.utc)
    intervals = [produce_interval_evidence(
        database_path, acceptance_contract=acceptance_contract, future_interval=interval,
        generated_at=now, holidays=holidays,
    ).report for interval in acceptance_contract.future_intervals]
    return {
        "version": PROGRESS_VERSION, "generated_at": now.isoformat(),
        "contract_hash": acceptance_contract.sha256,
        "evaluator_version": E7_PORTFOLIO_REPLAY_MANIFEST.evaluator_version,
        "manifest_hash": E7_PORTFOLIO_REPLAY_MANIFEST.sha256,
        "status": "invalid_evidence" if any(item["status"] == "invalid_evidence" for item in intervals)
                  else "not_started" if all(item["status"] == "not_started" for item in intervals)
                  else "observing_fixed_intervals",
        "intervals": intervals, "official_evaluation_permitted": False,
        "normal_cost": "not_run", "double_cost": "not_run", "random_control": "not_run",
        "safety": {"database_mutation": False, "kis_network_calls": 0,
                   "order_calls": 0, "cancel_calls": 0, "contract_activation": False},
    }


def _check_progress(payload: dict):
    if payload.get("version") != PROGRESS_VERSION or payload.get("contract_hash") != PINNED_CONTRACT_HASH:
        raise ValueError("post-recovery progress identity mismatch")
    if payload.get("official_evaluation_permitted") is not False:
        raise ValueError("progress artifact must not permit official evaluation")
    manifest = E7_PORTFOLIO_REPLAY_MANIFEST
    if payload.get("manifest_hash") != manifest.sha256 or payload.get("evaluator_version") != manifest.evaluator_version:
        raise ValueError("post-recovery evaluator identity drift")
    intervals = tuple(E7FutureInterval(
        item["future_interval"]["interval_id"],
        datetime.fromisoformat(item["future_interval"]["start"]),
        datetime.fromisoformat(item["future_interval"]["end"]),
    ) for item in payload["intervals"])
    _check_contract(E7EvidenceAcceptanceContract(intervals))
    if any(item.get("future_interval_definition_hash") != interval.sha256
           or item.get("contract_hash") != PINNED_CONTRACT_HASH
           for item, interval in zip(payload["intervals"], intervals)):
        raise ValueError("post-recovery interval progress drift")
    now = datetime.fromisoformat(payload["generated_at"])
    if now.tzinfo is None:
        raise ValueError("progress observation time must be timezone-aware")
    return now.astimezone(KST)


def _read_progress(path: Path, *, day):
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        saved_hash = stored.pop("report_hash", None)
        if saved_hash != _digest(stored) or _check_progress(stored).date() != day:
            raise ValueError("stored identity mismatch")
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("stored post-recovery progress drift") from exc
    return stored


def write_post_recovery_progress(payload: dict, *, report_root: Path) -> tuple[Path, bool]:
    now = _check_progress(payload)
    day = now.date()
    path = report_root / PINNED_CONTRACT_HASH / f"{day.isoformat()}.json"
    if path.exists():
        stored = _read_progress(path, day=day)
        if {k: v for k, v in stored.items() if k != "generated_at"} == {
                k: v for k, v in payload.items() if k != "generated_at"}:
            return path, False
        # Preserve the first observation and every changed-source revalidation.
        path = path.parent / "rechecks" / f"{now.strftime('%Y-%m-%dT%H%M%S%f')}.json"
        if path.exists():
            if _read_progress(path, day=day) != payload:
                raise ValueError("post-recovery revalidation identity drift")
            return path, False
    encoded = {**payload, "report_hash": _digest(payload)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(encoded, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return path, True
