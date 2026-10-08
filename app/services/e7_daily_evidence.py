"""Read-only daily evidence builder for the preregistered E7 future window."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from app.services.e7_portfolio_evaluator import E7_PORTFOLIO_REPLAY_MANIFEST, E7FutureInterval
from app.services.portfolio_replay import (
    DecisionPoint,
    ReplayBar,
    build_executable_decisions,
    group_decision_episodes,
)
from app.services.portfolio_replay_v2 import (
    PORTFOLIO_REPLAY_V2_VERSION,
    build_v2_replay_context,
)


E7_DAILY_EVIDENCE_SCHEMA_VERSION = 3
E7_EVIDENCE_VALIDATION_VERSION = "e7-shadow-lineage-v2-exact-id"
E7_DAILY_EVIDENCE_STATUS_COLLECTING = "collecting_future_sample"
E7_EXPECTED_EVALUATOR_VERSION = "portfolio-replay-v2-minute-mtm"
E7_EXPECTED_MANIFEST_SHA256 = (
    "1d61b288a715d3cde63f6ccf1e4dcc42d6affebd14fe9d4beaf3319a9e0dd3fa"
)


@dataclass(frozen=True, slots=True)
class _FutureDecisionRow:
    decision_id: str
    symbol: str
    event_time: datetime
    probability_up: float
    eligible_population: bool
    lineage_complete: bool


def _connect_readonly(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{database_path.resolve()}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("BEGIN")
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def _parse_datetime(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(
            tzinfo=E7_PORTFOLIO_REPLAY_MANIFEST.future_evaluation_start.tzinfo
        )
    return parsed


def _load_future_decisions(
    connection: sqlite3.Connection,
    *,
    through_trading_day: date,
    future_interval: E7FutureInterval | None = None,
    observed_until: datetime | None = None,
) -> tuple[list[_FutureDecisionRow], dict[str, Any]]:
    required_columns = {
        "serving_decision_ledger": {"shadow_predictions_json"},
        "serving_predictions": {"training_run_id", "artifact_id", "artifact_sha256"},
    }
    missing_columns = sorted(
        f"{table}.{column}"
        for table, required in required_columns.items()
        for column in required.difference({
            str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
        })
    )
    if missing_columns:
        return [], {
            "joined_future_rows": 0,
            "future_decision_rows": 0,
            "eligible_population_rows": 0,
            "incomplete_lineage_rows": 0,
            "shadow_lineage_validation": {
                "version": E7_EVIDENCE_VALIDATION_VERSION,
                "passed": False,
                "reason_counts": {"required_lineage_columns_missing": 1},
                "missing_columns": missing_columns,
            },
        }
    start = E7_PORTFOLIO_REPLAY_MANIFEST.future_evaluation_start
    end = datetime.combine(
        through_trading_day + timedelta(days=1),
        time.min,
        tzinfo=start.tzinfo,
    )
    if future_interval is not None:
        start = future_interval.start
        end = min(end, future_interval.end)
        if observed_until is not None:
            end = min(end, observed_until.astimezone(start.tzinfo))
    rows = connection.execute(
        """
        SELECT
            d.decision_id,
            d.symbol,
            d.event_time,
            d.horizon_min,
            d.signal_side,
            d.signal_allowed,
            d.time_gate_allowed,
            d.spread_gate_allowed,
            d.decision_stage,
            d.order_id,
            d.fill_id,
            d.active_training_run_id,
            d.active_artifact_id,
            d.active_artifact_sha256,
            d.shadow_predictions_json
        FROM serving_decision_ledger AS d
        WHERE d.horizon_min = ?
          AND d.event_time >= ?
          AND d.event_time < ?
        ORDER BY d.event_time, d.symbol, d.decision_id
        """,
        (
            E7_PORTFOLIO_REPLAY_MANIFEST.horizon_min,
            start.isoformat(),
            end.isoformat(),
        ),
    ).fetchall()
    # Use the recorded identity, never a Cartesian symbol/minute/model join.
    references = [_stored_shadow_prediction_id(row["shadow_predictions_json"]) for row in rows]
    selected_ids = sorted({reference for reference in references if reference})
    predictions: dict[str, dict[str, Any]] = {}
    prediction_fields = (
        "prediction_id", "model_version", "training_run_id", "artifact_id", "artifact_sha256",
        "probability_up", "probability_flat", "probability_down",
        "prediction_symbol", "prediction_event_time", "prediction_horizon_min",
    )
    for offset in range(0, len(selected_ids), 500):
        batch = selected_ids[offset:offset + 500]
        placeholders = ",".join("?" for _ in batch)
        for prediction in connection.execute(
            f"""SELECT prediction_id, model_version, training_run_id, artifact_id, artifact_sha256,
                       probability_up, probability_flat, probability_down,
                       symbol AS prediction_symbol, event_time AS prediction_event_time,
                       horizon_min AS prediction_horizon_min
                FROM serving_predictions WHERE prediction_id IN ({placeholders})""",
            batch,
        ):
            predictions[str(prediction["prediction_id"])] = dict(prediction)
    rows = [
        {**dict(row), **predictions.get(reference, dict.fromkeys(prediction_fields))}
        for row, reference in zip(rows, references)
    ]
    loaded: list[_FutureDecisionRow] = []
    incomplete_lineage_rows = 0
    eligible_rows = 0
    decision_counts = Counter(str(row["decision_id"]) for row in rows)
    minute_keys = [(row["symbol"], _parse_datetime(row["event_time"]).replace(second=0, microsecond=0)) for row in rows]
    minute_counts = Counter(minute_keys)
    checks = [_shadow_lineage_errors(row) for row in rows]
    shadow_ids_by_decision = {
        str(row["decision_id"]): shadow_id
        for row, (_, shadow_id) in zip(rows, checks)
        if shadow_id
    }
    prediction_counts = Counter(shadow_ids_by_decision.values())
    reason_counts: Counter[str] = Counter()
    failed_decisions: set[str] = set()
    lineage_digest = hashlib.sha256()
    ledger_digest = hashlib.sha256()
    prediction_digest = hashlib.sha256()
    for row, minute_key, (reasons, shadow_id) in zip(rows, minute_keys, checks):
        if decision_counts[str(row["decision_id"])] > 1:
            reasons.add("shadow_prediction_rows_ambiguous")
        if minute_counts[minute_key] > 1:
            reasons.add("duplicate_decision_minute")
        if shadow_id and prediction_counts[shadow_id] > 1:
            reasons.add("shadow_prediction_reused")
        reason_counts.update(reasons)
        if reasons:
            failed_decisions.add(str(row["decision_id"]))
        lineage_digest.update(
            json.dumps(dict(row), sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        lineage_digest.update(b"\n")
        if future_interval is not None:
            for digest, payload in (
                (ledger_digest, {key: value for key, value in row.items() if key not in prediction_fields}),
                (prediction_digest, {key: row[key] for key in prediction_fields}),
            ):
                digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
                digest.update(b"\n")
        lineage_complete = not reasons
        if not lineage_complete:
            incomplete_lineage_rows += 1
        baseline_did_not_buy = (
            str(row["signal_side"] or "") != "buy"
            or not bool(row["signal_allowed"])
        )
        eligible = (
            lineage_complete
            and baseline_did_not_buy
            and bool(row["time_gate_allowed"])
            and bool(row["spread_gate_allowed"])
            and str(row["decision_stage"] or "") == "signal_blocked"
            and not row["order_id"]
            and not row["fill_id"]
        )
        if eligible:
            eligible_rows += 1
        loaded.append(
            _FutureDecisionRow(
                decision_id=str(row["decision_id"]),
                symbol=str(row["symbol"]),
                event_time=_parse_datetime(row["event_time"]),
                probability_up=(
                    float(row["probability_up"]) if lineage_complete else 0.0
                ),
                eligible_population=eligible,
                lineage_complete=lineage_complete,
            )
        )
    return loaded, {
        "joined_future_rows": len(loaded),
        "future_decision_rows": len(decision_counts),
        "eligible_population_rows": eligible_rows,
        "incomplete_lineage_rows": incomplete_lineage_rows,
        **({"ledger_fingerprint": ledger_digest.hexdigest(),
            "prediction_fingerprint": prediction_digest.hexdigest()}
           if future_interval is not None else {}),
        "shadow_lineage_validation": {
            "version": E7_EVIDENCE_VALIDATION_VERSION,
            "passed": not reason_counts,
            "checked_decision_rows": len(decision_counts),
            "failed_decision_rows": len(failed_decisions),
            "reason_count_scope": "joined_rows",
            "reason_counts": dict(sorted(reason_counts.items())),
            "source_lineage_fingerprint": lineage_digest.hexdigest(),
        },
    }


def _stored_shadow_prediction_id(payload: Any) -> str | None:
    try:
        shadows = json.loads(payload)
    except (TypeError, ValueError):
        return None
    if not isinstance(shadows, list) or any(not isinstance(item, dict) for item in shadows):
        return None
    selected = [item for item in shadows if item.get("model_version") == E7_PORTFOLIO_REPLAY_MANIFEST.model_version]
    if len(selected) != 1:
        return None
    reference = selected[0].get("prediction_id")
    return reference if isinstance(reference, str) and reference.strip() else None


def _shadow_lineage_errors(row: dict[str, Any]) -> tuple[set[str], str | None]:
    reasons: set[str] = set()
    if not all(
        isinstance(row[key], str) and row[key].strip()
        for key in ("active_training_run_id", "active_artifact_id", "active_artifact_sha256")
    ):
        reasons.add("active_lineage_incomplete")
    if not row["prediction_id"]:
        reasons.add("shadow_prediction_row_missing")
    elif any(row[f"prediction_{key}"] != row[key] for key in ("symbol", "event_time", "horizon_min")):
        reasons.add("shadow_prediction_tuple_mismatch")
    if not all(
        isinstance(row[key], str) and row[key].strip()
        for key in ("training_run_id", "artifact_id", "artifact_sha256")
    ):
        reasons.add("shadow_lineage_incomplete")
    try:
        shadows = json.loads(row["shadow_predictions_json"])
    except (TypeError, ValueError):
        return reasons | {"shadow_predictions_malformed"}, None
    if not isinstance(shadows, list) or any(not isinstance(item, dict) for item in shadows):
        return reasons | {"shadow_predictions_malformed"}, None
    selected = [
        item for item in shadows
        if item.get("model_version") == E7_PORTFOLIO_REPLAY_MANIFEST.model_version
    ]
    if not selected:
        return reasons | {"shadow_prediction_missing"}, None
    if len(selected) != 1:
        return reasons | {"shadow_predictions_ambiguous"}, None
    shadow = selected[0]
    identity_fields = ("prediction_id", "model_version", "training_run_id", "artifact_id", "artifact_sha256")
    if not all(isinstance(shadow.get(key), str) and shadow[key].strip() for key in identity_fields):
        reasons.add("shadow_lineage_incomplete")
    if any(shadow.get(key) != row[key] for key in identity_fields):
        reasons.add("shadow_prediction_mismatch")
    for key in ("probability_up", "probability_flat", "probability_down"):
        values = (shadow.get(key), row[key])
        if any(
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not 0 <= value <= 1
            for value in values
        ):
            reasons.add("shadow_probability_invalid")
        elif values[0] != values[1]:
            reasons.add("shadow_prediction_mismatch")
    shadow_id = shadow.get("prediction_id")
    return reasons, shadow_id if isinstance(shadow_id, str) and shadow_id.strip() else None


def _load_bars(
    connection: sqlite3.Connection,
    *,
    symbols: Iterable[str],
    start_day: date,
    end_day: date,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict[str, list[ReplayBar]]:
    selected = sorted(set(symbols))
    if not selected:
        return {}
    placeholders = ",".join("?" for _ in selected)
    start = f"{start_day.isoformat()}T00:00:00"
    end = f"{(end_day + timedelta(days=1)).isoformat()}T00:00:00"
    if start_at is not None:
        start = start_at.isoformat()
    if end_at is not None:
        end = end_at.isoformat()
    rows = connection.execute(
        f"""
        SELECT symbol, bar_time, open, close
        FROM curated_minute_bars
        WHERE symbol IN ({placeholders})
          AND bar_time >= ?
          AND bar_time < ?
        ORDER BY symbol, bar_time
        """,
        (*selected, start, end),
    ).fetchall()
    bars: dict[str, list[ReplayBar]] = {}
    for row in rows:
        bars.setdefault(str(row["symbol"]), []).append(
            ReplayBar(
                symbol=str(row["symbol"]),
                bar_time=_parse_datetime(row["bar_time"]),
                open_price=float(row["open"]),
                close_price=float(row["close"]),
            )
        )
    return bars


def build_e7_daily_evidence(
    database_path: Path,
    *,
    through_trading_day: date,
    generated_at: datetime | None = None,
    observed_evaluator_version: str = PORTFOLIO_REPLAY_V2_VERSION,
    observed_manifest_hash: str | None = None,
) -> dict[str, Any]:
    """Build one E7 progress artifact without mutating the runtime database."""

    observed_hash = (
        observed_manifest_hash
        if observed_manifest_hash is not None
        else E7_PORTFOLIO_REPLAY_MANIFEST.sha256
    )
    created_at = generated_at or datetime.now(timezone.utc)
    required_tables = {
        "serving_decision_ledger",
        "serving_predictions",
        "curated_minute_bars",
    }
    with _connect_readonly(database_path) as connection:
        missing_tables = sorted(required_tables.difference(_table_names(connection)))
        if missing_tables:
            return _unavailable_report(
                through_trading_day=through_trading_day,
                generated_at=created_at,
                missing_tables=missing_tables,
                observed_evaluator_version=observed_evaluator_version,
                observed_manifest_hash=observed_hash,
            )
        rows, source = _load_future_decisions(
            connection,
            through_trading_day=through_trading_day,
        )
        eligible = [row for row in rows if row.eligible_population]
        points = [
            DecisionPoint(
                decision_id=row.decision_id,
                symbol=row.symbol,
                event_time=row.event_time,
                avoid=(
                    row.probability_up
                    < E7_PORTFOLIO_REPLAY_MANIFEST.threshold
                ),
            )
            for row in eligible
        ]
        grouped = group_decision_episodes(points)
        bars = _load_bars(
            connection,
            symbols=(row.symbol for row in eligible),
            start_day=E7_PORTFOLIO_REPLAY_MANIFEST.future_evaluation_start.date(),
            end_day=through_trading_day,
        )

    executable, execution_diagnostics = build_executable_decisions(
        grouped,
        bars,
        horizon_min=E7_PORTFOLIO_REPLAY_MANIFEST.horizon_min,
        forced_flat_time=E7_PORTFOLIO_REPLAY_MANIFEST.forced_flat_time,
    )
    rescue_decisions = [decision for decision in executable if not decision.avoid]
    context = build_v2_replay_context(
        rescue_decisions,
        bars,
        manifest=E7_PORTFOLIO_REPLAY_MANIFEST,
    )
    future_days = sorted(
        {row.event_time.date().isoformat() for row in rows}
    )
    symbols = sorted({decision.symbol for decision in rescue_decisions})
    identity_reasons = []
    if observed_evaluator_version != E7_EXPECTED_EVALUATOR_VERSION:
        identity_reasons.append("evaluator_version_drift")
    if PORTFOLIO_REPLAY_V2_VERSION != E7_EXPECTED_EVALUATOR_VERSION:
        identity_reasons.append("evaluator_definition_drift")
    if observed_hash != E7_EXPECTED_MANIFEST_SHA256:
        identity_reasons.append("manifest_hash_drift")
    if E7_PORTFOLIO_REPLAY_MANIFEST.sha256 != E7_EXPECTED_MANIFEST_SHA256:
        identity_reasons.append("manifest_definition_drift")
    mark_reasons = list(context.coverage.invalid_reasons)
    lineage_validation = source["shadow_lineage_validation"]
    lineage_reasons = list(lineage_validation["reason_counts"])
    evidence_reasons = [*identity_reasons, *lineage_reasons, *mark_reasons]
    mark_valid = context.coverage.valid
    identity_valid = not identity_reasons
    lineage_valid = bool(lineage_validation["passed"])

    requirements = {
        "trading_days": _requirement(
            len(future_days),
            E7_PORTFOLIO_REPLAY_MANIFEST.minimum_trading_days,
        ),
        "episodes": _requirement(
            len(rescue_decisions),
            E7_PORTFOLIO_REPLAY_MANIFEST.minimum_episodes,
        ),
        "symbols": _requirement(
            len(symbols),
            E7_PORTFOLIO_REPLAY_MANIFEST.minimum_symbols,
        ),
        "lineage_completion": {
            "current": (
                1.0
                if not rows
                else (
                    len(rows) - int(source["incomplete_lineage_rows"])
                )
                / len(rows)
            ),
            "required": 1.0,
            "passed": lineage_valid,
        },
    }
    minimums_passed = all(
        bool(item["passed"]) for item in requirements.values()
    )
    if not identity_valid or not mark_valid or not lineage_valid:
        evidence_health = "invalid"
        official_status = "invalid_evidence"
    elif not rows:
        evidence_health = "valid_no_future_rows"
        official_status = "not_available_yet"
    elif minimums_passed:
        evidence_health = "valid_ready_for_interval_definition"
        official_status = "ready_for_official_interval_evaluation"
    else:
        evidence_health = "valid_collecting"
        official_status = E7_DAILY_EVIDENCE_STATUS_COLLECTING
    prerequisite_status = (
        "blocked_invalid_evidence"
        if evidence_reasons
        else "ready"
        if minimums_passed
        else "waiting_minimum_sample"
    )
    source_fingerprint = _source_fingerprint(rows, bars)
    return {
        "schema_version": E7_DAILY_EVIDENCE_SCHEMA_VERSION,
        "evidence_validation_version": E7_EVIDENCE_VALIDATION_VERSION,
        "generated_at": created_at.isoformat(),
        "evaluator_version": observed_evaluator_version,
        "expected_evaluator_version": E7_EXPECTED_EVALUATOR_VERSION,
        "manifest_hash": observed_hash,
        "current_manifest_hash": E7_PORTFOLIO_REPLAY_MANIFEST.sha256,
        "expected_manifest_hash": E7_EXPECTED_MANIFEST_SHA256,
        "future_start": (
            E7_PORTFOLIO_REPLAY_MANIFEST.future_evaluation_start.isoformat()
        ),
        "through_trading_day": through_trading_day.isoformat(),
        "future_trading_days": len(future_days),
        "future_trading_day_list": future_days,
        "episodes": len(rescue_decisions),
        "eligible_population_episodes": len(executable),
        "symbols": len(symbols),
        "symbol_list": symbols,
        "symbol_count": len(symbols),
        "mark_observation_count": context.coverage.mark_observation_count,
        "missing_mark_count": context.coverage.missing_mark_count,
        "stale_mark_count": context.coverage.stale_mark_count,
        "invalid_mark_count": context.coverage.invalid_mark_count,
        "invalid_mark_reasons": mark_reasons,
        "evidence_health": {
            "status": evidence_health,
            "passed": identity_valid and mark_valid and lineage_valid,
            "reasons": evidence_reasons,
        },
        "profitability_assessment": {
            "status": "not_evaluated"
            if official_status != "ready_for_official_interval_evaluation"
            else "pending_official_interval_evaluation",
            "strategy_failure": False,
        },
        "normal_cost": {
            "status": prerequisite_status,
            "prerequisite_status": prerequisite_status,
            "prerequisites": {
                "identity_valid": identity_valid,
                "marks_valid": mark_valid,
                "shadow_lineage_valid": lineage_valid,
                "minimum_sample_passed": minimums_passed,
            },
        },
        "double_cost": {
            "status": prerequisite_status,
            "prerequisite_status": prerequisite_status,
            "multiplier": (
                E7_PORTFOLIO_REPLAY_MANIFEST.cost_sensitivity_multiplier
            ),
            "prerequisites": {
                "identity_valid": identity_valid,
                "marks_valid": mark_valid,
                "shadow_lineage_valid": lineage_valid,
                "minimum_sample_passed": minimums_passed,
            },
        },
        "random_control": {
            "required": True,
            "completed": False,
            "status": prerequisite_status,
            "required_simulations": (
                E7_PORTFOLIO_REPLAY_MANIFEST.random_control_simulations
            ),
            "completed_simulations": 0,
            "not_run_reason": prerequisite_status,
            "seed": E7_PORTFOLIO_REPLAY_MANIFEST.random_seed,
        },
        "future_intervals": {
            "interval_1_status": prerequisite_status,
            "interval_2_status": (
                "blocked_invalid_evidence" if evidence_reasons else "waiting_first_interval"
            ),
            "boundaries_fixed": False,
        },
        "minimum_requirements": {
            "required_trading_days": (
                E7_PORTFOLIO_REPLAY_MANIFEST.minimum_trading_days
            ),
            "required_episodes": E7_PORTFOLIO_REPLAY_MANIFEST.minimum_episodes,
            "required_symbols": E7_PORTFOLIO_REPLAY_MANIFEST.minimum_symbols,
            "current_progress": requirements,
            "status": "met" if minimums_passed else "not_met",
            **requirements,
        },
        "official_evaluation_status": official_status,
        "source": {
            **source,
            "grouped_population_episodes": len(grouped),
            "executable_population_episodes": len(executable),
            "execution_diagnostics": execution_diagnostics,
            "source_bar_count": context.mark_index.source_bar_count,
            "source_fingerprint": source_fingerprint,
            "database_access": "read-only",
            "database_mutation": False,
        },
    }


def _requirement(current: int, required: int) -> dict[str, Any]:
    return {
        "current": int(current),
        "required": int(required),
        "passed": int(current) >= int(required),
    }


def _source_fingerprint(
    rows: list[_FutureDecisionRow],
    bars: dict[str, list[ReplayBar]],
) -> str:
    payload = {
        "decisions": [
            (
                row.decision_id,
                row.symbol,
                row.event_time.isoformat(),
                row.probability_up,
                row.eligible_population,
                row.lineage_complete,
            )
            for row in rows
        ],
        "bars": [
            (
                bar.symbol,
                bar.bar_time.isoformat(),
                bar.open_price,
                bar.close_price,
            )
            for symbol in sorted(bars)
            for bar in bars[symbol]
        ],
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _unavailable_report(
    *,
    through_trading_day: date,
    generated_at: datetime,
    missing_tables: list[str],
    observed_evaluator_version: str,
    observed_manifest_hash: str,
) -> dict[str, Any]:
    return {
        "schema_version": E7_DAILY_EVIDENCE_SCHEMA_VERSION,
        "evidence_validation_version": E7_EVIDENCE_VALIDATION_VERSION,
        "generated_at": generated_at.isoformat(),
        "evaluator_version": observed_evaluator_version,
        "expected_evaluator_version": E7_EXPECTED_EVALUATOR_VERSION,
        "manifest_hash": observed_manifest_hash,
        "current_manifest_hash": E7_PORTFOLIO_REPLAY_MANIFEST.sha256,
        "expected_manifest_hash": E7_EXPECTED_MANIFEST_SHA256,
        "future_start": E7_PORTFOLIO_REPLAY_MANIFEST.future_evaluation_start.isoformat(),
        "through_trading_day": through_trading_day.isoformat(),
        "future_trading_days": 0,
        "episodes": 0,
        "symbols": 0,
        "symbol_list": [],
        "symbol_count": 0,
        "mark_observation_count": 0,
        "missing_mark_count": 0,
        "stale_mark_count": 0,
        "invalid_mark_count": 0,
        "evidence_health": {
            "status": "not_available",
            "passed": False,
            "reasons": ["required_tables_missing"],
        },
        "profitability_assessment": {
            "status": "not_evaluated",
            "strategy_failure": False,
        },
        "normal_cost": {
            "status": "not_available",
            "prerequisite_status": "required_tables_missing",
        },
        "double_cost": {
            "status": "not_available",
            "prerequisite_status": "required_tables_missing",
        },
        "random_control": {
            "required": True,
            "completed": False,
            "status": "not_available",
            "required_simulations": (
                E7_PORTFOLIO_REPLAY_MANIFEST.random_control_simulations
            ),
            "completed_simulations": 0,
            "not_run_reason": "required_tables_missing",
        },
        "future_intervals": {
            "interval_1_status": "not_available",
            "interval_2_status": "not_available",
            "boundaries_fixed": False,
        },
        "minimum_requirements": {
            "required_trading_days": (
                E7_PORTFOLIO_REPLAY_MANIFEST.minimum_trading_days
            ),
            "required_episodes": E7_PORTFOLIO_REPLAY_MANIFEST.minimum_episodes,
            "required_symbols": E7_PORTFOLIO_REPLAY_MANIFEST.minimum_symbols,
            "current_progress": {},
            "status": "not_met",
        },
        "official_evaluation_status": "not_available_yet",
        "source": {
            "missing_tables": missing_tables,
            "database_access": "read-only",
            "database_mutation": False,
        },
    }


def validate_e7_evidence_for_reuse(payload: dict[str, Any]) -> dict[str, Any]:
    """Do not promote immutable legacy artifacts to the new evidence validator."""
    source = payload.get("source")
    validation = source.get("shadow_lineage_validation") if isinstance(source, dict) else None
    validation = validation if isinstance(validation, dict) else {}
    reuse_reasons = []
    if (
        payload.get("schema_version") == E7_DAILY_EVIDENCE_SCHEMA_VERSION
        and payload.get("evidence_validation_version") == E7_EVIDENCE_VALIDATION_VERSION
        and validation.get("version") == E7_EVIDENCE_VALIDATION_VERSION
    ):
        health = payload.get("evidence_health", {})
        proof_consistent = (
            validation.get("passed") is True
            and validation.get("reason_counts") == {}
            and health.get("passed") is True
        ) or (
            health.get("passed") is False
            and health.get("status") == "invalid"
            and payload.get("official_evaluation_status") == "invalid_evidence"
        )
        if not proof_consistent:
            reuse_reasons.append("shadow_lineage_validation_inconsistent")
        if (
            PORTFOLIO_REPLAY_V2_VERSION != E7_EXPECTED_EVALUATOR_VERSION
            or any(payload.get(key) != E7_EXPECTED_EVALUATOR_VERSION for key in (
                "evaluator_version", "expected_evaluator_version"
            ))
        ):
            reuse_reasons.append("evaluator_version_drift")
        if (
            E7_PORTFOLIO_REPLAY_MANIFEST.sha256 != E7_EXPECTED_MANIFEST_SHA256
            or any(payload.get(key) != E7_EXPECTED_MANIFEST_SHA256 for key in (
                "manifest_hash", "current_manifest_hash", "expected_manifest_hash"
            ))
        ):
            reuse_reasons.append("manifest_hash_drift")
    else:
        reuse_reasons.append("shadow_lineage_validation_not_available")
    if not reuse_reasons:
        return payload
    result = dict(payload)
    reasons = list(payload.get("evidence_health", {}).get("reasons", []))
    reasons.extend(reuse_reasons)
    result["evidence_health"] = {"status": "invalid", "passed": False, "reasons": sorted(set(reasons))}
    result["official_evaluation_status"] = "invalid_evidence"
    result["profitability_assessment"] = {"status": "not_evaluated", "strategy_failure": False}
    for key in ("normal_cost", "double_cost", "random_control"):
        result[key] = {**payload.get(key, {}), "status": "blocked_invalid_evidence",
                       "prerequisite_status": "blocked_invalid_evidence"}
    result["future_intervals"] = {**payload.get("future_intervals", {}),
                                  "interval_1_status": "blocked_invalid_evidence",
                                  "interval_2_status": "blocked_invalid_evidence"}
    return result


def write_e7_daily_evidence_once(
    payload: dict[str, Any],
    *,
    dated_path: Path,
    latest_path: Path,
) -> tuple[dict[str, Any], bool]:
    """Write one immutable trading-day artifact; reuse it on same-day reruns."""

    if dated_path.exists():
        existing = json.loads(dated_path.read_text(encoding="utf-8"))
        if (
            existing.get("through_trading_day")
            != payload.get("through_trading_day")
        ):
            raise ValueError("dated E7 artifact trading day mismatch")
        return validate_e7_evidence_for_reuse(existing), False
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    dated_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    dated_tmp = dated_path.with_suffix(dated_path.suffix + ".tmp")
    latest_tmp = latest_path.with_suffix(latest_path.suffix + ".tmp")
    dated_tmp.write_text(encoded, encoding="utf-8")
    latest_tmp.write_text(encoded, encoding="utf-8")
    dated_tmp.replace(dated_path)
    latest_tmp.replace(latest_path)
    return payload, True
