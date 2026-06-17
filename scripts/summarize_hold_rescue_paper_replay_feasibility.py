#!/usr/bin/env python3
"""Check whether paper fills can support a hold-rescue replay.

This script is intentionally read-only.  It reconstructs paper position
lifecycles from local paper fills, then checks whether LightGBM shadow
predictions and future minute bars are available at the baseline exit points.
It does not submit orders, change gates, or update model state.
"""

from __future__ import annotations

import argparse
import bisect
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = REPO_ROOT / "runtime-data" / "dev.db"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime-data" / "reports" / "challengers"
DEFAULT_MODEL_VERSION = "lightgbm-h15-v1"
DEFAULT_SINCE_DATE = "2026-06-11"

MIN_CLOSED_LOTS = 50
MIN_LIGHTGBM_MATCHED_LOTS = 30
MIN_FUTURE_BAR_MATCHED_LOTS = 30
MIN_SYMBOLS = 3


@dataclass
class FillEvent:
    order_id: str
    symbol: str
    side: str
    event_time: datetime
    price: float
    qty: float


@dataclass
class OpenLot:
    symbol: str
    entry_time: datetime
    entry_price: float
    remaining_qty: float


@dataclass
class ClosedLot:
    symbol: str
    qty: float
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float

    @property
    def gross_return_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return ((self.exit_price / self.entry_price) - 1.0) * 100.0

    @property
    def cash_delta(self) -> float:
        return (self.exit_price - self.entry_price) * self.qty


@dataclass
class PredictionPoint:
    probability_up: float | None
    probability_flat: float | None
    probability_down: float | None
    predicted_label: str | None


@dataclass
class BarPoint:
    event_time: datetime
    close: float


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    return parsed


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_time(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def _minute_key(value: datetime) -> str:
    return value.replace(second=0, microsecond=0).isoformat()


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _side(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"buy", "b", "long", "매수"}:
        return "buy"
    if text in {"sell", "s", "exit", "매도"}:
        return "sell"
    return text


def _connect_readonly(database_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)


def _tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _pick(columns: set[str], candidates: Iterable[str]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(1) FROM {table}").fetchone()[0])


def _count_where_since(connection: sqlite3.Connection, table: str, time_col: str, since: str) -> int:
    return int(
        connection.execute(
            f"SELECT COUNT(1) FROM {table} WHERE substr({time_col}, 1, 10) >= ?",
            (since,),
        ).fetchone()[0]
    )


def _load_fills(connection: sqlite3.Connection, since_date: str) -> tuple[list[FillEvent], dict[str, Any]]:
    table_names = _tables(connection)
    if "paper_orders" not in table_names or "paper_fills" not in table_names:
        return [], {"status": "missing_tables", "required_tables": ["paper_orders", "paper_fills"]}

    order_columns = _columns(connection, "paper_orders")
    fill_columns = _columns(connection, "paper_fills")
    required = {
        "paper_orders": ["order_id", "symbol", "side"],
        "paper_fills": ["order_id"],
    }
    missing = {
        "paper_orders": [name for name in required["paper_orders"] if name not in order_columns],
        "paper_fills": [name for name in required["paper_fills"] if name not in fill_columns],
    }

    fill_time_col = _pick(fill_columns, ("event_time", "filled_at", "created_at", "timestamp"))
    fill_price_col = _pick(fill_columns, ("fill_price", "price", "avg_fill_price", "executed_price"))
    fill_qty_col = _pick(fill_columns, ("fill_qty", "qty", "quantity", "executed_qty"))
    if fill_time_col is None:
        missing["paper_fills"].append("event_time/fill time")
    if fill_price_col is None:
        missing["paper_fills"].append("fill_price/price")
    if fill_qty_col is None:
        missing["paper_fills"].append("fill_qty/qty")
    if any(missing.values()):
        return [], {"status": "missing_columns", "missing_columns": missing}

    rows = connection.execute(
        f"""
        SELECT
            f.order_id,
            o.symbol,
            o.side,
            f.{fill_time_col},
            f.{fill_price_col},
            f.{fill_qty_col}
        FROM paper_fills AS f
        JOIN paper_orders AS o ON o.order_id = f.order_id
        WHERE substr(f.{fill_time_col}, 1, 10) >= ?
        ORDER BY f.{fill_time_col} ASC, f.order_id ASC
        """,
        (since_date,),
    ).fetchall()
    fills: list[FillEvent] = []
    invalid_rows = 0
    unknown_sides: dict[str, int] = {}
    for row in rows:
        event_time = _parse_datetime(row[3])
        price = _float(row[4])
        qty = _float(row[5])
        side = _side(row[2])
        if side not in {"buy", "sell"}:
            unknown_sides[str(row[2])] = unknown_sides.get(str(row[2]), 0) + 1
            invalid_rows += 1
            continue
        if event_time is None or price is None or qty is None or price <= 0 or qty <= 0:
            invalid_rows += 1
            continue
        fills.append(
            FillEvent(
                order_id=str(row[0]),
                symbol=str(row[1]),
                side=side,
                event_time=event_time,
                price=price,
                qty=qty,
            )
        )
    return fills, {
        "status": "ok",
        "raw_joined_rows": len(rows),
        "valid_fill_events": len(fills),
        "invalid_rows": invalid_rows,
        "unknown_sides": unknown_sides,
        "time_column": fill_time_col,
        "price_column": fill_price_col,
        "qty_column": fill_qty_col,
    }


def reconstruct_closed_lots(fills: list[FillEvent]) -> tuple[list[ClosedLot], dict[str, Any]]:
    open_lots: dict[str, list[OpenLot]] = {}
    closed: list[ClosedLot] = []
    orphan_sell_qty = 0.0
    orphan_sell_events = 0

    for fill in fills:
        if fill.side == "buy":
            open_lots.setdefault(fill.symbol, []).append(
                OpenLot(
                    symbol=fill.symbol,
                    entry_time=fill.event_time,
                    entry_price=fill.price,
                    remaining_qty=fill.qty,
                )
            )
            continue

        sell_qty = fill.qty
        lots = open_lots.setdefault(fill.symbol, [])
        while sell_qty > 0 and lots:
            lot = lots[0]
            closed_qty = min(lot.remaining_qty, sell_qty)
            closed.append(
                ClosedLot(
                    symbol=fill.symbol,
                    qty=closed_qty,
                    entry_time=lot.entry_time,
                    entry_price=lot.entry_price,
                    exit_time=fill.event_time,
                    exit_price=fill.price,
                )
            )
            lot.remaining_qty -= closed_qty
            sell_qty -= closed_qty
            if lot.remaining_qty <= 1e-9:
                lots.pop(0)
        if sell_qty > 1e-9:
            orphan_sell_qty += sell_qty
            orphan_sell_events += 1

    open_qty_by_symbol = {
        symbol: round(sum(lot.remaining_qty for lot in lots), 6)
        for symbol, lots in open_lots.items()
        if sum(lot.remaining_qty for lot in lots) > 1e-9
    }
    return closed, {
        "closed_lots": len(closed),
        "open_symbols": len(open_qty_by_symbol),
        "open_qty_by_symbol": open_qty_by_symbol,
        "orphan_sell_events": orphan_sell_events,
        "orphan_sell_qty": round(orphan_sell_qty, 6),
    }


def _load_predictions(
    connection: sqlite3.Connection,
    *,
    since_date: str,
    horizon_min: int,
    model_version: str,
) -> tuple[dict[tuple[str, str], PredictionPoint], dict[str, Any]]:
    if "serving_predictions" not in _tables(connection):
        return {}, {"status": "missing_table", "required_table": "serving_predictions"}
    columns = _columns(connection, "serving_predictions")
    required = ["symbol", "event_time", "horizon_min", "model_version"]
    missing = [name for name in required if name not in columns]
    if missing:
        return {}, {"status": "missing_columns", "missing_columns": missing}

    probability_columns = {
        "probability_up": "probability_up" if "probability_up" in columns else None,
        "probability_flat": "probability_flat" if "probability_flat" in columns else None,
        "probability_down": "probability_down" if "probability_down" in columns else None,
        "predicted_label": "predicted_label" if "predicted_label" in columns else None,
    }
    select_probability = [
        probability_columns["probability_up"] or "NULL",
        probability_columns["probability_flat"] or "NULL",
        probability_columns["probability_down"] or "NULL",
        probability_columns["predicted_label"] or "NULL",
    ]
    rows = connection.execute(
        f"""
        SELECT symbol, event_time, {", ".join(select_probability)}
        FROM serving_predictions
        WHERE horizon_min = ?
          AND model_version = ?
          AND substr(event_time, 1, 10) >= ?
        ORDER BY event_time ASC
        """,
        (horizon_min, model_version, since_date),
    ).fetchall()
    predictions: dict[tuple[str, str], PredictionPoint] = {}
    invalid_rows = 0
    for row in rows:
        event_time = _parse_datetime(row[1])
        if event_time is None:
            invalid_rows += 1
            continue
        predictions[(str(row[0]), _minute_key(event_time))] = PredictionPoint(
            probability_up=_float(row[2]),
            probability_flat=_float(row[3]),
            probability_down=_float(row[4]),
            predicted_label=str(row[5]) if row[5] is not None else None,
        )
    return predictions, {
        "status": "ok",
        "model_version": model_version,
        "horizon_min": horizon_min,
        "raw_rows": len(rows),
        "matched_key_rows": len(predictions),
        "invalid_rows": invalid_rows,
        "available_probability_columns": {
            key: value is not None for key, value in probability_columns.items()
        },
    }


def _load_bars(connection: sqlite3.Connection, since_date: str) -> tuple[dict[str, list[BarPoint]], dict[str, Any]]:
    if "curated_minute_bars" not in _tables(connection):
        return {}, {"status": "missing_table", "required_table": "curated_minute_bars"}
    columns = _columns(connection, "curated_minute_bars")
    time_col = _pick(columns, ("bar_time", "event_time", "timestamp"))
    close_col = _pick(columns, ("close", "close_price"))
    missing = []
    if "symbol" not in columns:
        missing.append("symbol")
    if time_col is None:
        missing.append("bar_time/event_time")
    if close_col is None:
        missing.append("close")
    if missing:
        return {}, {"status": "missing_columns", "missing_columns": missing}

    rows = connection.execute(
        f"""
        SELECT symbol, {time_col}, {close_col}
        FROM curated_minute_bars
        WHERE substr({time_col}, 1, 10) >= ?
        ORDER BY symbol ASC, {time_col} ASC
        """,
        (since_date,),
    ).fetchall()
    bars: dict[str, list[BarPoint]] = {}
    invalid_rows = 0
    for row in rows:
        event_time = _parse_datetime(row[1])
        close = _float(row[2])
        if event_time is None or close is None or close <= 0:
            invalid_rows += 1
            continue
        bars.setdefault(str(row[0]), []).append(BarPoint(event_time=event_time, close=close))
    return bars, {
        "status": "ok",
        "raw_rows": len(rows),
        "valid_rows": sum(len(items) for items in bars.values()),
        "symbols": len(bars),
        "invalid_rows": invalid_rows,
        "time_column": time_col,
        "close_column": close_col,
    }


def _has_future_bar(
    bars_by_symbol: dict[str, list[BarPoint]],
    lot: ClosedLot,
    *,
    horizon_min: int,
    forced_flat_time: time,
) -> bool:
    symbol_bars = bars_by_symbol.get(lot.symbol, [])
    if not symbol_bars:
        return False
    if lot.exit_time.timetz().replace(tzinfo=None) >= forced_flat_time:
        return False
    exit_minute = lot.exit_time.replace(second=0, microsecond=0)
    target_time = exit_minute + timedelta(minutes=horizon_min)
    same_day_limit = datetime.combine(exit_minute.date(), forced_flat_time)
    if lot.exit_time.tzinfo is not None:
        same_day_limit = same_day_limit.replace(tzinfo=lot.exit_time.tzinfo)
    if target_time > same_day_limit:
        target_time = same_day_limit

    times = [bar.event_time for bar in symbol_bars]
    index = bisect.bisect_left(times, target_time)
    if index >= len(symbol_bars):
        return False
    candidate = symbol_bars[index]
    return candidate.event_time.date() == lot.exit_time.date()


def _summarize_closed_lots(
    lots: list[ClosedLot],
    predictions: dict[tuple[str, str], PredictionPoint],
    bars_by_symbol: dict[str, list[BarPoint]],
    *,
    horizon_min: int,
    forced_flat_time: time,
) -> dict[str, Any]:
    if not lots:
        return {
            "closed_lots": 0,
            "symbols": 0,
            "lightgbm_exit_prediction_matches": 0,
            "future_bar_matches": 0,
        }

    matched_predictions = 0
    matched_future_bars = 0
    hold_minutes: list[float] = []
    gross_returns: list[float] = []
    cash_deltas: list[float] = []
    matched_prediction_by_day: dict[str, int] = {}
    lots_by_day: dict[str, int] = {}
    lots_by_symbol: dict[str, int] = {}
    non_weekday_exit_lots = 0

    for lot in lots:
        day = lot.exit_time.date().isoformat()
        lots_by_day[day] = lots_by_day.get(day, 0) + 1
        lots_by_symbol[lot.symbol] = lots_by_symbol.get(lot.symbol, 0) + 1
        if lot.exit_time.weekday() >= 5:
            non_weekday_exit_lots += 1
        hold_minutes.append(max(0.0, (lot.exit_time - lot.entry_time).total_seconds() / 60.0))
        gross_returns.append(lot.gross_return_pct)
        cash_deltas.append(lot.cash_delta)
        if (lot.symbol, _minute_key(lot.exit_time)) in predictions:
            matched_predictions += 1
            matched_prediction_by_day[day] = matched_prediction_by_day.get(day, 0) + 1
        if _has_future_bar(
            bars_by_symbol,
            lot,
            horizon_min=horizon_min,
            forced_flat_time=forced_flat_time,
        ):
            matched_future_bars += 1

    def avg(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    return {
        "closed_lots": len(lots),
        "symbols": len(lots_by_symbol),
        "lots_by_symbol_top10": dict(sorted(lots_by_symbol.items(), key=lambda item: item[1], reverse=True)[:10]),
        "lots_by_exit_day": dict(sorted(lots_by_day.items())),
        "lightgbm_exit_prediction_matches": matched_predictions,
        "lightgbm_exit_prediction_match_rate": matched_predictions / len(lots),
        "lightgbm_matches_by_day": dict(sorted(matched_prediction_by_day.items())),
        "non_weekday_exit_lots": non_weekday_exit_lots,
        "future_bar_matches": matched_future_bars,
        "future_bar_match_rate": matched_future_bars / len(lots),
        "avg_hold_minutes": avg(hold_minutes),
        "median_hold_minutes": sorted(hold_minutes)[len(hold_minutes) // 2],
        "avg_gross_return_pct": avg(gross_returns),
        "gross_return_pct_sum": sum(gross_returns),
        "cash_delta_sum": sum(cash_deltas),
    }


def _decision(source_summary: dict[str, Any], reconstruction_summary: dict[str, Any]) -> dict[str, Any]:
    closed_lots = int(source_summary.get("closed_lots", 0))
    matched_predictions = int(source_summary.get("lightgbm_exit_prediction_matches", 0))
    matched_future_bars = int(source_summary.get("future_bar_matches", 0))
    symbols = int(source_summary.get("symbols", 0))
    blockers: list[str] = []
    warnings: list[str] = []

    if closed_lots < MIN_CLOSED_LOTS:
        blockers.append("closed_lot_sample_too_small")
    if matched_predictions < MIN_LIGHTGBM_MATCHED_LOTS:
        blockers.append("lightgbm_exit_prediction_sample_too_small")
    if matched_future_bars < MIN_FUTURE_BAR_MATCHED_LOTS:
        blockers.append("future_bar_sample_too_small")
    if symbols < MIN_SYMBOLS:
        warnings.append("few_symbols")
    if int(reconstruction_summary.get("orphan_sell_events", 0)) > 0:
        warnings.append("orphan_sell_events_present")
    if int(reconstruction_summary.get("open_symbols", 0)) > 0:
        warnings.append("open_lots_remaining")
    if int(source_summary.get("non_weekday_exit_lots", 0)) > 0:
        warnings.append("non_weekday_exit_lots_present")

    if blockers:
        status = "not_ready"
        recommended_action = "paper 원장 표본 또는 shadow prediction 연결 표본을 더 쌓은 뒤 재검토"
    else:
        status = "feasible_for_offline_replay"
        recommended_action = "다음 단계로 hold-rescue offline replay 리포트 구현 가능"

    return {
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "minimums": {
            "closed_lots": MIN_CLOSED_LOTS,
            "lightgbm_exit_prediction_matches": MIN_LIGHTGBM_MATCHED_LOTS,
            "future_bar_matches": MIN_FUTURE_BAR_MATCHED_LOTS,
            "symbols": MIN_SYMBOLS,
        },
        "recommended_action": recommended_action,
        "scope_guardrail": "offline feasibility only; no paper/live order, gate, config, or active model change",
    }


def analyze_database(
    connection: sqlite3.Connection,
    *,
    database_path: str,
    since_date: str,
    horizon_min: int,
    model_version: str,
    forced_flat_time: str,
) -> dict[str, Any]:
    parsed_forced_flat_time = _parse_time(forced_flat_time)
    table_names = _tables(connection)
    table_counts: dict[str, Any] = {}
    for table in ("paper_orders", "paper_fills", "serving_predictions", "curated_minute_bars"):
        if table in table_names:
            time_col = _pick(_columns(connection, table), ("event_time", "bar_time", "filled_at", "created_at"))
            table_counts[table] = {
                "total_rows": _count(connection, table),
                "rows_since": _count_where_since(connection, table, time_col, since_date) if time_col else None,
                "time_column": time_col,
            }
        else:
            table_counts[table] = {"missing": True}

    fills, fill_summary = _load_fills(connection, since_date)
    closed_lots, reconstruction_summary = reconstruct_closed_lots(fills)
    predictions, prediction_summary = _load_predictions(
        connection,
        since_date=since_date,
        horizon_min=horizon_min,
        model_version=model_version,
    )
    bars_by_symbol, bar_summary = _load_bars(connection, since_date)
    closed_summary = _summarize_closed_lots(
        closed_lots,
        predictions,
        bars_by_symbol,
        horizon_min=horizon_min,
        forced_flat_time=parsed_forced_flat_time,
    )
    decision = _decision(closed_summary, reconstruction_summary)
    return {
        "generated_at": _now_iso(),
        "report": "hold_rescue_paper_replay_feasibility",
        "database_path": database_path,
        "since_date": since_date,
        "horizon_min": horizon_min,
        "model_version": model_version,
        "forced_flat_time": forced_flat_time,
        "table_counts": table_counts,
        "fill_source": fill_summary,
        "position_reconstruction": reconstruction_summary,
        "lightgbm_shadow_source": prediction_summary,
        "future_bar_source": bar_summary,
        "closed_lot_summary": closed_summary,
        "decision": decision,
        "interpretation": {
            "what_this_is": "paper 체결 원장으로 hold-rescue offline replay를 해도 되는지 보는 준비도 리포트",
            "what_this_is_not": "hold-rescue 성과, 모델 승격 근거, 주문 정책 변경 근거가 아님",
        },
    }


def _fmt_pct(value: Any) -> str:
    number = _float(value)
    if number is None:
        return "확인 불가"
    return f"{number * 100.0:.2f}%" if abs(number) <= 1.0 else f"{number:.4f}%"


def render_markdown(report: dict[str, Any]) -> str:
    decision = report["decision"]
    closed = report["closed_lot_summary"]
    lines = [
        "# Hold-Rescue Paper Replay Feasibility",
        "",
        "## 요약",
        "",
        f"- 판정: `{decision['status']}`",
        f"- 권장 조치: {decision['recommended_action']}",
        f"- 범위: {decision['scope_guardrail']}",
        f"- 분석 기간: `{report['since_date']}` 이후, h{report['horizon_min']}, `{report['model_version']}`",
        "",
        "이 리포트는 hold-rescue 성과가 아니라 준비도 점검입니다. "
        "실제 paper 체결 원장으로 진입과 청산 구간을 재구성하고, baseline 청산 시점에 LightGBM shadow 예측과 이후 분봉이 붙는지만 확인합니다.",
        "",
        "관련 문서/코드 경로: "
        "`scripts/summarize_hold_rescue_paper_replay_feasibility.py`, "
        "`runtime-data/dev.db`, "
        "`runtime-data/reports/challengers/latest-hold-rescue-paper-replay-feasibility-h15.json`",
        "",
        "## 핵심 수치",
        "",
        f"- 재구성된 닫힌 lot: `{closed.get('closed_lots', 0)}`건",
        f"- 종목 수: `{closed.get('symbols', 0)}`개",
        f"- LightGBM exit 시점 예측 매칭: `{closed.get('lightgbm_exit_prediction_matches', 0)}`건 "
        f"({_fmt_pct(closed.get('lightgbm_exit_prediction_match_rate'))})",
        f"- 이후 h{report['horizon_min']} 분봉 매칭: `{closed.get('future_bar_matches', 0)}`건 "
        f"({_fmt_pct(closed.get('future_bar_match_rate'))})",
        f"- 평균 보유 시간: `{float(closed.get('avg_hold_minutes', 0.0)):.2f}`분",
        f"- baseline 청산 lot 기준 총 현금 손익: `{float(closed.get('cash_delta_sum', 0.0)):,.0f}`원",
        "",
        "관련 문서/코드 경로: "
        "`paper_orders`, `paper_fills`, `serving_predictions`, `curated_minute_bars`",
        "",
        "## 판정 기준",
        "",
    ]
    minimums = decision["minimums"]
    for key, value in minimums.items():
        lines.append(f"- `{key}` 최소 기준: `{value}`")
    if decision["blockers"]:
        lines.append(f"- blocker: `{', '.join(decision['blockers'])}`")
    else:
        lines.append("- blocker: 없음")
    if decision["warnings"]:
        lines.append(f"- warning: `{', '.join(decision['warnings'])}`")
    else:
        lines.append("- warning: 없음")
    lines.extend(
        [
            "",
            "관련 문서/코드 경로: "
            "`scripts/summarize_hold_rescue_paper_replay_feasibility.py`, "
            "`docs/Execution-Plan.md`",
            "",
            "## 해석",
            "",
            "- `feasible_for_offline_replay`이면 다음 단계에서 실제 hold-rescue replay를 구현할 수 있습니다.",
            "- `not_ready`이면 모델이 나쁘다는 뜻이 아니라, 재구성 원장이나 LightGBM shadow 연결 표본이 부족하다는 뜻입니다.",
            "- 이 결과만으로 KIS live shadow, paper 주문 정책, active model, gate 기준값을 바꾸지 않습니다.",
            "",
            "관련 문서/코드 경로: "
            "`docs/Current-Implementation.md`, "
            "`docs/Production-Transition-Progress.md`",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-path", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--since-date", default=DEFAULT_SINCE_DATE)
    parser.add_argument("--horizon-min", type=int, default=15)
    parser.add_argument("--model-version", default=DEFAULT_MODEL_VERSION)
    parser.add_argument("--forced-flat-time", default="15:20")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _parse_date(args.since_date)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"latest-hold-rescue-paper-replay-feasibility-h{args.horizon_min}.json"
    md_path = args.output_dir / f"latest-hold-rescue-paper-replay-feasibility-h{args.horizon_min}.md"
    with _connect_readonly(args.database_path) as connection:
        report = analyze_database(
            connection,
            database_path=str(args.database_path),
            since_date=args.since_date,
            horizon_min=args.horizon_min,
            model_version=args.model_version,
            forced_flat_time=args.forced_flat_time,
        )
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json_path": str(json_path), "md_path": str(md_path), "status": report["decision"]["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
