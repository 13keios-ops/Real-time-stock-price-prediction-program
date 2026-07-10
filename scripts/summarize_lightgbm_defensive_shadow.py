#!/usr/bin/env python3
"""Compare baseline buy signals with LightGBM defensive buy-avoid filters.

This is a read-only paper-shadow report.  It does not change the active model,
thresholds, gates, paper orders, or live orders.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
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
DEFAULT_DATABASE = REPO_ROOT / "runtime-data" / "dev.db"
DEFAULT_DIAGNOSTICS = (
    REPO_ROOT / "runtime-data" / "reports" / "challengers" / "latest-lightgbm-performance-diagnostics-h15.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime-data" / "reports" / "challengers"
DEFAULT_THRESHOLDS = (0.40, 0.45, 0.50, 0.54, 0.58)


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
    close_price: float | None

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


def _trade_cost_pct(diagnostics_path: Path) -> float:
    data = _read_json(diagnostics_path)
    value = _to_float(data.get("trade_cost_pct"))
    return value if value is not None else 0.108


def _connect_readonly(database_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)


def _choose_label_threshold(connection: sqlite3.Connection, horizon_min: int) -> float | None:
    row = connection.execute(
        """
        SELECT fl.threshold_pct, COUNT(1) AS row_count
        FROM serving_trade_signals AS s
        JOIN serving_predictions AS p
          ON p.symbol = s.symbol
         AND p.event_time = s.event_time
         AND p.horizon_min = ?
         AND p.model_version = ?
        JOIN feature_labels AS fl
          ON fl.symbol = s.symbol
         AND fl.event_time = s.event_time
         AND fl.horizon_min = ?
        WHERE s.side = 'buy'
          AND s.allowed = 1
          AND fl.future_return_pct IS NOT NULL
        GROUP BY fl.threshold_pct
        ORDER BY row_count DESC, fl.threshold_pct ASC
        LIMIT 1
        """,
        (horizon_min, f"lightgbm-h{horizon_min}-v1", horizon_min),
    ).fetchone()
    return float(row[0]) if row else None


def _load_rows(connection: sqlite3.Connection, horizon_min: int, label_threshold_pct: float) -> list[ShadowRow]:
    rows = connection.execute(
        """
        SELECT
            s.signal_id,
            s.symbol,
            s.event_time,
            s.confidence,
            p.probability_up,
            p.probability_flat,
            p.probability_down,
            fl.label,
            fl.future_return_pct
        FROM serving_trade_signals AS s
        JOIN serving_predictions AS p
          ON p.symbol = s.symbol
         AND p.event_time = s.event_time
         AND p.horizon_min = ?
         AND p.model_version = ?
        JOIN feature_labels AS fl
          ON fl.symbol = s.symbol
         AND fl.event_time = s.event_time
         AND fl.horizon_min = ?
         AND ABS(fl.threshold_pct - ?) < 0.000000001
        WHERE s.side = 'buy'
          AND s.allowed = 1
          AND fl.future_return_pct IS NOT NULL
        ORDER BY s.event_time ASC, s.symbol ASC, s.signal_id ASC
        """,
        (horizon_min, f"lightgbm-h{horizon_min}-v1", horizon_min, label_threshold_pct),
    ).fetchall()
    result: list[ShadowRow] = []
    for row in rows:
        future_return = _to_float(row[8])
        if future_return is None:
            continue
        result.append(
            ShadowRow(
                signal_id=str(row[0]),
                symbol=str(row[1]),
                event_time=str(row[2]),
                signal_confidence=_to_float(row[3]),
                probability_up=_to_float(row[4]),
                probability_flat=_to_float(row[5]),
                probability_down=_to_float(row[6]),
                label=str(row[7]),
                future_return_pct=future_return,
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


def _load_prediction_prices(connection: sqlite3.Connection, horizon_min: int) -> dict[str, list[PredictionPrice]]:
    rows = connection.execute(
        """
        SELECT
            p.symbol,
            p.event_time,
            p.probability_up,
            p.probability_flat,
            p.probability_down,
            b.close
        FROM serving_predictions AS p
        LEFT JOIN curated_minute_bars AS b
          ON b.symbol = p.symbol
         AND b.bar_time = p.event_time
        WHERE p.horizon_min = ?
          AND p.model_version = ?
        ORDER BY p.symbol ASC, p.event_time ASC
        """,
        (horizon_min, f"lightgbm-h{horizon_min}-v1"),
    ).fetchall()
    by_symbol: dict[str, list[PredictionPrice]] = {}
    for row in rows:
        by_symbol.setdefault(str(row[0]), []).append(
            PredictionPrice(
                symbol=str(row[0]),
                event_time=str(row[1]),
                probability_up=_to_float(row[2]),
                probability_flat=_to_float(row[3]),
                probability_down=_to_float(row[4]),
                close_price=_to_float(row[5]),
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
    if not values:
        return {
            "trades": 0,
            "win_rate": None,
            "loss_trades": 0,
            "average_net_return_pct": None,
            "cumulative_net_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "max_loss_streak": 0,
        }
    wins = sum(1 for value in values if value > 0)
    losses = sum(1 for value in values if value < 0)
    return {
        "trades": len(values),
        "win_rate": wins / len(values),
        "loss_trades": losses,
        "average_net_return_pct": sum(values) / len(values),
        "cumulative_net_return_pct": sum(values),
        "max_drawdown_pct": _max_drawdown_pct(values),
        "max_loss_streak": _max_loss_streak(values),
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
    if row.close_price is None or row.probability_down is None:
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
    skipped_rows = [row for row in rows if _is_defensive_skip(row, threshold, require_down_argmax)]
    kept_rows = [row for row in rows if row not in skipped_rows]
    skipped_returns = [row.future_return_pct - trade_cost_pct for row in skipped_rows]
    kept_returns = [row.future_return_pct - trade_cost_pct for row in kept_rows]
    skipped_net = sum(skipped_returns)
    skipped_loss_pct = -sum(value for value in skipped_returns if value < 0)
    missed_gain_pct = sum(value for value in skipped_returns if value > 0)
    baseline = _return_summary(baseline_returns)
    filtered = _return_summary(kept_returns)
    delta_net = filtered["cumulative_net_return_pct"] - baseline["cumulative_net_return_pct"]
    drawdown_reduction = baseline["max_drawdown_pct"] - filtered["max_drawdown_pct"]
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
            "cumulative_net_return_pct": skipped_net,
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
            if lot.entry_time < row.event_time < lot.exit_time and row.close_price is not None
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
        if first_exit is None or first_exit.close_price is None:
            early_returns.append(actual_return)
            early_net_cash += ((lot.exit_price - lot.entry_price) * lot.qty) - (notional * trade_cost_pct / 100.0)
            continue
        early_exit_lots += 1
        early_return = ((first_exit.close_price - lot.entry_price) / lot.entry_price * 100.0) - trade_cost_pct
        early_returns.append(early_return)
        early_net_cash += ((first_exit.close_price - lot.entry_price) * lot.qty) - (notional * trade_cost_pct / 100.0)
    actual = _return_summary(actual_returns)
    early = _return_summary(early_returns)
    return {
        "threshold": threshold,
        "require_down_argmax": require_down_argmax,
        "closed_lots_with_lightgbm_window": eligible_lots,
        "early_exit_lots": early_exit_lots,
        "early_exit_rate": early_exit_lots / eligible_lots if eligible_lots else 0.0,
        "actual": actual,
        "early_exit_shadow": early,
        "delta": {
            "net_return_pct": early["cumulative_net_return_pct"] - actual["cumulative_net_return_pct"],
            "drawdown_reduction_pct": actual["max_drawdown_pct"] - early["max_drawdown_pct"],
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
) -> dict[str, Any]:
    trade_cost_pct = _trade_cost_pct(diagnostics_path)
    _validate_date_range(start_date, end_date)
    with _connect_readonly(database_path) as connection:
        label_threshold_pct = _choose_label_threshold(connection, horizon_min)
        loaded_rows = _load_rows(connection, horizon_min, label_threshold_pct) if label_threshold_pct is not None else []
        rows = _filter_shadow_rows_by_date(
            loaded_rows,
            start_date=start_date,
            end_date=end_date,
        )
        closed_lots = _load_closed_lots(connection) if evaluate_early_exit else []
        predictions_by_symbol = (
            _load_prediction_prices(connection, horizon_min)
            if evaluate_early_exit
            else {}
        )
    threshold_summaries = [
        _threshold_summary(
            rows,
            threshold=threshold,
            trade_cost_pct=trade_cost_pct,
            require_down_argmax=require_down_argmax,
        )
        for threshold in thresholds
    ]
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
    best_by_net = max(threshold_summaries, key=lambda item: item["delta"]["net_return_pct"], default=None)
    best_by_drawdown = max(threshold_summaries, key=lambda item: item["delta"]["drawdown_reduction_pct"], default=None)
    best_early_exit_by_net = max(
        early_exit_summaries,
        key=lambda item: item["delta"]["net_return_pct"],
        default=None,
    )
    best_early_exit_by_cash = max(
        early_exit_summaries,
        key=lambda item: item["delta"]["net_cash"],
        default=None,
    )
    status = "completed" if rows else "no_joined_baseline_lightgbm_rows"
    if best_by_net and best_by_net["delta"]["net_return_pct"] > 0:
        status = "buy_avoid_candidate_found"
    if best_early_exit_by_net and best_early_exit_by_net["delta"]["net_return_pct"] > 0:
        status = "defensive_shadow_candidate_found"
    # Fail-closed random-control gate (docs/Buy-Avoid-Random-Control-Methodology.md).
    # The gate is a separate field (not a change to `status`) so existing
    # consumers keep working, but any wording like "loss-reduction candidate"
    # MUST check gate.passed first.
    best_verdict = (
        ((best_by_net or {}).get("random_control") or {}).get("comparison", {}).get("verdict")
        if best_by_net
        else None
    )
    random_control_gate = {
        "verdict": best_verdict,
        "passed": best_verdict == VERDICT_BETTER,
        "policy": (
            "buy-avoid may only be described as a loss-reduction candidate if passed=true; "
            "otherwise describe it as 'random-control advantage unproven'"
        ),
    }
    return {
        "generated_at": _now_iso(),
        "status": status,
        "horizon_min": horizon_min,
        "database_path": str(database_path),
        "diagnostics_path": str(diagnostics_path),
        "trade_cost_pct": trade_cost_pct,
        "label_threshold_pct": label_threshold_pct,
        "model_version": f"lightgbm-h{horizon_min}-v1",
        "baseline_signal_filter": "serving_trade_signals.side='buy' AND allowed=1",
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
        "automatic_promotion": False,
        "automatic_threshold_adoption": False,
        "automatic_order_change": False,
        "live_short_signal": False,
        "buy_avoid_shadow": {
            "thresholds": threshold_summaries,
            "best_by_net_delta": best_by_net,
            "best_by_drawdown_reduction": best_by_drawdown,
            "random_control_gate": random_control_gate,
        },
        "early_exit_shadow": {
            "status": (
                "not_evaluated_for_windowed_e5"
                if not evaluate_early_exit
                else "evaluated_from_closed_paper_lots"
                if closed_lots
                else "no_closed_paper_lots"
            ),
            "closed_lots_total": len(closed_lots),
            "thresholds": early_exit_summaries,
            "best_by_net_delta": best_early_exit_by_net,
            "best_by_cash_delta": best_early_exit_by_cash,
            "limitations": [
                "uses first LightGBM downside timestamp inside each already-closed paper lot window",
                "uses curated_minute_bars close as hypothetical early-exit price",
                "does not model broker queue, partial fill, order type, or slippage beyond the same trade_cost_pct",
            ],
        },
        "interpretation": {
            "summary": (
                "LightGBM downside probability is tested as a defensive buy-avoid filter against baseline buy signals."
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
    threshold_rows = []
    for item in summary.get("buy_avoid_shadow", {}).get("thresholds", []):
        baseline = item["baseline"]
        filtered = item["filtered"]
        skipped = item["skipped"]
        delta = item["delta"]
        threshold_rows.append(
            [
                item.get("threshold"),
                baseline.get("trades"),
                skipped.get("signals"),
                skipped.get("coverage_rate"),
                baseline.get("cumulative_net_return_pct"),
                filtered.get("cumulative_net_return_pct"),
                delta.get("net_return_pct"),
                delta.get("drawdown_reduction_pct"),
                delta.get("loss_trade_reduction"),
                skipped.get("avoided_loss_pct"),
                skipped.get("missed_gain_pct"),
            ]
        )
    best = summary.get("buy_avoid_shadow", {}).get("best_by_net_delta") or {}
    random_control_rows = []
    for item in summary.get("buy_avoid_shadow", {}).get("thresholds", []):
        control = item.get("random_control") or {}
        if control.get("status") != "ok":
            random_control_rows.append([item.get("threshold"), control.get("status"), "", "", "", ""])
            continue
        comparison = control.get("comparison", {})
        random_control_rows.append(
            [
                item.get("threshold"),
                control.get("n_skip"),
                control.get("actual_skipped_cumulative_net_pct"),
                control.get("analytic", {}).get("expected_random_skipped_sum_pct"),
                comparison.get("z_score"),
                comparison.get("verdict"),
            ]
        )
    gate = summary.get("buy_avoid_shadow", {}).get("random_control_gate") or {}
    early_rows = []
    for item in summary.get("early_exit_shadow", {}).get("thresholds", []):
        actual = item["actual"]
        early = item["early_exit_shadow"]
        delta = item["delta"]
        early_rows.append(
            [
                item.get("threshold"),
                item.get("closed_lots_with_lightgbm_window"),
                item.get("early_exit_lots"),
                item.get("early_exit_rate"),
                actual.get("cumulative_net_return_pct"),
                early.get("cumulative_net_return_pct"),
                delta.get("net_return_pct"),
                delta.get("drawdown_reduction_pct"),
                delta.get("loss_trade_reduction"),
                delta.get("net_cash"),
            ]
        )
    early_best = summary.get("early_exit_shadow", {}).get("best_by_net_delta") or {}
    lines = [
        "# LightGBM Defensive Shadow Report",
        "",
        f"- generated_at: `{summary.get('generated_at')}`",
        f"- status: `{summary.get('status')}`",
        f"- horizon_min: `{summary.get('horizon_min')}`",
        f"- model_version: `{summary.get('model_version')}`",
        f"- joined_rows: `{summary.get('joined_rows')}`",
        f"- requested_date_range: `{summary.get('requested_date_range', {}).get('start_date')}` ~ `{summary.get('requested_date_range', {}).get('end_date')}`",
        f"- date_range: `{summary.get('date_range', {}).get('start')}` ~ `{summary.get('date_range', {}).get('end')}`",
        f"- trade_cost_pct: `{summary.get('trade_cost_pct')}`",
        f"- label_threshold_pct: `{summary.get('label_threshold_pct')}`",
        "- automatic_promotion: `false`",
        "- automatic_threshold_adoption: `false`",
        "- automatic_order_change: `false`",
        "",
        "## Buy-Avoid Shadow",
        "",
        _markdown_table(
            [
                "down_threshold",
                "baseline_trades",
                "skipped",
                "skip_rate",
                "baseline_net_pct",
                "filtered_net_pct",
                "delta_net_pct",
                "dd_reduction_pct",
                "loss_trade_reduction",
                "avoided_loss_pct",
                "missed_gain_pct",
            ],
            threshold_rows,
        )
        if threshold_rows
        else "No joined rows.",
        "",
        "## Best By Net Delta",
        "",
        f"- threshold: `{best.get('threshold')}`",
        f"- delta_net_pct: `{_fmt((best.get('delta') or {}).get('net_return_pct'))}`",
        f"- baseline_net_pct: `{_fmt((best.get('baseline') or {}).get('cumulative_net_return_pct'))}`",
        f"- filtered_net_pct: `{_fmt((best.get('filtered') or {}).get('cumulative_net_return_pct'))}`",
        f"- skipped_signals: `{(best.get('skipped') or {}).get('signals')}`",
        "",
        "## Random Control (Same-Coverage Random Skip)",
        "",
        "baseline 평균이 마이너스면 아무 부분집합을 제거해도 delta는 양수가 된다. "
        "따라서 필터가 진짜 나쁜 거래를 고르는지는 '같은 개수를 무작위로 제거했을 때'와 비교해야 한다. "
        "공식/판정 규칙: `docs/Buy-Avoid-Random-Control-Methodology.md`",
        "",
        _markdown_table(
            [
                "down_threshold",
                "n_skip",
                "actual_skipped_net_pct",
                "random_expected_net_pct",
                "z_score",
                "verdict",
            ],
            random_control_rows,
        )
        if random_control_rows
        else "No rows.",
        "",
        f"- random_control_gate.passed: `{gate.get('passed')}`",
        f"- random_control_gate.verdict: `{gate.get('verdict')}`",
        "- gate.passed=false 인 동안 buy-avoid는 '손실 축소 후보'가 아니라 "
        "'무작위 대조군 대비 우위 미확인' 상태로만 표현한다.",
        "- legacy `status`/delta 수치는 호환용이며, 해석은 random_control_gate가 우선한다.",
        "",
        "## Early-Exit Shadow",
        "",
        f"- status: `{summary.get('early_exit_shadow', {}).get('status')}`",
        f"- closed_lots_total: `{summary.get('early_exit_shadow', {}).get('closed_lots_total')}`",
        "",
        _markdown_table(
            [
                "down_threshold",
                "eligible_lots",
                "early_exit_lots",
                "early_exit_rate",
                "actual_net_pct",
                "early_net_pct",
                "delta_net_pct",
                "dd_reduction_pct",
                "loss_trade_reduction",
                "delta_net_cash",
            ],
            early_rows,
        )
        if early_rows
        else "No early-exit rows.",
        "",
        "## Best Early Exit By Net Delta",
        "",
        f"- threshold: `{early_best.get('threshold')}`",
        f"- delta_net_pct: `{_fmt((early_best.get('delta') or {}).get('net_return_pct'))}`",
        f"- delta_net_cash: `{_fmt((early_best.get('delta') or {}).get('net_cash'), 0)}`",
        f"- early_exit_lots: `{early_best.get('early_exit_lots')}`",
        "",
        "## Interpretation",
        "",
        "- 이 리포트는 baseline 매수 허용 신호를 LightGBM 하락확률로 걸렀을 때의 연구용 비교다.",
        "- 실제 주문, active model, gate 기준값, threshold 정책은 바꾸지 않는다.",
        "- `delta_net_pct`가 양수라는 것만으로는 필터가 나쁜 거래를 골라냈다고 말할 수 없다. "
        "baseline 평균이 마이너스면 무작위 제거도 delta를 양수로 만들기 때문이다. "
        "반드시 위 Random Control 섹션의 z_score/verdict와 random_control_gate로 판단한다.",
        "- 기간이 짧고 LightGBM shadow 저장 구간이 제한되어 있으므로 승격 근거가 아니라 plan B 후보 검증의 첫 증거로만 본다.",
        "",
        "관련 문서/코드 경로:",
        "`scripts/summarize_lightgbm_defensive_shadow.py`,",
        "`runtime-data/dev.db`,",
        "`runtime-data/reports/challengers/latest-lightgbm-performance-diagnostics-h15.json`",
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

    summary = build_summary(
        database_path=args.database_path,
        diagnostics_path=args.diagnostics,
        horizon_min=args.horizon_min,
        thresholds=_parse_thresholds(args.thresholds),
        require_down_argmax=not args.allow_non_argmax_down,
        start_date=args.start_date,
        end_date=args.end_date,
        evaluate_early_exit=not args.skip_early_exit,
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
