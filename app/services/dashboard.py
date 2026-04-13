"""Local monitoring dashboard for runtime operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config.settings import load_settings
from app.models.registry import ModelRegistry
from app.observability.logging import configure_logging
from app.services.kis_account import refresh_kis_account_report
from app.services.runtime_scope import build_runtime_scope, filter_actual_rows
from app.storage.runtime_writer import get_sqlite_store
from app.universe.symbol_metadata import load_symbol_names, resolve_symbol_label, resolve_symbol_name


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
                "top_confidence": round(top_confidence, 4),
                "base_close": base_close,
                "predicted_change_pct": round(expected_return_pct, 4),
                "predicted_change_amount": expected_change_amount,
                "predicted_change_text": _prediction_move_text(top_label, expected_change_amount, expected_return_pct),
                "actual_change_pct": None if actual_return_pct is None else round(actual_return_pct, 4),
                "actual_change_amount": actual_change_amount,
                "actual_change_text": _actual_move_text(
                    actual_change_amount,
                    actual_return_pct,
                    target_time_reached=target_time_reached,
                    has_actual_value=actual_change_amount is not None and actual_return_pct is not None,
                ),
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


def collect_dashboard_payload(project_root: Path, *, recent_limit: int = 10) -> dict[str, Any]:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = get_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for the dashboard.")

    scope = build_runtime_scope(sqlite_store, settings)
    symbol_names = load_symbol_names(project_root)
    runtime_summary = _summarize_runtime(sqlite_store, scope)
    minute_bar_rows = _filtered_rows(sqlite_store, "curated_minute_bars", "bar_time", scope)
    feature_label_rows = _filtered_rows(sqlite_store, "feature_labels", "event_time", scope)
    active_registry = ModelRegistry(settings.runtime_data_dir).load()
    latest_training = _parse_json_column(
        _serialize_row(sqlite_store.fetch_latest_row("ml_training_runs", "completed_at")),
        "training_summary_json",
        target_key="training_summary",
    )
    latest_evaluation = _parse_json_column(
        _serialize_row(sqlite_store.fetch_latest_row("ml_model_evaluations", "evaluated_at")),
        "metrics_json",
        target_key="metrics",
    )

    active_models = active_registry.get("active_models", {}) if isinstance(active_registry, dict) else {}
    active_model_entry = active_models.get("15", {}) if isinstance(active_models, dict) else {}
    active_model_entry_60 = active_models.get("60", {}) if isinstance(active_models, dict) else {}

    latest_snapshot_rows = _filtered_rows(sqlite_store, "paper_portfolio_snapshots", "event_time", scope)
    positions = _filtered_rows(sqlite_store, "paper_positions", "symbol", scope)
    try:
        broker_account_report = refresh_kis_account_report(project_root=project_root, max_age_seconds=60).to_dict()
    except Exception as exc:  # pragma: no cover - dashboard should stay up even if broker refresh fails
        broker_account_report = {
            "ok": False,
            "trading_mode": settings.trading_mode,
            "fetched_at": None,
            "cache_used": False,
            "cache_age_seconds": None,
            "error": str(exc),
            "source": "kis-broker",
            "account_snapshot": None,
        }
    recent_prediction_rows = _filtered_rows(sqlite_store, "serving_predictions", "event_time", scope)[-recent_limit:]
    recent_predictions = _prediction_view(
        recent_prediction_rows,
        symbol_names,
        minute_bar_rows=minute_bar_rows,
        feature_label_rows=feature_label_rows,
        settings=settings,
    )
    recent_signal_rows = _filtered_rows(sqlite_store, "serving_trade_signals", "event_time", scope)[-recent_limit:]
    recent_signals = _signal_view(recent_signal_rows, symbol_names)
    recent_orders = _filtered_rows(sqlite_store, "paper_orders", "event_time", scope)[-recent_limit:]
    recent_fills = _filtered_rows(sqlite_store, "paper_fills", "event_time", scope)[-recent_limit:]
    recent_bars = minute_bar_rows[-recent_limit:]
    live_runtime_state = _normalize_live_runtime_state(
        _safe_load_json(settings.runtime_data_dir / "reports" / "live-runtime" / "state" / "listener-state.json")
    )
    latest_market_bar_time = _latest_time(recent_bars, "bar_time")
    latest_prediction_time = _latest_time(recent_predictions, "event_time")
    latest_signal_time = _latest_time(recent_signals, "event_time")
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
    local_account_state = {
        "status": "운용 중" if live_runtime_state.get("status") == "running" else "대기 중",
        "status_note": (
            "실시간 수집기가 켜져 있어 새 분이 닫힐 때마다 예측과 신호, 주문 후보를 계속 갱신합니다."
            if live_runtime_state.get("status") == "running"
            else "실시간 수집기가 꺼져 있어 마지막 기록만 보입니다."
        ),
    }

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "dashboard_scope": {
            "actual_runtime_only": True,
            "actual_symbol_minutes": len(scope.actual_symbol_minutes),
            "actual_order_ids": len(scope.actual_order_ids),
        },
        "project": {
            "name": settings.app_name,
            "environment": settings.app_env,
            "trading_mode": settings.trading_mode,
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
        "latest_training": latest_training,
        "latest_evaluation": latest_evaluation,
        "latest_backtest_report": _safe_load_json(settings.runtime_data_dir / "reports" / "backtests" / "latest-backtest-h15.json"),
        "latest_walk_forward_report": _safe_load_json(settings.runtime_data_dir / "reports" / "backtests" / "latest-walk-forward-h15.json"),
        "latest_challenger_report": _safe_load_json(settings.runtime_data_dir / "reports" / "challengers" / "latest-challengers-h15.json"),
        "latest_kis_verification": _safe_load_json(settings.runtime_data_dir / "reports" / "kis-ws" / "latest-verification.json"),
        "latest_portfolio_snapshot": latest_snapshot_rows[-1] if latest_snapshot_rows else None,
        "positions": positions,
        "broker_account_report": broker_account_report,
        "recent_predictions": recent_predictions,
        "recent_signals": recent_signals,
        "recent_orders": recent_orders,
        "recent_fills": recent_fills,
        "recent_minute_bars": recent_bars,
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


def _render_dashboard_html(payload: dict[str, Any], *, refresh_seconds: int, live_mode: bool) -> str:
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


def build_dashboard_snapshot(project_root: Path, *, refresh_seconds: int = 300, recent_limit: int = 10) -> DashboardSnapshotResult:
    settings = load_settings(project_root=project_root)
    payload = collect_dashboard_payload(project_root=project_root, recent_limit=recent_limit)
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
            if parsed.path in {"/", "/index.html"}:
                payload = collect_dashboard_payload(project_root=project_root, recent_limit=recent_limit)
                self._write_html(_render_dashboard_html(payload, refresh_seconds=refresh_seconds, live_mode=True))
                return
            if parsed.path == "/api/dashboard.json":
                self._write_json(collect_dashboard_payload(project_root=project_root, recent_limit=recent_limit))
                return
            if parsed.path == "/health":
                self._write_json({"ok": True, "service": "dashboard"})
                return
            self._write_json({"ok": False, "error": "not-found"}, status=HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    return DashboardHandler


def prepare_dashboard_server(project_root: Path, *, host: str = "127.0.0.1", port: int = 8765, refresh_seconds: int = 300, recent_limit: int = 10) -> tuple[ThreadingHTTPServer, DashboardServeInfo]:
    snapshot = build_dashboard_snapshot(project_root=project_root, refresh_seconds=refresh_seconds, recent_limit=recent_limit)
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
