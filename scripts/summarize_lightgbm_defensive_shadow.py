#!/usr/bin/env python3
"""Compare baseline buy signals with LightGBM defensive buy-avoid filters.

This is a read-only paper-shadow report.  It does not change the active model,
thresholds, gates, paper orders, or live orders.
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

try:  # repo-root import (pytest) or sibling import (direct script run)
    from scripts.buy_avoid_random_control import (
        VERDICT_BETTER,
        random_control_report,
    )
except ImportError:  # pragma: no cover - direct `python3 scripts/...` run
    from buy_avoid_random_control import (  # type: ignore[no-redef]
        VERDICT_BETTER,
        random_control_report,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config.settings import load_settings
from app.paper_trading.costs import (
    DEFAULT_RESEARCH_SLIPPAGE_BPS,
    build_domestic_stock_cost_model_metadata,
)
from app.services.portfolio_replay import (
    DecisionPoint,
    ReplayBar,
    build_executable_decisions,
    group_decision_episodes,
    portfolio_random_control,
    replay_long_only,
)

DEFAULT_DATABASE = REPO_ROOT / "runtime-data" / "dev.db"
DEFAULT_DIAGNOSTICS = (
    REPO_ROOT / "runtime-data" / "reports" / "challengers" / "latest-lightgbm-performance-diagnostics-h15.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime-data" / "reports" / "challengers"
DEFAULT_THRESHOLDS = (0.40, 0.45, 0.50, 0.54, 0.58)
MIN_CANDIDATE_EPISODES = 100
MIN_CANDIDATE_DAYS = 10
MIN_NONNEGATIVE_DAY_SHARE = 2.0 / 3.0
DEFAULT_RANDOM_SIMULATIONS = 200
DEFAULT_PORTFOLIO_RANDOM_SEED = 42


@dataclass(frozen=True)
class ShadowRow:
    signal_id: str
    symbol: str
    event_time: str
    signal_confidence: float | None
    probability_up: float | None
    probability_flat: float | None
    probability_down: float | None
    label: str
    future_return_pct: float
    training_run_id: str | None = None
    artifact_id: str | None = None
    artifact_sha256: str | None = None

    @property
    def down_is_argmax(self) -> bool:
        values = [self.probability_up, self.probability_flat, self.probability_down]
        if any(value is None for value in values):
            return False
        return bool(self.probability_down >= self.probability_up and self.probability_down >= self.probability_flat)


@dataclass(frozen=True)
class ClosedLot:
    symbol: str
    qty: float
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float


@dataclass(frozen=True)
class PredictionPrice:
    symbol: str
    event_time: str
    probability_up: float | None
    probability_flat: float | None
    probability_down: float | None
    executable_time: str | None
    executable_price: float | None

    @property
    def down_is_argmax(self) -> bool:
        values = [self.probability_up, self.probability_flat, self.probability_down]
        if any(value is None for value in values):
            return False
        return bool(self.probability_down >= self.probability_up and self.probability_down >= self.probability_flat)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _validate_date_range(start_date: str | None, end_date: str | None) -> None:
    start = date.fromisoformat(start_date) if start_date else None
    end = date.fromisoformat(end_date) if end_date else None
    if start is not None and end is not None and end < start:
        raise ValueError("end_date must be on or after start_date")


def _filter_shadow_rows_by_date(
    rows: list[ShadowRow],
    *,
    start_date: str | None,
    end_date: str | None,
) -> list[ShadowRow]:
    _validate_date_range(start_date, end_date)
    return [
        row
        for row in rows
        if (start_date is None or row.event_time[:10] >= start_date)
        and (end_date is None or row.event_time[:10] <= end_date)
    ]


def _filter_closed_lots_by_date(
    lots: list[ClosedLot],
    *,
    start_date: str | None,
    end_date: str | None,
) -> list[ClosedLot]:
    _validate_date_range(start_date, end_date)
    return [
        lot
        for lot in lots
        if (start_date is None or lot.entry_time[:10] >= start_date)
        and (end_date is None or lot.exit_time[:10] <= end_date)
    ]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _trade_cost_context(diagnostics_path: Path) -> dict[str, object]:
    data = _read_json(diagnostics_path)
    value = _to_float(data.get("trade_cost_pct"))
    metadata = build_domestic_stock_cost_model_metadata(
        slippage_bps=DEFAULT_RESEARCH_SLIPPAGE_BPS,
        round_trip_cost_pct=value,
    )
    metadata.update(
        {
            "source": "diagnostics_report" if value is not None else "shared_current_default",
            "source_path": str(diagnostics_path),
            "source_reported_version": data.get("cost_model_version"),
        }
    )
    return metadata


def _trade_cost_pct(diagnostics_path: Path) -> float:
    return float(_trade_cost_context(diagnostics_path)["round_trip_cost_pct"])


def _connect_readonly(database_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _select_lineage_segment(
    rows: list[ShadowRow],
    training_run_completed_at: dict[str, str] | None = None,
) -> tuple[list[ShadowRow], dict[str, Any], set[tuple[str, str, str]] | None]:
    training_run_completed_at = training_run_completed_at or {}
    complete_rows = [
        row
        for row in rows
        if row.training_run_id and row.artifact_id and row.artifact_sha256
    ]
    if not complete_rows:
        return (
            rows,
            {
                "status": "legacy_lineage_missing",
                "candidate_eligible": False,
                "blockers": ["no_complete_prediction_lineage"],
                "total_rows": len(rows),
                "complete_rows": 0,
                "missing_rows": len(rows),
                "distinct_complete_lineages": 0,
                "selected_lineage": None,
                "lineage_chain": [],
                "excluded_rows": 0,
            },
            None,
        )

    groups: dict[tuple[str, str, str], list[ShadowRow]] = {}
    for row in complete_rows:
        key = (
            str(row.training_run_id),
            str(row.artifact_id),
            str(row.artifact_sha256),
        )
        groups.setdefault(key, []).append(row)

    scope_start_date = min(row.event_time[:10] for row in complete_rows)
    scope_rows = [row for row in rows if row.event_time[:10] >= scope_start_date]
    scope_complete_rows = [
        row
        for row in scope_rows
        if row.training_run_id and row.artifact_id and row.artifact_sha256
    ]
    decision_groups: dict[tuple[str, str, str], list[ShadowRow]] = {}
    for row in scope_complete_rows:
        decision_groups.setdefault(
            (row.signal_id, row.symbol, row.event_time),
            [],
        ).append(row)
    ambiguous_decision_keys = {
        key
        for key, decision_rows in decision_groups.items()
        if len(
            {
                (
                    str(row.training_run_id),
                    str(row.artifact_id),
                    str(row.artifact_sha256),
                )
                for row in decision_rows
            }
        )
        > 1
    }
    selected_rows = sorted(
        [
            row
            for row in scope_complete_rows
            if (row.signal_id, row.symbol, row.event_time)
            not in ambiguous_decision_keys
        ],
        key=lambda row: (row.event_time, row.symbol, row.signal_id),
    )
    selected_keys = {
        (
            str(row.training_run_id),
            str(row.artifact_id),
            str(row.artifact_sha256),
        )
        for row in selected_rows
    }
    date_lineages: dict[str, set[tuple[str, str, str]]] = {}
    for row in selected_rows:
        date_lineages.setdefault(row.event_time[:10], set()).add(
            (
                str(row.training_run_id),
                str(row.artifact_id),
                str(row.artifact_sha256),
            )
        )

    blockers: list[str] = []
    scope_missing_rows = len(scope_rows) - len(scope_complete_rows)
    if scope_missing_rows:
        blockers.append("prediction_lineage_missing_inside_forward_scope")
    if ambiguous_decision_keys:
        blockers.append("multiple_lineages_for_same_decision")
    if any(len(keys) > 1 for keys in date_lineages.values()):
        blockers.append("multiple_lineages_same_trade_date")

    lineage_chain: list[dict[str, Any]] = []
    for key in sorted(
        selected_keys,
        key=lambda item: min(row.event_time for row in groups[item]),
    ):
        lineage_rows = sorted(
            groups[key],
            key=lambda row: (row.event_time, row.symbol, row.signal_id),
        )
        completed_at = training_run_completed_at.get(key[0])
        temporal_order_ok = False
        if completed_at:
            try:
                temporal_order_ok = datetime.fromisoformat(
                    completed_at
                ) < datetime.fromisoformat(lineage_rows[0].event_time)
            except ValueError:
                temporal_order_ok = False
        if not completed_at:
            blockers.append("training_run_registry_missing")
        elif not temporal_order_ok:
            blockers.append("training_completed_after_prediction_start")
        lineage_chain.append(
            {
                "training_run_id": key[0],
                "artifact_id": key[1],
                "artifact_sha256": key[2],
                "training_completed_at": completed_at,
                "temporal_order_ok": temporal_order_ok,
                "rows": len(lineage_rows),
                "start": lineage_rows[0].event_time if lineage_rows else None,
                "end": lineage_rows[-1].event_time if lineage_rows else None,
            }
        )

    blockers = sorted(set(blockers))
    candidate_eligible = not blockers
    selected_lineage = lineage_chain[0] if len(lineage_chain) == 1 else None
    return (
        selected_rows,
        {
            "status": (
                "validated_temporal_lineage_chain"
                if candidate_eligible
                else "temporal_lineage_chain_incomplete"
            ),
            "candidate_eligible": candidate_eligible,
            "blockers": blockers,
            "total_rows": len(rows),
            "complete_rows": len(complete_rows),
            "missing_rows": len(rows) - len(complete_rows),
            "distinct_complete_lineages": len(groups),
            "scope_start_date": scope_start_date,
            "scope_rows": len(scope_rows),
            "scope_missing_rows": scope_missing_rows,
            "legacy_rows_before_scope": len(rows) - len(scope_rows),
            "ambiguous_decision_rows": len(ambiguous_decision_keys),
            "trade_dates": len(date_lineages),
            "training_registry_available": bool(training_run_completed_at),
            "selected_lineage": selected_lineage,
            "lineage_chain": lineage_chain,
            "excluded_rows": len(rows) - len(selected_rows),
        },
        selected_keys,
    )


def _load_training_run_completion(
    connection: sqlite3.Connection,
) -> dict[str, str]:
    columns = _table_columns(connection, "ml_training_runs")
    if not {"training_run_id", "completed_at"}.issubset(columns):
        return {}
    return {
        str(training_run_id): str(completed_at)
        for training_run_id, completed_at in connection.execute(
            "SELECT training_run_id, completed_at FROM ml_training_runs"
        )
        if training_run_id and completed_at
    }


def _choose_label_threshold(connection: sqlite3.Connection, horizon_min: int) -> float | None:
    row = connection.execute(
        """
        SELECT threshold_pct, COUNT(1) AS row_count
        FROM feature_labels
        WHERE horizon_min = ?
          AND future_return_pct IS NOT NULL
        GROUP BY threshold_pct
        ORDER BY row_count DESC, threshold_pct ASC
        LIMIT 1
        """,
        (horizon_min,),
    ).fetchone()
    return float(row[0]) if row else None


def _load_rows(connection: sqlite3.Connection, horizon_min: int, label_threshold_pct: float) -> list[ShadowRow]:
    prediction_columns = _table_columns(connection, "serving_predictions")
    has_lineage = {
        "training_run_id",
        "artifact_id",
        "artifact_sha256",
    }.issubset(prediction_columns)
    lineage_select = (
        "training_run_id, artifact_id, artifact_sha256"
        if has_lineage
        else "NULL, NULL, NULL"
    )
    signal_rows = connection.execute(
        """
        SELECT signal_id, symbol, event_time, confidence
        FROM serving_trade_signals
        WHERE side = 'buy'
          AND allowed = 1
        ORDER BY event_time ASC, symbol ASC, signal_id ASC
        """
    ).fetchall()
    prediction_rows = connection.execute(
        f"""
        SELECT
            symbol,
            event_time,
            probability_up,
            probability_flat,
            probability_down,
            {lineage_select}
        FROM serving_predictions
        WHERE horizon_min = ?
          AND model_version = ?
        ORDER BY symbol ASC, event_time ASC, prediction_id ASC
        """,
        (horizon_min, f"lightgbm-h{horizon_min}-v1"),
    ).fetchall()
    label_rows = connection.execute(
        """
        SELECT symbol, event_time, label, future_return_pct
        FROM feature_labels
        WHERE horizon_min = ?
          AND ABS(threshold_pct - ?) < 0.000000001
          AND future_return_pct IS NOT NULL
        """,
        (horizon_min, label_threshold_pct),
    ).fetchall()

    predictions_by_key: dict[tuple[str, str], list[tuple[Any, ...]]] = {}
    for row in prediction_rows:
        predictions_by_key.setdefault((str(row[0]), str(row[1])), []).append(tuple(row))
    labels_by_key = {
        (str(row[0]), str(row[1])): (str(row[2]), float(row[3]))
        for row in label_rows
        if _to_float(row[3]) is not None
    }

    result: list[ShadowRow] = []
    for signal_id, symbol_value, event_time_value, confidence in signal_rows:
        symbol = str(symbol_value)
        event_time = str(event_time_value)
        label_row = labels_by_key.get((symbol, event_time))
        if label_row is None:
            continue
        label, future_return = label_row
        for prediction_row in predictions_by_key.get((symbol, event_time), []):
            result.append(
                ShadowRow(
                    signal_id=str(signal_id),
                    symbol=symbol,
                    event_time=event_time,
                    signal_confidence=_to_float(confidence),
                    probability_up=_to_float(prediction_row[2]),
                    probability_flat=_to_float(prediction_row[3]),
                    probability_down=_to_float(prediction_row[4]),
                    label=label,
                    future_return_pct=future_return,
                    training_run_id=(
                        str(prediction_row[5])
                        if prediction_row[5] is not None
                        else None
                    ),
                    artifact_id=(
                        str(prediction_row[6])
                        if prediction_row[6] is not None
                        else None
                    ),
                    artifact_sha256=(
                        str(prediction_row[7])
                        if prediction_row[7] is not None
                        else None
                    ),
                )
            )
    return result

def _load_closed_lots(connection: sqlite3.Connection) -> list[ClosedLot]:
    rows = connection.execute(
        """
        SELECT
            o.symbol,
            o.side,
            f.event_time,
            f.fill_qty,
            f.fill_price,
            f.fill_id
        FROM paper_fills AS f
        JOIN paper_orders AS o
          ON o.order_id = f.order_id
        WHERE f.fill_qty > 0
          AND f.fill_price IS NOT NULL
        ORDER BY f.event_time ASC, f.fill_id ASC
        """
    ).fetchall()
    open_lots: dict[str, list[dict[str, Any]]] = {}
    closed: list[ClosedLot] = []
    for symbol, side, event_time, qty_raw, price_raw, _fill_id in rows:
        qty = _to_float(qty_raw)
        price = _to_float(price_raw)
        if qty is None or price is None or qty <= 0 or price <= 0:
            continue
        symbol = str(symbol)
        if side == "buy":
            open_lots.setdefault(symbol, []).append(
                {
                    "qty": qty,
                    "entry_time": str(event_time),
                    "entry_price": price,
                }
            )
            continue
        if side != "sell":
            continue
        remaining = qty
        lots = open_lots.setdefault(symbol, [])
        while remaining > 0 and lots:
            lot = lots[0]
            consume = min(float(lot["qty"]), remaining)
            closed.append(
                ClosedLot(
                    symbol=symbol,
                    qty=consume,
                    entry_time=str(lot["entry_time"]),
                    entry_price=float(lot["entry_price"]),
                    exit_time=str(event_time),
                    exit_price=price,
                )
            )
            lot["qty"] = float(lot["qty"]) - consume
            remaining -= consume
            if lot["qty"] <= 0:
                lots.pop(0)
    return closed


def _load_prediction_prices(
    connection: sqlite3.Connection,
    horizon_min: int,
    *,
    bars_by_symbol: dict[str, list[ReplayBar]],
    lineage_keys: set[tuple[str, str, str]] | None = None,
) -> dict[str, list[PredictionPrice]]:
    prediction_columns = _table_columns(connection, "serving_predictions")
    has_lineage = {
        "training_run_id",
        "artifact_id",
        "artifact_sha256",
    }.issubset(prediction_columns)
    lineage_select = (
        "p.training_run_id, p.artifact_id, p.artifact_sha256"
        if has_lineage
        else "NULL, NULL, NULL"
    )
    rows = connection.execute(
        f"""
        SELECT
            p.symbol,
            p.event_time,
            p.probability_up,
            p.probability_flat,
            p.probability_down,
            {lineage_select}
        FROM serving_predictions AS p
        WHERE p.horizon_min = ?
          AND p.model_version = ?
        ORDER BY p.symbol ASC, p.event_time ASC
        """,
        (horizon_min, f"lightgbm-h{horizon_min}-v1"),
    ).fetchall()

    bar_times_by_symbol = {
        symbol: [bar.bar_time for bar in bars]
        for symbol, bars in bars_by_symbol.items()
    }
    by_symbol: dict[str, list[PredictionPrice]] = {}
    for row in rows:
        if lineage_keys is not None:
            row_lineage = (
                str(row[5]) if row[5] is not None else "",
                str(row[6]) if row[6] is not None else "",
                str(row[7]) if row[7] is not None else "",
            )
            if row_lineage not in lineage_keys:
                continue
        symbol = str(row[0])
        event_time = str(row[1])
        event_dt = datetime.fromisoformat(event_time)
        symbol_bars = bars_by_symbol.get(symbol, [])
        bar_times = bar_times_by_symbol.get(symbol, [])
        index = bisect_right(bar_times, event_dt)
        executable_bar = symbol_bars[index] if index < len(symbol_bars) else None
        if executable_bar is not None and executable_bar.bar_time.date() != event_dt.date():
            executable_bar = None
        by_symbol.setdefault(symbol, []).append(
            PredictionPrice(
                symbol=symbol,
                event_time=event_time,
                probability_up=_to_float(row[2]),
                probability_flat=_to_float(row[3]),
                probability_down=_to_float(row[4]),
                executable_time=(
                    executable_bar.bar_time.isoformat()
                    if executable_bar is not None
                    else None
                ),
                executable_price=(
                    executable_bar.open_price
                    if executable_bar is not None
                    else None
                ),
            )
        )
    return by_symbol

def _load_replay_bars(
    connection: sqlite3.Connection,
    rows: list[ShadowRow],
) -> dict[str, list[ReplayBar]]:
    if not rows:
        return {}
    symbols = sorted({row.symbol for row in rows})
    placeholders = ",".join("?" for _ in symbols)
    start_date = min(row.event_time[:10] for row in rows)
    end_date = max(row.event_time[:10] for row in rows)
    start_at = f"{start_date}T00:00:00"
    end_before = f"{(date.fromisoformat(end_date) + timedelta(days=1)).isoformat()}T00:00:00"
    loaded = connection.execute(
        f"""
        SELECT symbol, bar_time, open, close
        FROM curated_minute_bars
        WHERE symbol IN ({placeholders})
          AND bar_time >= ?
          AND bar_time < ?
        ORDER BY symbol ASC, bar_time ASC
        """,
        tuple([*symbols, start_at, end_before]),
    ).fetchall()
    by_symbol: dict[str, list[ReplayBar]] = {}
    for symbol, bar_time, open_price, close_price in loaded:
        parsed_open = _to_float(open_price)
        parsed_close = _to_float(close_price)
        if parsed_open is None or parsed_close is None:
            continue
        by_symbol.setdefault(str(symbol), []).append(
            ReplayBar(
                symbol=str(symbol),
                bar_time=datetime.fromisoformat(str(bar_time)),
                open_price=parsed_open,
                close_price=parsed_close,
            )
        )
    return by_symbol


def _max_drawdown_pct(returns: Iterable[float]) -> float:
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in returns:
        cumulative += value
        if cumulative > peak:
            peak = cumulative
        drawdown = peak - cumulative
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    return max_drawdown


def _max_loss_streak(returns: Iterable[float]) -> int:
    current = 0
    worst = 0
    for value in returns:
        if value < 0:
            current += 1
            worst = max(worst, current)
        else:
            current = 0
    return worst


def _return_summary(values: list[float]) -> dict[str, Any]:
    total = sum(values)
    drawdown_points = _max_drawdown_pct(values)
    if not values:
        return {
            "trades": 0,
            "signal_rows": 0,
            "win_rate": None,
            "loss_trades": 0,
            "average_net_return_pct": None,
            "sum_net_return_pct_points": 0.0,
            "max_drawdown_pct_points": 0.0,
            "max_loss_streak": 0,
            "return_aggregation": "sum_of_overlapping_signal_pct_points_not_account_return",
            "cumulative_net_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "legacy_aliases_deprecated": True,
        }
    wins = sum(1 for value in values if value > 0)
    losses = sum(1 for value in values if value < 0)
    return {
        "trades": len(values),
        "signal_rows": len(values),
        "win_rate": wins / len(values),
        "loss_trades": losses,
        "average_net_return_pct": total / len(values),
        "sum_net_return_pct_points": total,
        "max_drawdown_pct_points": drawdown_points,
        "max_loss_streak": _max_loss_streak(values),
        "return_aggregation": "sum_of_overlapping_signal_pct_points_not_account_return",
        "cumulative_net_return_pct": total,
        "max_drawdown_pct": drawdown_points,
        "legacy_aliases_deprecated": True,
    }


def _is_defensive_skip(row: ShadowRow, threshold: float, require_down_argmax: bool) -> bool:
    if row.probability_down is None:
        return False
    if row.probability_down < threshold:
        return False
    if require_down_argmax and not row.down_is_argmax:
        return False
    return True


def _is_defensive_exit(row: PredictionPrice, threshold: float, require_down_argmax: bool) -> bool:
    if row.executable_price is None or row.executable_time is None or row.probability_down is None:
        return False
    if row.probability_down < threshold:
        return False
    if require_down_argmax and not row.down_is_argmax:
        return False
    return True


def _threshold_summary(
    rows: list[ShadowRow],
    *,
    threshold: float,
    trade_cost_pct: float,
    require_down_argmax: bool,
) -> dict[str, Any]:
    baseline_returns = [row.future_return_pct - trade_cost_pct for row in rows]
    skipped_rows: list[ShadowRow] = []
    kept_rows: list[ShadowRow] = []
    for row in rows:
        if _is_defensive_skip(row, threshold, require_down_argmax):
            skipped_rows.append(row)
        else:
            kept_rows.append(row)
    skipped_returns = [row.future_return_pct - trade_cost_pct for row in skipped_rows]
    kept_returns = [row.future_return_pct - trade_cost_pct for row in kept_rows]
    skipped_net = sum(skipped_returns)
    skipped_loss_pct = -sum(value for value in skipped_returns if value < 0)
    missed_gain_pct = sum(value for value in skipped_returns if value > 0)
    baseline = _return_summary(baseline_returns)
    filtered = _return_summary(kept_returns)
    delta_net = filtered["sum_net_return_pct_points"] - baseline["sum_net_return_pct_points"]
    drawdown_reduction = baseline["max_drawdown_pct_points"] - filtered["max_drawdown_pct_points"]
    # Same-coverage random-skip control.  See docs/Buy-Avoid-Random-Control-Methodology.md:
    # a positive delta alone is NOT evidence of selectivity when the baseline
    # mean is negative, so every threshold must also be scored against a
    # random skip of identical size.
    random_control = random_control_report(
        baseline_returns,
        len(skipped_rows),
        skipped_net,
    )
    return {
        "threshold": threshold,
        "require_down_argmax": require_down_argmax,
        "baseline": baseline,
        "filtered": filtered,
        "random_control": random_control,
        "skipped": {
            "signals": len(skipped_rows),
            "coverage_rate": len(skipped_rows) / len(rows) if rows else 0.0,
            "loss_trades": sum(1 for value in skipped_returns if value < 0),
            "win_trades": sum(1 for value in skipped_returns if value > 0),
            "average_net_return_pct": (skipped_net / len(skipped_returns)) if skipped_returns else None,
            "sum_net_return_pct_points": skipped_net,
            "cumulative_net_return_pct": skipped_net,
            "legacy_alias_deprecated": True,
            "avoided_loss_pct": skipped_loss_pct,
            "missed_gain_pct": missed_gain_pct,
        },
        "delta": {
            "net_return_pct": delta_net,
            "drawdown_reduction_pct": drawdown_reduction,
            "loss_trade_reduction": baseline["loss_trades"] - filtered["loss_trades"],
            "trade_reduction": baseline["trades"] - filtered["trades"],
        },
    }


def _portfolio_threshold_summary(
    rows: list[ShadowRow],
    bars_by_symbol: dict[str, list[ReplayBar]],
    *,
    threshold: float,
    require_down_argmax: bool,
    horizon_min: int,
    forced_flat_time: time,
    initial_cash: float,
    max_position_pct: float,
    max_open_positions: int,
    slippage_bps: float,
    random_simulations: int,
) -> dict[str, Any]:
    points = [
        DecisionPoint(
            decision_id=row.signal_id,
            symbol=row.symbol,
            event_time=datetime.fromisoformat(row.event_time),
            avoid=_is_defensive_skip(row, threshold, require_down_argmax),
        )
        for row in rows
    ]
    episodes = group_decision_episodes(points)
    executable, execution_diagnostics = build_executable_decisions(
        episodes,
        bars_by_symbol,
        horizon_min=horizon_min,
        forced_flat_time=forced_flat_time,
    )
    replay_kwargs: dict[str, object] = {
        "initial_cash": initial_cash,
        "max_position_pct": max_position_pct,
        "max_open_positions": max_open_positions,
        "slippage_bps": slippage_bps,
    }
    baseline = replay_long_only(
        executable,
        respect_decision_avoid=False,
        **replay_kwargs,
    )
    policy = replay_long_only(
        executable,
        respect_decision_avoid=True,
        **replay_kwargs,
    )
    veto_count = sum(1 for decision in executable if decision.avoid)
    delta_return = (
        float(policy["portfolio_return_pct"])
        - float(baseline["portfolio_return_pct"])
    )
    failed_reasons: list[str] = []
    if len(episodes) < MIN_CANDIDATE_EPISODES:
        failed_reasons.append("insufficient_decision_episodes")
    if int(policy["counters"]["trades_executed"]) < MIN_CANDIDATE_EPISODES:
        failed_reasons.append("insufficient_executed_trades")
    if int(policy["trading_days"]) < MIN_CANDIDATE_DAYS:
        failed_reasons.append("insufficient_trading_days")
    if float(policy["nonnegative_day_share"]) < MIN_NONNEGATIVE_DAY_SHARE:
        failed_reasons.append("day_consistency_failed")
    if float(policy["portfolio_return_pct"]) <= 0:
        failed_reasons.append("absolute_portfolio_return_not_positive")
    if float(policy["average_trade_net_return_pct"]) <= 0:
        failed_reasons.append("average_trade_expectancy_not_positive")
    if delta_return <= 0:
        failed_reasons.append("baseline_delta_not_positive")

    if failed_reasons:
        random_control = {
            "status": "not_run_basic_profitability_failed",
            "passed": False,
            "population_episodes": len(executable),
            "veto_count": veto_count,
            "simulations_requested": random_simulations,
            "seed": DEFAULT_PORTFOLIO_RANDOM_SEED,
            "reason": "random control runs only after sample, absolute profit, expectancy, day consistency, and baseline delta gates pass",
        }
    else:
        random_control = portfolio_random_control(
            executable,
            actual_policy_return_pct=float(policy["portfolio_return_pct"]),
            veto_count=veto_count,
            simulations=random_simulations,
            seed=DEFAULT_PORTFOLIO_RANDOM_SEED,
            replay_kwargs=replay_kwargs,
        )
        if not bool(random_control.get("passed")):
            failed_reasons.append("portfolio_random_control_failed")

    return {
        "status": "candidate" if not failed_reasons else "rejected",
        "decision_rows": len(rows),
        "decision_episodes": len(episodes),
        "executable_episodes": len(executable),
        "execution_diagnostics": execution_diagnostics,
        "baseline": baseline,
        "policy": policy,
        "delta_portfolio_return_pct": delta_return,
        "portfolio_random_control": random_control,
        "candidate_eligibility": {
            "passed": not failed_reasons,
            "failed_reasons": failed_reasons,
            "minimum_decision_episodes": MIN_CANDIDATE_EPISODES,
            "minimum_trading_days": MIN_CANDIDATE_DAYS,
            "minimum_nonnegative_day_share": MIN_NONNEGATIVE_DAY_SHARE,
        },
    }


def _early_exit_threshold_summary(
    closed_lots: list[ClosedLot],
    predictions_by_symbol: dict[str, list[PredictionPrice]],
    *,
    threshold: float,
    trade_cost_pct: float,
    require_down_argmax: bool,
) -> dict[str, Any]:
    eligible_lots = 0
    early_exit_lots = 0
    actual_returns: list[float] = []
    early_returns: list[float] = []
    actual_net_cash = 0.0
    early_net_cash = 0.0
    gross_notional = 0.0
    for lot in closed_lots:
        if lot.entry_price <= 0 or lot.qty <= 0:
            continue
        predictions = predictions_by_symbol.get(lot.symbol, [])
        in_lot_window = [
            row
            for row in predictions
            if lot.entry_time < row.event_time < lot.exit_time
            and row.executable_time is not None
            and row.executable_time < lot.exit_time
            and row.executable_price is not None
        ]
        if not in_lot_window:
            continue
        eligible_lots += 1
        first_exit = next(
            (row for row in in_lot_window if _is_defensive_exit(row, threshold, require_down_argmax)),
            None,
        )
        actual_return = ((lot.exit_price - lot.entry_price) / lot.entry_price * 100.0) - trade_cost_pct
        actual_returns.append(actual_return)
        notional = lot.entry_price * lot.qty
        gross_notional += notional
        actual_net_cash += ((lot.exit_price - lot.entry_price) * lot.qty) - (notional * trade_cost_pct / 100.0)
        if first_exit is None or first_exit.executable_price is None:
            early_returns.append(actual_return)
            early_net_cash += ((lot.exit_price - lot.entry_price) * lot.qty) - (notional * trade_cost_pct / 100.0)
            continue
        early_exit_lots += 1
        early_return = ((first_exit.executable_price - lot.entry_price) / lot.entry_price * 100.0) - trade_cost_pct
        early_returns.append(early_return)
        early_net_cash += ((first_exit.executable_price - lot.entry_price) * lot.qty) - (notional * trade_cost_pct / 100.0)
    actual = _return_summary(actual_returns)
    early = _return_summary(early_returns)
    return {
        "threshold": threshold,
        "require_down_argmax": require_down_argmax,
        "closed_lots_with_lightgbm_window": eligible_lots,
        "early_exit_lots": early_exit_lots,
        "early_exit_rate": early_exit_lots / eligible_lots if eligible_lots else 0.0,
        "execution_price_basis": "next_minute_open_after_completed_prediction_bar",
        "actual": actual,
        "early_exit_shadow": early,
        "delta": {
            "net_return_pct_points": early["sum_net_return_pct_points"] - actual["sum_net_return_pct_points"],
            "net_return_pct": early["sum_net_return_pct_points"] - actual["sum_net_return_pct_points"],
            "drawdown_reduction_pct_points": actual["max_drawdown_pct_points"] - early["max_drawdown_pct_points"],
            "drawdown_reduction_pct": actual["max_drawdown_pct_points"] - early["max_drawdown_pct_points"],
            "loss_trade_reduction": actual["loss_trades"] - early["loss_trades"],
            "net_cash": early_net_cash - actual_net_cash,
            "actual_net_cash": actual_net_cash,
            "early_exit_net_cash": early_net_cash,
            "gross_entry_notional": gross_notional,
        },
    }


def build_summary(
    *,
    database_path: Path,
    diagnostics_path: Path,
    horizon_min: int,
    thresholds: list[float],
    require_down_argmax: bool,
    start_date: str | None = None,
    end_date: str | None = None,
    evaluate_early_exit: bool = True,
    portfolio_initial_cash: float = 25_000_000.0,
    portfolio_max_position_pct: float = 0.08,
    portfolio_max_open_positions: int = 5,
    portfolio_slippage_bps: float = 3.0,
    forced_flat_time: time = time(15, 20),
    random_simulations: int = DEFAULT_RANDOM_SIMULATIONS,
) -> dict[str, Any]:
    cost_model = _trade_cost_context(diagnostics_path)
    trade_cost_pct = float(cost_model["round_trip_cost_pct"])
    _validate_date_range(start_date, end_date)
    with _connect_readonly(database_path) as connection:
        label_threshold_pct = _choose_label_threshold(connection, horizon_min)
        loaded_rows = (
            _load_rows(connection, horizon_min, label_threshold_pct)
            if label_threshold_pct is not None
            else []
        )
        window_rows = _filter_shadow_rows_by_date(
            loaded_rows,
            start_date=start_date,
            end_date=end_date,
        )
        training_run_completed_at = _load_training_run_completion(connection)
        rows, lineage_summary, lineage_keys = _select_lineage_segment(
            window_rows, training_run_completed_at
        )
        loaded_closed_lots = _load_closed_lots(connection) if evaluate_early_exit else []
        closed_lots = _filter_closed_lots_by_date(
            loaded_closed_lots,
            start_date=start_date,
            end_date=end_date,
        )
        bars_by_symbol = (
            _load_replay_bars(connection, rows)
            if _table_columns(connection, "curated_minute_bars")
            else {}
        )
        predictions_by_symbol = (
            _load_prediction_prices(
                connection,
                horizon_min,
                bars_by_symbol=bars_by_symbol,
                lineage_keys=lineage_keys,
            )
            if evaluate_early_exit
            else {}
        )

    threshold_summaries: list[dict[str, Any]] = []
    for threshold in thresholds:
        item = _threshold_summary(
            rows,
            threshold=threshold,
            trade_cost_pct=trade_cost_pct,
            require_down_argmax=require_down_argmax,
        )
        item["portfolio_replay"] = _portfolio_threshold_summary(
            rows,
            bars_by_symbol,
            threshold=threshold,
            require_down_argmax=require_down_argmax,
            horizon_min=horizon_min,
            forced_flat_time=forced_flat_time,
            initial_cash=portfolio_initial_cash,
            max_position_pct=portfolio_max_position_pct,
            max_open_positions=portfolio_max_open_positions,
            slippage_bps=portfolio_slippage_bps,
            random_simulations=random_simulations,
        )
        eligibility = item["portfolio_replay"]["candidate_eligibility"]
        failed_reasons = list(eligibility.get("failed_reasons", []))
        verdict = (
            (item.get("random_control") or {})
            .get("comparison", {})
            .get("verdict")
        )
        if verdict != VERDICT_BETTER:
            failed_reasons.append("signal_row_random_control_failed")
        if not bool(lineage_summary.get("candidate_eligible")):
            failed_reasons.append("prediction_lineage_incomplete")
        eligibility["failed_reasons"] = sorted(set(failed_reasons))
        eligibility["passed"] = not eligibility["failed_reasons"]
        item["portfolio_replay"]["status"] = (
            "candidate" if eligibility["passed"] else "rejected"
        )
        threshold_summaries.append(item)

    early_exit_summaries = [
        _early_exit_threshold_summary(
            closed_lots,
            predictions_by_symbol,
            threshold=threshold,
            trade_cost_pct=trade_cost_pct,
            require_down_argmax=require_down_argmax,
        )
        for threshold in thresholds
    ]
    best_by_net = max(
        threshold_summaries,
        key=lambda item: item["delta"]["net_return_pct"],
        default=None,
    )
    best_by_drawdown = max(
        threshold_summaries,
        key=lambda item: item["delta"]["drawdown_reduction_pct"],
        default=None,
    )
    best_early_exit_by_net = max(
        early_exit_summaries,
        key=lambda item: item["delta"]["net_return_pct_points"],
        default=None,
    )
    best_early_exit_by_cash = max(
        early_exit_summaries,
        key=lambda item: item["delta"]["net_cash"],
        default=None,
    )
    candidate_thresholds = [
        item
        for item in threshold_summaries
        if bool(
            item.get("portfolio_replay", {})
            .get("candidate_eligibility", {})
            .get("passed")
        )
    ]
    if not rows:
        status = "no_joined_baseline_lightgbm_rows"
    elif not bool(lineage_summary.get("candidate_eligible")):
        status = "diagnostic_only_lineage_missing"
    elif candidate_thresholds:
        status = "portfolio_candidate_found"
    elif any(
        "portfolio_random_control_failed"
        in (
            item.get("portfolio_replay", {})
            .get("candidate_eligibility", {})
            .get("failed_reasons", [])
        )
        for item in threshold_summaries
    ):
        status = "rejected_portfolio_random_control"
    else:
        status = "rejected_no_absolute_portfolio_profit"

    best_verdict = (
        ((best_by_net or {}).get("random_control") or {})
        .get("comparison", {})
        .get("verdict")
        if best_by_net
        else None
    )
    random_control_gate = {
        "verdict": best_verdict,
        "passed": best_verdict == VERDICT_BETTER,
        "policy": (
            "candidate status requires same-coverage signal-row random control, "
            "episode-level portfolio random control, absolute after-cost profit, "
            "day consistency, minimum sample, and complete artifact lineage"
        ),
    }
    early_exit_status = (
        "not_evaluated_for_windowed_e5"
        if not evaluate_early_exit
        else "diagnostic_only_future_validation_required"
        if closed_lots
        else "no_closed_paper_lots"
    )
    return {
        "generated_at": _now_iso(),
        "status": status,
        "horizon_min": horizon_min,
        "database_path": str(database_path),
        "diagnostics_path": str(diagnostics_path),
        "trade_cost_pct": trade_cost_pct,
        "cost_model_version": cost_model["version"],
        "cost_model": cost_model,
        "label_threshold_pct": label_threshold_pct,
        "model_version": f"lightgbm-h{horizon_min}-v1",
        "prediction_lineage": lineage_summary,
        "baseline_signal_filter": "serving_trade_signals.side='buy' AND allowed=1",
        "window_joined_rows": len(window_rows),
        "joined_rows": len(rows),
        "requested_date_range": {
            "start_date": start_date,
            "end_date": end_date,
        },
        "date_range": {
            "start": rows[0].event_time if rows else None,
            "end": rows[-1].event_time if rows else None,
        },
        "symbols": sorted({row.symbol for row in rows}),
        "metric_semantics": {
            "signal_return_metric": "sum_net_return_pct_points",
            "signal_return_is_account_return": False,
            "portfolio_return_metric": "portfolio_replay.policy.portfolio_return_pct",
            "portfolio_return_basis": "cash_and_position_constrained_account_equity",
            "legacy_cumulative_net_return_pct": "deprecated alias for overlapping signal pct-point sum",
        },
        "portfolio_parameters": {
            "initial_cash": portfolio_initial_cash,
            "max_position_pct": portfolio_max_position_pct,
            "max_open_positions": portfolio_max_open_positions,
            "slippage_bps_per_side": portfolio_slippage_bps,
            "forced_flat_time": forced_flat_time.isoformat(timespec="minutes"),
            "decision_episode_gap_seconds": 90,
            "random_simulations": random_simulations,
            "random_seed": DEFAULT_PORTFOLIO_RANDOM_SEED,
        },
        "automatic_promotion": False,
        "automatic_threshold_adoption": False,
        "automatic_order_change": False,
        "live_short_signal": False,
        "buy_avoid_shadow": {
            "thresholds": threshold_summaries,
            "diagnostic_best_by_signal_sum_delta": best_by_net,
            "best_by_net_delta": best_by_net,
            "best_by_drawdown_reduction": best_by_drawdown,
            "random_control_gate": random_control_gate,
            "candidate_thresholds": [
                item.get("threshold") for item in candidate_thresholds
            ],
        },
        "early_exit_shadow": {
            "status": early_exit_status,
            "candidate_eligible": False,
            "future_only_validation_required": True,
            "closed_lots_total_before_date_filter": len(loaded_closed_lots),
            "closed_lots_total": len(closed_lots),
            "evaluated_date_range": {
                "start_date": start_date,
                "end_date": end_date,
            },
            "thresholds": early_exit_summaries,
            "diagnostic_best_by_net_delta": best_early_exit_by_net,
            "diagnostic_best_by_cash_delta": best_early_exit_by_cash,
            "best_by_net_delta": best_early_exit_by_net,
            "best_by_cash_delta": best_early_exit_by_cash,
            "limitations": [
                "uses the first next-minute open after a completed LightGBM downside prediction",
                "threshold results are diagnostic and require a pre-registered future window",
                "does not model broker queue, partial fill, order type, or tick-level bid/ask",
            ],
        },
        "interpretation": {
            "summary": (
                "LightGBM downside probability is evaluated as a defensive filter, "
                "but only the constrained portfolio replay can support profitability."
            ),
            "not_a_model_promotion": True,
            "not_a_live_order_change": True,
            "uses_closed_horizon_labels": True,
        },
    }


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(_fmt(value) for value in row) + " |")
    return "\n".join(lines)


def render_markdown(summary: dict[str, Any]) -> str:
    threshold_rows: list[list[Any]] = []
    random_control_rows: list[list[Any]] = []
    portfolio_rows: list[list[Any]] = []
    for item in summary.get("buy_avoid_shadow", {}).get("thresholds", []):
        baseline = item.get("baseline", {})
        filtered = item.get("filtered", {})
        skipped = item.get("skipped", {})
        delta = item.get("delta", {})
        threshold_rows.append(
            [
                item.get("threshold"),
                baseline.get("signal_rows"),
                skipped.get("signals"),
                skipped.get("coverage_rate"),
                baseline.get("sum_net_return_pct_points"),
                filtered.get("sum_net_return_pct_points"),
                delta.get("net_return_pct"),
            ]
        )
        control = item.get("random_control") or {}
        comparison = control.get("comparison", {})
        random_control_rows.append(
            [
                item.get("threshold"),
                control.get("n_skip"),
                control.get("actual_skipped_cumulative_net_pct"),
                control.get("analytic", {}).get("expected_random_skipped_sum_pct"),
                comparison.get("z_score"),
                comparison.get("verdict") or control.get("status"),
            ]
        )
        replay = item.get("portfolio_replay", {})
        replay_baseline = replay.get("baseline", {})
        replay_policy = replay.get("policy", {})
        portfolio_control = replay.get("portfolio_random_control", {})
        eligibility = replay.get("candidate_eligibility", {})
        portfolio_rows.append(
            [
                item.get("threshold"),
                replay.get("decision_episodes"),
                replay.get("executable_episodes"),
                replay_baseline.get("counters", {}).get("trades_executed"),
                replay_policy.get("counters", {}).get("trades_executed"),
                replay_baseline.get("portfolio_return_pct"),
                replay_policy.get("portfolio_return_pct"),
                replay.get("delta_portfolio_return_pct"),
                portfolio_control.get("verdict"),
                "pass" if eligibility.get("passed") else "reject",
            ]
        )

    early_rows: list[list[Any]] = []
    for item in summary.get("early_exit_shadow", {}).get("thresholds", []):
        actual = item.get("actual", {})
        early = item.get("early_exit_shadow", {})
        delta = item.get("delta", {})
        early_rows.append(
            [
                item.get("threshold"),
                item.get("closed_lots_with_lightgbm_window"),
                item.get("early_exit_lots"),
                actual.get("sum_net_return_pct_points"),
                early.get("sum_net_return_pct_points"),
                delta.get("net_return_pct_points"),
                delta.get("net_cash"),
            ]
        )

    best = summary.get("buy_avoid_shadow", {}).get(
        "diagnostic_best_by_signal_sum_delta"
    ) or {}
    early_best = summary.get("early_exit_shadow", {}).get(
        "diagnostic_best_by_net_delta"
    ) or {}
    gate = summary.get("buy_avoid_shadow", {}).get("random_control_gate") or {}
    lineage = summary.get("prediction_lineage") or {}
    selected_lineage = lineage.get("selected_lineage") or {}

    lines = [
        "# LightGBM Defensive Shadow Report",
        "",
        f"- generated_at: {summary.get('generated_at')}",
        f"- status: {summary.get('status')}",
        f"- horizon_min: {summary.get('horizon_min')}",
        f"- model_version: {summary.get('model_version')}",
        f"- window_joined_rows: {summary.get('window_joined_rows')}",
        f"- selected_lineage_rows: {summary.get('joined_rows')}",
        f"- date_range: {summary.get('date_range', {}).get('start')} ~ {summary.get('date_range', {}).get('end')}",
        f"- trade_cost_pct: {summary.get('trade_cost_pct')}",
        f"- cost_model_version: {summary.get('cost_model_version')}",
        f"- portfolio_random_control_simulations: {summary.get('portfolio_parameters', {}).get('random_simulations')}",
        f"- portfolio_random_control_seed: {summary.get('portfolio_parameters', {}).get('random_seed')}",
        "- automatic_promotion: false",
        "- automatic_threshold_adoption: false",
        "- automatic_order_change: false",
        "",
        "## Prediction Lineage",
        "",
        f"- status: {lineage.get('status')}",
        f"- candidate_eligible: {lineage.get('candidate_eligible')}",
        f"- complete_rows: {lineage.get('complete_rows')}",
        f"- missing_rows: {lineage.get('missing_rows')}",
        f"- distinct_complete_lineages: {lineage.get('distinct_complete_lineages')}",
        f"- selected_training_run_id: {selected_lineage.get('training_run_id')}",
        f"- selected_artifact_id: {selected_lineage.get('artifact_id')}",
        "",
        "## Signal-Row Diagnostic",
        "",
        "아래 합계는 서로 겹치는 분 단위 신호 수익률 포인트의 합이며 계좌 수익률이 아니다.",
        "",
        _markdown_table(
            [
                "down_threshold",
                "signal_rows",
                "skipped_rows",
                "skip_rate",
                "baseline_sum_pct_points",
                "filtered_sum_pct_points",
                "delta_pct_points",
            ],
            threshold_rows,
        )
        if threshold_rows
        else "No joined rows.",
        "",
        "## Same-Coverage Signal Random Control",
        "",
        _markdown_table(
            [
                "down_threshold",
                "n_skip",
                "actual_skipped_sum_points",
                "random_expected_sum_points",
                "z_score",
                "verdict",
            ],
            random_control_rows,
        )
        if random_control_rows
        else "No rows.",
        "",
        f"- random_control_gate.passed: {gate.get('passed')}",
        f"- random_control_gate.verdict: {gate.get('verdict')}",
        "",
        "## Decision-Episode Portfolio Replay",
        "",
        "반복 분 신호를 의사결정 구간으로 묶고 다음 분봉 시가, 현금, 비중, 최대 보유 수, "
        "종목 중복, 수수료, 세금, 슬리피지, 장마감 청산을 반영한다.",
        "",
        _markdown_table(
            [
                "down_threshold",
                "episodes",
                "executable",
                "baseline_trades",
                "policy_trades",
                "baseline_return_pct",
                "policy_return_pct",
                "delta_return_pct",
                "random_verdict",
                "eligibility",
            ],
            portfolio_rows,
        )
        if portfolio_rows
        else "No executable decision episodes.",
        "",
        f"- candidate_thresholds: {summary.get('buy_avoid_shadow', {}).get('candidate_thresholds')}",
        "",
        "## Diagnostic Best Signal Delta",
        "",
        f"- threshold: {best.get('threshold')}",
        f"- delta_sum_pct_points: {_fmt((best.get('delta') or {}).get('net_return_pct'))}",
        "- 이 항목은 진단 정렬값일 뿐 후보 판정값이 아니다.",
        "",
        "## Early-Exit Diagnostic",
        "",
        f"- status: {summary.get('early_exit_shadow', {}).get('status')}",
        f"- candidate_eligible: {summary.get('early_exit_shadow', {}).get('candidate_eligible')}",
        f"- closed_lots_total: {summary.get('early_exit_shadow', {}).get('closed_lots_total')}",
        "- 체결가는 예측이 완성된 다음 분봉의 시가를 사용한다.",
        "- 같은 bar close를 쓴 과거 early-exit 결과와 직접 비교하지 않는다.",
        "- threshold는 미래 구간에 사전 고정해 재검증하기 전까지 후보가 아니다.",
        "",
        _markdown_table(
            [
                "down_threshold",
                "eligible_lots",
                "early_exit_lots",
                "actual_sum_points",
                "early_sum_points",
                "delta_points",
                "delta_cash",
            ],
            early_rows,
        )
        if early_rows
        else "No early-exit rows.",
        "",
        f"- diagnostic_best_threshold: {early_best.get('threshold')}",
        f"- diagnostic_delta_cash: {_fmt((early_best.get('delta') or {}).get('net_cash'), 0)}",
        "",
        "## Interpretation",
        "",
        "- 후보 통과에는 신호 무작위 대조, 포트폴리오 무작위 대조, 비용 후 절대수익 양수, "
        "거래당 기대값 양수, 거래일 일관성, 최소 표본, 완전한 모델 계보가 모두 필요하다.",
        "- cumulative_net_return_pct는 겹치는 신호 포인트 합의 호환용 별칭이며 계좌 수익률로 사용하지 않는다.",
        "- 현재 계좌 replay 비용 정본은 2026 보통주 왕복 0.29%이며 구형 0.108% 결과와 직접 비교하지 않는다.",
        "- 실제 주문, active model, gate, threshold 정책은 바꾸지 않는다.",
        "",
        "관련 문서/코드 경로:",
        "app/services/portfolio_replay.py,",
        "scripts/summarize_lightgbm_defensive_shadow.py,",
        "runtime-data/dev.db",
    ]
    return "\n".join(lines) + "\n"


def _parse_thresholds(values: list[str] | None) -> list[float]:
    if not values:
        return list(DEFAULT_THRESHOLDS)
    thresholds: list[float] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part:
                thresholds.append(float(part))
    return sorted(set(thresholds))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-path", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--diagnostics", type=Path, default=DEFAULT_DIAGNOSTICS)
    parser.add_argument("--horizon-min", type=int, default=15)
    parser.add_argument("--threshold", action="append", dest="thresholds")
    parser.add_argument("--allow-non-argmax-down", action="store_true")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--skip-early-exit", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    settings = load_settings(REPO_ROOT)

    summary = build_summary(
        database_path=args.database_path,
        diagnostics_path=args.diagnostics,
        horizon_min=args.horizon_min,
        thresholds=_parse_thresholds(args.thresholds),
        require_down_argmax=not args.allow_non_argmax_down,
        start_date=args.start_date,
        end_date=args.end_date,
        evaluate_early_exit=not args.skip_early_exit,
        portfolio_initial_cash=settings.strategy.paper_initial_cash,
        portfolio_max_position_pct=settings.strategy.max_position_pct,
        portfolio_max_open_positions=settings.strategy.max_open_positions,
        portfolio_slippage_bps=settings.strategy.slippage_bps,
        forced_flat_time=time.fromisoformat(settings.market_calendar.forced_flat_time),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"latest-lightgbm-defensive-shadow-h{args.horizon_min}.json"
    md_path = args.output_dir / f"latest-lightgbm-defensive-shadow-h{args.horizon_min}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps({"ok": True, "json_path": str(json_path), "markdown_path": str(md_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
