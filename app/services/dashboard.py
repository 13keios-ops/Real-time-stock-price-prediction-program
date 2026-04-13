"""Local monitoring dashboard for runtime operations."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.config.settings import load_settings
from app.models.registry import ModelRegistry
from app.observability.logging import configure_logging
from app.services.kis_account import refresh_kis_account_report
from app.services.runtime_scope import build_runtime_scope, filter_actual_rows
from app.storage.runtime_writer import get_sqlite_store
from app.universe.symbol_metadata import load_symbol_names, resolve_symbol_label, resolve_symbol_name
from app.utils.time import get_timezone, now_local


RANGE_OPTIONS = [
    ("today", "오늘"),
    ("day", "특정일"),
    ("3d", "최근 3일"),
    ("7d", "최근 7일"),
    ("30d", "최근 30일"),
    ("all", "전체"),
]


@dataclass(slots=True)
class DashboardPeriodFilter:
    range_key: str
    selected_date: str
    label: str
    description: str
    start_at: datetime | None
    end_at: datetime | None


def _safe_load_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8").lstrip("\ufeff"))
    except (OSError, json.JSONDecodeError):
        return None


def _serialize_row(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _parse_json_column(row: dict[str, Any] | None, key: str, *, target_key: str) -> dict[str, Any] | None:
    if row is None or key not in row:
        return row
    payload = dict(row)
    raw = payload.pop(key, None)
    if raw is None:
        payload[target_key] = None
        return payload
    try:
        payload[target_key] = json.loads(str(raw))
    except json.JSONDecodeError:
        payload[target_key] = {"raw": raw}
    return payload


def _filtered_rows(sqlite_store, table_name: str, order_by: str, scope) -> list[dict[str, Any]]:
    rows = [dict(row) for row in sqlite_store.fetch_all_rows(table_name, order_by)]
    return filter_actual_rows(table_name, rows, scope)


def _read_version(project_root: Path) -> str:
    version_path = project_root / "VERSION"
    try:
        value = version_path.read_text(encoding="utf-8").strip()
    except OSError:
        return "미설정"
    return value or "미설정"


def _build_period_filter(settings, *, range_key: str | None = None, selected_date_text: str | None = None) -> DashboardPeriodFilter:
    timezone = get_timezone(settings.timezone)
    today_local = now_local(settings.timezone).date()
    normalized_range = str(range_key or "today").strip().lower()
    if normalized_range not in {"today", "day", "3d", "7d", "30d", "all"}:
        normalized_range = "today"

    try:
        selected_date = date.fromisoformat(str(selected_date_text)) if selected_date_text else today_local
    except ValueError:
        selected_date = today_local

    anchor_date = today_local if normalized_range == "today" else selected_date
    if normalized_range == "all":
        return DashboardPeriodFilter(
            range_key="all",
            selected_date=anchor_date.isoformat(),
            label="전체 기간",
            description="누적된 실제 운용 데이터를 모두 봅니다.",
            start_at=None,
            end_at=None,
        )

    start_date = anchor_date
    end_date = anchor_date + timedelta(days=1)
    label = anchor_date.isoformat()
    description = "선택한 날짜 기준 실제 운용 데이터를 보여줍니다."
    if normalized_range == "3d":
        start_date = anchor_date - timedelta(days=2)
        label = f"{anchor_date.isoformat()} 기준 최근 3일"
        description = "선택한 날짜를 포함한 최근 3일 실제 운용 데이터를 보여줍니다."
    elif normalized_range == "7d":
        start_date = anchor_date - timedelta(days=6)
        label = f"{anchor_date.isoformat()} 기준 최근 7일"
        description = "선택한 날짜를 포함한 최근 7일 실제 운용 데이터를 보여줍니다."
    elif normalized_range == "30d":
        start_date = anchor_date - timedelta(days=29)
        label = f"{anchor_date.isoformat()} 기준 최근 30일"
        description = "선택한 날짜를 포함한 최근 30일 실제 운용 데이터를 보여줍니다."
    elif normalized_range == "today":
        label = "오늘"
        description = "오늘 발생한 실제 운용 데이터만 보여줍니다."

    return DashboardPeriodFilter(
        range_key=normalized_range,
        selected_date=anchor_date.isoformat(),
        label=label,
        description=description,
        start_at=datetime.combine(start_date, time.min, tzinfo=timezone),
        end_at=datetime.combine(end_date, time.min, tzinfo=timezone),
    )


def _row_time(row: dict[str, Any], *field_names: str) -> datetime | None:
    for field_name in field_names:
        value = row.get(field_name)
        if value is None:
            continue
        parsed = _parse_iso_datetime(value)
        if parsed is not None:
            return parsed
    return None


def _filter_rows_by_period(rows: list[dict[str, Any]], period_filter: DashboardPeriodFilter, *field_names: str) -> list[dict[str, Any]]:
    if period_filter.start_at is None or period_filter.end_at is None:
        return list(rows)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        parsed = _row_time(row, *field_names)
        if parsed is None:
            continue
        if period_filter.start_at <= parsed < period_filter.end_at:
            filtered.append(row)
    return filtered


def _reverse_recent(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return list(reversed(rows[-limit:])) if limit > 0 else list(reversed(rows))


def _summarize_runtime(sqlite_store, scope) -> dict[str, int]:
    evaluation_rows = [dict(row) for row in sqlite_store.fetch_all_rows("ml_model_evaluations", "evaluated_at")]
    return {
        "raw_market_ticks": len(_filtered_rows(sqlite_store, "raw_market_ticks", "event_time", scope)),
        "raw_orderbook_ticks": len(_filtered_rows(sqlite_store, "raw_orderbook_ticks", "event_time", scope)),
        "minute_bars": len(_filtered_rows(sqlite_store, "curated_minute_bars", "bar_time", scope)),
        "feature_rows": len(_filtered_rows(sqlite_store, "feature_model_inputs", "event_time", scope)),
        "labels": len(_filtered_rows(sqlite_store, "feature_labels", "event_time", scope)),
        "predictions": len(_filtered_rows(sqlite_store, "serving_predictions", "event_time", scope)),
        "signals": len(_filtered_rows(sqlite_store, "serving_trade_signals", "event_time", scope)),
        "orders": len(_filtered_rows(sqlite_store, "paper_orders", "event_time", scope)),
        "fills": len(_filtered_rows(sqlite_store, "paper_fills", "event_time", scope)),
        "positions": len(_filtered_rows(sqlite_store, "paper_positions", "symbol", scope)),
        "portfolio_snapshots": len(_filtered_rows(sqlite_store, "paper_portfolio_snapshots", "event_time", scope)),
        "training_runs": sqlite_store.count_rows("ml_training_runs"),
        "evaluations": sqlite_store.count_rows("ml_model_evaluations"),
        "backtests": sum(1 for row in evaluation_rows if str(row["split_name"]).startswith("backtest_")),
        "walk_forward_runs": sum(1 for row in evaluation_rows if str(row["split_name"]).startswith("walk_forward_")),
        "challenger_runs": sum(1 for row in evaluation_rows if str(row["split_name"]).startswith("challenger_")),
    }


def _translate_prediction_label(label: str) -> str:
    return {
        "up": "상승",
        "flat": "보합",
        "down": "하락",
    }.get(str(label), str(label))


def _translate_signal_side(side: str) -> str:
    return {
        "buy": "매수",
        "sell": "매도",
    }.get(str(side), str(side))


def _parse_iso_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _format_signed_change(amount: float | None, pct: float | None) -> str:
    if amount is None or pct is None:
        return "-"
    if abs(amount) < 0.5:
        amount_text = "0원"
    else:
        amount_text = f"{amount:+,.0f}원"
    if abs(pct) < 0.005:
        pct_text = "0.00%"
    else:
        pct_text = f"{pct:+.2f}%"
    return f"{amount_text} ({pct_text})"


def _prediction_move_text(label: str, amount: float | None, pct: float | None) -> str:
    direction = _translate_prediction_label(label)
    if amount is None or pct is None:
        return f"{direction} 우세 / 기준가 없음"
    return f"{direction} 우세 / {_format_signed_change(amount, pct)}"


def _actual_move_text(
    amount: float | None,
    pct: float | None,
    *,
    target_time_reached: bool,
    has_actual_value: bool,
) -> str:
    if has_actual_value:
        return _format_signed_change(amount, pct)
    return "결과 없음" if target_time_reached else "대기 중"


def _classify_actual_label(actual_return_pct: float | None, threshold_pct: float) -> str | None:
    if actual_return_pct is None:
        return None
    if actual_return_pct >= threshold_pct:
        return "up"
    if actual_return_pct <= -threshold_pct:
        return "down"
    return "flat"


def _prediction_threshold_pct(settings, horizon_min: int) -> float:
    if int(horizon_min) == 60:
        return float(settings.strategy.label_threshold_60)
    return float(settings.strategy.label_threshold_15)


def _build_bar_lookup(rows: list[dict[str, Any]]) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, datetime]]:
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    latest_by_symbol: dict[str, datetime] = {}
    for row in rows:
        symbol = str(row.get("symbol", ""))
        bar_time = str(row.get("bar_time", ""))
        lookup[(symbol, bar_time)] = row
        parsed = _parse_iso_datetime(bar_time)
        if parsed is None:
            continue
        existing = latest_by_symbol.get(symbol)
        if existing is None or parsed > existing:
            latest_by_symbol[symbol] = parsed
    return lookup, latest_by_symbol


def _build_label_lookup(rows: list[dict[str, Any]]) -> dict[tuple[str, str, int], dict[str, Any]]:
    return {
        (str(row.get("symbol", "")), str(row.get("event_time", "")), int(row.get("horizon_min", 0))): row
        for row in rows
    }


def _signal_reason_summary(row: dict[str, Any]) -> str:
    reason_text = str(row.get("reason", ""))
    tokens = [item.strip() for item in reason_text.split(";") if item.strip()]
    summaries: list[str] = []
    if "long_only_policy" in tokens and str(row.get("side")) == "sell":
        summaries.append("하락 예측이었지만 현재 전략이 매수 전용이라 차단")
    if "spread_gate=spread_too_wide" in tokens:
        summaries.append("호가 스프레드가 넓어 차단")
    if "confidence_below_threshold" in tokens:
        summaries.append("신뢰도가 기준치보다 낮음")
    if "time_gate=outside_window" in tokens:
        summaries.append("허용 시간대 밖이라 차단")
    if not summaries and row.get("allowed"):
        return "전략 조건을 통과해 주문 후보로 인정"
    if not summaries:
        return reason_text or "-"
    return " / ".join(summaries)


def _normalize_live_runtime_state(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "stopped",
            "process_running": False,
            "prediction_horizons": ["15", "60"],
            "trading_signal_horizon": "15",
            "status_note": "실시간 수집기와 예측기가 현재 꺼져 있습니다.",
        }
    status = str(payload.get("status", "stopped"))
    process_running = bool(payload.get("process_running"))
    if process_running and status == "running":
        status_note = "실시간 수집기와 예측기가 현재 실행 중입니다."
    elif status == "failed":
        status_note = "실시간 수집기가 시작에 실패했습니다."
    else:
        status = "stopped"
        status_note = "실시간 수집기와 예측기가 현재 꺼져 있습니다."
    normalized = dict(payload)
    normalized["status"] = status
    normalized["process_running"] = process_running
    normalized["status_note"] = status_note
    normalized.setdefault("prediction_horizons", ["15", "60"])
    normalized.setdefault("trading_signal_horizon", "15")
    return normalized


def _latest_time(rows: list[dict[str, Any]], field_name: str) -> str | None:
    if not rows:
        return None
    return str(rows[-1].get(field_name)) if rows[-1].get(field_name) else None


def _prediction_view(
    rows: list[dict[str, Any]],
    symbol_names: dict[str, str],
    *,
    minute_bar_rows: list[dict[str, Any]],
    feature_label_rows: list[dict[str, Any]],
    settings,
) -> list[dict[str, Any]]:
    bar_lookup, latest_bar_time_by_symbol = _build_bar_lookup(minute_bar_rows)
    label_lookup = _build_label_lookup(feature_label_rows)
    rendered: list[dict[str, Any]] = []
    for row in rows:
        probabilities = {
            "up": float(row["probability_up"]),
            "flat": float(row["probability_flat"]),
            "down": float(row["probability_down"]),
        }
        top_label, top_confidence = max(probabilities.items(), key=lambda item: item[1])
        symbol = str(row["symbol"])
        event_time_text = str(row["event_time"])
        horizon_min = int(row["horizon_min"])
        threshold_pct = _prediction_threshold_pct(settings, horizon_min)
        event_time = _parse_iso_datetime(event_time_text)
        base_bar = bar_lookup.get((symbol, event_time_text))
        base_close = float(base_bar["close"]) if base_bar and base_bar.get("close") is not None else None
        expected_return_pct = threshold_pct * (probabilities["up"] - probabilities["down"])
        expected_change_amount = (base_close * expected_return_pct / 100.0) if base_close is not None else None

        actual_change_amount: float | None = None
        actual_return_pct: float | None = None
        target_time_reached = False
        if event_time is not None:
            target_time = event_time + timedelta(minutes=horizon_min)
            future_bar = bar_lookup.get((symbol, target_time.isoformat()))
            latest_symbol_time = latest_bar_time_by_symbol.get(symbol)
            target_time_reached = latest_symbol_time is not None and latest_symbol_time >= target_time
            if future_bar and base_close not in (None, 0):
                future_close = float(future_bar["close"])
                actual_change_amount = future_close - base_close
                actual_return_pct = ((future_close / base_close) - 1.0) * 100.0
            else:
                label_row = label_lookup.get((symbol, event_time_text, horizon_min))
                if label_row and base_close not in (None, 0):
                    actual_return_pct = float(label_row.get("future_return_pct", 0.0))
                    actual_change_amount = base_close * actual_return_pct / 100.0
        actual_label = _classify_actual_label(actual_return_pct, threshold_pct)
        success = actual_label == top_label if actual_label is not None else None

        rendered.append(
            {
                "prediction_id": row["prediction_id"],
                "symbol": symbol,
                "symbol_name": resolve_symbol_name(symbol, symbol_names),
                "symbol_label": resolve_symbol_label(symbol, symbol_names),
                "event_time": event_time_text,
                "horizon_min": horizon_min,
                "model_version": row["model_version"],
                "top_label": top_label,
                "top_label_text": _translate_prediction_label(top_label),
                "top_confidence": round(top_confidence, 4),
                "base_close": base_close,
                "predicted_change_pct": round(expected_return_pct, 4),
                "predicted_change_amount": expected_change_amount,
                "predicted_change_text": _prediction_move_text(top_label, expected_change_amount, expected_return_pct),
                "predicted_result_text": f"{_translate_prediction_label(top_label)} 예상",
                "actual_change_pct": None if actual_return_pct is None else round(actual_return_pct, 4),
                "actual_change_amount": actual_change_amount,
                "actual_label": actual_label,
                "actual_label_text": _translate_prediction_label(actual_label) if actual_label is not None else "대기 중",
                "actual_change_text": _actual_move_text(
                    actual_change_amount,
                    actual_return_pct,
                    target_time_reached=target_time_reached,
                    has_actual_value=actual_change_amount is not None and actual_return_pct is not None,
                ),
                "success": success,
                "success_text": "성공" if success is True else ("실패" if success is False else "대기 중"),
            }
        )
    return rendered


def _signal_view(rows: list[dict[str, Any]], symbol_names: dict[str, str]) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        payload["symbol_name"] = resolve_symbol_name(str(row["symbol"]), symbol_names)
        payload["symbol_label"] = resolve_symbol_label(str(row["symbol"]), symbol_names)
        payload["side_label"] = _translate_signal_side(str(row["side"]))
        payload["allowed_text"] = "허용" if row.get("allowed") else "차단"
        payload["signal_summary"] = _signal_reason_summary(payload)
        payload["signal_horizon_text"] = "15분"
        rendered.append(payload)
    return rendered


def _summarize_runtime_from_rows(
    *,
    raw_market_ticks: list[dict[str, Any]],
    raw_orderbook_ticks: list[dict[str, Any]],
    minute_bars: list[dict[str, Any]],
    feature_rows: list[dict[str, Any]],
    labels: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    portfolio_snapshots: list[dict[str, Any]],
    training_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        "raw_market_ticks": len(raw_market_ticks),
        "raw_orderbook_ticks": len(raw_orderbook_ticks),
        "minute_bars": len(minute_bars),
        "feature_rows": len(feature_rows),
        "labels": len(labels),
        "predictions": len(predictions),
        "signals": len(signals),
        "orders": len(orders),
        "fills": len(fills),
        "positions": len(positions),
        "portfolio_snapshots": len(portfolio_snapshots),
        "training_runs": len(training_rows),
        "evaluations": len(evaluation_rows),
        "backtests": sum(1 for row in evaluation_rows if str(row.get("split_name", "")).startswith("backtest_")),
        "walk_forward_runs": sum(1 for row in evaluation_rows if str(row.get("split_name", "")).startswith("walk_forward_")),
        "challenger_runs": sum(1 for row in evaluation_rows if str(row.get("split_name", "")).startswith("challenger_")),
    }


def _build_prediction_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    horizon_counter = Counter(str(row.get("horizon_min", "-")) for row in rows)
    predicted_counter = Counter(str(row.get("top_label", "")) for row in rows if row.get("top_label"))
    evaluated = [row for row in rows if row.get("success") is not None]
    success_count = sum(1 for row in evaluated if row.get("success") is True)
    actual_counter = Counter(str(row.get("actual_label", "")) for row in evaluated if row.get("actual_label"))
    predicted_change_values = [abs(float(row.get("predicted_change_amount") or 0.0)) for row in rows if row.get("predicted_change_amount") is not None]
    actual_change_values = [abs(float(row.get("actual_change_amount") or 0.0)) for row in evaluated if row.get("actual_change_amount") is not None]
    return {
        "total": len(rows),
        "evaluated": len(evaluated),
        "pending": max(len(rows) - len(evaluated), 0),
        "success_count": success_count,
        "success_rate": (success_count / len(evaluated)) if evaluated else None,
        "horizon_counts": {key: int(value) for key, value in sorted(horizon_counter.items())},
        "predicted_label_counts": {key: int(value) for key, value in sorted(predicted_counter.items())},
        "actual_label_counts": {key: int(value) for key, value in sorted(actual_counter.items())},
        "avg_predicted_change_amount": (sum(predicted_change_values) / len(predicted_change_values)) if predicted_change_values else None,
        "avg_actual_change_amount": (sum(actual_change_values) / len(actual_change_values)) if actual_change_values else None,
        "latest_prediction_time": _latest_time(rows, "event_time"),
    }


def _build_signal_order_summary(signals: list[dict[str, Any]], orders: list[dict[str, Any]], fills: list[dict[str, Any]]) -> dict[str, Any]:
    signal_counter = Counter(str(row.get("side", "")) for row in signals)
    order_counter = Counter(str(row.get("side", "")) for row in orders)
    fill_qty = sum(int(row.get("fill_qty", 0) or 0) for row in fills)
    total_orders = len(orders)
    return {
        "signal_buy": signal_counter.get("buy", 0),
        "signal_sell": signal_counter.get("sell", 0),
        "signal_allowed": sum(1 for row in signals if row.get("allowed")),
        "signal_blocked": sum(1 for row in signals if not row.get("allowed")),
        "order_buy": order_counter.get("buy", 0),
        "order_sell": order_counter.get("sell", 0),
        "orders_total": total_orders,
        "fills": len(fills),
        "fill_qty": fill_qty,
        "fill_rate": (len(fills) / total_orders) if total_orders else None,
        "latest_signal_time": _latest_time(signals, "event_time"),
        "latest_order_time": _latest_time(orders, "event_time"),
        "latest_fill_time": _latest_time(fills, "event_time"),
    }


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _build_local_account_summary(
    *,
    latest_snapshot: dict[str, Any] | None,
    positions: list[dict[str, Any]],
    all_positions: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    settings,
    live_runtime_state: dict[str, Any],
) -> dict[str, Any]:
    order_summary = _build_signal_order_summary([], orders, fills)
    gross_market_value = float((latest_snapshot or {}).get("gross_market_value") or 0.0)
    net_liquidation_value = float((latest_snapshot or {}).get("net_liquidation_value") or 0.0)
    closed_positions = sorted(
        [
            row
            for row in all_positions
            if int(row.get("qty", 0) or 0) <= 0 and (abs(float(row.get("realized_pnl", 0) or 0.0)) > 0 or row.get("updated_at"))
        ],
        key=lambda row: _row_time(row, "updated_at", "opened_at") or datetime.min.replace(tzinfo=get_timezone(settings.timezone)),
        reverse=True,
    )
    return {
        "status": "운용 중" if live_runtime_state.get("status") == "running" else "대기 중",
        "status_note": (
            "실시간 수집기가 실행 중이라 새 분이 닫힐 때마다 예측과 신호를 계속 갱신합니다."
            if live_runtime_state.get("status") == "running"
            else "실시간 수집기가 멈춰 있어 마지막 기록만 표시합니다."
        ),
        "initial_cash": settings.strategy.paper_initial_cash,
        "cash_balance": (latest_snapshot or {}).get("cash_balance"),
        "net_liquidation_value": (latest_snapshot or {}).get("net_liquidation_value"),
        "gross_market_value": (latest_snapshot or {}).get("gross_market_value"),
        "realized_pnl": (latest_snapshot or {}).get("realized_pnl"),
        "unrealized_pnl": (latest_snapshot or {}).get("unrealized_pnl"),
        "open_positions": len(positions),
        "positions": positions,
        "closed_positions_count": len(closed_positions),
        "recent_closed_positions": closed_positions[:10],
        "buy_orders": order_summary.get("order_buy", 0),
        "sell_orders": order_summary.get("order_sell", 0),
        "orders_total": order_summary.get("orders_total", 0),
        "fills": order_summary.get("fills", 0),
        "fill_qty": order_summary.get("fill_qty", 0),
        "fill_rate": order_summary.get("fill_rate"),
        "capital_in_market_ratio": _safe_ratio(gross_market_value, net_liquidation_value) if net_liquidation_value else None,
        "strategy_summary": f"15분 신호로만 주문 판단, 최대 {settings.strategy.max_open_positions}종목, 종목당 {settings.strategy.max_position_pct:.0%} 한도, 최대 보유 {settings.strategy.max_hold_minutes}분",
        "latest_snapshot_time": (latest_snapshot or {}).get("event_time"),
    }


def _build_account_view(name: str, report: dict[str, Any] | None) -> dict[str, Any]:
    payload = report or {}
    snapshot = payload.get("account_snapshot") or {}
    positions = snapshot.get("positions") or []
    return {
        "name": name,
        "ok": bool(payload.get("ok")),
        "status_text": "연결됨" if bool(payload.get("ok")) else "미연결",
        "error": payload.get("error"),
        "fetched_at": payload.get("fetched_at"),
        "cache_used": bool(payload.get("cache_used")),
        "trading_mode": payload.get("trading_mode"),
        "account_no_masked": snapshot.get("account_no_masked"),
        "product_code": snapshot.get("product_code"),
        "cash_balance": snapshot.get("cash_balance"),
        "stock_evaluation_amount": snapshot.get("stock_evaluation_amount"),
        "total_evaluation_amount": snapshot.get("total_evaluation_amount"),
        "total_profit_loss_amount": snapshot.get("total_profit_loss_amount"),
        "total_asset_amount": snapshot.get("total_asset_amount"),
        "positions": positions,
        "positions_count": len(positions),
        "account_note": (
            "브로커에서 직접 조회한 실제 계좌 상태입니다. 현재는 잔고와 보유 종목 중심으로 표시합니다."
            if bool(payload.get("ok"))
            else "실전 계좌는 아직 자격정보가 없거나 조회를 일부러 비활성화한 상태일 수 있습니다."
        ),
    }


def _build_today_report(
    *,
    period_filter: DashboardPeriodFilter,
    prediction_summary: dict[str, Any],
    signal_order_summary: dict[str, Any],
    local_account_summary: dict[str, Any],
    paper_account_view: dict[str, Any],
    active_model: dict[str, Any],
    latest_challenger_report: dict[str, Any] | None,
) -> dict[str, Any]:
    insights: list[str] = []
    next_steps: list[str] = []
    success_rate = prediction_summary.get("success_rate")
    fills = int(signal_order_summary.get("fills", 0))
    orders_total = int(signal_order_summary.get("orders_total", 0))
    blocked = int(signal_order_summary.get("signal_blocked", 0))
    total_signals = int(signal_order_summary.get("signal_buy", 0)) + int(signal_order_summary.get("signal_sell", 0))
    realized_pnl = local_account_summary.get("realized_pnl")

    if prediction_summary.get("total", 0) == 0:
        insights.append("선택한 기간에는 실제 예측 기록이 아직 없습니다.")
        next_steps.append("실시간 수집기를 켜고 장중 데이터를 더 쌓아야 합니다.")
    else:
        insights.append(
            f"{period_filter.label} 기준 실제 예측 {prediction_summary.get('total', 0)}건, 신호 {total_signals}건, 주문 {orders_total}건, 체결 {fills}건이 기록되었습니다."
        )
        if success_rate is not None:
            insights.append(f"예측 결과가 확정된 건의 성공률은 {success_rate * 100:.1f}% 입니다.")
        else:
            insights.append("아직 결과가 확정되지 않은 예측이 많아 성공률을 계산하기 어렵습니다.")
        avg_predicted = prediction_summary.get("avg_predicted_change_amount")
        if avg_predicted is not None:
            insights.append(f"예측 1건당 평균 예상 변동 금액은 약 {avg_predicted:,.0f}원입니다.")

    if blocked > 0:
        insights.append("차단된 신호가 있어 리스크 게이트가 적극적으로 작동 중입니다.")
        next_steps.append("차단 사유를 확인해 스프레드 기준과 시간 게이트가 과도한지 검토합니다.")
    if orders_total > 0:
        insights.append(f"주문 대비 체결 비율은 {(fills / orders_total) * 100:.1f}% 입니다.")

    if local_account_summary.get("open_positions", 0) == 0:
        insights.append("로컬 모의운용 계좌에 현재 열린 포지션이 없습니다.")
    else:
        insights.append(f"로컬 모의운용 계좌는 현재 {local_account_summary.get('open_positions', 0)}개 종목을 보유 중입니다.")
    if realized_pnl is not None:
        insights.append(f"로컬 모의운용 계좌의 누적 실현 손익은 {realized_pnl:,.0f}원입니다.")

    if paper_account_view.get("ok"):
        insights.append("브로커 모의계좌 조회는 정상입니다.")
    else:
        next_steps.append("브로커 모의계좌 조회 오류를 먼저 해결해야 합니다.")

    challenger_action = (latest_challenger_report or {}).get("recommended_action")
    if challenger_action == "keep_active":
        insights.append(f"현재 활성 모델 {active_model.get('model_version') or '-'} 유지가 권장되고 있습니다.")
    elif challenger_action:
        next_steps.append(f"챌린저 검토 결과: {challenger_action}")

    if not next_steps:
        next_steps.append("다음 장중 데이터가 더 쌓이면 워크포워드 안정성과 신호 품질을 다시 점검합니다.")

    return {
        "summary": insights[0] if insights else "오늘의 분석 데이터가 아직 부족합니다.",
        "headline": f"{period_filter.label} 기준 자동 요약",
        "insights": insights,
        "next_steps": next_steps,
    }


def collect_dashboard_payload(
    project_root: Path,
    *,
    recent_limit: int = 10,
    range_key: str | None = None,
    selected_date: str | None = None,
) -> dict[str, Any]:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = get_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for the dashboard.")

    scope = build_runtime_scope(sqlite_store, settings)
    symbol_names = load_symbol_names(project_root)
    period_filter = _build_period_filter(settings, range_key=range_key, selected_date_text=selected_date)
    runtime_summary_all = _summarize_runtime(sqlite_store, scope)

    raw_market_rows_all = _filtered_rows(sqlite_store, "raw_market_ticks", "event_time", scope)
    raw_orderbook_rows_all = _filtered_rows(sqlite_store, "raw_orderbook_ticks", "event_time", scope)
    minute_bar_rows_all = _filtered_rows(sqlite_store, "curated_minute_bars", "bar_time", scope)
    feature_rows_all = _filtered_rows(sqlite_store, "feature_model_inputs", "event_time", scope)
    feature_label_rows_all = _filtered_rows(sqlite_store, "feature_labels", "event_time", scope)
    prediction_rows_all = _filtered_rows(sqlite_store, "serving_predictions", "event_time", scope)
    signal_rows_all = _filtered_rows(sqlite_store, "serving_trade_signals", "event_time", scope)
    order_rows_all = _filtered_rows(sqlite_store, "paper_orders", "event_time", scope)
    fill_rows_all = _filtered_rows(sqlite_store, "paper_fills", "event_time", scope)
    position_rows_all = _filtered_rows(sqlite_store, "paper_positions", "symbol", scope)
    open_position_rows_all = [row for row in position_rows_all if int(row.get("qty", 0) or 0) > 0]
    snapshot_rows_all = _filtered_rows(sqlite_store, "paper_portfolio_snapshots", "event_time", scope)

    training_rows_all = [
        _parse_json_column(dict(row), "training_summary_json", target_key="training_summary")
        for row in sqlite_store.fetch_all_rows("ml_training_runs", "completed_at")
    ]
    evaluation_rows_all = [
        _parse_json_column(dict(row), "metrics_json", target_key="metrics")
        for row in sqlite_store.fetch_all_rows("ml_model_evaluations", "evaluated_at")
    ]

    raw_market_rows = _filter_rows_by_period(raw_market_rows_all, period_filter, "event_time")
    raw_orderbook_rows = _filter_rows_by_period(raw_orderbook_rows_all, period_filter, "event_time")
    minute_bar_rows = _filter_rows_by_period(minute_bar_rows_all, period_filter, "bar_time")
    feature_rows = _filter_rows_by_period(feature_rows_all, period_filter, "event_time")
    feature_label_rows = _filter_rows_by_period(feature_label_rows_all, period_filter, "event_time")
    prediction_rows = _filter_rows_by_period(prediction_rows_all, period_filter, "event_time")
    signal_rows = _filter_rows_by_period(signal_rows_all, period_filter, "event_time")
    order_rows = _filter_rows_by_period(order_rows_all, period_filter, "event_time")
    fill_rows = _filter_rows_by_period(fill_rows_all, period_filter, "event_time")
    snapshot_rows = _filter_rows_by_period(snapshot_rows_all, period_filter, "event_time")
    training_rows = _filter_rows_by_period(training_rows_all, period_filter, "completed_at")
    evaluation_rows = _filter_rows_by_period(evaluation_rows_all, period_filter, "evaluated_at")

    runtime_summary = _summarize_runtime_from_rows(
        raw_market_ticks=raw_market_rows,
        raw_orderbook_ticks=raw_orderbook_rows,
        minute_bars=minute_bar_rows,
        feature_rows=feature_rows,
        labels=feature_label_rows,
        predictions=prediction_rows,
        signals=signal_rows,
        orders=order_rows,
        fills=fill_rows,
        positions=open_position_rows_all,
        portfolio_snapshots=snapshot_rows,
        training_rows=training_rows,
        evaluation_rows=evaluation_rows,
    )

    active_registry = ModelRegistry(settings.runtime_data_dir).load()
    latest_training = training_rows_all[-1] if training_rows_all else None
    latest_evaluation = evaluation_rows_all[-1] if evaluation_rows_all else None

    active_models = active_registry.get("active_models", {}) if isinstance(active_registry, dict) else {}
    active_model_entry = active_models.get("15", {}) if isinstance(active_models, dict) else {}
    active_model_entry_60 = active_models.get("60", {}) if isinstance(active_models, dict) else {}

    latest_portfolio_snapshot = snapshot_rows[-1] if snapshot_rows else (snapshot_rows_all[-1] if snapshot_rows_all else None)
    positions = open_position_rows_all
    prediction_views = _prediction_view(
        prediction_rows,
        symbol_names,
        minute_bar_rows=minute_bar_rows_all,
        feature_label_rows=feature_label_rows_all,
        settings=settings,
    )
    signal_views = _signal_view(signal_rows, symbol_names)
    recent_predictions = _reverse_recent(prediction_views, recent_limit)
    recent_signals = _reverse_recent(signal_views, recent_limit)
    recent_orders = _reverse_recent(order_rows, recent_limit)
    recent_fills = _reverse_recent(fill_rows, recent_limit)
    recent_bars = _reverse_recent(minute_bar_rows, recent_limit)

    prediction_summary = _build_prediction_summary(prediction_views)
    signal_order_summary = _build_signal_order_summary(signal_rows, order_rows, fill_rows)

    live_runtime_state = _normalize_live_runtime_state(
        _safe_load_json(settings.runtime_data_dir / "reports" / "live-runtime" / "state" / "listener-state.json")
    )
    latest_market_bar_time = _latest_time(minute_bar_rows, "bar_time")
    latest_prediction_time = _latest_time(prediction_views, "event_time")
    latest_signal_time = _latest_time(signal_views, "event_time")
    actual_labels = runtime_summary.get("labels", 0)
    learning_mode = "actual_runtime" if actual_labels > 0 else "offline_research"
    learning_note = (
        "현재 실제 운용 라벨이 있어 학습 현황을 실운용 데이터 기준으로 해석할 수 있습니다."
        if learning_mode == "actual_runtime"
        else "현재 실제 운용 라벨이 0건이라, 아래 학습·챌린저 값은 저장된 연구용 오프라인 평가 결과입니다."
    )
    active_status_note = (
        "최신 학습 모델은 LightGBM 후보이지만, 승격 검증을 통과하지 못해 아직 활성 모델이 아닙니다."
        if active_model_entry.get("model_version") != (latest_training or {}).get("model_version")
        else "최신 학습 모델과 현재 활성 모델이 같습니다."
    )
    if live_runtime_state.get("status") == "running":
        operation_note = "실시간 수집기와 예측기가 현재 실행 중입니다. 새 분이 닫힐 때마다 15분·60분 예측이 기록되고, 15분 기준으로만 신호를 생성합니다."
    else:
        operation_note = "현재는 대시보드만 실행 중이거나, 마지막 장중 검증 결과만 남아 있습니다. 실시간 수집기를 켜야 예측과 신호가 계속 늘어납니다."
    if recent_bars:
        minute_note = "최근 분봉은 실제 장중 KIS 체결 데이터로 생성된 기록입니다. 주문이나 체결이 없어도 시장 데이터만 들어오면 분봉은 만들어질 수 있습니다."
    else:
        minute_note = "최근 실제 운용 분봉이 아직 없습니다."
    ml_state = {
        "status": "대기 (장후 재학습)",
        "latest_completed_at": (latest_training or {}).get("completed_at"),
        "latest_model_version": (latest_training or {}).get("model_version"),
        "active_model_version_h15": active_model_entry.get("model_version"),
        "active_model_version_h60": active_model_entry_60.get("model_version"),
        "note": "현재 상시 학습 프로세스는 따로 켜져 있지 않고, 마지막 학습 완료 결과를 기준으로 표시합니다.",
    }
    local_account_state = _build_local_account_summary(
        latest_snapshot=latest_portfolio_snapshot,
        positions=positions,
        all_positions=position_rows_all,
        orders=order_rows,
        fills=fill_rows,
        settings=settings,
        live_runtime_state=live_runtime_state,
    )

    def _load_account(mode: str) -> dict[str, Any]:
        try:
            return refresh_kis_account_report(project_root=project_root, account_mode=mode, max_age_seconds=60).to_dict()
        except Exception as exc:  # pragma: no cover
            return {
                "ok": False,
                "trading_mode": mode,
                "fetched_at": None,
                "cache_used": False,
                "cache_age_seconds": None,
                "error": str(exc),
                "source": "kis-broker",
                "account_snapshot": None,
            }

    paper_account_report = _load_account("paper")
    live_account_report = _load_account("live")
    today_training_runs = _reverse_recent(training_rows, 5)
    today_evaluations = _reverse_recent(evaluation_rows, 5)

    latest_backtest_report = _safe_load_json(settings.runtime_data_dir / "reports" / "backtests" / "latest-backtest-h15.json")
    latest_walk_forward_report = _safe_load_json(settings.runtime_data_dir / "reports" / "backtests" / "latest-walk-forward-h15.json")
    latest_challenger_report = _safe_load_json(settings.runtime_data_dir / "reports" / "challengers" / "latest-challengers-h15.json")
    latest_kis_verification = _safe_load_json(settings.runtime_data_dir / "reports" / "kis-ws" / "latest-verification.json")

    paper_account_view = _build_account_view("모의계좌(실제)", paper_account_report)
    live_account_view = _build_account_view("실 운용계좌", live_account_report)
    account_views = {
        "virtual_paper": local_account_state,
        "paper_broker": paper_account_view,
        "live_broker": live_account_view,
    }

    model_rows = [
        {
            "name": "활성 모델 (15분)",
            "model_version": active_model_entry.get("model_version"),
            "model_kind": active_model_entry.get("model_kind"),
            "status": "운용 중",
            "score": None,
            "note": "현재 실시간 예측에 사용되는 15분 모델입니다.",
        },
        {
            "name": "활성 모델 (60분)",
            "model_version": active_model_entry_60.get("model_version") or "미설정",
            "model_kind": active_model_entry_60.get("model_kind") or "fallback",
            "status": "운용 중",
            "score": None,
            "note": "60분 예측용 활성 모델입니다.",
        },
        {
            "name": "최신 학습 모델",
            "model_version": (latest_training or {}).get("model_version"),
            "model_kind": (latest_training or {}).get("training_summary", {}).get("model_kind") if latest_training else None,
            "status": "대기 중",
            "score": (latest_evaluation or {}).get("accuracy"),
            "note": "가장 최근에 학습된 모델입니다. 승격 검증을 통과해야 활성 모델이 됩니다.",
        },
    ]

    today_report = _build_today_report(
        period_filter=period_filter,
        prediction_summary=prediction_summary,
        signal_order_summary=signal_order_summary,
        local_account_summary=local_account_state,
        paper_account_view=paper_account_view,
        active_model=active_model_entry,
        latest_challenger_report=latest_challenger_report,
    )

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "version": _read_version(project_root),
        "period_filter": {
            "range_key": period_filter.range_key,
            "selected_date": period_filter.selected_date,
            "label": period_filter.label,
            "description": period_filter.description,
            "options": [{"value": key, "label": label} for key, label in RANGE_OPTIONS],
        },
        "dashboard_scope": {
            "actual_runtime_only": True,
            "actual_symbol_minutes": len(scope.actual_symbol_minutes),
            "actual_order_ids": len(scope.actual_order_ids),
            "actual_runtime_filter_note": "샘플, synthetic, demo, replay 데이터는 제외됩니다.",
        },
        "project": {
            "name": settings.app_name,
            "environment": settings.app_env,
            "trading_mode": settings.trading_mode,
            "allow_live_orders": settings.allow_live_orders,
            "runtime_data_dir": str(settings.runtime_data_dir),
            "paper_initial_cash": settings.strategy.paper_initial_cash,
            "enable_paper_execution": settings.strategy.enable_paper_execution,
            "max_open_positions": settings.strategy.max_open_positions,
            "max_position_pct": settings.strategy.max_position_pct,
            "max_hold_minutes": settings.strategy.max_hold_minutes,
        },
        "runtime_summary": runtime_summary,
        "active_model": active_model_entry,
        "active_model_h60": active_model_entry_60,
        "local_account_state": local_account_state,
        "system_status": {
            "live_runtime": live_runtime_state,
            "ml_state": ml_state,
            "latest_market_bar_time": latest_market_bar_time,
            "latest_prediction_time": latest_prediction_time,
            "latest_signal_time": latest_signal_time,
            "operation_note": operation_note,
            "minute_note": minute_note,
            "prediction_horizons": ["15분", "60분"],
            "signal_horizon": "15분",
        },
        "learning_context": {
            "mode": learning_mode,
            "actual_runtime_labels": actual_labels,
            "note": learning_note,
            "active_status_note": active_status_note,
        },
        "model_rows": model_rows,
        "prediction_summary": prediction_summary,
        "signal_order_summary": signal_order_summary,
        "latest_training": latest_training,
        "latest_evaluation": latest_evaluation,
        "today_training_runs": today_training_runs,
        "today_evaluations": today_evaluations,
        "latest_backtest_report": latest_backtest_report,
        "latest_walk_forward_report": latest_walk_forward_report,
        "latest_challenger_report": latest_challenger_report,
        "latest_kis_verification": latest_kis_verification,
        "latest_portfolio_snapshot": latest_portfolio_snapshot,
        "positions": positions,
        "broker_account_report": paper_account_report,
        "paper_account_report": paper_account_report,
        "live_account_report": live_account_report,
        "account_views": account_views,
        "recent_predictions": recent_predictions,
        "recent_signals": recent_signals,
        "recent_orders": recent_orders,
        "recent_fills": recent_fills,
        "recent_minute_bars": recent_bars,
        "today_report": today_report,
        "runtime_summary_all": runtime_summary_all,
        "audit": {
            "progress": _safe_load_json(settings.runtime_data_dir / "reports" / "codex" / "automation" / "state" / "latest-progress.json"),
            "backlog": _safe_load_json(settings.runtime_data_dir / "reports" / "codex" / "automation" / "backlog" / "latest-priority-backlog.json"),
        },
    }


def _esc(value: Any) -> str:
    if value is None:
        return "-"
    return html.escape(str(value))


def _money(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return format(float(value), ",.0f")
    except (TypeError, ValueError):
        return _esc(value)


def _pct(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return _esc(value)


def _ratio_pct(value: Any, digits: int = 1) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return _esc(value)


def _refresh_interval_text(refresh_seconds: int) -> str:
    if refresh_seconds % 60 == 0:
        minutes = max(refresh_seconds // 60, 1)
        return f"{minutes}분"
    return f"{max(refresh_seconds, 1)}초"


def _table(headers: list[str], rows: list[list[Any]], empty_text: str) -> str:
    if not rows:
        return f'<div class="empty">{_esc(empty_text)}</div>'
    header_html = "".join(f"<th>{_esc(header)}</th>" for header in headers)
    row_html = []
    for row in rows:
        row_html.append("<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in row) + "</tr>")
    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{''.join(row_html)}</tbody></table>"


def _list(items: list[str], empty_text: str) -> str:
    if not items:
        return f'<div class="empty">{_esc(empty_text)}</div>'
    return "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>"


def _pill_row(items: list[str]) -> str:
    return '<div class="pillrow">' + "".join(f'<span class="pill">{item}</span>' for item in items if item) + "</div>"


def _tab_button(target: str, label: str, *, active: bool = False) -> str:
    class_name = "tab-button is-active" if active else "tab-button"
    aria_selected = "true" if active else "false"
    return f'<button class="{class_name}" type="button" data-tab-target="{_esc(target)}" aria-selected="{aria_selected}">{_esc(label)}</button>'


def _subtab_button(group: str, target: str, label: str, *, active: bool = False, vertical: bool = False) -> str:
    class_name = "subtab-button is-active" if active else "subtab-button"
    if vertical:
        class_name += " is-vertical"
    aria_selected = "true" if active else "false"
    return (
        f'<button class="{class_name}" type="button" '
        f'data-subtab-group="{_esc(group)}" data-subtab-target="{_esc(target)}" aria-selected="{aria_selected}">'
        f"{_esc(label)}</button>"
    )


def _account_table_rows(account_view: dict[str, Any]) -> list[list[Any]]:
    return [
        [
            row.get("symbol"),
            row.get("name"),
            row.get("holding_qty"),
            _money(row.get("current_price")),
            _money(row.get("evaluation_amount")),
            _money(row.get("evaluation_profit_loss_amount")),
        ]
        for row in account_view.get("positions", [])
    ]


def _prediction_expected_cell(row: dict[str, Any]) -> str:
    result_text = str(row.get("predicted_result_text") or "-")
    change_text = str(row.get("predicted_change_text") or "-")
    return f"{result_text} / {change_text}"


def _prediction_actual_cell(row: dict[str, Any]) -> str:
    if row.get("actual_label") is None:
        return str(row.get("actual_change_text") or "대기 중")
    return f"{row.get('actual_label_text') or '-'} / {row.get('actual_change_text') or '-'}"


def _render_dashboard_html(payload: dict[str, Any], *, refresh_seconds: int, live_mode: bool) -> str:
    return _render_dashboard_html_v2(payload, refresh_seconds=refresh_seconds, live_mode=live_mode)

    runtime = payload.get("runtime_summary", {})
    active_model = payload.get("active_model", {})
    active_model_h60 = payload.get("active_model_h60", {})
    challenger = payload.get("latest_challenger_report", {}) or {}
    kis = payload.get("latest_kis_verification", {}) or {}
    portfolio = payload.get("latest_portfolio_snapshot", {}) or {}
    broker_account_report = payload.get("broker_account_report", {}) or {}
    broker_account = broker_account_report.get("account_snapshot") or {}
    system_status = payload.get("system_status", {}) or {}
    live_runtime = system_status.get("live_runtime", {}) or {}
    ml_state = system_status.get("ml_state", {}) or {}
    local_account_state = payload.get("local_account_state", {}) or {}
    latest_training = payload.get("latest_training", {}) or {}
    latest_evaluation = payload.get("latest_evaluation", {}) or {}
    latest_backtest = payload.get("latest_backtest_report", {}) or {}
    latest_walk_forward = payload.get("latest_walk_forward_report", {}) or {}
    learning_context = payload.get("learning_context", {}) or {}
    audit_progress = (payload.get("audit") or {}).get("progress") or {}
    audit_backlog = (payload.get("audit") or {}).get("backlog") or {}
    scope = payload.get("dashboard_scope", {})
    refresh_meta = f'<meta http-equiv="refresh" content="{max(refresh_seconds, 1)}">' if live_mode else ""
    refresh_text = _refresh_interval_text(refresh_seconds)

    prediction_rows = [
        [
            row["event_time"],
            row["symbol"],
            row["symbol_name"],
            f'{row["horizon_min"]}분',
            row["model_version"],
            _money(row.get("base_close")),
            row["predicted_change_text"],
            row["actual_change_text"],
        ]
        for row in payload.get("recent_predictions", [])
    ]
    signal_rows = [
        [
            row["event_time"],
            row["symbol"],
            row["symbol_name"],
            row["signal_horizon_text"],
            row["side_label"],
            row["allowed_text"],
            row["signal_summary"],
        ]
        for row in payload.get("recent_signals", [])
    ]
    order_rows = [
        [row["event_time"], row["symbol"], row["side"], row["qty"], row["status"]]
        for row in payload.get("recent_orders", [])
    ]
    fill_rows = [
        [row["event_time"], row["order_id"], _money(row.get("fill_price")), row.get("fill_qty")]
        for row in payload.get("recent_fills", [])
    ]
    bar_rows = [
        [row["bar_time"], row["symbol"], _money(row.get("close")), _money(row.get("volume"))]
        for row in payload.get("recent_minute_bars", [])
    ]
    position_rows = [
        [row["symbol"], row["qty"], _money(row.get("avg_price")), _money(row.get("last_price")), _money(row.get("unrealized_pnl"))]
        for row in payload.get("positions", [])
    ]
    broker_position_rows = [
        [
            row.get("symbol"),
            row.get("name"),
            row.get("holding_qty"),
            _money(row.get("current_price")),
            _money(row.get("evaluation_amount")),
            _money(row.get("evaluation_profit_loss_amount")),
        ]
        for row in broker_account.get("positions", [])
    ]
    challenger_rows = [
        [
            row.get("rank"),
            row.get("candidate_name"),
            row.get("model_version"),
            _pct(row.get("overall_accuracy"), 4),
            _pct(row.get("trade_hit_rate"), 4),
            _pct(row.get("cumulative_net_return_pct"), 4),
        ]
        for row in challenger.get("candidates", [])
    ]
    walk_forward_rows = [
        [
            row.get("fold"),
            _pct(row.get("overall_accuracy"), 4),
            row.get("trades_taken"),
            _pct(row.get("trade_hit_rate"), 4),
            _pct(row.get("cumulative_net_return_pct"), 4),
        ]
        for row in latest_walk_forward.get("fold_summaries", [])
    ]
    runtime_detail_rows = [
        ["원시 체결", runtime.get("raw_market_ticks", 0)],
        ["원시 호가", runtime.get("raw_orderbook_ticks", 0)],
        ["분봉", runtime.get("minute_bars", 0)],
        ["특징 행", runtime.get("feature_rows", 0)],
        ["라벨", runtime.get("labels", 0)],
        ["학습 실행", runtime.get("training_runs", 0)],
        ["평가 실행", runtime.get("evaluations", 0)],
        ["백테스트", runtime.get("backtests", 0)],
        ["워크포워드", runtime.get("walk_forward_runs", 0)],
        ["챌린저 비교", runtime.get("challenger_runs", 0)],
    ]
    project_rows = [
        ["프로젝트", payload.get("project", {}).get("name")],
        ["환경", payload.get("project", {}).get("environment")],
        ["운영 모드", payload.get("project", {}).get("trading_mode")],
        ["런타임 폴더", payload.get("project", {}).get("runtime_data_dir")],
        ["실데이터 minute 수", scope.get("actual_symbol_minutes")],
        ["실제 주문 ID 수", scope.get("actual_order_ids")],
    ]
    operation_rows = [
        ["대시보드", "실행 중"],
        ["실시간 수집기", "실행 중" if live_runtime.get("status") == "running" else "중지"],
        ["실시간 예측 수평선", "15분, 60분"],
        ["실제 신호 생성 기준", system_status.get("signal_horizon")],
        ["15분 활성 모델", active_model.get("model_version")],
        ["60분 활성 모델", active_model_h60.get("model_version") or "미설정 (baseline fallback)"],
        ["최근 실시간 분봉 시각", system_status.get("latest_market_bar_time")],
        ["최근 예측 시각", system_status.get("latest_prediction_time")],
        ["최근 신호 시각", system_status.get("latest_signal_time")],
        ["머신러닝 상태", ml_state.get("status")],
        ["최근 학습 완료", ml_state.get("latest_completed_at")],
        ["현재 전략 해석", "하락 예측도 계산하지만 현재 주문 정책은 매수 전용"],
    ]
    backlog_items = [
        f"<strong>{_esc(item.get('id'))}</strong> / {_esc(item.get('priority'))} / {_esc(item.get('status'))}<br>{_esc(item.get('problem'))}<br><span class=\"muted\">권장 조치: {_esc(item.get('recommended_change'))}</span>"
        for item in (audit_backlog.get("items") or [])[:5]
    ]
    next_actions = [_esc(item) for item in (audit_progress.get("next_actions") or [])]

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {refresh_meta}
  <title>실시간 주가 예측 대시보드</title>
  <style>
    body {{ margin:0; font-family:"Segoe UI",sans-serif; background:#f7f3ea; color:#1f2933; }}
    .wrap {{ max-width:1280px; margin:0 auto; padding:24px; }}
    .hero,.grid {{ display:grid; gap:16px; }}
    .hero {{ grid-template-columns:1.4fr 1fr; margin-bottom:16px; }}
    .grid {{ grid-template-columns:repeat(4,minmax(0,1fr)); margin-bottom:16px; }}
    .cols {{ display:grid; grid-template-columns:1.2fr 0.8fr; gap:16px; }}
    .stack {{ display:grid; gap:16px; }}
    .card {{ background:rgba(255,252,246,.94); border:1px solid rgba(31,41,51,.12); border-radius:20px; padding:20px 22px; box-shadow:0 18px 40px rgba(31,41,51,.10); }}
    .eyebrow {{ display:inline-block; padding:6px 10px; border-radius:999px; background:rgba(13,92,99,.12); color:#0d5c63; font-size:12px; font-weight:700; text-transform:uppercase; }}
    h1 {{ margin:14px 0 8px; font-size:32px; }}
    h2 {{ margin:0 0 12px; font-size:19px; }}
    h3 {{ margin:16px 0 8px; font-size:15px; }}
    .muted {{ color:#5f6c7b; font-size:14px; line-height:1.6; }}
    .pillrow {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }}
    .pill {{ padding:8px 10px; border-radius:999px; background:#fff; border:1px solid rgba(31,41,51,.12); font-size:13px; }}
    .action-row {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-top:12px; }}
    .action-button {{ appearance:none; border:none; cursor:pointer; padding:10px 14px; border-radius:12px; background:#0d5c63; color:#fff; font-size:14px; font-weight:700; box-shadow:0 10px 24px rgba(13,92,99,.18); }}
    .action-button:disabled {{ opacity:.6; cursor:wait; }}
    .metric {{ font-size:28px; font-weight:700; margin-top:6px; }}
    .tabs {{ display:flex; flex-wrap:wrap; gap:10px; margin-bottom:16px; }}
    .tab-button {{ appearance:none; border:none; cursor:pointer; padding:12px 16px; border-radius:14px; background:rgba(255,252,246,.94); color:#5f6c7b; font-size:15px; font-weight:700; box-shadow:0 10px 24px rgba(31,41,51,.08); }}
    .tab-button.is-active {{ background:#0d5c63; color:#fff; }}
    .tab-panel {{ display:none; }}
    .tab-panel.is-active {{ display:block; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ text-align:left; padding:10px 8px; border-top:1px solid rgba(31,41,51,.12); vertical-align:top; }}
    th {{ color:#5f6c7b; font-size:12px; text-transform:uppercase; }}
    thead th {{ border-top:none; }}
    .empty {{ color:#5f6c7b; font-size:14px; padding:8px 0; }}
    ul {{ margin:0; padding-left:18px; }}
    li {{ margin:8px 0; }}
    @media (max-width: 1100px) {{ .hero,.cols,.grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="card">
        <span class="eyebrow">실운용 데이터 기준</span>
        <h1>실시간 주가 예측 대시보드</h1>
        <div class="muted">샘플, synthetic, demo, replay 데이터는 기본적으로 제외합니다. 현재 화면은 실제 KIS 기반 운용 데이터만 보여줍니다.</div>
      </div>
      <div class="card">
        <div class="pillrow">
          <span class="pill">운영 모드: {_esc(payload.get('project', {}).get('trading_mode'))}</span>
          <span class="pill">활성 모델: {_esc(active_model.get('model_version'))}</span>
          <span class="pill">장 상태: {_esc(kis.get('session_status'))}</span>
          <span class="pill">실시간 수집기: {'실행 중' if live_runtime.get('status') == 'running' else '중지'}</span>
          <span class="pill">자동 새로고침: {refresh_text}</span>
        </div>
        <div class="action-row">
          <button id="refresh-dashboard-button" class="action-button" type="button">상태 업데이트</button>
        </div>
        <div class="muted" style="margin-top:12px;">업데이트 시각: {_esc(payload.get('generated_at'))}<br>실운용 필터: {'켜짐' if scope.get('actual_runtime_only') else '꺼짐'}<br>실데이터 minute 수: {_esc(scope.get('actual_symbol_minutes'))}<br>{_esc(system_status.get('operation_note'))}</div>
      </div>
    </section>
    <section class="grid">
      <div class="card"><div class="muted">예측 건수</div><div class="metric">{_esc(runtime.get('predictions', 0))}</div></div>
      <div class="card"><div class="muted">신호 건수</div><div class="metric">{_esc(runtime.get('signals', 0))}</div></div>
      <div class="card"><div class="muted">주문 건수</div><div class="metric">{_esc(runtime.get('orders', 0))}</div></div>
      <div class="card"><div class="muted">평가 금액</div><div class="metric">{_money(portfolio.get('net_liquidation_value'))}</div></div>
    </section>

    <section class="tabs" role="tablist" aria-label="대시보드 탭">
      <button class="tab-button is-active" type="button" data-tab-target="tab-trading" aria-selected="true">1. 거래 현황</button>
      <button class="tab-button" type="button" data-tab-target="tab-learning" aria-selected="false">2. 학습 현황</button>
      <button class="tab-button" type="button" data-tab-target="tab-other" aria-selected="false">3. 그 외</button>
    </section>

    <section id="tab-trading" class="tab-panel is-active">
      <section class="cols">
        <div class="stack">
          <div class="card">
            <h2>현재 프로그램 상태</h2>
            {_table(['항목','상태'], operation_rows, '현재 상태 정보가 없습니다.')}
            <div class="muted" style="margin-top:12px;">{_esc(live_runtime.get('status_note'))}<br>{_esc(ml_state.get('note'))}</div>
          </div>
          <div class="card">
            <h2>최근 예측</h2>
            {_table(['시각','종목코드','종목명','수평선','모델','기준가','예상 변동','실제 결과'], prediction_rows, '최근 실제 운용 예측이 없습니다. 실시간 수집기가 꺼져 있으면 값이 늘어나지 않습니다.')}
            <div class="muted" style="margin-top:12px;">예상 변동은 현재 분 종가와 수평선별 기준 변동폭을 바탕으로 계산한 기대 금액입니다. 실제 결과는 해당 수평선 시간이 지난 뒤 같은 기준가 대비 얼마나 움직였는지 보여줍니다.</div>
          </div>
          <div class="card">
            <h2>최근 신호</h2>
            {_table(['시각','종목코드','종목명','신호 기준','방향','허용 여부','설명'], signal_rows, '최근 실제 운용 신호가 없습니다.')}
            <div class="muted" style="margin-top:12px;">여기서 매도는 실제 매도 주문이 아니라, 모델이 하락 확률을 더 높게 본 원시 신호입니다. 현재 전략은 매수 전용이라 보유 종목이 없어도 차단된 매도 신호가 보일 수 있습니다.</div>
          </div>
          <div class="card">
            <h2>최근 주문</h2>
            {_table(['시각','종목','방향','수량','상태'], order_rows, '최근 실제 운용 주문이 없습니다.')}
          </div>
          <div class="card">
            <h2>최근 체결과 분봉</h2>
            {_table(['시각','주문 ID','체결가','수량'], fill_rows, '최근 실제 운용 체결이 없습니다.')}
            <div style="height:10px"></div>
            {_table(['시각','종목','종가','거래량'], bar_rows, '최근 실제 운용 분봉이 없습니다.')}
            <div class="muted" style="margin-top:12px;">{_esc(system_status.get('minute_note'))}</div>
          </div>
        </div>
        <div class="stack">
          <div class="card">
            <h2>로컬 모의운용 계좌</h2>
            <div class="pillrow">
              <span class="pill">평가 금액 {_money(portfolio.get('net_liquidation_value'))}</span>
              <span class="pill">현금 {_money(portfolio.get('cash_balance'))}</span>
              <span class="pill">미실현 손익 {_money(portfolio.get('unrealized_pnl'))}</span>
              <span class="pill">실현 손익 {_money(portfolio.get('realized_pnl'))}</span>
            </div>
            <div class="pillrow" style="margin-top:10px;">
              <span class="pill">운용 상태 {_esc(local_account_state.get('status'))}</span>
            </div>
            <div class="pillrow" style="margin-top:10px;">
              <span class="pill">초기 예수금 {_money(payload.get('project', {}).get('paper_initial_cash'))}</span>
              <span class="pill">주문 실행 {'켜짐' if payload.get('project', {}).get('enable_paper_execution') else '꺼짐'}</span>
              <span class="pill">최대 종목 수 {_esc(payload.get('project', {}).get('max_open_positions'))}</span>
              <span class="pill">종목당 최대 비중 {_esc(payload.get('project', {}).get('max_position_pct'))}</span>
              <span class="pill">최대 보유 시간 {_esc(payload.get('project', {}).get('max_hold_minutes'))}분</span>
            </div>
            <div class="muted" style="margin-top:12px;">최근 스냅샷 시각: {_esc(portfolio.get('event_time'))}</div>
            <div style="margin-top:12px;">{_table(['종목','수량','평균 단가','현재가','미실현 손익'], position_rows, '현재 기록된 포지션이 없습니다.')}</div>
            <div class="muted" style="margin-top:12px;">프로그램 내부 모의주문 엔진이 기록한 가상 포트폴리오입니다. 우리 전략이 실제로 어떤 주문을 냈는지 추적하는 용도입니다.<br>{_esc(local_account_state.get('status_note'))}</div>
          </div>
          <div class="card">
            <h2>브로커 모의계좌 잔고</h2>
            <div class="pillrow">
              <span class="pill">조회 성공: {'예' if broker_account_report.get('ok') else '아니오'}</span>
              <span class="pill">캐시 사용: {'예' if broker_account_report.get('cache_used') else '아니오'}</span>
              <span class="pill">계좌: {_esc(broker_account.get('account_no_masked'))}</span>
              <span class="pill">상품코드: {_esc(broker_account.get('product_code'))}</span>
            </div>
            <div class="pillrow" style="margin-top:10px;">
              <span class="pill">예수금 {_money(broker_account.get('cash_balance'))}</span>
              <span class="pill">유가평가 {_money(broker_account.get('stock_evaluation_amount'))}</span>
              <span class="pill">총평가 {_money(broker_account.get('total_evaluation_amount'))}</span>
              <span class="pill">총손익 {_money(broker_account.get('total_profit_loss_amount'))}</span>
            </div>
            <div class="muted" style="margin-top:12px;">최근 조회 시각: {_esc(broker_account_report.get('fetched_at'))}<br>오류: {_esc(broker_account_report.get('error')) if broker_account_report.get('error') else '없음'}</div>
            <div style="margin-top:12px;">{_table(['종목','종목명','보유수량','현재가','평가금액','평가손익'], broker_position_rows, '브로커 계좌 보유 종목이 없습니다.')}</div>
            <div class="muted" style="margin-top:12px;">한국투자 모의투자 계좌에서 직접 조회한 실제 잔고입니다. 프로그램 내부 가상 포트폴리오와 다를 수 있습니다.</div>
          </div>
          <div class="card">
            <h2>KIS 연결 상태</h2>
            <div class="pillrow">
              <span class="pill">연결 준비: {'예' if kis.get('connection_ready') else '아니오'}</span>
              <span class="pill">실데이터 수신: {'예' if kis.get('market_data_flow_ok') else '아니오'}</span>
              <span class="pill">승인 키: {'발급됨' if kis.get('approval_key_issued') else '없음'}</span>
            </div>
            <div class="muted" style="margin-top:12px;">장 상태: {_esc(kis.get('session_status'))}<br>상태 메모: {_esc(kis.get('status_note'))}<br>수신 프레임: {_esc(kis.get('frames_received'))} / 제어 프레임: {_esc(kis.get('control_frames'))}</div>
          </div>
        </div>
      </section>
    </section>

    <section id="tab-learning" class="tab-panel">
      <section class="cols">
        <div class="stack">
          <div class="card">
            <h2>실운용 학습 상태</h2>
            <div class="pillrow">
              <span class="pill">실운용 라벨 수: {_esc(learning_context.get('actual_runtime_labels'))}</span>
              <span class="pill">실운용 특징 행 수: {_esc(runtime.get('feature_rows', 0))}</span>
              <span class="pill">실운용 예측 건수: {_esc(runtime.get('predictions', 0))}</span>
              <span class="pill">실데이터 수신: {'예' if kis.get('market_data_flow_ok') else '아니오'}</span>
            </div>
            <div class="muted" style="margin-top:12px;">실운용 학습 상태는 실제 장중 데이터와 그로부터 생성된 라벨을 기준으로 표시합니다.<br>{_esc(learning_context.get('note'))}</div>
          </div>
          <div class="card">
            <h2>현재 운용 모델 상태</h2>
            <div class="pillrow">
              <span class="pill">활성 모델: {_esc(active_model.get('model_version'))}</span>
              <span class="pill">모델 종류: {_esc(active_model.get('model_kind'))}</span>
              <span class="pill">권장 조치: {_esc(challenger.get('recommended_action'))}</span>
              <span class="pill">워크포워드 게이트: {_esc(challenger.get('walk_forward_gate_status'))}</span>
            </div>
            <div class="muted" style="margin-top:12px;">{_esc(learning_context.get('active_status_note'))}<br>{_esc(challenger.get('walk_forward_gate_reason'))}</div>
          </div>
        </div>
        <div class="stack">
          <div class="card">
            <h2>오프라인 연구 결과</h2>
            <div class="pillrow">
              <span class="pill">표시 기준: 오프라인 연구 결과</span>
              <span class="pill">최신 학습 모델: {_esc(latest_training.get('model_version'))}</span>
            </div>
            <div class="muted" style="margin-top:12px;">백테스트, 워크포워드, 챌린저 비교는 저장된 연구용 평가 결과입니다. 실제 실운용 수익이나 장중 실시간 성과와는 구분해서 봐야 합니다.</div>
          </div>
          <div class="card">
            <h2>최신 학습 요약</h2>
            <div class="pillrow">
              <span class="pill">모델 버전: {_esc(latest_training.get('model_version'))}</span>
              <span class="pill">학습 행 수: {_esc(latest_training.get('train_rows'))}</span>
              <span class="pill">검증 행 수: {_esc(latest_training.get('validation_rows'))}</span>
              <span class="pill">특징 세트: {_esc(latest_training.get('feature_set_version'))}</span>
            </div>
            <div class="muted" style="margin-top:12px;">완료 시각: {_esc(latest_training.get('completed_at'))}</div>
          </div>
          <div class="card">
            <h2>최신 평가 요약</h2>
            <div class="pillrow">
              <span class="pill">분할 이름: {_esc(latest_evaluation.get('split_name'))}</span>
              <span class="pill">정확도: {_pct(latest_evaluation.get('accuracy'), 4)}</span>
              <span class="pill">평가 행 수: {_esc(latest_evaluation.get('total_rows'))}</span>
            </div>
          </div>
          <div class="card">
            <h2>백테스트 요약</h2>
            <div class="pillrow">
              <span class="pill">정확도: {_pct(latest_backtest.get('overall_accuracy'), 4)}</span>
              <span class="pill">거래 수: {_esc(latest_backtest.get('trades_taken'))}</span>
              <span class="pill">평균 순수익률: {_pct(latest_backtest.get('average_net_return_pct'), 4)}</span>
              <span class="pill">누적 순수익률: {_pct(latest_backtest.get('cumulative_net_return_pct'), 4)}</span>
            </div>
          </div>
          <div class="card">
            <h2>워크포워드 요약</h2>
            <div class="pillrow">
              <span class="pill">fold 수: {_esc(latest_walk_forward.get('folds'))}</span>
              <span class="pill">정확도: {_pct(latest_walk_forward.get('overall_accuracy'), 4)}</span>
              <span class="pill">거래 수: {_esc(latest_walk_forward.get('trades_taken'))}</span>
              <span class="pill">누적 순수익률: {_pct(latest_walk_forward.get('cumulative_net_return_pct'), 4)}</span>
            </div>
          </div>
          <div class="card">
            <h2>챌린저 비교</h2>
            {_table(['순위','후보','모델 버전','정확도','거래 적중률','누적 순수익률'], challenger_rows, '챌린저 비교 결과가 없습니다.')}
          </div>
          <div class="card">
            <h2>워크포워드 fold 요약</h2>
            {_table(['fold','정확도','거래 수','거래 적중률','누적 순수익률'], walk_forward_rows, '워크포워드 fold 요약이 없습니다.')}
          </div>
        </div>
      </section>
    </section>

    <section id="tab-other" class="tab-panel">
      <section class="cols">
        <div class="stack">
          <div class="card">
            <h2>프로젝트 및 데이터 범위</h2>
            {_table(['항목','값'], project_rows, '표시할 프로젝트 정보가 없습니다.')}
          </div>
          <div class="card">
            <h2>상세 집계</h2>
            {_table(['항목','값'], runtime_detail_rows, '상세 집계가 없습니다.')}
          </div>
        </div>
        <div class="stack">
          <div class="card">
            <h2>자동 점검 요약</h2>
            <div class="muted">{_esc(audit_progress.get('last_run_summary') or '자동 점검 요약이 아직 없습니다.')}</div>
            <h3>우선순위 backlog</h3>
            {_list(backlog_items, '표시할 backlog 항목이 없습니다.')}
            <h3>다음 작업</h3>
            {_list(next_actions, '기록된 다음 작업이 없습니다.')}
          </div>
          <div class="card">
            <h2>대시보드 안내</h2>
            <div class="muted">이 화면은 실제 KIS 기반 운용 데이터만 보여줍니다. 샘플, synthetic, demo, replay 경로에서 만들어진 데이터는 기본적으로 제외됩니다.</div>
          </div>
        </div>
      </section>
    </section>
  </div>
  <script>
    (() => {{
      const buttons = Array.from(document.querySelectorAll('[data-tab-target]'));
      const panels = Array.from(document.querySelectorAll('.tab-panel'));
      const refreshButton = document.getElementById('refresh-dashboard-button');
      const storageKey = 'realtime-stock-dashboard-active-tab';
      const activate = (targetId) => {{
        const fallbackId = 'tab-trading';
        const nextId = document.getElementById(targetId) ? targetId : fallbackId;
        buttons.forEach((button) => {{
          const active = button.dataset.tabTarget === nextId;
          button.classList.toggle('is-active', active);
          button.setAttribute('aria-selected', active ? 'true' : 'false');
        }});
        panels.forEach((panel) => {{
          panel.classList.toggle('is-active', panel.id === nextId);
        }});
        if (window.location.hash !== `#${{nextId}}`) {{
          history.replaceState(null, '', `#${{nextId}}`);
        }}
        try {{
          window.localStorage.setItem(storageKey, nextId);
        }} catch (error) {{
        }}
      }};
      buttons.forEach((button) => {{
        button.addEventListener('click', () => activate(button.dataset.tabTarget));
      }});
      let initialTab = window.location.hash ? window.location.hash.slice(1) : '';
      if (!initialTab) {{
        try {{
          initialTab = window.localStorage.getItem(storageKey) || '';
        }} catch (error) {{
          initialTab = '';
        }}
      }}
      activate(initialTab || 'tab-trading');
      window.addEventListener('hashchange', () => activate(window.location.hash.slice(1)));
      if (refreshButton) {{
        refreshButton.addEventListener('click', () => {{
          refreshButton.disabled = true;
          refreshButton.textContent = '업데이트 중...';
          window.location.reload();
        }});
      }}
    }})();
  </script>
</body>
</html>"""


def _render_dashboard_html_v2(payload: dict[str, Any], *, refresh_seconds: int, live_mode: bool) -> str:
    project = payload.get("project", {}) or {}
    period_filter = payload.get("period_filter", {}) or {}
    runtime = payload.get("runtime_summary", {}) or {}
    runtime_all = payload.get("runtime_summary_all", {}) or {}
    scope = payload.get("dashboard_scope", {}) or {}
    system_status = payload.get("system_status", {}) or {}
    live_runtime = system_status.get("live_runtime", {}) or {}
    ml_state = system_status.get("ml_state", {}) or {}
    active_model = payload.get("active_model", {}) or {}
    active_model_h60 = payload.get("active_model_h60", {}) or {}
    learning_context = payload.get("learning_context", {}) or {}
    latest_training = payload.get("latest_training", {}) or {}
    latest_evaluation = payload.get("latest_evaluation", {}) or {}
    latest_backtest = payload.get("latest_backtest_report", {}) or {}
    latest_walk_forward = payload.get("latest_walk_forward_report", {}) or {}
    latest_challenger = payload.get("latest_challenger_report", {}) or {}
    latest_kis = payload.get("latest_kis_verification", {}) or {}
    prediction_summary = payload.get("prediction_summary", {}) or {}
    signal_order_summary = payload.get("signal_order_summary", {}) or {}
    today_report = payload.get("today_report", {}) or {}
    account_views = payload.get("account_views", {}) or {}
    virtual_account = account_views.get("virtual_paper", {}) or {}
    paper_account = account_views.get("paper_broker", {}) or {}
    live_account = account_views.get("live_broker", {}) or {}
    audit_progress = (payload.get("audit") or {}).get("progress") or {}
    audit_backlog = (payload.get("audit") or {}).get("backlog") or {}

    refresh_meta = f'<meta http-equiv="refresh" content="{max(refresh_seconds, 1)}">' if live_mode else ""
    refresh_text = _refresh_interval_text(refresh_seconds)

    prediction_rows = [
        [
            row.get("event_time"),
            row.get("symbol_label"),
            f"{row.get('horizon_min')}분",
            row.get("model_version"),
            _money(row.get("base_close")),
            _prediction_expected_cell(row),
            _prediction_actual_cell(row),
            row.get("success_text"),
        ]
        for row in payload.get("recent_predictions", [])
    ]
    signal_rows = [
        [row.get("event_time"), row.get("symbol"), row.get("symbol_name"), row.get("signal_horizon_text"), row.get("side_label"), row.get("allowed_text"), row.get("signal_summary")]
        for row in payload.get("recent_signals", [])
    ]
    order_rows = [
        [row.get("event_time"), row.get("symbol"), _translate_signal_side(str(row.get("side", ""))), row.get("qty"), _money(row.get("limit_price")), row.get("status")]
        for row in payload.get("recent_orders", [])
    ]
    fill_rows = [
        [row.get("event_time"), row.get("order_id"), _money(row.get("fill_price")), row.get("fill_qty"), _money(row.get("commission"))]
        for row in payload.get("recent_fills", [])
    ]
    bar_rows = [
        [row.get("bar_time"), row.get("symbol"), _money(row.get("open")), _money(row.get("high")), _money(row.get("low")), _money(row.get("close")), _money(row.get("volume"))]
        for row in payload.get("recent_minute_bars", [])
    ]
    virtual_position_rows = [
        [row.get("symbol"), row.get("qty"), _money(row.get("avg_price")), _money(row.get("last_price")), _money(row.get("market_value")), _money(row.get("unrealized_pnl"))]
        for row in virtual_account.get("positions", [])
    ]
    virtual_closed_position_rows = [
        [
            row.get("updated_at"),
            row.get("symbol"),
            _money(row.get("last_price")),
            _money(row.get("realized_pnl")),
        ]
        for row in virtual_account.get("recent_closed_positions", [])
    ]
    virtual_buy_order_rows = [
        [row.get("event_time"), row.get("symbol"), row.get("qty"), _money(row.get("limit_price")), row.get("status")]
        for row in payload.get("recent_orders", [])
        if str(row.get("side", "")).lower() == "buy"
    ]
    virtual_sell_order_rows = [
        [row.get("event_time"), row.get("symbol"), row.get("qty"), _money(row.get("limit_price")), row.get("status")]
        for row in payload.get("recent_orders", [])
        if str(row.get("side", "")).lower() == "sell"
    ]
    virtual_fill_activity_rows = [
        [row.get("event_time"), row.get("order_id"), _money(row.get("fill_price")), row.get("fill_qty"), _money(row.get("commission"))]
        for row in payload.get("recent_fills", [])
    ]
    virtual_signal_activity_rows = [
        [row.get("event_time"), row.get("symbol_name"), row.get("side_label"), row.get("allowed_text"), row.get("signal_summary")]
        for row in payload.get("recent_signals", [])
    ]
    paper_position_rows = _account_table_rows(paper_account)
    live_position_rows = _account_table_rows(live_account)
    model_rows = [
        [row.get("name"), row.get("model_version"), row.get("model_kind"), row.get("status"), _ratio_pct(row.get("score"), 2) if row.get("score") is not None else "-", row.get("note")]
        for row in payload.get("model_rows", [])
    ]
    today_training_rows = [
        [row.get("completed_at"), row.get("model_version"), row.get("train_rows"), row.get("validation_rows"), row.get("feature_set_version")]
        for row in payload.get("today_training_runs", [])
    ]
    today_evaluation_rows = [
        [row.get("evaluated_at"), row.get("split_name"), _ratio_pct(row.get("accuracy"), 2), row.get("total_rows")]
        for row in payload.get("today_evaluations", [])
    ]
    challenger_rows = [
        [row.get("rank"), row.get("candidate_name"), row.get("model_version"), _ratio_pct(row.get("overall_accuracy"), 2), _ratio_pct(row.get("trade_hit_rate"), 2), _pct(row.get("cumulative_net_return_pct"), 2)]
        for row in latest_challenger.get("candidates", [])
    ]
    walk_forward_rows = [
        [row.get("fold"), _ratio_pct(row.get("overall_accuracy"), 2), row.get("trades_taken"), _ratio_pct(row.get("trade_hit_rate"), 2), _pct(row.get("cumulative_net_return_pct"), 2)]
        for row in latest_walk_forward.get("fold_summaries", [])
    ]
    status_rows = [
        ["운영 모드", project.get("trading_mode")],
        ["활성 모델 (15분)", active_model.get("model_version")],
        ["활성 모델 (60분)", active_model_h60.get("model_version") or "미설정"],
        ["장 상태", latest_kis.get("session_status")],
        ["실시간 수집기", "실행 중" if live_runtime.get("status") == "running" else "중지"],
        ["실데이터 수신", "예" if latest_kis.get("market_data_flow_ok") else "아니오"],
        ["최근 분봉 시각", system_status.get("latest_market_bar_time")],
        ["최근 예측 시각", system_status.get("latest_prediction_time")],
        ["최근 신호 시각", system_status.get("latest_signal_time")],
        ["머신러닝 상태", ml_state.get("status")],
        ["최근 학습 완료", ml_state.get("latest_completed_at")],
        ["현재 범위", period_filter.get("label")],
    ]
    setting_rows = [
        ["앱 이름", project.get("name")],
        ["환경", project.get("environment")],
        ["런타임 폴더", project.get("runtime_data_dir")],
        ["초기 예수금", _money(project.get("paper_initial_cash"))],
        ["최대 종목 수", project.get("max_open_positions")],
        ["종목당 최대 비중", project.get("max_position_pct")],
        ["최대 보유 시간", f"{project.get('max_hold_minutes')}분"],
        ["실전 주문 허용", "예" if project.get("allow_live_orders") else "아니오"],
        ["자동 새로고침", refresh_text],
        ["실제 minute 수", scope.get("actual_symbol_minutes")],
        ["누적 예측 수", runtime_all.get("predictions", 0)],
        ["현재 범위 예측 수", runtime.get("predictions", 0)],
    ]
    prediction_status_pills = [
        f"예측 총건수: {prediction_summary.get('total', 0)}",
        f"결과 확정: {prediction_summary.get('evaluated', 0)}",
        f"대기 중: {prediction_summary.get('pending', 0)}",
        f"예측 성공: {prediction_summary.get('success_count', 0)}",
        f"성공률: {_ratio_pct(prediction_summary.get('success_rate'), 1)}",
    ]
    signal_status_pills = [
        f"매수 신호: {signal_order_summary.get('signal_buy', 0)}",
        f"매도 신호: {signal_order_summary.get('signal_sell', 0)}",
        f"허용 신호: {signal_order_summary.get('signal_allowed', 0)}",
        f"차단 신호: {signal_order_summary.get('signal_blocked', 0)}",
        f"주문: {signal_order_summary.get('orders_total', 0)}",
        f"체결: {signal_order_summary.get('fills', 0)}",
    ]
    virtual_account_pills = [
        f"운용 상태: {virtual_account.get('status')}",
        f"초기 예수금: {_money(virtual_account.get('initial_cash'))}",
        f"현재 현금: {_money(virtual_account.get('cash_balance'))}",
        f"평가 금액: {_money(virtual_account.get('net_liquidation_value'))}",
        f"실현 손익: {_money(virtual_account.get('realized_pnl'))}",
        f"미실현 손익: {_money(virtual_account.get('unrealized_pnl'))}",
    ]
    paper_account_pills = [
        f"연결 상태: {paper_account.get('status_text') or '-'}",
        f"계좌: {paper_account.get('account_no_masked') or '-'}",
        f"상품코드: {paper_account.get('product_code') or '-'}",
        f"예수금: {_money(paper_account.get('cash_balance'))}",
        f"총자산: {_money(paper_account.get('total_asset_amount'))}",
        f"총손익: {_money(paper_account.get('total_profit_loss_amount'))}",
    ]
    live_account_pills = [
        f"연결 상태: {live_account.get('status_text') or '-'}",
        f"계좌: {live_account.get('account_no_masked') or '-'}",
        f"상품코드: {live_account.get('product_code') or '-'}",
        f"예수금: {_money(live_account.get('cash_balance'))}",
        f"총자산: {_money(live_account.get('total_asset_amount'))}",
        f"총손익: {_money(live_account.get('total_profit_loss_amount'))}",
    ]
    ml_status_pills = [
        f"실운용 라벨: {learning_context.get('actual_runtime_labels', 0)}건",
        f"실운용 특징: {runtime.get('feature_rows', 0)}건",
        f"최신 학습 모델: {latest_training.get('model_version') or '-'}",
        f"활성 모델(15분): {active_model.get('model_version') or '-'}",
        f"활성 모델(60분): {active_model_h60.get('model_version') or '미설정'}",
        f"ML 상태: {ml_state.get('status') or '-'}",
    ]
    runtime_rows = [
        ["원시 체결", runtime.get("raw_market_ticks", 0)],
        ["원시 호가", runtime.get("raw_orderbook_ticks", 0)],
        ["분봉", runtime.get("minute_bars", 0)],
        ["특징", runtime.get("feature_rows", 0)],
        ["라벨", runtime.get("labels", 0)],
        ["학습", runtime.get("training_runs", 0)],
        ["평가", runtime.get("evaluations", 0)],
        ["백테스트", runtime.get("backtests", 0)],
        ["워크포워드", runtime.get("walk_forward_runs", 0)],
        ["챌린저", runtime.get("challenger_runs", 0)],
    ]
    backlog_items = [
        f"<strong>{_esc(item.get('id'))}</strong> / {_esc(item.get('priority'))} / {_esc(item.get('status'))}<br>{_esc(item.get('problem'))}<br><span class=\"muted\">권장 조치: {_esc(item.get('recommended_change'))}</span>"
        for item in (audit_backlog.get("items") or [])[:5]
    ]
    next_actions = [_esc(item) for item in (audit_progress.get("next_actions") or [])]
    option_html = "".join(
        f'<option value="{_esc(option.get("value"))}" {"selected" if option.get("value") == period_filter.get("range_key") else ""}>{_esc(option.get("label"))}</option>'
        for option in period_filter.get("options", [])
    )
    metrics_html = "".join(
        f'<div class="metric-card"><div class="metric-label">{_esc(label)}</div><div class="metric-value">{_esc(value)}</div></div>'
        for label, value in [
            ("실데이터 minute", scope.get("actual_symbol_minutes", 0)),
            ("예측", runtime.get("predictions", 0)),
            ("신호", runtime.get("signals", 0)),
            ("주문", runtime.get("orders", 0)),
            ("체결", runtime.get("fills", 0)),
            ("열린 포지션", virtual_account.get("open_positions", 0)),
        ]
    )
    tab_buttons = "".join(
        [
            _tab_button("tab-virtual-paper", "모의투자(가상)", active=True),
            _tab_button("tab-paper-broker", "모의계좌(실제)"),
            _tab_button("tab-live-broker", "실 운용계좌"),
            _tab_button("tab-ml", "머신러닝 현황"),
            _tab_button("tab-status", "상태 및 설정"),
            _tab_button("tab-predictions", "예측현황"),
            _tab_button("tab-signal-orders", "신호 & 주문현황"),
            _tab_button("tab-fills-bars", "체결과 분봉"),
            _tab_button("tab-daily-report", "오늘의 리포트"),
            _tab_button("tab-other", "기타"),
        ]
    )

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {refresh_meta}
  <title>실시간 주가 예측 대시보드</title>
  <style>
    body {{ margin:0; background:#f4efe6; color:#15212d; font-family:"Segoe UI","Malgun Gothic",sans-serif; }}
    .wrap {{ max-width:1320px; margin:0 auto; padding:18px 20px 40px; }}
    .card {{ background:#fffaf3; border:1px solid rgba(21,33,45,.12); border-radius:22px; padding:18px 20px; box-shadow:0 18px 40px rgba(21,33,45,.08); }}
    .hero {{ display:grid; grid-template-columns:1.15fr .85fr; gap:16px; margin-bottom:18px; }}
    .hero-title {{ display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }}
    .version {{ font-size:16px; font-weight:600; margin-top:12px; white-space:nowrap; }}
    h1 {{ margin:0; font-size:44px; letter-spacing:-1px; }}
    h2 {{ margin:0 0 14px; font-size:28px; }}
    h3 {{ margin:0 0 10px; font-size:20px; }}
    .muted {{ color:#5e6b79; font-size:14px; line-height:1.6; }}
    .pillrow {{ display:flex; flex-wrap:wrap; gap:8px; margin:10px 0 0; }}
    .pill {{ display:inline-flex; align-items:center; gap:6px; padding:8px 12px; border-radius:999px; border:1px solid rgba(21,33,45,.12); background:#fff; font-size:14px; }}
    .hero-actions {{ display:flex; gap:12px; align-items:flex-start; justify-content:space-between; }}
    .action-button {{ appearance:none; border:none; border-radius:12px; background:#0d5c63; color:#fff; padding:12px 16px; font-size:16px; font-weight:700; cursor:pointer; box-shadow:0 10px 24px rgba(13,92,99,.20); }}
    .action-button:disabled {{ opacity:.7; cursor:wait; }}
    .status-box {{ max-height:140px; overflow:auto; padding-right:8px; }}
    .filter-form {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:14px; align-items:center; }}
    .filter-form select, .filter-form input {{ border:1px solid rgba(21,33,45,.16); border-radius:10px; padding:10px 12px; font-size:14px; background:#fff; }}
    .filter-form button {{ appearance:none; border:1px solid rgba(21,33,45,.16); border-radius:10px; background:#fff; padding:10px 14px; font-size:14px; cursor:pointer; }}
    .metrics {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:12px; margin:0 0 18px; }}
    .metric-card {{ background:#fffaf3; border:1px solid rgba(21,33,45,.12); border-radius:18px; padding:16px; box-shadow:0 14px 30px rgba(21,33,45,.06); }}
    .metric-label {{ color:#5e6b79; font-size:14px; }}
    .metric-value {{ margin-top:8px; font-size:28px; font-weight:800; }}
    .tabs {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:12px; margin-bottom:18px; }}
    .tab-button {{ appearance:none; width:100%; border:1px solid rgba(21,33,45,.18); border-radius:14px; background:#fff; padding:16px 12px; font-size:17px; font-weight:700; cursor:pointer; }}
    .tab-button.is-active {{ background:#0d5c63; color:#fff; border-color:#0d5c63; }}
    .tab-panel {{ display:none; }}
    .tab-panel.is-active {{ display:block; }}
    .subtab-shell {{ display:grid; grid-template-columns:240px minmax(0,1fr); gap:16px; }}
    .subtab-nav {{ display:grid; gap:10px; align-content:start; }}
    .subtab-button {{ appearance:none; width:100%; border:1px solid rgba(21,33,45,.18); border-radius:14px; background:#fff; padding:14px 12px; font-size:15px; font-weight:700; text-align:left; cursor:pointer; }}
    .subtab-button.is-active {{ background:#15212d; color:#fff; border-color:#15212d; }}
    .subtab-panel {{ display:none; }}
    .subtab-panel.is-active {{ display:block; }}
    .expand-tabs {{ display:flex; flex-wrap:wrap; gap:10px; margin:8px 0 16px; }}
    .expand-button {{ appearance:none; border:1px solid rgba(21,33,45,.18); border-radius:999px; background:#fff; padding:10px 14px; font-size:14px; font-weight:700; cursor:pointer; }}
    .expand-button.is-active {{ background:#0d5c63; color:#fff; border-color:#0d5c63; }}
    .expand-panel {{ display:none; }}
    .expand-panel.is-active {{ display:block; }}
    .layout-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
    .stack {{ display:grid; gap:16px; }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    th, td {{ text-align:left; padding:10px 8px; border-top:1px solid rgba(21,33,45,.10); vertical-align:top; }}
    thead th {{ border-top:none; color:#5e6b79; font-size:12px; text-transform:uppercase; letter-spacing:.03em; }}
    .empty {{ color:#5e6b79; font-size:14px; padding:8px 0; }}
    ul {{ margin:0; padding-left:18px; }}
    li {{ margin:8px 0; }}
    @media (max-width: 1200px) {{ .hero,.layout-2,.metrics,.tabs,.subtab-shell {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="card">
        <div class="hero-title">
          <div>
            <h1>실시간 주가 예측 대시보드</h1>
            {_pill_row([f"운영 모드: {project.get('trading_mode')}", f"활성 모델(15분): {active_model.get('model_version')}", f"활성 모델(60분): {active_model_h60.get('model_version') or '미설정'}", f"장 상태: {latest_kis.get('session_status')}", f"실시간 수집기: {'실행 중' if live_runtime.get('status') == 'running' else '중지'}", f"자동 새로고침: {refresh_text}"])}
          </div>
          <div class="version">Ver {_esc(payload.get('version'))}</div>
        </div>
        <form class="filter-form" method="get" action="/">
          <label>조회 범위 <select name="range">{option_html}</select></label>
          <label>기준 날짜 <input type="date" name="date" value="{_esc(period_filter.get('selected_date'))}"></label>
          <button type="submit">범위 적용</button>
        </form>
      </div>
      <div class="card">
        <div class="hero-actions">
          <button id="refresh-dashboard-button" class="action-button" type="button">상태 업데이트</button>
          <div class="status-box muted">업데이트 시각: {_esc(payload.get('generated_at'))}<br>상태 요약: {_esc(system_status.get('operation_note'))}<br>실제 데이터 기준: {_esc(scope.get('actual_runtime_filter_note'))}<br>현재 범위: {_esc(period_filter.get('label'))}<br>{_esc(period_filter.get('description'))}<br>예측 수평선: {_esc(', '.join(system_status.get('prediction_horizons') or []))}<br>신호 생성 기준: {_esc(system_status.get('signal_horizon') or '-')}</div>
        </div>
      </div>
    </section>
    <section class="metrics">{metrics_html}</section>
    <section class="tabs" role="tablist" aria-label="대시보드 탭">{tab_buttons}</section>

    <section id="tab-virtual-paper" class="tab-panel is-active">
      <div class="card">
        <h2>모의투자(가상)</h2>
        <div class="subtab-shell">
          <div class="subtab-nav" role="tablist" aria-label="모의투자 가상 세부 탭">
            {_subtab_button("virtual-paper", "virtual-overview", "상태 설명", active=True, vertical=True)}
            {_subtab_button("virtual-paper", "virtual-holdings", "보유 종목", vertical=True)}
            {_subtab_button("virtual-paper", "virtual-activity", "매수/매도 및 체결현황", vertical=True)}
          </div>
          <div>
            <div id="virtual-overview" class="subtab-panel is-active" data-subtab-panel="virtual-paper">
              {_pill_row(virtual_account_pills)}
              <div class="muted" style="margin-top:12px;">{_esc(virtual_account.get('status_note'))}<br>운용 방식: {_esc(virtual_account.get('strategy_summary'))}<br>최근 스냅샷 시각: {_esc(virtual_account.get('latest_snapshot_time'))}</div>
              <div class="pillrow" style="margin-top:12px;">
                <span class="pill">열린 포지션: {virtual_account.get('open_positions', 0)}건</span>
                <span class="pill">최근 종료 포지션: {virtual_account.get('closed_positions_count', 0)}건</span>
                <span class="pill">총 주문: {virtual_account.get('orders_total', 0)}건</span>
                <span class="pill">체결률: {_ratio_pct(virtual_account.get('fill_rate'), 1)}</span>
              </div>
              <div class="muted" style="margin-top:12px;">이 계좌는 프로그램 내부의 가상 장부입니다. 실제 장중 데이터로 신호를 만들고, 우리 규칙에 따라 모의주문과 모의체결을 기록합니다. 브로커 모의계좌와 값이 다를 수 있어도 이상이 아닙니다.</div>
            </div>
            <div id="virtual-holdings" class="subtab-panel" data-subtab-panel="virtual-paper">
              <h3>현재 보유 종목</h3>
              {_table(['종목','수량','평균 단가','현재가','평가 금액','미실현 손익'], virtual_position_rows, '현재 열린 가상 포지션은 없습니다. 아래 최근 종료 포지션을 함께 확인해 주세요.')}
              <div style="margin-top:18px;">
                <h3>최근 종료 포지션</h3>
                {_table(['종료 시각','종목','마지막 가격','실현 손익'], virtual_closed_position_rows, '기록된 최근 종료 포지션이 없습니다.')}
              </div>
            </div>
            <div id="virtual-activity" class="subtab-panel" data-subtab-panel="virtual-paper">
              {_pill_row([f"총 주문: {virtual_account.get('orders_total', 0)}건", f"매수 주문: {virtual_account.get('buy_orders', 0)}건", f"매도 주문: {virtual_account.get('sell_orders', 0)}건", f"체결: {virtual_account.get('fills', 0)}건", f"체결 수량: {virtual_account.get('fill_qty', 0)}주", f"포지션 비중: {_ratio_pct(virtual_account.get('capital_in_market_ratio'), 1)}"])}
              <div class="expand-tabs" role="tablist" aria-label="모의투자 가상 거래 세부 탭">
                {_subtab_button("virtual-activity", "virtual-activity-buy", f"매수 주문 {len(virtual_buy_order_rows)}건", active=True)}
                {_subtab_button("virtual-activity", "virtual-activity-sell", f"매도 주문 {len(virtual_sell_order_rows)}건")}
                {_subtab_button("virtual-activity", "virtual-activity-fills", f"체결 {len(virtual_fill_activity_rows)}건")}
                {_subtab_button("virtual-activity", "virtual-activity-signals", f"최근 신호 {len(virtual_signal_activity_rows)}건")}
              </div>
              <div id="virtual-activity-buy" class="expand-panel is-active" data-subtab-panel="virtual-activity">
                {_table(['시각','종목','수량','지정가','상태'], virtual_buy_order_rows, '최근 매수 주문이 없습니다.')}
              </div>
              <div id="virtual-activity-sell" class="expand-panel" data-subtab-panel="virtual-activity">
                {_table(['시각','종목','수량','지정가','상태'], virtual_sell_order_rows, '최근 매도 주문이 없습니다.')}
              </div>
              <div id="virtual-activity-fills" class="expand-panel" data-subtab-panel="virtual-activity">
                {_table(['시각','주문 ID','체결가','수량','수수료'], virtual_fill_activity_rows, '최근 체결이 없습니다.')}
              </div>
              <div id="virtual-activity-signals" class="expand-panel" data-subtab-panel="virtual-activity">
                {_table(['시각','종목','방향','허용 여부','설명'], virtual_signal_activity_rows, '최근 신호가 없습니다.')}
              </div>
              <div class="muted" style="margin-top:12px;">매도 주문과 매도 신호는 실제 숏 전략이 아니라, 보유 종목 청산 또는 하락 우세 판단에서 나온 내부 기록일 수 있습니다.</div>
            </div>
          </div>
        </div>
      </div>
    </section>
    <section id="tab-paper-broker" class="tab-panel"><div class="layout-2"><div class="stack"><div class="card"><h2>모의계좌(실제)</h2>{_pill_row(paper_account_pills)}<div class="muted" style="margin-top:12px;">최근 조회 시각: {_esc(paper_account.get('fetched_at'))}<br>조회 메모: {_esc(paper_account.get('account_note'))}<br>오류: {_esc(paper_account.get('error') or '없음')}</div></div><div class="card"><h3>보유 종목</h3>{_table(['종목','종목명','보유수량','현재가','평가금액','평가손익'], paper_position_rows, '브로커 모의계좌 보유 종목이 없습니다.')}</div></div><div class="stack"><div class="card"><h3>매수/매도 현황 안내</h3><div class="muted">현재 브로커 계좌 탭은 잔고와 보유 종목 중심으로 표시합니다. 브로커 주문·체결 내역을 별도 조회하는 기능은 아직 연결하지 않았습니다.</div></div><div class="card"><h3>설명</h3><div class="muted">한국투자 모의투자 계좌에서 직접 조회한 실제 잔고입니다. 로컬 모의운용 계좌와 값이 다를 수 있습니다.</div></div></div></div></section>
    <section id="tab-live-broker" class="tab-panel"><div class="layout-2"><div class="stack"><div class="card"><h2>실 운용계좌</h2>{_pill_row(live_account_pills)}<div class="muted" style="margin-top:12px;">최근 조회 시각: {_esc(live_account.get('fetched_at'))}<br>조회 메모: {_esc(live_account.get('account_note'))}<br>오류: {_esc(live_account.get('error') or '없음')}</div></div><div class="card"><h3>보유 종목</h3>{_table(['종목','종목명','보유수량','현재가','평가금액','평가손익'], live_position_rows, '실 운용계좌 정보가 없거나 아직 조회되지 않았습니다.')}</div></div><div class="stack"><div class="card"><h3>매수/매도 현황 안내</h3><div class="muted">실전 계좌는 현재 조회 위주로만 표시합니다. 실전 자격정보를 넣지 않았거나 조회를 일부러 막아둔 경우 빈 상태가 정상입니다.</div></div><div class="card"><h3>설명</h3><div class="muted">실전 계좌가 연결되면 보유 종목과 잔고를 같은 틀로 비교할 수 있습니다. 현재는 실전 주문 기능을 켜지 않았습니다.</div></div></div></div></section>
    <section id="tab-ml" class="tab-panel"><div class="layout-2"><div class="stack"><div class="card"><h2>머신러닝 현황</h2>{_pill_row(ml_status_pills)}<div class="muted" style="margin-top:12px;">{_esc(learning_context.get('note'))}<br>{_esc(learning_context.get('active_status_note'))}</div></div><div class="card"><h3>모델별 상태</h3>{_table(['구분','모델 버전','종류','상태','평가 점수','메모'], model_rows, '표시할 모델 상태가 없습니다.')}</div><div class="card"><h3>선택 기간 학습 결과</h3>{_table(['완료 시각','모델 버전','학습 행 수','검증 행 수','특징 세트'], today_training_rows, '현재 범위에 학습 기록이 없습니다.')}</div></div><div class="stack"><div class="card"><h3>선택 기간 평가 결과</h3>{_table(['평가 시각','분할 이름','정확도','행 수'], today_evaluation_rows, '현재 범위에 평가 기록이 없습니다.')}</div><div class="card"><h3>최신 검증 요약</h3>{_pill_row([f"최신 평가 정확도: {_ratio_pct(latest_evaluation.get('accuracy'), 2) if latest_evaluation else '-'}", f"백테스트 정확도: {_ratio_pct(latest_backtest.get('overall_accuracy'), 2) if latest_backtest else '-'}", f"워크포워드 정확도: {_ratio_pct(latest_walk_forward.get('overall_accuracy'), 2) if latest_walk_forward else '-'}", f"챌린저 권장: {latest_challenger.get('recommended_action') or '-'}"])}</div><div class="card"><h3>챌린저 비교</h3>{_table(['순위','후보','모델 버전','정확도','거래 적중률','누적 순수익률'], challenger_rows, '챌린저 비교 결과가 없습니다.')}</div><div class="card"><h3>워크포워드 상세</h3>{_table(['fold','정확도','거래 수','거래 적중률','누적 순수익률'], walk_forward_rows, '워크포워드 상세 결과가 없습니다.')}</div></div></div></section>
    <section id="tab-status" class="tab-panel"><div class="layout-2"><div class="stack"><div class="card"><h2>현재 프로그램 상태</h2>{_table(['항목','값'], status_rows, '상태 정보가 없습니다.')}<div class="muted" style="margin-top:12px;">{_esc(system_status.get('operation_note'))}<br>{_esc(live_runtime.get('status_note'))}</div></div><div class="card"><h3>KIS 연결 상태</h3>{_pill_row([f"연결 준비: {'예' if latest_kis.get('connection_ready') else '아니오'}", f"실데이터 수신: {'예' if latest_kis.get('market_data_flow_ok') else '아니오'}", f"승인 키 발급: {'예' if latest_kis.get('approval_key_issued') else '아니오'}", f"수신 프레임: {latest_kis.get('frames_received', 0)}", f"제어 프레임: {latest_kis.get('control_frames', 0)}"])}<div class="muted" style="margin-top:12px;">상태 메모: {_esc(latest_kis.get('status_note') or '-')}</div></div></div><div class="stack"><div class="card"><h3>운용 및 설정</h3>{_table(['항목','값'], setting_rows, '표시할 설정이 없습니다.')}</div><div class="card"><h3>집계 현황</h3>{_table(['항목','값'], runtime_rows, '표시할 집계가 없습니다.')}</div></div></div></section>
    <section id="tab-predictions" class="tab-panel"><div class="layout-2"><div class="stack"><div class="card"><h2>예측현황</h2>{_pill_row(prediction_status_pills + [f"최근 예측 시각: {prediction_summary.get('latest_prediction_time') or '-'}"])}<div class="muted" style="margin-top:12px;">예측 성공률은 실제 결과가 확정된 예측만 기준으로 계산합니다. 선택 기간 전체 기준으로 집계하며, 아래 표는 최근 예측 위주로 보여줍니다.</div></div><div class="card"><h3>예측 상세</h3>{_table(['시각','종목','수평선','모델','기준가','예측 결과 및 예상 변동','실제 결과','성공 여부'], prediction_rows, '현재 범위에 예측 기록이 없습니다.')}</div></div><div class="stack"><div class="card"><h3>수평선별 집계</h3>{_pill_row([f"{key}분: {value}건" for key, value in (prediction_summary.get('horizon_counts') or {}).items()] + [f"상승 예측: {(prediction_summary.get('predicted_label_counts') or {}).get('up', 0)}건", f"하락 예측: {(prediction_summary.get('predicted_label_counts') or {}).get('down', 0)}건", f"보합 예측: {(prediction_summary.get('predicted_label_counts') or {}).get('flat', 0)}건"] )}</div><div class="card"><h3>예측 해석 메모</h3><div class="muted">예측 결과는 기준가 대비 예상 변동 금액과 실제 결과를 함께 보여줍니다. 아직 목표 시점이 지나지 않은 예측은 실제 결과가 대기 중으로 표시됩니다. 실제 결과가 확정되면 성공/실패 판정이 함께 갱신됩니다.</div></div></div></div></section>
    <section id="tab-signal-orders" class="tab-panel"><div class="layout-2"><div class="stack"><div class="card"><h2>신호 & 주문현황</h2>{_pill_row(signal_status_pills + [f"최근 신호 시각: {signal_order_summary.get('latest_signal_time') or '-'}", f"최근 주문 시각: {signal_order_summary.get('latest_order_time') or '-'}", f"최근 체결 시각: {signal_order_summary.get('latest_fill_time') or '-'}"])}<div class="muted" style="margin-top:12px;">매도는 실제 매도 주문이라기보다, 모델이 하락 확률을 높게 본 원시 신호일 수 있습니다. 현재 기본 정책은 매수 전용이라 이런 매도 신호는 차단되는 것이 정상입니다.</div></div><div class="card"><h3>신호 기록</h3>{_table(['시각','종목코드','종목명','기준','방향','허용 여부','설명'], signal_rows, '현재 범위에 신호 기록이 없습니다.')}</div></div><div class="stack"><div class="card"><h3>주문 기록</h3>{_table(['시각','종목코드','방향','수량','지정가','상태'], order_rows, '현재 범위에 주문 기록이 없습니다.')}</div></div></div></section>
    <section id="tab-fills-bars" class="tab-panel"><div class="layout-2"><div class="stack"><div class="card"><h2>최근 체결</h2>{_table(['시각','주문 ID','체결가','수량','수수료'], fill_rows, '현재 범위에 실제 체결 기록이 없습니다.')}</div></div><div class="stack"><div class="card"><h2>최근 분봉</h2>{_table(['시각','종목','시가','고가','저가','종가','거래량'], bar_rows, '현재 범위에 분봉 기록이 없습니다.')}<div class="muted" style="margin-top:12px;">{_esc(system_status.get('minute_note'))}</div></div></div></div></section>
    <section id="tab-daily-report" class="tab-panel"><div class="layout-2"><div class="stack"><div class="card"><h2>오늘의 리포트</h2>{_pill_row([f"리포트 기준: {today_report.get('headline') or '-'}", f"실현 손익: {_money(virtual_account.get('realized_pnl'))}", f"브로커 예수금: {_money(paper_account.get('cash_balance'))}", f"체결: {signal_order_summary.get('fills', 0)}건", f"예측 성공률: {_ratio_pct(prediction_summary.get('success_rate'), 1)}"])}<div class="muted" style="margin-top:12px;">{_esc(today_report.get('summary'))}</div></div><div class="card"><h3>분석과 고찰</h3>{_list([_esc(item) for item in today_report.get('insights', [])], '기록된 분석이 없습니다.')}</div></div><div class="stack"><div class="card"><h3>향후 접근 방향</h3>{_list([_esc(item) for item in today_report.get('next_steps', [])], '기록된 다음 방향이 없습니다.')}</div></div></div></section>
    <section id="tab-other" class="tab-panel"><div class="layout-2"><div class="stack"><div class="card"><h2>자동 점검 요약</h2><div class="muted">{_esc(audit_progress.get('last_run_summary') or '자동 점검 요약이 아직 없습니다.')}</div><h3 style="margin-top:14px;">우선순위 backlog</h3>{_list(backlog_items, '표시할 backlog 항목이 없습니다.')}<h3 style="margin-top:14px;">다음 작업</h3>{_list(next_actions, '기록된 다음 작업이 없습니다.')}</div></div><div class="stack"><div class="card"><h3>안내</h3><div class="muted">이 화면은 실제 KIS 기반 운용 데이터만 보여줍니다. 샘플, synthetic, demo, replay 데이터는 제외됩니다. 조회 범위를 바꾸면 특정 날짜나 최근 기간 기준으로 데이터를 다시 볼 수 있습니다.</div></div></div></div></section>
  </div>
  <script>
    (() => {{
      const buttons = Array.from(document.querySelectorAll('[data-tab-target]'));
      const panels = Array.from(document.querySelectorAll('.tab-panel'));
      const refreshButton = document.getElementById('refresh-dashboard-button');
      const storageKey = 'realtime-stock-dashboard-active-tab';
      const activateSubtabGroup = (group, targetId) => {{
        const buttonsInGroup = Array.from(document.querySelectorAll(`[data-subtab-group="${{group}}"]`));
        const panelsInGroup = Array.from(document.querySelectorAll(`[data-subtab-panel="${{group}}"]`));
        const fallbackId = panelsInGroup.length ? panelsInGroup[0].id : '';
        const nextId = document.getElementById(targetId) ? targetId : fallbackId;
        buttonsInGroup.forEach((button) => {{
          const active = button.dataset.subtabTarget === nextId;
          button.classList.toggle('is-active', active);
          button.setAttribute('aria-selected', active ? 'true' : 'false');
        }});
        panelsInGroup.forEach((panel) => {{
          panel.classList.toggle('is-active', panel.id === nextId);
        }});
      }};
      const activate = (targetId) => {{
        const fallbackId = 'tab-virtual-paper';
        const nextId = document.getElementById(targetId) ? targetId : fallbackId;
        buttons.forEach((button) => {{
          const active = button.dataset.tabTarget === nextId;
          button.classList.toggle('is-active', active);
          button.setAttribute('aria-selected', active ? 'true' : 'false');
        }});
        panels.forEach((panel) => panel.classList.toggle('is-active', panel.id === nextId));
        if (window.location.hash !== `#${{nextId}}`) {{
          history.replaceState(null, '', `#${{nextId}}`);
        }}
        try {{
          window.localStorage.setItem(storageKey, nextId);
        }} catch (error) {{}}
      }};
      buttons.forEach((button) => button.addEventListener('click', () => activate(button.dataset.tabTarget)));
      Array.from(document.querySelectorAll('[data-subtab-group]')).forEach((button) => {{
        button.addEventListener('click', () => activateSubtabGroup(button.dataset.subtabGroup, button.dataset.subtabTarget));
      }});
      let initialTab = window.location.hash ? window.location.hash.slice(1) : '';
      if (!initialTab) {{
        try {{
          initialTab = window.localStorage.getItem(storageKey) || '';
        }} catch (error) {{
          initialTab = '';
        }}
      }}
      activate(initialTab || 'tab-virtual-paper');
      activateSubtabGroup('virtual-paper', 'virtual-overview');
      activateSubtabGroup('virtual-activity', 'virtual-activity-buy');
      window.addEventListener('hashchange', () => activate(window.location.hash.slice(1)));
      if (refreshButton) {{
        refreshButton.addEventListener('click', () => {{
          refreshButton.disabled = true;
          refreshButton.textContent = '업데이트 중...';
          window.location.reload();
        }});
      }}
    }})();
  </script>
</body>
</html>"""


@dataclass(slots=True)
class DashboardSnapshotResult:
    snapshot_html_path: Path
    snapshot_json_path: Path
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_html_path": str(self.snapshot_html_path),
            "snapshot_json_path": str(self.snapshot_json_path),
            "generated_at": self.payload.get("generated_at"),
        }


@dataclass(slots=True)
class DashboardServeInfo:
    host: str
    port: int
    refresh_seconds: int
    url: str
    snapshot_html_path: Path
    snapshot_json_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "refresh_seconds": self.refresh_seconds,
            "url": self.url,
            "snapshot_html_path": str(self.snapshot_html_path),
            "snapshot_json_path": str(self.snapshot_json_path),
        }


def build_dashboard_snapshot(
    project_root: Path,
    *,
    refresh_seconds: int = 300,
    recent_limit: int = 10,
    range_key: str | None = None,
    selected_date: str | None = None,
) -> DashboardSnapshotResult:
    settings = load_settings(project_root=project_root)
    payload = collect_dashboard_payload(
        project_root=project_root,
        recent_limit=recent_limit,
        range_key=range_key,
        selected_date=selected_date,
    )
    report_dir = settings.runtime_data_dir / "reports" / "dashboard"
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "latest-dashboard.json"
    html_path = report_dir / "latest-dashboard.html"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(_render_dashboard_html(payload, refresh_seconds=refresh_seconds, live_mode=False), encoding="utf-8")
    return DashboardSnapshotResult(snapshot_html_path=html_path, snapshot_json_path=json_path, payload=payload)


def _make_dashboard_handler(project_root: Path, *, refresh_seconds: int, recent_limit: int):
    class DashboardHandler(BaseHTTPRequestHandler):
        def _write_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _write_html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            encoded = body.encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            range_key = (params.get("range", ["today"])[0] or "today").strip().lower()
            selected_date = (params.get("date", [""])[0] or "").strip() or None
            if parsed.path in {"/", "/index.html"}:
                payload = collect_dashboard_payload(
                    project_root=project_root,
                    recent_limit=recent_limit,
                    range_key=range_key,
                    selected_date=selected_date,
                )
                self._write_html(_render_dashboard_html(payload, refresh_seconds=refresh_seconds, live_mode=True))
                return
            if parsed.path == "/api/dashboard.json":
                self._write_json(
                    collect_dashboard_payload(
                        project_root=project_root,
                        recent_limit=recent_limit,
                        range_key=range_key,
                        selected_date=selected_date,
                    )
                )
                return
            if parsed.path == "/health":
                self._write_json({"ok": True, "service": "dashboard"})
                return
            self._write_json({"ok": False, "error": "not-found"}, status=HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    return DashboardHandler


def prepare_dashboard_server(
    project_root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    refresh_seconds: int = 300,
    recent_limit: int = 10,
) -> tuple[ThreadingHTTPServer, DashboardServeInfo]:
    snapshot = build_dashboard_snapshot(
        project_root=project_root,
        refresh_seconds=refresh_seconds,
        recent_limit=recent_limit,
    )
    server = ThreadingHTTPServer((host, port), _make_dashboard_handler(project_root=project_root, refresh_seconds=refresh_seconds, recent_limit=recent_limit))
    actual_host, actual_port = server.server_address
    return server, DashboardServeInfo(
        host=str(actual_host),
        port=int(actual_port),
        refresh_seconds=refresh_seconds,
        url=f"http://{actual_host}:{actual_port}",
        snapshot_html_path=snapshot.snapshot_html_path,
        snapshot_json_path=snapshot.snapshot_json_path,
    )
