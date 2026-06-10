"""Local monitoring dashboard for runtime operations."""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from time import sleep
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from app.config.settings import load_settings
from app.models.lightgbm_model import LightGbmDirectionModel, find_latest_lightgbm_artifact
from app.models.registry import ModelRegistry
from app.observability.logging import configure_logging
from app.services.kis_account import refresh_kis_account_report
from app.services.live_execution_sync import build_live_order_fill_consistency_summary_from_store
from app.services.live_order_monitoring import (
    build_live_order_attention_summary_from_store,
    build_live_phase2_parent_order_limit_summary_from_store,
    live_order_attention_summary_to_dict,
    live_phase2_parent_order_limit_summary_to_dict,
)
from app.services.ws_recovery_evidence import is_real_ws_recovery_evidence_type
from app.services.paper_alignment import apply_alignment_baseline, filter_rows_after_alignment
from app.services.paper_reconciliation import build_paper_account_reconciliation_payload, load_local_paper_account_state
from app.services.runtime_scope import build_runtime_scope, filter_actual_rows
from app.storage.runtime_writer import get_sqlite_store
from app.universe.symbol_metadata import load_symbol_names, resolve_symbol_label, resolve_symbol_name
from app.utils.time import get_market_session_status, get_timezone, now_local


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


def _write_text_with_retries(path: Path, content: str, *, encoding: str = "utf-8", attempts: int = 6) -> None:
    last_error: OSError | None = None
    for attempt in range(max(attempts, 1)):
        temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temp_path.write_text(content, encoding=encoding)
            temp_path.replace(path)
            return
        except OSError as exc:
            last_error = exc
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            if attempt + 1 >= attempts:
                break
            sleep(0.2 * (attempt + 1))

    if last_error is not None:
        raise last_error


def _load_cached_dashboard_payload(project_root: Path) -> dict[str, Any] | None:
    settings = load_settings(project_root=project_root)
    cached = _safe_load_json(settings.runtime_data_dir / "reports" / "dashboard" / "latest-dashboard.json")
    return cached if isinstance(cached, dict) else None


def _should_use_cached_dashboard(*, path: str, range_key: str, selected_date: str | None, refresh_requested: bool) -> bool:
    if refresh_requested:
        return False
    if path not in {"/", "/index.html", "/api/dashboard.json"}:
        return False
    if range_key != "today":
        return False
    if selected_date:
        return False
    return True


def _mark_dashboard_payload_stale(payload: dict[str, Any], *, message: str, detail: str) -> dict[str, Any]:
    stale_payload = json.loads(json.dumps(payload, ensure_ascii=False))
    stale_payload["stale_fallback"] = {
        "active": True,
        "message": message,
        "detail": detail,
        "served_at": datetime.now().astimezone().isoformat(),
    }
    system_status = stale_payload.setdefault("system_status", {})
    current_note = str(system_status.get("operation_note") or "")
    fallback_note = f"{message} 마지막 정상 스냅샷을 대신 보여주고 있습니다."
    system_status["operation_note"] = f"{fallback_note} {current_note}".strip()
    return stale_payload


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


def _filtered_rows(
    sqlite_store,
    table_name: str,
    order_by: str,
    scope,
    period_filter: DashboardPeriodFilter | None = None,
) -> list[dict[str, Any]]:
    if (
        period_filter is not None
        and period_filter.start_at is not None
        and period_filter.end_at is not None
        and order_by in {"bar_time", "event_time", "completed_at", "evaluated_at", "as_of"}
    ):
        rows = [
            dict(row)
            for row in sqlite_store.fetch_rows_between(
                table_name,
                order_by,
                period_filter.start_at.isoformat(),
                period_filter.end_at.isoformat(),
                order_by,
            )
        ]
    else:
        rows = [dict(row) for row in sqlite_store.fetch_all_rows(table_name, order_by)]
    return filter_actual_rows(table_name, rows, scope)


def _raw_count_from_scope(scope, table_name: str, period_filter: DashboardPeriodFilter | None = None) -> int:
    counts_by_minute = getattr(scope, "actual_raw_counts_by_table", {}).get(table_name, {})
    if period_filter is None or period_filter.start_at is None or period_filter.end_at is None:
        return int(sum(counts_by_minute.values()))
    total = 0
    for (_, minute_text), count in counts_by_minute.items():
        minute_time = _parse_iso_datetime(f"{minute_text}:00")
        if minute_time is None:
            continue
        if minute_time.tzinfo is None and period_filter.start_at.tzinfo is not None:
            minute_time = minute_time.replace(tzinfo=period_filter.start_at.tzinfo)
        if period_filter.start_at <= minute_time < period_filter.end_at:
            total += int(count)
    return total


def _build_live_fill_consistency_view(sqlite_store, *, trading_day: str) -> dict[str, Any]:
    try:
        summary = build_live_order_fill_consistency_summary_from_store(sqlite_store, trading_day=trading_day)
    except Exception as exc:  # pragma: no cover - dashboard must stay available on partial live schema.
        return {
            "status": "unknown",
            "trading_day": trading_day,
            "checked_order_count": 0,
            "mismatch_count": 0,
            "mismatches": [],
            "error": str(exc),
        }
    status = "empty" if summary.checked_order_count == 0 else "ok" if summary.ok else "mismatch"
    return {
        "status": status,
        "trading_day": summary.trading_day,
        "checked_order_count": summary.checked_order_count,
        "mismatch_count": summary.mismatch_count,
        "mismatches": [
            {
                "order_id": item.order_id,
                "order_filled_qty": item.order_filled_qty,
                "live_fill_qty_sum": item.live_fill_qty_sum,
            }
            for item in summary.mismatches
        ],
        "error": None,
    }


def _build_live_order_attention_view(sqlite_store, *, trading_day: str, now: datetime) -> dict[str, Any]:
    try:
        summary = build_live_order_attention_summary_from_store(sqlite_store, trading_day=trading_day, now=now)
    except Exception as exc:  # pragma: no cover - dashboard must stay available on partial live schema.
        return {
            "status": "unknown",
            "trading_day": trading_day,
            "checked_order_count": 0,
            "open_order_count": 0,
            "attention_count": 0,
            "max_attention_age_minutes": None,
            "attention_orders": [],
            "error": str(exc),
        }
    return live_order_attention_summary_to_dict(summary)


def _build_live_phase2_parent_order_limit_view(sqlite_store, *, trading_day: str) -> dict[str, Any]:
    try:
        summary = build_live_phase2_parent_order_limit_summary_from_store(sqlite_store, trading_day=trading_day)
    except Exception as exc:  # pragma: no cover - dashboard must stay available on partial live schema.
        return {
            "status": "unknown",
            "trading_day": trading_day,
            "max_parent_orders_per_day": 1,
            "checked_order_count": 0,
            "parent_order_count": 0,
            "blocked_parent_order_count": 0,
            "remaining_parent_orders": 0,
            "blocked_by_limit": False,
            "parent_orders": [],
            "error": str(exc),
        }
    return live_phase2_parent_order_limit_summary_to_dict(summary)


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

    anchor_date = selected_date if normalized_range == "today" else selected_date
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
        if anchor_date == today_local:
            label = "오늘"
            description = "오늘 발생한 실제 운용 데이터만 보여줍니다."
        else:
            label = f"최근 장중 ({anchor_date.isoformat()})"
            description = "현재 날짜에 장중 기록이 없어, 마지막 실제 장중 날짜 기준으로 보여줍니다."

    return DashboardPeriodFilter(
        range_key=normalized_range,
        selected_date=anchor_date.isoformat(),
        label=label,
        description=description,
        start_at=datetime.combine(start_date, time.min, tzinfo=timezone),
        end_at=datetime.combine(end_date, time.min, tzinfo=timezone),
    )


def _resolve_default_dashboard_date(
    settings,
    *,
    minute_bar_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
    signal_rows: list[dict[str, Any]],
) -> str | None:
    latest_timestamp: datetime | None = None
    for rows, field_name in (
        (minute_bar_rows, "bar_time"),
        (prediction_rows, "event_time"),
        (signal_rows, "event_time"),
    ):
        for row in rows:
            parsed = _parse_iso_datetime(row.get(field_name))
            if parsed is None:
                continue
            if latest_timestamp is None or parsed > latest_timestamp:
                latest_timestamp = parsed
    if latest_timestamp is None:
        return None

    today_local = now_local(settings.timezone).date()
    latest_local_date = latest_timestamp.astimezone(get_timezone(settings.timezone)).date()
    if latest_local_date < today_local:
        return latest_local_date.isoformat()
    return None


def _resolve_default_dashboard_date_from_scope(settings, scope) -> str | None:
    latest_minute = max(getattr(scope, "actual_global_minutes", set()) or {""})
    if not latest_minute:
        return None
    latest_timestamp = _parse_iso_datetime(f"{latest_minute}:00")
    if latest_timestamp is None:
        return None
    today_local = now_local(settings.timezone).date()
    latest_local_date = latest_timestamp.astimezone(get_timezone(settings.timezone)).date()
    if latest_local_date < today_local:
        return latest_local_date.isoformat()
    return None


def _period_filter_from_runtime_scope(settings, scope) -> DashboardPeriodFilter | None:
    minutes = sorted(getattr(scope, "actual_global_minutes", set()) or [])
    if not minutes:
        return None
    start_at = _parse_iso_datetime(f"{minutes[0]}:00")
    end_at = _parse_iso_datetime(f"{minutes[-1]}:00")
    if start_at is None or end_at is None:
        return None
    return DashboardPeriodFilter(
        range_key="actual-scope",
        selected_date=start_at.astimezone(get_timezone(settings.timezone)).date().isoformat(),
        label="actual-scope",
        description="actual runtime scope",
        start_at=start_at,
        end_at=end_at + timedelta(minutes=1),
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


def _summarize_runtime(sqlite_store, scope, settings) -> dict[str, int]:
    evaluation_rows = [dict(row) for row in sqlite_store.fetch_all_rows("ml_model_evaluations", "evaluated_at")]
    scope_filter = _period_filter_from_runtime_scope(settings, scope)
    return {
        "raw_market_ticks": _raw_count_from_scope(scope, "raw_market_ticks"),
        "raw_orderbook_ticks": _raw_count_from_scope(scope, "raw_orderbook_ticks"),
        "minute_bars": len(_filtered_rows(sqlite_store, "curated_minute_bars", "bar_time", scope, scope_filter)),
        "feature_rows": len(_filtered_rows(sqlite_store, "feature_model_inputs", "event_time", scope, scope_filter)),
        "labels": len(_filtered_rows(sqlite_store, "feature_labels", "event_time", scope, scope_filter)),
        "predictions": len(_filtered_rows(sqlite_store, "serving_predictions", "event_time", scope, scope_filter)),
        "signals": len(_filtered_rows(sqlite_store, "serving_trade_signals", "event_time", scope, scope_filter)),
        "orders": len(_filtered_rows(sqlite_store, "paper_orders", "event_time", scope)),
        "fills": len(_filtered_rows(sqlite_store, "paper_fills", "event_time", scope)),
        "broker_order_submissions": len(_filtered_rows(sqlite_store, "broker_paper_order_submissions", "event_time", scope)),
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
    result_status: str,
    has_actual_value: bool,
) -> str:
    if has_actual_value:
        return _format_signed_change(amount, pct)
    return "결과 없음" if result_status == "no_result" else "대기 중"


def _parse_market_clock(value: str | None, *, fallback: str = "15:30") -> time:
    raw = str(value or fallback).strip() or fallback
    try:
        hour_text, minute_text, *_ = raw.split(":")
        return time(int(hour_text), int(minute_text))
    except (TypeError, ValueError):
        hour_text, minute_text = fallback.split(":")
        return time(int(hour_text), int(minute_text))


def _prediction_outcome_is_closed(
    *,
    event_time: datetime | None,
    target_time: datetime | None,
    latest_symbol_time: datetime | None,
    settings,
) -> bool:
    if event_time is None or target_time is None:
        return True

    timezone = get_timezone(settings.timezone)
    now = now_local(settings.timezone)
    event_local = event_time.astimezone(timezone)
    target_local = target_time.astimezone(timezone)
    latest_local = latest_symbol_time.astimezone(timezone) if latest_symbol_time is not None else None
    close_time = _parse_market_clock(settings.market_calendar.session_close)
    close_at = datetime.combine(event_local.date(), close_time, tzinfo=timezone)

    if latest_symbol_time is not None and latest_symbol_time >= target_time:
        return True
    if now >= target_local:
        return True
    if event_local.date() < now.date():
        return True
    if now >= close_at and target_local > close_at:
        return True
    if latest_local is not None and latest_local.date() > event_local.date():
        return True
    if latest_local is not None and latest_local.date() == event_local.date() and latest_local >= close_at and target_local > latest_local:
        return True
    return False


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


def _build_bar_lookup(
    rows: list[dict[str, Any]]
) -> tuple[
    dict[tuple[str, str], dict[str, Any]],
    dict[str, datetime],
    dict[str, dict[str, list[Any]]],
]:
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    latest_by_symbol: dict[str, datetime] = {}
    unsorted_entries: defaultdict[str, list[tuple[datetime, dict[str, Any]]]] = defaultdict(list)
    for row in rows:
        symbol = str(row.get("symbol", ""))
        bar_time = str(row.get("bar_time", ""))
        lookup[(symbol, bar_time)] = row
        parsed = _parse_iso_datetime(bar_time)
        if parsed is None:
            continue
        unsorted_entries[symbol].append((parsed, row))
        existing = latest_by_symbol.get(symbol)
        if existing is None or parsed > existing:
            latest_by_symbol[symbol] = parsed

    bar_index: dict[str, dict[str, list[Any]]] = {}
    for symbol, entries in unsorted_entries.items():
        entries.sort(key=lambda item: item[0])
        bar_index[symbol] = {
            "times": [item[0] for item in entries],
            "rows": [item[1] for item in entries],
        }
    return lookup, latest_by_symbol, bar_index


def _build_label_lookup(rows: list[dict[str, Any]]) -> dict[tuple[str, str, int], dict[str, Any]]:
    return {
        (str(row.get("symbol", "")), str(row.get("event_time", "")), int(row.get("horizon_min", 0))): row
        for row in rows
    }


def _find_first_same_day_bar_at_or_after(
    bar_index: dict[str, dict[str, list[Any]]],
    *,
    symbol: str,
    target_time: datetime,
) -> dict[str, Any] | None:
    index_entry = bar_index.get(symbol)
    if not index_entry:
        return None
    bar_times = index_entry.get("times") or []
    bar_rows = index_entry.get("rows") or []
    if not bar_times or not bar_rows:
        return None
    candidate_index = bisect_left(bar_times, target_time)
    while candidate_index < len(bar_times):
        candidate_time = bar_times[candidate_index]
        if candidate_time.date() != target_time.date():
            return None
        return bar_rows[candidate_index]
    return None


def _effective_active_model_entry(
    settings,
    *,
    active_entry: dict[str, Any] | None,
    horizon_min: int,
) -> dict[str, Any]:
    if isinstance(active_entry, dict) and active_entry.get("model_version"):
        normalized = dict(active_entry)
        normalized.setdefault("status", "registry")
        return normalized
    fallback_model_version = settings.model_version_h60 if int(horizon_min) == 60 else settings.model_version_h15
    return {
        "model_version": fallback_model_version,
        "model_kind": "builtin",
        "builtin_name": "baseline",
        "status": "builtin_fallback",
        "note": "활성 레지스트리가 없어서 기본 baseline 모델을 사용 중입니다.",
    }


def _signal_reason_summary(row: dict[str, Any]) -> str:
    reason_text = str(row.get("reason", ""))
    tokens = [item.strip() for item in reason_text.split(";") if item.strip()]
    token_map = dict(item.split("=", 1) for item in tokens if "=" in item)
    summaries: list[str] = []
    if "long_only_policy" in tokens and str(row.get("side")) == "sell":
        summaries.append("하락 예측이었지만 현재 전략이 매수 전용이라 차단")
    if "spread_gate=spread_too_wide" in tokens:
        summaries.append("호가 스프레드가 넓어 차단")
    if "spread_gate=spread_ok" in tokens:
        summaries.append("호가 스프레드 통과")
    if "confidence_below_threshold" in tokens:
        summaries.append("신뢰도가 기준치보다 낮음")
    if "time_gate=outside_window" in tokens:
        summaries.append("허용 시간대 밖이라 차단")
    if "time_gate=after_new_entry_window" in tokens:
        summaries.append("신규 진입 허용 시간 종료")
    if "time_gate=within_window" in tokens:
        summaries.append("신규 진입 시간 통과")
    if token_map.get("model"):
        summaries.append(f"모델 {token_map['model']}")
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


def _build_freshness_snapshot(
    timestamp_text: str | None,
    *,
    timezone_name: str,
    warning_after_minutes: int,
    stale_after_minutes: int,
    missing_label: str,
) -> dict[str, Any]:
    parsed = _parse_iso_datetime(timestamp_text)
    if parsed is None:
        return {
            "available": False,
            "timestamp": None,
            "age_minutes": None,
            "state": "missing",
            "label": missing_label,
            "note": missing_label,
        }

    timezone = get_timezone(timezone_name)
    localized = parsed.astimezone(timezone) if parsed.tzinfo else parsed.replace(tzinfo=timezone)
    age_minutes = max((now_local(timezone_name) - localized).total_seconds() / 60.0, 0.0)

    if age_minutes <= warning_after_minutes:
        state = "fresh"
        label = "최신"
    elif age_minutes <= stale_after_minutes:
        state = "aging"
        label = "주의"
    else:
        state = "stale"
        label = "지연"

    rounded_age = int(round(age_minutes))
    if rounded_age < 1:
        age_text = "방금 전"
    elif rounded_age < 60:
        age_text = f"{rounded_age}분 전"
    elif rounded_age < 1440:
        hours = rounded_age // 60
        minutes = rounded_age % 60
        age_text = f"{hours}시간 {minutes}분 전" if minutes else f"{hours}시간 전"
    else:
        days = rounded_age // 1440
        hours = (rounded_age % 1440) // 60
        age_text = f"{days}일 {hours}시간 전" if hours else f"{days}일 전"

    return {
        "available": True,
        "timestamp": localized.isoformat(),
        "age_minutes": round(age_minutes, 2),
        "state": state,
        "label": label,
        "note": f"{age_text} 업데이트",
    }


def _build_status_alerts(
    *,
    live_runtime_state: dict[str, Any],
    latest_kis_verification: dict[str, Any] | None,
    freshness: dict[str, Any],
    runtime_summary: dict[str, int],
    latest_training: dict[str, Any] | None,
    latest_evaluation: dict[str, Any] | None,
) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    runtime_status = str(live_runtime_state.get("status") or "").lower()
    session_status = str((latest_kis_verification or {}).get("session_status") or "").lower()
    market_bar_freshness = freshness.get("latest_market_bar", {}) or {}
    prediction_freshness = freshness.get("latest_prediction", {}) or {}
    kis_freshness = freshness.get("latest_kis_verification", {}) or {}
    training_freshness = freshness.get("latest_training", {}) or {}
    evaluation_freshness = freshness.get("latest_evaluation", {}) or {}
    latest_kis = latest_kis_verification or {}
    live_market_data_fresh = runtime_status == "running" and market_bar_freshness.get("state") == "fresh"

    if runtime_status != "running":
        alerts.append(
            {
                "level": "warning",
                "title": "실시간 수집기가 멈춰 있습니다",
                "message": "분봉, 예측, 신호는 실시간 수집기가 살아 있어야 계속 갱신됩니다. 우선 현재 상태를 먼저 확인해 주세요.",
            }
        )
    elif market_bar_freshness.get("state") == "stale":
        if session_status == "regular-session":
            alerts.append(
                {
                    "level": "warning",
                    "title": "실시간 분봉 갱신이 지연되고 있습니다",
                    "message": f"최근 분봉 시각이 오래됐습니다. 현재 상태는 {market_bar_freshness.get('note') or '지연'} 입니다.",
                }
            )
        else:
            alerts.append(
                {
                    "level": "info",
                    "title": "최근 분봉은 마지막 장중 기록 기준입니다",
                    "message": f"현재 장외 상태라 분봉이 더 늘지 않을 수 있습니다. 마지막 분봉 기준은 {market_bar_freshness.get('timestamp') or '-'} 입니다.",
                }
            )

    kis_failure_message = latest_kis.get("error") or latest_kis.get("status_note") or "실시간 수신이 확인되지 않았습니다."
    kis_regular_session_failure = latest_kis and (
        (session_status == "regular-session" and latest_kis.get("ok") is False)
        or (session_status == "regular-session" and latest_kis.get("connection_ready") is False)
        or (session_status == "regular-session" and latest_kis.get("market_data_flow_ok") is False)
    )
    if kis_regular_session_failure and not live_market_data_fresh:
        alerts.append(
            {
                "level": "warning",
                "title": "KIS 실시간 검증이 실패했습니다",
                "message": f"{kis_failure_message}",
            }
        )
    elif latest_kis and latest_kis.get("ok") is False and session_status in {"weekend", "holiday", "overnight", "pre-open", "post-close"}:
        alerts.append(
            {
                "level": "info",
                "title": "KIS 검증은 장외 기준으로 기록되었습니다",
                "message": f"{latest_kis.get('status_note') or kis_failure_message}",
            }
        )
    elif latest_kis and kis_freshness.get("state") == "stale":
        alerts.append(
            {
                "level": "info",
                "title": "KIS 연결 검증 기록이 오래되었습니다",
                "message": f"마지막 검증 시각은 {latest_kis.get('verified_at') or '-'} 이고, 현재 신선도는 {kis_freshness.get('label') or '지연'} 입니다.",
            }
        )

    if prediction_freshness.get("state") == "stale" and runtime_summary.get("predictions", 0) > 0:
        if session_status == "regular-session":
            alerts.append(
                {
                    "level": "info",
                    "title": "최근 예측 기록이 멈춰 보입니다",
                    "message": f"최근 예측 시각이 오래됐습니다. 현재 상태는 {prediction_freshness.get('note') or '지연'} 입니다.",
                }
            )
        else:
            alerts.append(
                {
                    "level": "info",
                    "title": "최근 예측은 마지막 장중 계산 기준입니다",
                    "message": f"현재 장외 상태라 새 예측이 더 쌓이지 않을 수 있습니다. 마지막 예측 기준은 {prediction_freshness.get('timestamp') or '-'} 입니다.",
                }
            )

    if session_status != "regular-session" and runtime_summary.get("training_runs", 0) == 0:
        if latest_training is None:
            alerts.append(
                {
                    "level": "info",
                    "title": "최근 학습 기록이 없습니다",
                    "message": "최근 전체 학습 기록을 찾지 못했습니다. 장후 재학습 경로를 한 번 점검해 주세요.",
                }
            )
        elif training_freshness.get("state") == "stale":
            alerts.append(
                {
                    "level": "info",
                    "title": "최근 학습 기록이 오래되었습니다",
                    "message": f"최근 전체 학습 결과는 {latest_training.get('completed_at') or '-'} 기준이며, 현재 신선도는 {training_freshness.get('label') or '-'} 입니다.",
                }
            )

    if session_status != "regular-session" and runtime_summary.get("evaluations", 0) == 0:
        if latest_evaluation is None:
            alerts.append(
                {
                    "level": "info",
                    "title": "최근 평가 기록이 없습니다",
                    "message": "backtest, walk-forward, challenger 같은 최신 평가 기록을 찾지 못했습니다.",
                }
            )
        elif evaluation_freshness.get("state") == "stale":
            alerts.append(
                {
                    "level": "info",
                    "title": "최근 평가 기록이 오래되었습니다",
                    "message": f"최근 전체 평가 결과는 {latest_evaluation.get('evaluated_at') or '-'} 기준이며, 현재 신선도는 {evaluation_freshness.get('label') or '-'} 입니다.",
                }
            )

    return alerts[:4]

    if runtime_status != "running":
        alerts.append(
            {
                "level": "warning",
                "title": "실시간 수집기가 멈춰 있습니다",
                "message": "장중 예측과 신호는 실시간 수집기가 살아 있어야 계속 갱신됩니다. 런타임 상태를 먼저 확인해 주세요.",
            }
        )
    elif market_bar_freshness.get("state") == "stale":
        alerts.append(
            {
                "level": "warning",
                "title": "실시간 분봉 갱신이 지연되고 있습니다",
                "message": f"최근 분봉 시각이 오래됐습니다. 현재 상태는 {market_bar_freshness.get('note') or '지연'} 입니다.",
            }
        )

    kis_failure_message = latest_kis.get("error") or latest_kis.get("status_note") or "실시간 수신이 확인되지 않았습니다."
    if latest_kis and (
        (session_status == "regular-session" and latest_kis.get("ok") is False)
        or (session_status == "regular-session" and latest_kis.get("connection_ready") is False)
        or (session_status == "regular-session" and latest_kis.get("market_data_flow_ok") is False)
    ):
        alerts.append(
            {
                "level": "warning",
                "title": "KIS 실시간 검증이 실패했습니다",
                "message": f"{kis_failure_message}",
            }
        )
    elif latest_kis and latest_kis.get("ok") is False and session_status in {"weekend", "holiday", "overnight", "pre-open", "post-close"}:
        alerts.append(
            {
                "level": "info",
                "title": "KIS 검증은 장외 기준으로 기록되었습니다",
                "message": f"{latest_kis.get('status_note') or kis_failure_message}",
            }
        )
    elif latest_kis and kis_freshness.get("state") == "stale":
        alerts.append(
            {
                "level": "info",
                "title": "KIS 연결 검증 기록이 오래되었습니다",
                "message": f"마지막 검증 시각은 {latest_kis.get('verified_at') or '-'} 이고, 현재 신선도는 {kis_freshness.get('label') or '지연'} 입니다.",
            }
        )

    if prediction_freshness.get("state") == "stale" and runtime_summary.get("predictions", 0) > 0:
        alerts.append(
            {
                "level": "info",
                "title": "최근 예측 기록이 멈춰 보입니다",
                "message": f"최근 예측 시각이 오래됐습니다. 현재 상태는 {prediction_freshness.get('note') or '지연'} 입니다.",
            }
        )

    if session_status != "regular-session" and runtime_summary.get("training_runs", 0) == 0:
        if latest_training is None:
            alerts.append(
                {
                    "level": "info",
                    "title": "최근 학습 기록이 없습니다",
                    "message": "최근 전체 학습 기록을 찾지 못했습니다. 장후 재학습 경로를 한 번 점검해 주세요.",
                }
            )
        elif training_freshness.get("state") == "stale":
            alerts.append(
                {
                    "level": "info",
                    "title": "최근 학습 기록이 오래되었습니다",
                    "message": f"최근 전체 학습 결과는 {latest_training.get('completed_at') or '-'} 기준이며, 현재 신선도는 {training_freshness.get('label') or '-'} 입니다.",
                }
            )

    if session_status != "regular-session" and runtime_summary.get("evaluations", 0) == 0:
        if latest_evaluation is None:
            alerts.append(
                {
                    "level": "info",
                    "title": "최근 평가 기록이 없습니다",
                    "message": "backtest, walk-forward, challenger 같은 최신 평가 기록을 찾지 못했습니다.",
                }
            )
        elif evaluation_freshness.get("state") == "stale":
            alerts.append(
                {
                    "level": "info",
                    "title": "최근 평가 기록이 오래되었습니다",
                    "message": f"최근 전체 평가 결과는 {latest_evaluation.get('evaluated_at') or '-'} 기준이며, 현재 신선도는 {evaluation_freshness.get('label') or '-'} 입니다.",
                }
            )

    return alerts[:4]


def _prediction_view(
    rows: list[dict[str, Any]],
    symbol_names: dict[str, str],
    *,
    minute_bar_rows: list[dict[str, Any]],
    feature_label_rows: list[dict[str, Any]],
    settings,
) -> list[dict[str, Any]]:
    bar_lookup, latest_bar_time_by_symbol, bar_index = _build_bar_lookup(minute_bar_rows)
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
        result_status = "pending"
        if event_time is not None:
            target_time = event_time + timedelta(minutes=horizon_min)
            future_bar = _find_first_same_day_bar_at_or_after(
                bar_index,
                symbol=symbol,
                target_time=target_time,
            )
            latest_symbol_time = latest_bar_time_by_symbol.get(symbol)
            if future_bar and base_close not in (None, 0):
                future_close = float(future_bar["close"])
                actual_change_amount = future_close - base_close
                actual_return_pct = ((future_close / base_close) - 1.0) * 100.0
            else:
                label_row = label_lookup.get((symbol, event_time_text, horizon_min))
                if label_row and base_close not in (None, 0):
                    actual_return_pct = float(label_row.get("future_return_pct", 0.0))
                    actual_change_amount = base_close * actual_return_pct / 100.0
            result_status = (
                "no_result"
                if actual_return_pct is None
                and _prediction_outcome_is_closed(
                    event_time=event_time,
                    target_time=target_time,
                    latest_symbol_time=latest_symbol_time,
                    settings=settings,
                )
                else "pending"
            )
        actual_label = _classify_actual_label(actual_return_pct, threshold_pct)
        success = actual_label == top_label if actual_label is not None else None
        if actual_label is not None:
            result_status = "evaluated"
        actual_label_text = (
            _translate_prediction_label(actual_label)
            if actual_label is not None
            else ("결과 없음" if result_status == "no_result" else "대기 중")
        )
        success_text = (
            "성공"
            if success is True
            else ("실패" if success is False else ("결과 없음" if result_status == "no_result" else "대기 중"))
        )

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
                "actual_label_text": actual_label_text,
                "actual_change_text": _actual_move_text(
                    actual_change_amount,
                    actual_return_pct,
                    result_status=result_status,
                    has_actual_value=actual_change_amount is not None and actual_return_pct is not None,
                ),
                "result_status": result_status,
                "success": success,
                "success_text": success_text,
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


def _prediction_flow_model_text(row: dict[str, Any]) -> str:
    confidence_text = _ratio_pct(row.get("top_confidence"), 2)
    return (
        f"{row.get('horizon_min')}분 {row.get('model_version')}: "
        f"{row.get('top_label_text')} {confidence_text} / {row.get('predicted_change_text') or '-'}"
    )


def _prediction_flow_actual_text(row: dict[str, Any]) -> str:
    return (
        f"{row.get('horizon_min')}분 실제 {row.get('actual_label_text')} / "
        f"{row.get('actual_change_text')} / {row.get('success_text')}"
    )


def _prediction_flow_order_text(order: dict[str, Any]) -> str:
    order_kind = "청산" if "close" in str(order.get("order_id") or "") else "진입"
    return (
        f"{order_kind} {_translate_signal_side(str(order.get('side') or ''))} "
        f"{order.get('qty')}주 @ {_money(order.get('limit_price'))} / {order.get('status')}"
    )


def _prediction_flow_fill_text(fills: list[dict[str, Any]]) -> str:
    if not fills:
        return "체결 없음"
    total_qty = sum(int(row.get("fill_qty", 0) or 0) for row in fills)
    notional = sum(float(row.get("fill_price", 0.0) or 0.0) * int(row.get("fill_qty", 0) or 0) for row in fills)
    total_fee_tax = sum(float(row.get("commission", 0.0) or 0.0) + float(row.get("tax", 0.0) or 0.0) for row in fills)
    avg_price = (notional / total_qty) if total_qty else None
    return f"{len(fills)}건 / {total_qty}주 / 평균 {_money(avg_price)} / 비용 {_money(total_fee_tax)}"


def _prediction_model_family(model_version: Any) -> str:
    normalized = str(model_version or "").strip().lower()
    if "lightgbm" in normalized:
        return "LightGBM"
    if "baseline" in normalized:
        return "Baseline"
    return str(model_version or "기타 모델")


def _prediction_flow_model_block(predictions: list[dict[str, Any]]) -> str:
    if not predictions:
        return "-"
    horizons = sorted({int(row.get("horizon_min", 0) or 0) for row in predictions})
    ordered_horizons = [horizon for horizon in (15, 60) if horizon in horizons]
    ordered_horizons.extend(horizon for horizon in horizons if horizon not in {15, 60})
    blocks: list[str] = []
    for horizon in ordered_horizons:
        rows = [row for row in predictions if int(row.get("horizon_min", 0) or 0) == horizon]
        lines = [f"{horizon}분"]
        families_seen: set[str] = set()
        for row in sorted(rows, key=lambda item: str(item.get("model_version") or "")):
            family = _prediction_model_family(row.get("model_version"))
            families_seen.add(family)
            confidence_text = _ratio_pct(row.get("top_confidence"), 2)
            lines.append(
                f"- {family}: {row.get('top_label_text') or '-'} {confidence_text} / "
                f"{row.get('predicted_change_text') or '-'}"
            )
        for family in ("Baseline", "LightGBM"):
            if family not in families_seen:
                lines.append(f"- {family}: 저장된 serving 예측 없음")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _prediction_flow_actual_block(predictions: list[dict[str, Any]]) -> str:
    if not predictions:
        return "-"
    horizons = sorted({int(row.get("horizon_min", 0) or 0) for row in predictions})
    ordered_horizons = [horizon for horizon in (15, 60) if horizon in horizons]
    ordered_horizons.extend(horizon for horizon in horizons if horizon not in {15, 60})
    blocks: list[str] = []
    for horizon in ordered_horizons:
        rows = [row for row in predictions if int(row.get("horizon_min", 0) or 0) == horizon]
        primary = rows[0]
        blocks.append(
            "\n".join(
                [
                    f"{horizon}분",
                    f"- 실제: {primary.get('actual_label_text') or '-'} / {primary.get('actual_change_text') or '-'}",
                    f"- 판정: {primary.get('success_text') or '-'}",
                ]
            )
        )
    return "\n\n".join(blocks)


def _semicolon_fields(value: Any) -> tuple[dict[str, str], set[str]]:
    fields: dict[str, str] = {}
    flags: set[str] = set()
    for token in [item.strip() for item in str(value or "").split(";") if item.strip()]:
        if "=" in token:
            key, raw_value = token.split("=", 1)
            fields[key.strip()] = raw_value.strip()
        else:
            flags.add(token)
    return fields, flags


def _prediction_flow_strategy_summary(signal: dict[str, Any]) -> str:
    fields, flags = _semicolon_fields(signal.get("reason"))
    reasons: list[str] = []
    if str(signal.get("side") or "") == "sell" and "long_only_policy" in flags:
        reasons.append("매수전용 정책으로 매도 차단")
    if fields.get("time_gate") == "after_new_entry_window":
        reasons.append("신규 진입 시간 종료")
    elif fields.get("time_gate") == "outside_window":
        reasons.append("허용 시간대 밖")
    elif fields.get("time_gate") == "within_window":
        reasons.append("진입 시간 통과")
    if fields.get("spread_gate") == "spread_too_wide":
        reasons.append("호가 스프레드 과다")
    elif fields.get("spread_gate") == "spread_ok":
        reasons.append("호가 스프레드 통과")
    if "confidence_below_threshold" in flags:
        reasons.append("신뢰도 기준 미달")
    if not reasons and signal.get("allowed"):
        reasons.append("신호 게이트 통과")
    return ", ".join(reasons[:3]) if reasons else str(signal.get("signal_summary") or "-")


def _prediction_flow_execution_summary(risk_event: dict[str, Any] | None) -> str:
    if not risk_event:
        return "실행 게이트 기록 없음"
    fields, flags = _semicolon_fields(risk_event.get("detail"))
    open_reason = fields.get("open_reason")
    reason_labels = {
        "ok": "실행 조건 통과",
        "max_open_positions_reached": "최대 보유종목 수 도달",
        "broker_order_pending": "브로커 미체결/조회 대기",
        "recently_closed": "직전 청산 후 재진입 대기",
        "position_already_open": "이미 보유 중",
        "invalid_target": "목표 포지션 없음",
    }
    if open_reason:
        return reason_labels.get(open_reason, open_reason)
    if "signal_allowed=False" in flags or fields.get("signal_allowed") == "False":
        return "신호 차단으로 주문 없음"
    detail = str(risk_event.get("detail") or "").strip()
    return detail[:80] if detail else "실행 게이트 기록 있음"


def _prediction_flow_signal_text(signal: dict[str, Any] | None, risk_event: dict[str, Any] | None) -> str:
    if signal is None:
        return "신호 없음"
    side_text = signal.get("side_label") or _translate_signal_side(str(signal.get("side") or ""))
    allowed_text = signal.get("allowed_text") or ("허용" if signal.get("allowed") else "차단")
    return "\n".join(
        [
            f"신호: {side_text} {allowed_text} / 신뢰도 {_ratio_pct(signal.get('confidence'), 2)}",
            f"판단: {_prediction_flow_strategy_summary(signal)}",
            f"실행: {_prediction_flow_execution_summary(risk_event)}",
        ]
    )


def _is_close_order(order: dict[str, Any]) -> bool:
    return "close" in str(order.get("order_id") or "").lower()


def _order_filled_summary(order: dict[str, Any], fills_by_order: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    fills = fills_by_order.get(str(order.get("order_id") or ""), [])
    total_qty = sum(int(row.get("fill_qty", 0) or 0) for row in fills)
    notional = sum(float(row.get("fill_price", 0.0) or 0.0) * int(row.get("fill_qty", 0) or 0) for row in fills)
    total_cost = sum(float(row.get("commission", 0.0) or 0.0) + float(row.get("tax", 0.0) or 0.0) for row in fills)
    return {
        "filled_qty": total_qty,
        "avg_price": (notional / total_qty) if total_qty else None,
        "notional": notional,
        "cost": total_cost,
    }


def _build_paper_order_profit_texts(order_rows: list[dict[str, Any]], fill_rows: list[dict[str, Any]]) -> dict[str, str]:
    fills_by_order: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in fill_rows:
        fills_by_order[str(row.get("order_id") or "")].append(row)

    lot_book: defaultdict[str, list[dict[str, float]]] = defaultdict(list)
    profit_texts: dict[str, str] = {}
    for order in sorted(order_rows, key=lambda item: (str(item.get("event_time") or ""), str(item.get("order_id") or ""))):
        order_id = str(order.get("order_id") or "")
        if not order_id:
            continue
        summary = _order_filled_summary(order, fills_by_order)
        filled_qty = int(summary["filled_qty"] or 0)
        avg_price = summary["avg_price"]
        if filled_qty <= 0 or avg_price is None:
            profit_texts[order_id] = "체결 없음"
            continue
        symbol = str(order.get("symbol") or "")
        side = str(order.get("side") or "")
        if side == "buy":
            lot_book[symbol].append(
                {
                    "qty": float(filled_qty),
                    "avg_price": float(avg_price),
                    "cost": float(summary["cost"] or 0.0),
                }
            )
            profit_texts[order_id] = "진입 체결 / 실현손익 대기"
            continue
        if side != "sell":
            profit_texts[order_id] = "손익 계산 대상 아님"
            continue

        remaining = float(filled_qty)
        matched_qty = 0.0
        basis = 0.0
        gross_profit = 0.0
        buy_cost_used = 0.0
        lots = lot_book[symbol]
        while remaining > 0 and lots:
            lot = lots[0]
            use_qty = min(remaining, lot["qty"])
            basis += lot["avg_price"] * use_qty
            gross_profit += (float(avg_price) - lot["avg_price"]) * use_qty
            matched_qty += use_qty
            cost_ratio = use_qty / lot["qty"] if lot["qty"] else 0.0
            buy_cost_used += lot["cost"] * cost_ratio
            lot["qty"] -= use_qty
            lot["cost"] -= lot["cost"] * cost_ratio
            remaining -= use_qty
            if lot["qty"] <= 0:
                lots.pop(0)
        if matched_qty <= 0 or basis <= 0:
            profit_texts[order_id] = "청산 손익 계산 불가"
            continue
        sell_cost_used = float(summary["cost"] or 0.0) * (matched_qty / filled_qty)
        net_profit = gross_profit - buy_cost_used - sell_cost_used
        profit_pct = (net_profit / basis) * 100.0
        profit_texts[order_id] = f"청산 {_format_signed_change(net_profit, profit_pct)}"
    return profit_texts


def _prediction_flow_order_block(signal_orders: list[dict[str, Any]], close_orders: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    if signal_orders:
        blocks.append("신호 주문\n" + "\n".join(f"- {_prediction_flow_order_text(order)}" for order in signal_orders))
    if close_orders:
        blocks.append("별도 청산\n" + "\n".join(f"- {_prediction_flow_order_text(order)}" for order in close_orders))
    return "\n\n".join(blocks) if blocks else "주문 없음"


def _prediction_flow_profit_text(orders: list[dict[str, Any]], profit_by_order: dict[str, str]) -> str:
    if not orders:
        return "주문 없음"
    lines = []
    for order in orders:
        order_id = str(order.get("order_id") or "")
        prefix = "청산" if _is_close_order(order) else "진입"
        text = profit_by_order.get(order_id, "손익 계산 불가")
        if text.startswith(prefix):
            lines.append(text)
        else:
            lines.append(f"{prefix}: {text}")
    return "\n".join(lines)


def _prediction_flow_primary_prediction(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    preferred_horizon = 15
    preferred_rows = [
        row
        for row in predictions
        if int(row.get("horizon_min", 0) or 0) == preferred_horizon
    ]
    if not preferred_rows:
        preferred_rows = list(predictions)
    baseline = next(
        (
            row
            for row in preferred_rows
            if _prediction_model_family(row.get("model_version")) == "Baseline"
        ),
        None,
    )
    if baseline is not None:
        return baseline
    active_like = next(
        (
            row
            for row in preferred_rows
            if _prediction_model_family(row.get("model_version")) != "LightGBM"
        ),
        None,
    )
    return active_like if active_like is not None else preferred_rows[0]


def _round_trip_cost_pct(settings) -> float:
    return max(float(settings.strategy.slippage_bps), 0.0) * 2.0 / 100.0


def _bar_close_at_or_after(
    bar_index: dict[str, dict[str, list[Any]]],
    *,
    symbol: str,
    event_time: datetime,
) -> float | None:
    row = _find_first_same_day_bar_at_or_after(bar_index, symbol=symbol, target_time=event_time)
    if row is None or row.get("close") is None:
        return None
    try:
        return float(row["close"])
    except (TypeError, ValueError):
        return None


def _format_signed_pct(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _esc(value)
    if abs(numeric) < 0.005:
        return f"{0:.{digits}f}%"
    return f"{numeric:+.{digits}f}%"


def _build_signal_replay_summary(
    signal_views: list[dict[str, Any]],
    minute_bar_rows: list[dict[str, Any]],
    *,
    settings,
) -> dict[str, Any]:
    _, _, bar_index = _build_bar_lookup(minute_bar_rows)
    round_trip_cost_pct = _round_trip_cost_pct(settings)
    position_notional = float(settings.strategy.paper_initial_cash) * float(settings.strategy.max_position_pct)
    forced_flat_clock = _parse_market_clock(settings.market_calendar.forced_flat_time)
    min_confidence = float(settings.strategy.min_signal_confidence)
    max_hold_minutes = int(settings.strategy.max_hold_minutes)
    max_open_positions = int(settings.strategy.max_open_positions)

    positions: dict[str, dict[str, Any]] = {}
    trades: list[dict[str, Any]] = []
    skipped_no_price = 0
    skipped_max_positions = 0
    skipped_already_open = 0
    avoided_short_entries = 0

    def close_position(symbol: str, exit_time: datetime, exit_price: float, reason: str) -> None:
        position = positions.pop(symbol, None)
        if position is None:
            return
        entry_price = float(position["entry_price"])
        gross_return_pct = ((exit_price / entry_price) - 1.0) * 100.0 if entry_price else 0.0
        net_return_pct = gross_return_pct - round_trip_cost_pct
        net_pnl = position_notional * net_return_pct / 100.0
        trades.append(
            {
                "symbol": symbol,
                "entry_time": position["entry_time"].isoformat(),
                "exit_time": exit_time.isoformat(),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "gross_return_pct": gross_return_pct,
                "net_return_pct": net_return_pct,
                "net_pnl": net_pnl,
                "exit_reason": reason,
                "entry_signal_id": position.get("signal_id"),
            }
        )

    def close_due_positions(current_time: datetime) -> None:
        due_symbols: list[tuple[str, datetime, float, str]] = []
        for symbol, position in list(positions.items()):
            entry_time = position["entry_time"]
            due_time = entry_time + timedelta(minutes=max_hold_minutes)
            if current_time >= due_time:
                due_price = _bar_close_at_or_after(bar_index, symbol=symbol, event_time=due_time)
                if due_price is not None:
                    due_symbols.append((symbol, due_time, due_price, "time_exit"))
                    continue
            if current_time.timetz().replace(tzinfo=None) >= forced_flat_clock:
                current_price = _bar_close_at_or_after(bar_index, symbol=symbol, event_time=current_time)
                if current_price is not None:
                    due_symbols.append((symbol, current_time, current_price, "forced_flat"))
        for symbol, exit_time, exit_price, reason in due_symbols:
            close_position(symbol, exit_time, exit_price, reason)

    for signal in sorted(signal_views, key=lambda item: (str(item.get("event_time") or ""), str(item.get("symbol") or ""))):
        symbol = str(signal.get("symbol") or "")
        event_time = _parse_iso_datetime(signal.get("event_time"))
        if not symbol or event_time is None:
            continue
        close_due_positions(event_time)
        price = _bar_close_at_or_after(bar_index, symbol=symbol, event_time=event_time)
        if price is None:
            skipped_no_price += 1
            continue
        side = str(signal.get("side") or "")
        confidence = float(signal.get("confidence") or 0.0)
        fields, _ = _semicolon_fields(signal.get("reason"))
        spread_ok = fields.get("spread_gate") != "spread_too_wide"
        entry_allowed = bool(signal.get("allowed")) and side == "buy"
        exit_signal = side == "sell" and confidence >= min_confidence and spread_ok

        if symbol in positions and exit_signal:
            close_position(symbol, event_time, price, "sell_signal_exit")
            continue
        if side == "sell" and symbol not in positions:
            avoided_short_entries += 1
            continue
        if not entry_allowed:
            continue
        if symbol in positions:
            skipped_already_open += 1
            continue
        if len(positions) >= max_open_positions:
            skipped_max_positions += 1
            continue
        positions[symbol] = {
            "entry_time": event_time,
            "entry_price": price,
            "signal_id": signal.get("signal_id"),
        }

    for symbol, position in list(positions.items()):
        due_time = position["entry_time"] + timedelta(minutes=max_hold_minutes)
        due_price = _bar_close_at_or_after(bar_index, symbol=symbol, event_time=due_time)
        if due_price is not None:
            close_position(symbol, due_time, due_price, "time_exit")

    closed_trades = len(trades)
    net_return_sum = sum(float(trade["net_return_pct"]) for trade in trades)
    gross_return_sum = sum(float(trade["gross_return_pct"]) for trade in trades)
    net_pnl_sum = sum(float(trade["net_pnl"]) for trade in trades)
    wins = sum(1 for trade in trades if float(trade["net_return_pct"]) > 0)
    signal_exit_count = sum(1 for trade in trades if trade.get("exit_reason") == "sell_signal_exit")
    time_exit_count = sum(1 for trade in trades if trade.get("exit_reason") == "time_exit")
    forced_flat_count = sum(1 for trade in trades if trade.get("exit_reason") == "forced_flat")
    return {
        "model": "long_only_signal_replay",
        "description": "미보유+매수 허용은 진입, 보유+매도 신호는 청산, 미보유+매도 신호는 신규 숏 없이 진입 회피로 보는 현물 기준 replay입니다.",
        "cost_model": "round_trip_slippage_only",
        "round_trip_cost_pct": round_trip_cost_pct,
        "position_notional": position_notional,
        "signals_seen": len(signal_views),
        "trades_opened": closed_trades + len(positions),
        "trades_closed": closed_trades,
        "open_positions": len(positions),
        "wins": wins,
        "win_rate": (wins / closed_trades) if closed_trades else None,
        "gross_return_sum_pct": gross_return_sum,
        "net_return_sum_pct": net_return_sum,
        "average_net_return_pct": (net_return_sum / closed_trades) if closed_trades else None,
        "estimated_net_pnl": net_pnl_sum,
        "signal_exit_count": signal_exit_count,
        "time_exit_count": time_exit_count,
        "forced_flat_count": forced_flat_count,
        "avoided_short_entries": avoided_short_entries,
        "skipped_max_positions": skipped_max_positions,
        "skipped_already_open": skipped_already_open,
        "skipped_no_price": skipped_no_price,
        "recent_trades": trades[-10:],
    }


def _build_paper_fill_return_summary(
    order_rows: list[dict[str, Any]],
    fill_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    fills_by_order: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in fill_rows:
        fills_by_order[str(row.get("order_id") or "")].append(row)

    lot_book: defaultdict[str, list[dict[str, float]]] = defaultdict(list)
    closed_trades: list[dict[str, Any]] = []
    for order in sorted(order_rows, key=lambda item: (str(item.get("event_time") or ""), str(item.get("order_id") or ""))):
        order_id = str(order.get("order_id") or "")
        summary = _order_filled_summary(order, fills_by_order)
        filled_qty = int(summary["filled_qty"] or 0)
        avg_price = summary["avg_price"]
        if not order_id or filled_qty <= 0 or avg_price is None:
            continue
        symbol = str(order.get("symbol") or "")
        side = str(order.get("side") or "")
        if side == "buy":
            lot_book[symbol].append(
                {
                    "qty": float(filled_qty),
                    "avg_price": float(avg_price),
                    "cost": float(summary["cost"] or 0.0),
                }
            )
            continue
        if side != "sell":
            continue
        remaining = float(filled_qty)
        matched_qty = 0.0
        basis = 0.0
        gross_profit = 0.0
        buy_cost_used = 0.0
        lots = lot_book[symbol]
        while remaining > 0 and lots:
            lot = lots[0]
            use_qty = min(remaining, lot["qty"])
            basis += lot["avg_price"] * use_qty
            gross_profit += (float(avg_price) - lot["avg_price"]) * use_qty
            matched_qty += use_qty
            cost_ratio = use_qty / lot["qty"] if lot["qty"] else 0.0
            buy_cost_used += lot["cost"] * cost_ratio
            lot["qty"] -= use_qty
            lot["cost"] -= lot["cost"] * cost_ratio
            remaining -= use_qty
            if lot["qty"] <= 0:
                lots.pop(0)
        if matched_qty <= 0 or basis <= 0:
            continue
        sell_cost_used = float(summary["cost"] or 0.0) * (matched_qty / filled_qty)
        net_pnl = gross_profit - buy_cost_used - sell_cost_used
        net_return_pct = (net_pnl / basis) * 100.0
        closed_trades.append(
            {
                "symbol": symbol,
                "order_id": order_id,
                "event_time": order.get("event_time"),
                "matched_qty": matched_qty,
                "basis": basis,
                "net_pnl": net_pnl,
                "net_return_pct": net_return_pct,
            }
        )

    total_basis = sum(float(trade["basis"]) for trade in closed_trades)
    total_net_pnl = sum(float(trade["net_pnl"]) for trade in closed_trades)
    wins = sum(1 for trade in closed_trades if float(trade["net_pnl"]) > 0)
    return {
        "model": "actual_paper_fills_fifo",
        "description": "실제 paper 체결 원장을 FIFO로 맞춘 청산 손익입니다.",
        "closed_trades": len(closed_trades),
        "wins": wins,
        "win_rate": (wins / len(closed_trades)) if closed_trades else None,
        "total_basis": total_basis,
        "net_pnl": total_net_pnl,
        "return_on_basis_pct": (total_net_pnl / total_basis * 100.0) if total_basis else None,
        "recent_trades": closed_trades[-10:],
    }


def _prediction_flow_view(
    prediction_views: list[dict[str, Any]],
    signal_views: list[dict[str, Any]],
    order_rows: list[dict[str, Any]],
    fill_rows: list[dict[str, Any]],
    risk_event_rows: list[dict[str, Any]],
    *,
    limit: int,
    latest_first: bool = True,
) -> list[dict[str, Any]]:
    predictions_by_key: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in prediction_views:
        predictions_by_key[(str(row.get("symbol") or ""), str(row.get("event_time") or ""))].append(row)

    signals_by_key: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in signal_views:
        signals_by_key[(str(row.get("symbol") or ""), str(row.get("event_time") or ""))].append(row)

    orders_by_key: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    orders_by_prediction_id: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    orders_by_signal_id: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in order_rows:
        orders_by_key[(str(row.get("symbol") or ""), str(row.get("event_time") or ""))].append(row)
        prediction_id = str(row.get("prediction_id") or "")
        signal_id = str(row.get("signal_id") or "")
        if prediction_id:
            orders_by_prediction_id[prediction_id].append(row)
        if signal_id:
            orders_by_signal_id[signal_id].append(row)

    fills_by_order: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in fill_rows:
        fills_by_order[str(row.get("order_id") or "")].append(row)

    risk_events_by_key: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in risk_event_rows:
        risk_events_by_key[(str(row.get("symbol") or ""), str(row.get("event_time") or ""))].append(row)

    profit_by_order = _build_paper_order_profit_texts(order_rows, fill_rows)

    flow_rows: list[dict[str, Any]] = []
    for (symbol, event_time), prediction_group in predictions_by_key.items():
        predictions = sorted(prediction_group, key=lambda item: int(item.get("horizon_min", 0) or 0))
        primary = _prediction_flow_primary_prediction(predictions)
        signals = signals_by_key.get((symbol, event_time), [])
        signal = signals[0] if signals else None
        exact_orders: dict[str, dict[str, Any]] = {}
        prediction_id = str(primary.get("prediction_id") or "")
        if prediction_id:
            for order in orders_by_prediction_id.get(prediction_id, []):
                exact_orders[str(order.get("order_id") or "")] = order
        signal_ids = {str(row.get("signal_id") or "") for row in signals if row.get("signal_id")}
        for signal_id in signal_ids:
            for order in orders_by_signal_id.get(signal_id, []):
                exact_orders[str(order.get("order_id") or "")] = order
        fallback_orders = orders_by_key.get((symbol, event_time), [])
        orders_source = "id" if exact_orders else "time"
        if exact_orders:
            signal_orders = list(exact_orders.values())
            close_orders = [
                order
                for order in fallback_orders
                if _is_close_order(order) and str(order.get("order_id") or "") not in exact_orders
            ]
        else:
            signal_orders = [order for order in fallback_orders if not _is_close_order(order)]
            close_orders = [order for order in fallback_orders if _is_close_order(order)]
        signal_orders = sorted(
            signal_orders,
            key=lambda item: str(item.get("order_id") or ""),
        )
        close_orders = sorted(close_orders, key=lambda item: str(item.get("order_id") or ""))
        orders = signal_orders + close_orders
        related_fills: list[dict[str, Any]] = []
        for order in orders:
            related_fills.extend(fills_by_order.get(str(order.get("order_id") or ""), []))

        model_text = _prediction_flow_model_block(predictions)
        actual_text = _prediction_flow_actual_block(predictions)
        risk_events = risk_events_by_key.get((symbol, event_time), [])
        risk_event = next((row for row in risk_events if str(row.get("gate") or "") == "online_signal_policy"), None)
        if risk_event is None and risk_events:
            risk_event = risk_events[0]
        signal_text = _prediction_flow_signal_text(signal, risk_event)
        order_text = _prediction_flow_order_block(signal_orders, close_orders)
        fill_text = _prediction_flow_fill_text(related_fills) if orders else "주문 없음"
        profit_text = _prediction_flow_profit_text(orders, profit_by_order)
        link_text = "예측-신호: 동일 종목/시각"
        if signal_orders:
            if orders_source == "id":
                link_text += " / 신호 주문: prediction_id 또는 signal_id"
            else:
                link_text += " / 신호 주문: 동일 종목/시각 보조"
        if close_orders:
            link_text += " / 별도 청산: 포지션 관리 주문"
        if related_fills:
            link_text += " / 체결: 주문ID"
        if not orders:
            link_text += " / 주문 없음"

        flow_rows.append(
            {
                "event_time": event_time,
                "symbol": symbol,
                "symbol_label": primary.get("symbol_label") or symbol,
                "prediction_id": primary.get("prediction_id"),
                "model_prediction_text": model_text,
                "actual_result_text": actual_text,
                "signal_text": signal_text,
                "order_text": order_text,
                "fill_text": fill_text,
                "profit_text": profit_text,
                "link_text": link_text,
            }
        )

    flow_rows.sort(
        key=lambda row: (str(row.get("event_time") or ""), str(row.get("symbol") or "")),
        reverse=latest_first,
    )
    limited = flow_rows[:limit] if limit > 0 else flow_rows
    for index, row in enumerate(limited, start=1):
        row["flow_no"] = index
    return limited


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
    broker_order_submissions: list[dict[str, Any]],
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
        "broker_order_submissions": len(broker_order_submissions),
        "positions": len(positions),
        "portfolio_snapshots": len(portfolio_snapshots),
        "training_runs": len(training_rows),
        "evaluations": len(evaluation_rows),
        "backtests": sum(1 for row in evaluation_rows if str(row.get("split_name", "")).startswith("backtest_")),
        "walk_forward_runs": sum(1 for row in evaluation_rows if str(row.get("split_name", "")).startswith("walk_forward_")),
        "challenger_runs": sum(1 for row in evaluation_rows if str(row.get("split_name", "")).startswith("challenger_")),
    }


def _prediction_rollup(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [row for row in rows if row.get("success") is not None]
    pending = [row for row in rows if str(row.get("result_status") or "pending") == "pending"]
    no_result = [row for row in rows if str(row.get("result_status") or "") == "no_result"]
    success_count = sum(1 for row in evaluated if row.get("success") is True)
    predicted_change_values = [abs(float(row.get("predicted_change_amount") or 0.0)) for row in rows if row.get("predicted_change_amount") is not None]
    actual_change_values = [abs(float(row.get("actual_change_amount") or 0.0)) for row in evaluated if row.get("actual_change_amount") is not None]
    return {
        "total": len(rows),
        "evaluated": len(evaluated),
        "pending": len(pending),
        "no_result": len(no_result),
        "success_count": success_count,
        "success_rate": (success_count / len(evaluated)) if evaluated else None,
        "avg_predicted_change_amount": (sum(predicted_change_values) / len(predicted_change_values)) if predicted_change_values else None,
        "avg_actual_change_amount": (sum(actual_change_values) / len(actual_change_values)) if actual_change_values else None,
    }


def _prediction_session_label(event_time_text: str | None) -> str:
    event_time = _parse_iso_datetime(event_time_text)
    if event_time is None:
        return "시간 미상"
    return "오전" if event_time.hour < 12 else "오후"


def _prediction_hour_slot_label(event_time_text: str | None) -> str:
    event_time = _parse_iso_datetime(event_time_text)
    if event_time is None:
        return "시간 미상"
    return f"{event_time.hour:02d}시"


def _build_prediction_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    horizon_counter = Counter(str(row.get("horizon_min", "-")) for row in rows)
    predicted_counter = Counter(str(row.get("top_label", "")) for row in rows if row.get("top_label"))
    evaluated = [row for row in rows if row.get("success") is not None]
    actual_counter = Counter(str(row.get("actual_label", "")) for row in evaluated if row.get("actual_label"))
    session_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    hour_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    direction_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        session_groups[_prediction_session_label(row.get("event_time"))].append(row)
        hour_groups[_prediction_hour_slot_label(row.get("event_time"))].append(row)
        direction_groups[str(row.get("top_label") or "unknown")].append(row)

    return {
        **_prediction_rollup(rows),
        "horizon_counts": {key: int(value) for key, value in sorted(horizon_counter.items())},
        "predicted_label_counts": {key: int(value) for key, value in sorted(predicted_counter.items())},
        "actual_label_counts": {key: int(value) for key, value in sorted(actual_counter.items())},
        "session_stats": {key: _prediction_rollup(value) for key, value in sorted(session_groups.items())},
        "hour_slot_stats": {key: _prediction_rollup(value) for key, value in sorted(hour_groups.items())},
        "direction_stats": {key: _prediction_rollup(value) for key, value in sorted(direction_groups.items())},
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


def _build_account_sync_status(
    local_account_summary: dict[str, Any],
    paper_account_view: dict[str, Any],
    *,
    order_mirroring_enabled: bool,
    mirrored_order_count: int,
) -> dict[str, Any]:
    local_positions = {
        str(row.get("symbol")): int(row.get("qty", 0) or 0)
        for row in (local_account_summary.get("positions") or [])
        if int(row.get("qty", 0) or 0) > 0
    }
    broker_positions = {
        str(row.get("symbol")): int(row.get("holding_qty", 0) or 0)
        for row in (paper_account_view.get("positions") or [])
        if int(row.get("holding_qty", 0) or 0) > 0
    }
    def _float_or_none(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    local_cash = _float_or_none(local_account_summary.get("cash_balance"))
    broker_raw_cash = _float_or_none(paper_account_view.get("cash_balance"))
    broker_stock_value = _float_or_none(paper_account_view.get("stock_evaluation_amount"))
    broker_total_asset = _float_or_none(paper_account_view.get("total_asset_amount"))
    broker_effective_cash = (
        broker_total_asset - broker_stock_value
        if broker_total_asset is not None and broker_stock_value is not None
        else broker_raw_cash
    )
    cash_gap = None
    raw_cash_gap = None
    if local_cash is not None and broker_effective_cash is not None:
        cash_gap = local_cash - broker_effective_cash
    if local_cash is not None and broker_raw_cash is not None:
        raw_cash_gap = local_cash - broker_raw_cash
    positions_match = local_positions == broker_positions
    balance_match = cash_gap is not None and abs(cash_gap) < 1.0
    if order_mirroring_enabled:
        note = (
            "로컬 가상 주문을 브로커 모의계좌에도 함께 제출하도록 설정되어 있습니다. "
            "다만 브로커 측 거절, 부분 체결, 체결 시차가 있으면 주문 직후에는 잔고와 보유 수량이 잠시 다를 수 있습니다."
        )
    else:
        note = (
            "현재는 로컬 가상 주문만 자동 실행되고, 브로커 모의투자 계좌 주문은 자동 연동되지 않습니다. "
            "그래서 현재 보유 상태가 같더라도 주문 이력과 예수금은 일치하지 않을 수 있습니다."
        )
    return {
        "order_mirroring_enabled": order_mirroring_enabled,
        "mirrored_order_count": int(mirrored_order_count),
        "positions_match": positions_match,
        "balance_match": balance_match,
        "cash_gap": cash_gap,
        "raw_cash_gap": raw_cash_gap,
        "broker_effective_cash_balance": broker_effective_cash,
        "broker_raw_cash_balance": broker_raw_cash,
        "local_positions": local_positions,
        "broker_positions": broker_positions,
        "status": "일치" if positions_match and balance_match else "불일치",
        "note": note,
    }


def _build_lightgbm_status(
    *,
    settings,
    latest_training: dict[str, Any] | None,
    latest_evaluation: dict[str, Any] | None,
    active_model_entry: dict[str, Any],
    runtime_summary: dict[str, Any],
) -> dict[str, Any]:
    artifact_path = find_latest_lightgbm_artifact(settings.runtime_data_dir, horizon_min=15)
    artifact_updated_at = None
    if artifact_path and artifact_path.exists():
        artifact_updated_at = datetime.fromtimestamp(artifact_path.stat().st_mtime, tz=get_timezone(settings.timezone)).isoformat()
    artifact_lineage = _build_lightgbm_artifact_lineage_status(settings=settings, latest_training=latest_training)

    training_summary = (latest_training or {}).get("training_summary") or {}
    latest_model_version = (latest_training or {}).get("model_version") or "미학습"
    return {
        "framework": "LightGBM",
        "available": artifact_path is not None and artifact_path.exists(),
        "artifact_path": str(artifact_path) if artifact_path else None,
        "artifact_updated_at": artifact_updated_at,
        "latest_model_version": latest_model_version,
        "active_model_version": active_model_entry.get("model_version"),
        "is_active": active_model_entry.get("model_version") == latest_model_version,
        "train_rows": (latest_training or {}).get("train_rows"),
        "validation_rows": (latest_training or {}).get("validation_rows"),
        "validation_accuracy": (latest_evaluation or {}).get("accuracy"),
        "validation_split_name": (latest_evaluation or {}).get("split_name"),
        "evaluated_rows": (latest_evaluation or {}).get("total_rows"),
        "validation_evaluated_at": (latest_evaluation or {}).get("evaluated_at"),
        "labels_seen": training_summary.get("labels_seen") or [],
        "class_labels": training_summary.get("class_labels") or [],
        "feature_count": len(training_summary.get("feature_names") or []),
        "training_window": training_summary.get("training_window") or "recent_60_trading_days_plus_today",
        "actual_feature_rows": runtime_summary.get("feature_rows", 0),
        "actual_label_rows": runtime_summary.get("labels", 0),
        "description": "최근 60거래일과 오늘 장중 분봉·호가 기반 수치 특징으로 다음 15분/60분의 상승·보합·하락 확률을 학습합니다. 장중에는 추론만 수행하고, 장후 재학습 또는 실제 데이터 재구성 시점에만 새 모델을 만듭니다.",
        **artifact_lineage,
    }


def _build_lightgbm_artifact_lineage_status(
    *,
    settings,
    latest_training: dict[str, Any] | None,
) -> dict[str, Any]:
    artifact_path = find_latest_lightgbm_artifact(settings.runtime_data_dir, horizon_min=15)
    latest_training_run_id = str((latest_training or {}).get("training_run_id") or "")
    base = {
        "artifact_lineage_status": "artifact_missing",
        "artifact_lineage_label": "아티팩트 없음",
        "artifact_training_run_id": None,
        "expected_training_run_id": latest_training_run_id or None,
        "artifact_dataset_scope": None,
        "artifact_holdout_first_event_time": None,
        "artifact_lineage_promotable": False,
    }
    if artifact_path is None or not artifact_path.exists():
        return base
    try:
        artifact = LightGbmDirectionModel.from_path(artifact_path).artifact
    except Exception as exc:  # pragma: no cover - corrupted local joblib is environment-specific
        base.update(
            {
                "artifact_lineage_status": "artifact_unreadable",
                "artifact_lineage_label": "아티팩트 읽기 실패",
                "artifact_lineage_error": str(exc),
            }
        )
        return base

    artifact_training_run_id = artifact.training_run_id
    status = "artifact_training_run_match"
    label = "DB 학습 run과 일치"
    promotable = True
    if not artifact_training_run_id:
        status = "artifact_missing_training_run_id"
        label = "legacy artifact metadata 없음"
        promotable = False
    elif not latest_training_run_id:
        status = "unknown_training_summary"
        label = "DB 최신 학습 run 없음"
        promotable = False
    elif str(artifact_training_run_id) != latest_training_run_id:
        status = "artifact_training_run_mismatch"
        label = "DB 학습 run과 artifact 불일치"
        promotable = False

    base.update(
        {
            "artifact_lineage_status": status,
            "artifact_lineage_label": label,
            "artifact_training_run_id": artifact_training_run_id,
            "artifact_dataset_scope": artifact.dataset_scope,
            "artifact_holdout_first_event_time": artifact.challenger_holdout_first_event_time,
            "artifact_lineage_promotable": promotable,
        }
    )
    return base


def _apply_current_challenger_dashboard_guards(
    report: dict[str, Any] | list[Any] | None,
    lightgbm_status: dict[str, Any],
) -> dict[str, Any] | list[Any] | None:
    if not isinstance(report, dict):
        return report
    guarded = json.loads(json.dumps(report, ensure_ascii=False))
    artifact_status = str(lightgbm_status.get("artifact_lineage_status") or "")
    artifact_training_run_id = lightgbm_status.get("artifact_training_run_id")
    guard_note = ""
    if artifact_status and artifact_status != "artifact_training_run_match":
        guard_note = (
            "현재 dashboard 생성 시점의 LightGBM artifact lineage guard가 적용되어, "
            f"artifact 상태 {artifact_status} 후보는 승격 불가로 표시합니다."
        )

    candidates = guarded.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            is_lightgbm = (
                str(candidate.get("candidate_name")) == "latest_lightgbm"
                or str(candidate.get("model_kind")) == "lightgbm_artifact"
            )
            if not is_lightgbm:
                continue
            candidate.setdefault("report_promotable", candidate.get("promotable"))
            candidate["artifact_training_status"] = artifact_status or candidate.get("artifact_training_status")
            candidate["artifact_training_run_id"] = artifact_training_run_id or candidate.get("artifact_training_run_id")
            if artifact_status and artifact_status != "artifact_training_run_match":
                candidate["promotable"] = False
                candidate["promotion_block_reason_current"] = guard_note

    if guard_note:
        guarded["current_guard_status"] = "artifact_lineage_guard_applied"
        guarded["current_guard_note"] = guard_note
    else:
        guarded["current_guard_status"] = "artifact_lineage_guard_ok"
    return guarded


def _challenger_decision_label(candidate: dict[str, Any], report: dict[str, Any]) -> str:
    candidate_version = str(candidate.get("model_version") or "")
    candidate_name = str(candidate.get("candidate_name") or "")
    recommended_version = str(report.get("recommended_model_version") or "")
    promoted_version = str(report.get("promoted_model_version") or "")
    recommended_action = str(report.get("recommended_action") or "")
    if bool(report.get("promotion_applied")) and promoted_version and candidate_version == promoted_version:
        return "승격됨"
    if recommended_version and candidate_version == recommended_version:
        if recommended_action == "promote":
            return "승격 권장"
        if recommended_action == "review_required":
            return "검토 필요"
        if recommended_action == "keep_active" and candidate_name == "active_model":
            return "유지 권장"
    if candidate_name == "active_model":
        return "현재 활성"
    return "관찰"


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
    recent_limit: int = 100,
    range_key: str | None = None,
    selected_date: str | None = None,
) -> dict[str, Any]:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = get_sqlite_store(
        settings,
        initialize_schema=False,
        busy_timeout_ms=2_000,
        read_retry_delays=(0.0, 0.05, 0.15),
    )
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for the dashboard.")

    scope = build_runtime_scope(sqlite_store, settings)
    symbol_names = load_symbol_names(project_root)
    runtime_summary_all = _summarize_runtime(sqlite_store, scope, settings)

    default_dashboard_date = None
    if (range_key or "today").strip().lower() == "today" and not selected_date:
        default_dashboard_date = _resolve_default_dashboard_date_from_scope(settings, scope)
    period_filter = _build_period_filter(
        settings,
        range_key=range_key,
        selected_date_text=selected_date or default_dashboard_date,
    )
    calendar_today_filter = _build_period_filter(
        settings,
        range_key="day",
        selected_date_text=now_local(settings.timezone).date().isoformat(),
    )
    dashboard_now = datetime.now().astimezone()
    live_fill_consistency = _build_live_fill_consistency_view(
        sqlite_store,
        trading_day=period_filter.selected_date,
    )
    live_order_attention = _build_live_order_attention_view(
        sqlite_store,
        trading_day=period_filter.selected_date,
        now=dashboard_now,
    )
    live_phase2_parent_order_limit = _build_live_phase2_parent_order_limit_view(
        sqlite_store,
        trading_day=period_filter.selected_date,
    )

    minute_bar_rows = _filtered_rows(sqlite_store, "curated_minute_bars", "bar_time", scope, period_filter)
    feature_rows = _filtered_rows(sqlite_store, "feature_model_inputs", "event_time", scope, period_filter)
    feature_label_rows = _filtered_rows(sqlite_store, "feature_labels", "event_time", scope, period_filter)
    prediction_rows = _filtered_rows(sqlite_store, "serving_predictions", "event_time", scope, period_filter)
    signal_rows = _filtered_rows(sqlite_store, "serving_trade_signals", "event_time", scope, period_filter)
    order_rows = _filtered_rows(sqlite_store, "paper_orders", "event_time", scope, period_filter)
    fill_rows = _filtered_rows(sqlite_store, "paper_fills", "event_time", scope, period_filter)
    risk_event_rows = _filtered_rows(sqlite_store, "ops_risk_events", "event_time", scope, period_filter)
    broker_submission_rows = _filtered_rows(
        sqlite_store,
        "broker_paper_order_submissions",
        "event_time",
        scope,
        period_filter,
    )
    broker_submission_rows_all = _filtered_rows(sqlite_store, "broker_paper_order_submissions", "event_time", scope)
    position_rows_all = _filtered_rows(sqlite_store, "paper_positions", "symbol", scope)
    open_position_rows_all = [row for row in position_rows_all if int(row.get("qty", 0) or 0) > 0]
    snapshot_rows = _filtered_rows(sqlite_store, "paper_portfolio_snapshots", "event_time", scope, period_filter)
    snapshot_rows_all = _filtered_rows(sqlite_store, "paper_portfolio_snapshots", "event_time", scope)

    training_rows_all = [
        _parse_json_column(dict(row), "training_summary_json", target_key="training_summary")
        for row in sqlite_store.fetch_all_rows("ml_training_runs", "completed_at")
    ]
    evaluation_rows_all = [
        _parse_json_column(dict(row), "metrics_json", target_key="metrics")
        for row in sqlite_store.fetch_all_rows("ml_model_evaluations", "evaluated_at")
    ]

    raw_market_count = _raw_count_from_scope(scope, "raw_market_ticks", period_filter)
    raw_orderbook_count = _raw_count_from_scope(scope, "raw_orderbook_ticks", period_filter)
    training_rows = _filter_rows_by_period(training_rows_all, period_filter, "completed_at")
    evaluation_rows = _filter_rows_by_period(evaluation_rows_all, period_filter, "evaluated_at")
    today_training_rows = _filter_rows_by_period(training_rows_all, calendar_today_filter, "completed_at")
    today_evaluation_rows = _filter_rows_by_period(evaluation_rows_all, calendar_today_filter, "evaluated_at")
    current_order_rows = filter_rows_after_alignment(
        order_rows,
        runtime_data_dir=settings.runtime_data_dir,
        time_fields=("event_time",),
    )
    current_fill_rows = filter_rows_after_alignment(
        fill_rows,
        runtime_data_dir=settings.runtime_data_dir,
        time_fields=("event_time",),
    )

    runtime_summary = _summarize_runtime_from_rows(
        raw_market_ticks=[],
        raw_orderbook_ticks=[],
        minute_bars=minute_bar_rows,
        feature_rows=feature_rows,
        labels=feature_label_rows,
        predictions=prediction_rows,
        signals=signal_rows,
        orders=order_rows,
        fills=fill_rows,
        broker_order_submissions=broker_submission_rows,
        positions=open_position_rows_all,
        portfolio_snapshots=snapshot_rows,
        training_rows=training_rows,
        evaluation_rows=evaluation_rows,
    )
    runtime_summary["raw_market_ticks"] = raw_market_count
    runtime_summary["raw_orderbook_ticks"] = raw_orderbook_count

    active_registry = ModelRegistry(settings.runtime_data_dir).load()
    latest_training = training_rows_all[-1] if training_rows_all else None
    latest_evaluation = evaluation_rows_all[-1] if evaluation_rows_all else None
    latest_training_validation_evaluation = None
    latest_training_any_evaluation = None
    if latest_training is not None:
        training_run_id = str(latest_training.get("training_run_id") or "")
        for row in reversed(evaluation_rows_all):
            if str(row.get("training_run_id") or "") == training_run_id:
                if latest_training_any_evaluation is None:
                    latest_training_any_evaluation = row
                if str(row.get("split_name") or "") == "validation":
                    latest_training_validation_evaluation = row
                    break
    if latest_training_validation_evaluation is not None:
        latest_evaluation = latest_training_validation_evaluation
    elif latest_training_any_evaluation is not None:
        latest_evaluation = latest_training_any_evaluation

    active_models = active_registry.get("active_models", {}) if isinstance(active_registry, dict) else {}
    active_model_entry = _effective_active_model_entry(
        settings,
        active_entry=active_models.get("15", {}) if isinstance(active_models, dict) else {},
        horizon_min=15,
    )
    active_model_entry_60 = _effective_active_model_entry(
        settings,
        active_entry=active_models.get("60", {}) if isinstance(active_models, dict) else {},
        horizon_min=60,
    )

    latest_portfolio_snapshot = snapshot_rows[-1] if snapshot_rows else (snapshot_rows_all[-1] if snapshot_rows_all else None)
    aligned_snapshot, aligned_position_rows_all, _ = apply_alignment_baseline(
        latest_snapshot=dict(latest_portfolio_snapshot) if latest_portfolio_snapshot is not None else None,
        position_rows=[dict(row) for row in position_rows_all],
        runtime_data_dir=settings.runtime_data_dir,
    )
    latest_portfolio_snapshot = aligned_snapshot
    position_rows_all = aligned_position_rows_all
    positions = [row for row in aligned_position_rows_all if int(row.get("qty", 0) or 0) > 0]
    prediction_views = _prediction_view(
        prediction_rows,
        symbol_names,
        minute_bar_rows=minute_bar_rows,
        feature_label_rows=feature_label_rows,
        settings=settings,
    )
    signal_views = _signal_view(signal_rows, symbol_names)
    recent_predictions = _reverse_recent(prediction_views, recent_limit)
    prediction_details = list(reversed(prediction_views))
    recent_signals = _reverse_recent(signal_views, recent_limit)
    recent_orders = _reverse_recent(order_rows, recent_limit)
    recent_fills = _reverse_recent(fill_rows, recent_limit)
    recent_bars = _reverse_recent(minute_bar_rows, recent_limit)
    recent_broker_order_submissions = _reverse_recent(broker_submission_rows, recent_limit)
    prediction_flow_full_day = period_filter.range_key in {"today", "day"}
    prediction_flow_rows = _prediction_flow_view(
        prediction_views,
        signal_views,
        order_rows,
        fill_rows,
        risk_event_rows,
        limit=0 if prediction_flow_full_day else recent_limit,
        latest_first=not prediction_flow_full_day,
    )

    prediction_summary = _build_prediction_summary(prediction_views)
    signal_order_summary = _build_signal_order_summary(signal_rows, order_rows, fill_rows)
    signal_replay_summary = _build_signal_replay_summary(
        signal_views,
        minute_bar_rows,
        settings=settings,
    )
    paper_fill_return_summary = _build_paper_fill_return_summary(order_rows, fill_rows)

    live_runtime_state = _normalize_live_runtime_state(
        _safe_load_json(settings.runtime_data_dir / "reports" / "live-runtime" / "state" / "listener-state.json")
    )
    current_session_status = str(live_runtime_state.get("current_session_status") or "").strip()
    if not current_session_status:
        current_session_status = get_market_session_status(settings.market_calendar, now_local(settings.timezone))
    latest_market_bar_time = _latest_time(minute_bar_rows, "bar_time")
    latest_prediction_time = _latest_time(prediction_views, "event_time")
    latest_signal_time = _latest_time(signal_views, "event_time")
    freshness = {
        "dashboard_generated": _build_freshness_snapshot(
            datetime.now().astimezone().isoformat(),
            timezone_name=settings.timezone,
            warning_after_minutes=3,
            stale_after_minutes=10,
            missing_label="대시보드 생성 시각 없음",
        ),
        "latest_market_bar": _build_freshness_snapshot(
            latest_market_bar_time,
            timezone_name=settings.timezone,
            warning_after_minutes=3,
            stale_after_minutes=10,
            missing_label="최근 분봉 없음",
        ),
        "latest_prediction": _build_freshness_snapshot(
            latest_prediction_time,
            timezone_name=settings.timezone,
            warning_after_minutes=3,
            stale_after_minutes=10,
            missing_label="최근 예측 없음",
        ),
        "latest_signal": _build_freshness_snapshot(
            latest_signal_time,
            timezone_name=settings.timezone,
            warning_after_minutes=3,
            stale_after_minutes=10,
            missing_label="최근 신호 없음",
        ),
    }
    actual_labels = runtime_summary.get("labels", 0)
    learning_mode = "actual_runtime" if actual_labels > 0 else "actual_runtime_pending"
    learning_note = (
        "현재 실제 운용 라벨이 있어 학습 현황을 실운용 데이터 기준으로 해석할 수 있습니다."
        if learning_mode == "actual_runtime"
        else "현재 실제 운용 라벨이 0건이라, 실데이터 기반 학습·검증 결과는 아직 생성되지 않았습니다."
    )
    active_status_note = (
        "최신 학습 모델은 LightGBM 후보이지만, 승격 검증을 통과하지 못해 아직 활성 모델이 아닙니다."
        if active_model_entry.get("model_version") != (latest_training or {}).get("model_version")
        else "최신 학습 모델과 현재 활성 모델이 같습니다."
    )
    if current_session_status == "holiday":
        operation_note = "오늘은 설정된 휴장일입니다. 실시간 수집기와 예측기는 꺼두는 것이 정상입니다."
    elif current_session_status == "overnight":
        operation_note = "현재는 장전 워밍업 전 야간 대기 시간입니다. live runtime 이 꺼져 있어도 정상일 수 있습니다."
    elif live_runtime_state.get("status") == "running":
        operation_note = "실시간 수집기와 예측기가 현재 실행 중입니다. 새 분이 닫힐 때마다 15분·60분 예측이 기록되고, 15분 기준으로만 신호를 생성합니다."
    else:
        operation_note = "현재는 대시보드만 실행 중이거나, 마지막 장중 검증 결과만 남아 있습니다. 실시간 수집기를 켜야 예측과 신호가 계속 늘어납니다."
    if recent_bars:
        minute_note = "최근 분봉은 실제 장중 KIS 체결 데이터로 생성된 기록입니다. 주문이나 체결이 없어도 시장 데이터만 들어오면 분봉은 만들어질 수 있습니다."
    else:
        minute_note = "최근 실제 운용 분봉이 아직 없습니다."
    freshness["latest_kis_verification"] = _build_freshness_snapshot(
        (_safe_load_json(settings.runtime_data_dir / "reports" / "kis-ws" / "latest-verification.json") or {}).get("verified_at"),
        timezone_name=settings.timezone,
        warning_after_minutes=30,
        stale_after_minutes=180,
        missing_label="KIS 검증 기록 없음",
    )
    freshness["latest_training"] = _build_freshness_snapshot(
        (latest_training or {}).get("completed_at"),
        timezone_name=settings.timezone,
        warning_after_minutes=720,
        stale_after_minutes=2880,
        missing_label="최근 학습 기록 없음",
    )
    freshness["latest_evaluation"] = _build_freshness_snapshot(
        (latest_evaluation or {}).get("evaluated_at"),
        timezone_name=settings.timezone,
        warning_after_minutes=720,
        stale_after_minutes=2880,
        missing_label="최근 평가 기록 없음",
    )

    ml_state = {
        "status": "장중 분석·예측 중" if live_runtime_state.get("status") == "running" else "대기 (장후 재학습)",
        "latest_completed_at": (latest_training or {}).get("completed_at"),
        "latest_model_version": (latest_training or {}).get("model_version"),
        "active_model_version_h15": active_model_entry.get("model_version"),
        "active_model_version_h60": active_model_entry_60.get("model_version"),
        "today_training_count": 0,
        "today_evaluation_count": 0,
        "recent_training_count": len(training_rows_all),
        "recent_evaluation_count": len(evaluation_rows_all),
        "training_mode": "장중에는 추론만 수행하고, 장후 재학습 또는 실제 데이터 재구성 시점에만 새 모델을 학습합니다.",
        "effective_h60_note": active_model_entry_60.get("note"),
        "latest_post_close_maintenance": None,
        "note": (
            "실시간 수집기는 장중 예측을 계속 수행하고, 학습 상태는 마지막 실제 데이터 기반 재학습 결과를 보여줍니다."
            if actual_labels > 0
            else "실제 장중 라벨이 아직 부족해 학습 상태는 마지막 연구용 결과를 참고하는 준비 단계입니다."
        ),
    }
    local_account_state = _build_local_account_summary(
        latest_snapshot=latest_portfolio_snapshot,
        positions=positions,
        all_positions=position_rows_all,
        orders=current_order_rows,
        fills=current_fill_rows,
        settings=settings,
        live_runtime_state=live_runtime_state,
    )
    reconciliation_local_account_state = load_local_paper_account_state(settings)

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
    today_training_runs = _reverse_recent(today_training_rows, 5)
    today_evaluations = _reverse_recent(today_evaluation_rows, 5)
    recent_training_runs = _reverse_recent(training_rows_all, 5)
    recent_evaluations = _reverse_recent(evaluation_rows_all, 8)
    latest_post_close_ml_maintenance = _safe_load_json(
        settings.runtime_data_dir / "reports" / "ml-maintenance" / "state" / "latest-post-close-ml.json"
    )
    latest_post_close_label_refresh = _safe_load_json(
        settings.runtime_data_dir / "reports" / "ml-maintenance" / "state" / "latest-post-close-label-refresh.json"
    )
    ml_state["today_training_count"] = len(today_training_runs)
    ml_state["today_evaluation_count"] = len(today_evaluations)
    ml_state["latest_post_close_maintenance"] = latest_post_close_ml_maintenance
    ml_state["latest_post_close_label_refresh"] = latest_post_close_label_refresh

    latest_backtest_report = _safe_load_json(settings.runtime_data_dir / "reports" / "backtests" / "latest-backtest-h15.json")
    latest_walk_forward_report = _safe_load_json(settings.runtime_data_dir / "reports" / "backtests" / "latest-walk-forward-h15.json")
    latest_challenger_report = _safe_load_json(settings.runtime_data_dir / "reports" / "challengers" / "latest-challengers-h15.json")
    latest_walk_forward_setup_status = _build_walk_forward_setup_status(latest_walk_forward_report)
    latest_kis_verification = _safe_load_json(settings.runtime_data_dir / "reports" / "kis-ws" / "latest-verification.json")
    latest_kis_live_data_quality = _safe_load_json(
        settings.runtime_data_dir / "reports" / "data-quality" / "latest-kis-live-data-quality.json"
    )
    latest_feature_source_drift = _safe_load_json(
        settings.runtime_data_dir / "reports" / "data-quality" / "latest-feature-source-drift.json"
    )
    latest_kis_live_feature_diagnostics = _safe_load_json(
        settings.runtime_data_dir / "reports" / "data-quality" / "latest-kis-live-feature-diagnostics.json"
    )
    latest_local_setup_check = _safe_load_json(
        settings.runtime_data_dir / "reports" / "recovery" / "latest-local-setup-check.json"
    )
    latest_codex_premarket_readiness = _safe_load_json(
        settings.runtime_data_dir
        / "reports"
        / "codex"
        / "ops"
        / "premarket-readiness"
        / "latest-premarket-readiness.json"
    )
    latest_live_readiness = _safe_load_json(
        settings.runtime_data_dir / "reports" / "live-readiness" / "latest-readiness.json"
    )
    latest_local_setup_freshness = _build_freshness_snapshot(
        latest_local_setup_check.get("checked_at") if isinstance(latest_local_setup_check, dict) else None,
        timezone_name=settings.timezone,
        warning_after_minutes=30,
        stale_after_minutes=180,
        missing_label="장전 점검 기록 없음",
    )
    if isinstance(latest_kis_verification, dict):
        latest_kis_verification = dict(latest_kis_verification)
        latest_kis_verification.setdefault(
            "latest_kis_verification_session_status",
            latest_kis_verification.get("session_status"),
        )
        latest_kis_verification["current_session_status"] = current_session_status
        latest_kis_verification["session_status"] = current_session_status
        if current_session_status == "holiday":
            latest_kis_verification["status_note"] = "오늘은 설정된 휴장일이므로 장중 실시간 데이터 수신을 기대하지 않습니다."
    status_alerts = _build_status_alerts(
        live_runtime_state=live_runtime_state,
        latest_kis_verification=latest_kis_verification if isinstance(latest_kis_verification, dict) else None,
        freshness=freshness,
        runtime_summary=runtime_summary,
        latest_training=latest_training if isinstance(latest_training, dict) else None,
        latest_evaluation=latest_evaluation if isinstance(latest_evaluation, dict) else None,
    )
    if int(live_fill_consistency.get("mismatch_count") or 0) > 0:
        status_alerts.insert(
            0,
            {
                "level": "warning",
                "title": "실전 fill 정합성 불일치",
                "message": (
                    f"{live_fill_consistency.get('trading_day') or '-'} 기준 "
                    f"{live_fill_consistency.get('mismatch_count')}건의 live order/fill 수량 불일치가 있습니다. "
                    "신규 실전 주문 intent는 차단되어야 합니다."
                ),
            },
        )
        status_alerts = status_alerts[:4]
    if int(live_order_attention.get("attention_count") or 0) > 0:
        status_alerts.insert(
            0,
            {
                "level": "warning",
                "title": "실전 주문 상태 확인 필요",
                "message": (
                    f"{live_order_attention.get('trading_day') or '-'} 기준 "
                    f"unknown/stuck 실전 주문 {live_order_attention.get('attention_count')}건이 있습니다. "
                    "브로커 조회로 상태를 확정하기 전 신규 실전 주문 intent는 보수적으로 차단해야 합니다."
                ),
            },
        )
        status_alerts = status_alerts[:4]

    paper_account_view = _build_account_view("모의계좌(실제)", paper_account_report)
    live_account_view = _build_account_view("실 운용계좌", live_account_report)
    account_sync = _build_account_sync_status(
        reconciliation_local_account_state,
        paper_account_view,
        order_mirroring_enabled=settings.strategy.enable_broker_paper_mirroring,
        mirrored_order_count=len(broker_submission_rows_all),
    )
    paper_account_reconciliation = build_paper_account_reconciliation_payload(
        local_account_state=reconciliation_local_account_state,
        broker_report=paper_account_report,
        order_mirroring_enabled=settings.strategy.enable_broker_paper_mirroring,
        mirrored_order_count=len(broker_submission_rows_all),
    )
    lightgbm_status = _build_lightgbm_status(
        settings=settings,
        latest_training=latest_training,
        latest_evaluation=latest_evaluation,
        active_model_entry=active_model_entry,
        runtime_summary=runtime_summary,
    )
    latest_challenger_report = _apply_current_challenger_dashboard_guards(latest_challenger_report, lightgbm_status)
    lightgbm_status["today_training_count"] = len(today_training_runs)
    lightgbm_status["today_evaluation_count"] = len(today_evaluations)
    lightgbm_status["recent_training_count"] = len(training_rows_all)
    lightgbm_status["recent_evaluation_count"] = len(evaluation_rows_all)
    lightgbm_status["latest_post_close_maintenance"] = latest_post_close_ml_maintenance
    lightgbm_status["latest_post_close_label_refresh"] = latest_post_close_label_refresh
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
            "note": active_model_entry_60.get("note") or "60분 예측용 활성 모델입니다.",
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
            "enable_broker_paper_mirroring": settings.strategy.enable_broker_paper_mirroring,
            "max_open_positions": settings.strategy.max_open_positions,
            "max_position_pct": settings.strategy.max_position_pct,
            "max_hold_minutes": settings.strategy.max_hold_minutes,
        },
        "runtime_summary": runtime_summary,
        "active_model": active_model_entry,
        "active_model_h60": active_model_entry_60,
        "local_account_state": local_account_state,
        "status_alerts": status_alerts,
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
            "freshness": freshness,
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
        "signal_replay_summary": signal_replay_summary,
        "paper_fill_return_summary": paper_fill_return_summary,
        "latest_training": latest_training,
        "latest_evaluation": latest_evaluation,
        "today_training_runs": today_training_runs,
        "today_evaluations": today_evaluations,
        "recent_training_runs": recent_training_runs,
        "recent_evaluations": recent_evaluations,
        "latest_backtest_report": latest_backtest_report,
        "latest_walk_forward_report": latest_walk_forward_report,
        "latest_walk_forward_setup_status": latest_walk_forward_setup_status,
        "latest_challenger_report": latest_challenger_report,
        "latest_kis_verification": latest_kis_verification,
        "latest_kis_live_data_quality": latest_kis_live_data_quality,
        "latest_feature_source_drift": latest_feature_source_drift,
        "latest_kis_live_feature_diagnostics": latest_kis_live_feature_diagnostics,
        "latest_local_setup_check": latest_local_setup_check,
        "latest_local_setup_freshness": latest_local_setup_freshness,
        "latest_codex_premarket_readiness": latest_codex_premarket_readiness,
        "latest_live_readiness": latest_live_readiness,
        "live_fill_consistency": live_fill_consistency,
        "live_order_attention": live_order_attention,
        "live_phase2_parent_order_limit": live_phase2_parent_order_limit,
        "latest_post_close_ml_maintenance": latest_post_close_ml_maintenance,
        "latest_portfolio_snapshot": latest_portfolio_snapshot,
        "positions": positions,
        "broker_account_report": paper_account_report,
        "paper_account_report": paper_account_report,
        "live_account_report": live_account_report,
        "account_views": account_views,
        "account_sync": account_sync,
        "paper_account_reconciliation": paper_account_reconciliation,
        "lightgbm_status": lightgbm_status,
        "recent_predictions": recent_predictions,
        "prediction_details": prediction_details,
        "prediction_flow_rows": prediction_flow_rows,
        "prediction_flow_full_day": prediction_flow_full_day,
        "recent_signals": recent_signals,
        "recent_orders": recent_orders,
        "recent_fills": recent_fills,
        "recent_broker_order_submissions": recent_broker_order_submissions,
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


def _render_dashboard_error_html(message: str, *, detail: str | None = None) -> str:
    detail_html = f"<p>{_esc(detail)}</p>" if detail else ""
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>\ub300\uc2dc\ubcf4\ub4dc \uc77c\uc2dc \uc810\uac80</title>
  <style>
    body {{ margin:0; background:#f4efe6; color:#15212d; font-family:\"Segoe UI\",\"Malgun Gothic\",sans-serif; }}
    .wrap {{ max-width:920px; margin:0 auto; padding:40px 20px; }}
    .card {{ background:#fffaf3; border:1px solid rgba(21,33,45,.12); border-radius:22px; padding:26px 28px; box-shadow:0 18px 40px rgba(21,33,45,.08); }}
    h1 {{ margin:0 0 14px; font-size:34px; }}
    p {{ margin:10px 0; line-height:1.7; }}
    .muted {{ color:#5e6b79; }}
    .button {{ display:inline-block; margin-top:14px; padding:10px 16px; border-radius:12px; background:#0d5c63; color:#fff; text-decoration:none; font-weight:700; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>\ub300\uc2dc\ubcf4\ub4dc \ub370\uc774\ud130\ub97c \uc7a0\uc2dc \ubd88\ub7ec\uc624\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4</h1>
      <p>{_esc(message)}</p>
      {detail_html}
      <p class="muted">\uc2e4\uc2dc\uac04 \uc218\uc9d1\uae30\uac00 \uac19\uc740 SQLite \ud30c\uc77c\uc5d0 \uae30\ub85d \uc911\uc774\ub77c \uc7a0\uae50 \ucda9\ub3cc\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4. \uc7a0\uc2dc \ud6c4 \ub2e4\uc2dc \uc0c1\ud0dc \uc5c5\ub370\uc774\ud2b8\ub97c \ub20c\ub7ec \uc8fc\uc138\uc694.</p>
      <a class="button" href="/">\ub2e4\uc2dc \uc2dc\ub3c4</a>
    </div>
  </div>
</body>
</html>"""

def _money(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):,.0f}원"
    except (TypeError, ValueError):
        return _esc(value)


def _signed_money(value: Any) -> str:
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _esc(value)
    if abs(numeric) < 0.5:
        return "0원"
    return f"{numeric:+,.0f}원"


def _number(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return _esc(value)


def _pct(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return _esc(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_walk_forward_setup_status(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict) or not report:
        return {
            "status": "missing",
            "status_label": "없음",
            "setup_status": "missing",
            "setup_status_label": "없음",
            "gate_status": "missing",
            "gate_status_label": "없음",
            "gate_reason": "정본 walk-forward 보고서가 아직 없습니다.",
            "note": "정본 walk-forward 보고서가 아직 없습니다.",
            "reasons": [],
        }

    min_train_rows = _optional_int(report.get("min_train_rows"))
    test_window_rows = _optional_int(report.get("test_window_rows"))
    step_rows = _optional_int(report.get("step_rows"))
    gap_rows = _optional_int(report.get("gap_rows"))
    max_train_rows = _optional_int(report.get("max_train_rows"))
    folds = _optional_int(report.get("folds"))
    reasons: list[str] = []

    if min_train_rows is not None and min_train_rows < 1000:
        reasons.append(f"min_train_rows={min_train_rows}은 승격 판단용 학습창으로 너무 작습니다.")
    if test_window_rows is not None and test_window_rows < 100:
        reasons.append(f"test_window_rows={test_window_rows}은 fold별 검증 표본으로 너무 작습니다.")
    if max_train_rows is not None and max_train_rows < 1000:
        reasons.append(f"max_train_rows={max_train_rows}은 장기 데이터 학습창으로 너무 작습니다.")
    if folds is not None and folds > 5000:
        reasons.append(f"folds={folds}로 너무 잘게 쪼개진 평가입니다.")

    setup_status = "needs_review" if reasons else "ok"
    note = " ".join(reasons) if reasons else "게이트 기준 walk-forward 설정이 기본 점검을 통과했습니다."

    overall_accuracy = _optional_float(report.get("overall_accuracy"))
    cumulative_net = _optional_float(report.get("cumulative_net_return_pct"))
    fold_summaries = report.get("fold_summaries")
    weakest_fold_accuracy = None
    if isinstance(fold_summaries, list) and fold_summaries:
        fold_accuracies: list[float] = []
        for fold in fold_summaries:
            if not isinstance(fold, dict):
                continue
            accuracy = _optional_float(fold.get("overall_accuracy"))
            if accuracy is not None:
                fold_accuracies.append(accuracy)
        if fold_accuracies:
            weakest_fold_accuracy = min(fold_accuracies)

    gate_reasons: list[str] = []
    if setup_status == "needs_review":
        gate_reasons.append("walk-forward 설정 점검이 필요합니다.")
    if overall_accuracy is None:
        gate_reasons.append("overall_accuracy가 없습니다.")
    elif overall_accuracy < 0.55:
        gate_reasons.append(f"overall_accuracy={overall_accuracy:.4f}로 0.55 미만입니다.")
    if weakest_fold_accuracy is not None and weakest_fold_accuracy <= 0.0:
        gate_reasons.append("최소 fold 정확도가 0 이하입니다.")
    if cumulative_net is None:
        gate_reasons.append("cumulative_net_return_pct가 없습니다.")
    elif cumulative_net <= 0.0:
        gate_reasons.append(f"cumulative_net_return_pct={cumulative_net:.4f}로 양수가 아닙니다.")

    gate_status = "needs_review" if gate_reasons else "pass"
    gate_reason = " ".join(gate_reasons) if gate_reasons else "워크포워드 gate 기준을 통과했습니다."
    return {
        "status": setup_status,
        "status_label": "점검 필요" if setup_status == "needs_review" else "정상",
        "setup_status": setup_status,
        "setup_status_label": "점검 필요" if setup_status == "needs_review" else "정상",
        "gate_status": gate_status,
        "gate_status_label": "점검 필요" if gate_status == "needs_review" else "통과",
        "gate_reason": gate_reason,
        "weakest_fold_accuracy": weakest_fold_accuracy,
        "note": note,
        "reasons": reasons,
        "evaluated_at": report.get("evaluated_at"),
        "model_version": report.get("model_version"),
        "folds": folds,
        "min_train_rows": min_train_rows,
        "test_window_rows": test_window_rows,
        "step_rows": step_rows,
        "gap_rows": gap_rows,
        "max_train_rows": max_train_rows,
        "overall_accuracy": report.get("overall_accuracy"),
        "trade_hit_rate": report.get("trade_hit_rate"),
        "cumulative_net_return_pct": report.get("cumulative_net_return_pct"),
        "reference_path": "runtime-data/reports/backtests/latest-walk-forward-h15.json",
    }


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


def _duration_seconds_text(value: Any) -> str:
    if value is None:
        return "-"
    try:
        seconds = max(int(float(value)), 0)
    except (TypeError, ValueError):
        return _esc(value)
    if seconds < 60:
        return f"{seconds}초"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}분"
    hours = minutes // 60
    minutes = minutes % 60
    if hours < 24:
        return f"{hours}시간 {minutes}분" if minutes else f"{hours}시간"
    days = hours // 24
    hours = hours % 24
    return f"{days}일 {hours}시간" if hours else f"{days}일"


def _scroll_box(content: str, *, max_height: int = 380, css_class: str = "data-scroll") -> str:
    return f'<div class="{css_class}" style="max-height:{max_height}px;">{content}</div>'


def _table(
    headers: list[str],
    rows: list[list[Any]],
    empty_text: str,
    *,
    scroll_height: int = 380,
    table_class: str | None = None,
) -> str:
    if not rows:
        return f'<div class="empty">{_esc(empty_text)}</div>'
    header_html = "".join(f"<th>{_esc(header)}</th>" for header in headers)
    row_html = []
    for row in rows:
        row_html.append("<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in row) + "</tr>")
    class_attr = f' class="{_esc(table_class)}"' if table_class else ""
    return _scroll_box(
        f"<table{class_attr}><thead><tr>{header_html}</tr></thead><tbody>{''.join(row_html)}</tbody></table>",
        max_height=scroll_height,
    )


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _readiness_fixture_check(report: dict[str, Any], key: str) -> dict[str, Any]:
    for item in report.get("fixture_checks") or []:
        if isinstance(item, dict) and item.get("key") == key:
            return item
    return {}


def _format_evidence_freshness(details: dict[str, Any]) -> str:
    age = details.get("evidence_age_seconds")
    max_age = details.get("max_evidence_age_seconds")
    if age is None and max_age is None:
        return "-"
    if age is None:
        return f"max {max_age}s"
    if max_age is None:
        return f"{age}s"
    return f"{age}s / max {max_age}s"


def _format_yes_no(value: Any) -> str:
    if value is None:
        return "-"
    return "예" if bool(value) else "아니오"


def _format_ws_reconnect_snapshot(details: dict[str, Any]) -> str:
    stable = _as_dict(details.get("stable"))
    source = stable or details
    cumulative = source.get("cumulative_reconnects")
    consecutive = source.get("consecutive_reconnects")
    storm = source.get("reconnect_storm")
    if cumulative is None and consecutive is None and storm is None:
        return "-"
    return f"누적 {cumulative if cumulative is not None else '-'}, 연속 {consecutive if consecutive is not None else '-'}, storm {_format_yes_no(storm)}"


def _list(items: list[str], empty_text: str, *, scroll_height: int = 320) -> str:
    if not items:
        return f'<div class="empty">{_esc(empty_text)}</div>'
    return _scroll_box("<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>", max_height=scroll_height)


def _pill_row(items: list[str]) -> str:
    return '<div class="pillrow">' + "".join(f'<span class="pill">{item}</span>' for item in items if item) + "</div>"


def _alert_list(items: list[dict[str, str]]) -> str:
    if not items:
        return '<div class="muted">지금은 즉시 조치가 필요한 경고가 없습니다.</div>'
    rows: list[str] = []
    for item in items:
        level = str(item.get("level") or "info").strip().lower()
        css_class = "alert-card is-warning" if level == "warning" else "alert-card"
        rows.append(
            f'<div class="{css_class}">'
            f'<strong>{_esc(item.get("title") or "-")}</strong>'
            f'<div class="muted">{_esc(item.get("message") or "-")}</div>'
            "</div>"
        )
    return '<div class="alert-list">' + "".join(rows) + "</div>"


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


def _section_card(title: str, body: str, *, note: str | None = None) -> str:
    note_html = f'<div class="muted" style="margin-top:12px;">{note}</div>' if note else ""
    return f'<div class="card card-embedded"><h3>{_esc(title)}</h3>{body}{note_html}</div>'


def _stack_cards(*cards: str) -> str:
    return '<div class="stack">' + "".join(cards) + "</div>"


def _render_subtab_shell(title: str, group: str, sections: list[tuple[str, str, str]]) -> str:
    nav_html = []
    panel_html = []
    for index, (target, label, content) in enumerate(sections):
        active = index == 0
        nav_html.append(_subtab_button(group, target, label, active=active, vertical=True))
        panel_html.append(
            f'<div id="{_esc(target)}" class="subtab-panel{" is-active" if active else ""}" '
            f'data-subtab-panel="{_esc(group)}">{content}</div>'
        )
    return (
        f'<section class="section-shell"><h2>{_esc(title)}</h2><div class="subtab-shell">'
        f'<div class="subtab-nav" role="tablist" aria-label="{_esc(title)} 세부 탭">{"".join(nav_html)}</div>'
        f'<div>{"".join(panel_html)}</div></div></section>'
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
    refresh_meta = ""
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
        for row in (payload.get("prediction_details") or payload.get("recent_predictions", []))
    ]
    prediction_rows = [
        [
            row["event_time"],
            row.get("symbol_label") or row["symbol"],
            f'{row["horizon_min"]}분',
            row["model_version"],
            _money(row.get("base_close")),
            row["predicted_change_text"],
            row["actual_change_text"],
            row.get("success_text") or "-",
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
        [row["bar_time"], row["symbol"], _money(row.get("close")), _number(row.get("volume"))]
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
        ["브로커 모의주문 미러링", "예" if payload.get("project", {}).get("enable_broker_paper_mirroring") else "아니오"],
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
              <h2>검증 및 비교 결과</h2>
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
              <span class="pill">거래합산 순수익률: {_pct(latest_backtest.get('trade_sum_net_return_pct', latest_backtest.get('cumulative_net_return_pct')), 4)}</span>
              <span class="pill">비용 차감 합계: {_pct(latest_backtest.get('estimated_cost_drag_pct'), 4)}</span>
            </div>
          </div>
          <div class="card">
            <h2>워크포워드 요약</h2>
            <div class="pillrow">
              <span class="pill">fold 수: {_esc(latest_walk_forward.get('folds'))}</span>
              <span class="pill">정확도: {_pct(latest_walk_forward.get('overall_accuracy'), 4)}</span>
              <span class="pill">거래 수: {_esc(latest_walk_forward.get('trades_taken'))}</span>
              <span class="pill">거래합산 순수익률: {_pct(latest_walk_forward.get('trade_sum_net_return_pct', latest_walk_forward.get('cumulative_net_return_pct')), 4)}</span>
              <span class="pill">비용 차감 합계: {_pct(latest_walk_forward.get('estimated_cost_drag_pct'), 4)}</span>
            </div>
          </div>
          <div class="card">
            <h2>챌린저 비교</h2>
            {_table(['순위','후보','모델 버전','정확도','거래 적중률','거래 수','누적 순수익률','평가 자격','승격 판단','독립성/아티팩트'], challenger_rows, '챌린저 비교 결과가 없습니다.')}
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
        const triggerRefresh = () => {{
          refreshButton.disabled = true;
          refreshButton.textContent = '업데이트 중...';
          fetch('/api/refresh', {{ cache: 'no-store' }})
            .catch(() => null)
            .finally(() => window.location.reload());
        }};
        refreshButton.addEventListener('click', () => {{
          triggerRefresh();
        }});
        const refreshIntervalMs = {max(refresh_seconds, 1) * 1000};
        window.setTimeout(() => {{
          triggerRefresh();
        }}, refreshIntervalMs);
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
    status_alerts = payload.get("status_alerts", []) or []
    freshness = system_status.get("freshness", {}) or {}
    dashboard_freshness = freshness.get("dashboard_generated", {}) or {}
    market_bar_freshness = freshness.get("latest_market_bar", {}) or {}
    prediction_freshness = freshness.get("latest_prediction", {}) or {}
    signal_freshness = freshness.get("latest_signal", {}) or {}
    kis_freshness = freshness.get("latest_kis_verification", {}) or {}
    training_freshness = freshness.get("latest_training", {}) or {}
    evaluation_freshness = freshness.get("latest_evaluation", {}) or {}
    active_model = payload.get("active_model", {}) or {}
    active_model_h60 = payload.get("active_model_h60", {}) or {}
    learning_context = payload.get("learning_context", {}) or {}
    latest_training = payload.get("latest_training", {}) or {}
    latest_evaluation = payload.get("latest_evaluation", {}) or {}
    latest_backtest = payload.get("latest_backtest_report", {}) or {}
    latest_walk_forward = payload.get("latest_walk_forward_report", {}) or {}
    latest_walk_forward_setup = payload.get("latest_walk_forward_setup_status", {}) or {}
    latest_challenger = payload.get("latest_challenger_report", {}) or {}
    latest_kis = payload.get("latest_kis_verification", {}) or {}
    latest_kis_quality = payload.get("latest_kis_live_data_quality", {}) or {}
    latest_feature_source_drift = payload.get("latest_feature_source_drift", {}) or {}
    latest_kis_feature_diagnostics = payload.get("latest_kis_live_feature_diagnostics", {}) or {}
    latest_local_setup = payload.get("latest_local_setup_check", {}) or {}
    latest_local_setup_freshness = payload.get("latest_local_setup_freshness", {}) or {}
    lightgbm_status = payload.get("lightgbm_status", {}) or {}
    prediction_summary = payload.get("prediction_summary", {}) or {}
    signal_order_summary = payload.get("signal_order_summary", {}) or {}
    signal_replay_summary = payload.get("signal_replay_summary", {}) or {}
    paper_fill_return_summary = payload.get("paper_fill_return_summary", {}) or {}
    prediction_flow_full_day = bool(payload.get("prediction_flow_full_day"))
    today_report = payload.get("today_report", {}) or {}
    account_views = payload.get("account_views", {}) or {}
    virtual_account = account_views.get("virtual_paper", {}) or {}
    paper_account = account_views.get("paper_broker", {}) or {}
    live_account = account_views.get("live_broker", {}) or {}
    account_sync = payload.get("account_sync", {}) or {}
    paper_account_reconciliation = payload.get("paper_account_reconciliation", {}) or {}
    audit_progress = (payload.get("audit") or {}).get("progress") or {}
    audit_backlog = (payload.get("audit") or {}).get("backlog") or {}

    refresh_meta = ""
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
    prediction_flow_rows = [
        [
            row.get("flow_no"),
            row.get("event_time"),
            row.get("symbol_label"),
            row.get("model_prediction_text"),
            row.get("actual_result_text"),
            row.get("signal_text"),
            row.get("order_text"),
            row.get("fill_text"),
            row.get("profit_text"),
            row.get("link_text"),
        ]
        for row in payload.get("prediction_flow_rows", [])
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
        [row.get("bar_time"), row.get("symbol"), _money(row.get("open")), _money(row.get("high")), _money(row.get("low")), _money(row.get("close")), _number(row.get("volume"))]
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
    recent_training_rows = [
        [row.get("completed_at"), row.get("model_version"), row.get("train_rows"), row.get("validation_rows"), row.get("feature_set_version")]
        for row in payload.get("recent_training_runs", [])
    ]
    recent_evaluation_rows = [
        [row.get("evaluated_at"), row.get("split_name"), _ratio_pct(row.get("accuracy"), 2), row.get("total_rows")]
        for row in payload.get("recent_evaluations", [])
    ]
    challenger_rows = [
        [
            row.get("rank"),
            row.get("candidate_name"),
            row.get("model_version"),
            _ratio_pct(row.get("overall_accuracy"), 2),
            _ratio_pct(row.get("trade_hit_rate"), 2),
            row.get("trades_taken"),
            _pct(row.get("cumulative_net_return_pct"), 2),
            "있음" if row.get("promotable") else "없음",
            _challenger_decision_label(row, latest_challenger),
            row.get("artifact_training_status") or row.get("evaluation_independence_status") or "-",
        ]
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
        ["KIS 검증 상태", kis_freshness.get("label") or "미확인"],
        ["KIS 마지막 검증", latest_kis.get("verified_at") or "-"],
        ["최근 분봉 시각", system_status.get("latest_market_bar_time")],
        ["분봉 신선도", market_bar_freshness.get("label") or "미확인"],
        ["최근 예측 시각", system_status.get("latest_prediction_time")],
        ["예측 신선도", prediction_freshness.get("label") or "미확인"],
        ["최근 신호 시각", system_status.get("latest_signal_time")],
        ["신호 신선도", signal_freshness.get("label") or "미확인"],
        ["머신러닝 상태", ml_state.get("status")],
        ["최근 학습 완료", ml_state.get("latest_completed_at")],
        ["학습 결과 신선도", training_freshness.get("label") or "미확인"],
        ["대시보드 갱신", payload.get("generated_at")],
        ["대시보드 신선도", dashboard_freshness.get("label") or "미확인"],
        ["현재 범위", period_filter.get("label")],
    ]
    local_setup_dashboard = latest_local_setup.get("dashboard_status") or {}
    local_setup_live_runtime = latest_local_setup.get("live_runtime_status") or {}
    local_setup_watchdog = latest_local_setup.get("watchdog_status") or {}
    local_setup_startup = latest_local_setup.get("runtime_startup_launcher_status") or {}
    local_setup_blockers = latest_local_setup.get("blockers") or []
    local_setup_mirroring_enabled = latest_local_setup.get("broker_paper_mirroring_enabled")
    local_setup_mirroring_level = latest_local_setup.get("broker_paper_mirroring_level") or "-"
    local_setup_mirroring_status = latest_local_setup.get("broker_paper_mirroring_status") or "-"
    latest_codex_premarket_readiness = payload.get("latest_codex_premarket_readiness", {}) or {}
    latest_live_readiness = payload.get("latest_live_readiness", {}) or {}
    live_readiness_run = latest_live_readiness.get("readiness_run") or {}
    live_readiness_checks = (live_readiness_run.get("checks_json") or {}).get("checks") or {}
    live_readiness_blockers = latest_live_readiness.get("blocking_reasons") or []
    ws_recovery_check = _readiness_fixture_check(latest_live_readiness, "ws_recovery")
    ws_recovery_details = _as_dict(ws_recovery_check.get("details"))
    ws_recovery_stable = _as_dict(ws_recovery_details.get("stable"))
    ws_recovery_evidence_type = str(ws_recovery_details.get("evidence_type") or "").strip()
    local_setup_rows = [
        ["전체 상태", "ok" if latest_local_setup.get("ok") else "점검 필요" if latest_local_setup else "-"],
        ["점검 시각", latest_local_setup.get("checked_at") or "-"],
        [
            "점검 신선도",
            (
                f"{latest_local_setup_freshness.get('label')} / {latest_local_setup_freshness.get('note')}"
                if latest_local_setup_freshness.get("available")
                else latest_local_setup_freshness.get("label") or "-"
            ),
        ],
        ["blockers", ", ".join(local_setup_blockers) if local_setup_blockers else "none"],
        ["대시보드", local_setup_dashboard.get("status") or "-"],
        ["대시보드 응답", "예" if local_setup_dashboard.get("dashboard_api_responding") else "아니오"],
        ["watchdog", local_setup_watchdog.get("status") or "-"],
        ["live runtime", local_setup_live_runtime.get("status") or "-"],
        ["장 상태", local_setup_watchdog.get("market_session_status") or local_setup_live_runtime.get("session_status") or "-"],
        ["live runtime 필요", "예" if local_setup_watchdog.get("live_runtime_should_run") else "아니오"],
        [
            "브로커 paper 미러링",
            (
                f"{'예' if local_setup_mirroring_enabled else '아니오'} / "
                f"{local_setup_mirroring_level} / {local_setup_mirroring_status}"
            ),
        ],
        ["KIS 시세 자격정보", "준비됨" if local_setup_live_runtime.get("credentials_ready_for_quotes") else "점검 필요"],
        ["startup launcher", "ok" if local_setup_startup.get("ok") else "점검 필요" if local_setup_startup else "-"],
        ["websockets", "예" if latest_local_setup.get("websockets_available") else "아니오"],
        ["lightgbm", "예" if latest_local_setup.get("lightgbm_available") else "아니오"],
    ]
    live_readiness_rows = [
        ["Codex premarket", latest_codex_premarket_readiness.get("status") or "-"],
        ["Live readiness", latest_live_readiness.get("status") or live_readiness_run.get("status") or "-"],
        ["phase", latest_live_readiness.get("phase") or live_readiness_run.get("phase") or "-"],
        ["trading day", latest_live_readiness.get("trading_day") or live_readiness_run.get("trading_day") or "-"],
        ["생성 시각", latest_live_readiness.get("generated_at") or live_readiness_run.get("checked_at") or "-"],
        ["dry-run", "예" if latest_live_readiness.get("dry_run") else "아니오" if latest_live_readiness else "-"],
        ["DB 기록", "예" if latest_live_readiness.get("recorded") else "아니오" if latest_live_readiness else "-"],
        ["DB 경로", latest_live_readiness.get("database_path") or "-"],
        ["통과", "예" if live_readiness_run.get("passed") else "아니오" if live_readiness_run else "-"],
        ["blockers", ", ".join(live_readiness_blockers) if live_readiness_blockers else "none"],
        ["token refresh", "ok" if live_readiness_checks.get("token_refresh") else "미검증/차단"],
        ["WS recovery", "ok" if live_readiness_checks.get("ws_recovery") else "미검증/차단"],
        ["WS recovery 상태", ws_recovery_check.get("status") or "-"],
        ["WS evidence type", ws_recovery_evidence_type or "-"],
        [
            "WS real evidence",
            _format_yes_no(is_real_ws_recovery_evidence_type(ws_recovery_evidence_type))
            if ws_recovery_evidence_type
            else "-",
        ],
        ["WS evidence freshness", _format_evidence_freshness(ws_recovery_details)],
        ["WS stable state", ws_recovery_stable.get("state") or "-"],
        [
            "WS stable frames",
            (
                f"{ws_recovery_stable.get('frames_since_connect')} / {ws_recovery_stable.get('frames_seen_total')}"
                if ws_recovery_stable
                else "-"
            ),
        ],
        ["WS reconnects", _format_ws_reconnect_snapshot(ws_recovery_details)],
        ["WS observed at", ws_recovery_stable.get("observed_at") or ws_recovery_details.get("checked_at") or "-"],
        ["account snapshot", "ok" if live_readiness_checks.get("account_snapshot") else "미검증/차단"],
        ["market status", "ok" if live_readiness_checks.get("market_status") else "미검증/차단"],
        ["kill switch", "ok" if live_readiness_checks.get("kill_switch") else "미검증/차단"],
        ["database", "ok" if live_readiness_checks.get("database") else "미검증/차단"],
        ["disk space", "ok" if live_readiness_checks.get("disk_space") else "미검증/차단"],
        ["dashboard", "ok" if live_readiness_checks.get("dashboard") else "미검증/차단"],
        [
            "storage migration",
            "ok" if live_readiness_checks.get("storage_migration_state") else "미검증/차단",
        ],
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
        f"결과 없음: {prediction_summary.get('no_result', 0)}",
        f"예측 성공: {prediction_summary.get('success_count', 0)}",
        f"성공률: {_ratio_pct(prediction_summary.get('success_rate'), 1)}",
        f"신호 replay 손익: {_signed_money(signal_replay_summary.get('estimated_net_pnl'))} / {_format_signed_pct(signal_replay_summary.get('net_return_sum_pct'))}",
        f"실제 paper 청산손익: {_signed_money(paper_fill_return_summary.get('net_pnl'))} / {_format_signed_pct(paper_fill_return_summary.get('return_on_basis_pct'))}",
    ]
    prediction_session_rows = [
        [
            key,
            value.get("total", 0),
            value.get("evaluated", 0),
            value.get("success_count", 0),
            _ratio_pct(value.get("success_rate"), 1),
            _money(value.get("avg_actual_change_amount")),
        ]
        for key, value in (prediction_summary.get("session_stats") or {}).items()
    ]
    prediction_hour_rows = [
        [
            key,
            value.get("total", 0),
            value.get("evaluated", 0),
            value.get("success_count", 0),
            _ratio_pct(value.get("success_rate"), 1),
        ]
        for key, value in (prediction_summary.get("hour_slot_stats") or {}).items()
    ]
    prediction_direction_rows = [
        [
            _translate_prediction_label(key if key != "unknown" else None),
            value.get("total", 0),
            value.get("evaluated", 0),
            value.get("success_count", 0),
            _ratio_pct(value.get("success_rate"), 1),
            _money(value.get("avg_predicted_change_amount")),
            _money(value.get("avg_actual_change_amount")),
        ]
        for key, value in (prediction_summary.get("direction_stats") or {}).items()
    ]
    return_interpretation_rows = [
        [
            "예측 정확도",
            f"{prediction_summary.get('evaluated', 0)}건 확정",
            _ratio_pct(prediction_summary.get("success_rate"), 1),
            "up/down/flat 예측 label이 실제 label과 맞았는지 봅니다. 주문 실행 여부와는 별도입니다.",
        ],
        [
            "신호 replay",
            f"{signal_replay_summary.get('trades_closed', 0)}건 청산 / {signal_replay_summary.get('trades_opened', 0)}건 진입",
            f"{_signed_money(signal_replay_summary.get('estimated_net_pnl'))} / {_format_signed_pct(signal_replay_summary.get('net_return_sum_pct'))}",
            (
                "미보유+매수 허용은 진입, 보유+매도 신호는 청산, 미보유+매도는 신규 숏 없이 진입 회피로 보는 "
                "현물 기준 가상 수익률입니다."
            ),
        ],
        [
            "실제 paper 체결",
            f"{paper_fill_return_summary.get('closed_trades', 0)}건 청산",
            f"{_signed_money(paper_fill_return_summary.get('net_pnl'))} / {_format_signed_pct(paper_fill_return_summary.get('return_on_basis_pct'))}",
            "실제 paper 체결 원장을 FIFO로 맞춘 청산 손익입니다. 시간기반 paper 청산과 브로커 체결 결과가 섞여 있습니다.",
        ],
    ]
    signal_replay_rows = [
        ["계산 방식", signal_replay_summary.get("model") or "-"],
        ["거래 비용 모델", signal_replay_summary.get("cost_model") or "-"],
        ["왕복 비용", _format_signed_pct(signal_replay_summary.get("round_trip_cost_pct"))],
        ["가정 포지션 금액", _money(signal_replay_summary.get("position_notional"))],
        ["관측 신호", signal_replay_summary.get("signals_seen", 0)],
        ["진입", signal_replay_summary.get("trades_opened", 0)],
        ["청산", signal_replay_summary.get("trades_closed", 0)],
        ["승률", _ratio_pct(signal_replay_summary.get("win_rate"), 1)],
        ["신호 청산", signal_replay_summary.get("signal_exit_count", 0)],
        ["시간 청산", signal_replay_summary.get("time_exit_count", 0)],
        ["장마감 청산", signal_replay_summary.get("forced_flat_count", 0)],
        ["미보유 매도 회피", signal_replay_summary.get("avoided_short_entries", 0)],
        ["최대 보유수 초과 스킵", signal_replay_summary.get("skipped_max_positions", 0)],
        ["순손익", _signed_money(signal_replay_summary.get("estimated_net_pnl"))],
        ["거래합산 순수익률", _format_signed_pct(signal_replay_summary.get("net_return_sum_pct"))],
        ["설명", signal_replay_summary.get("description") or "-"],
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
    sync_rows = [
        ["현재 비교 상태", account_sync.get("status") or "-"],
        ["브로커 주문 자동 연동", "예" if account_sync.get("order_mirroring_enabled") else "아니오"],
        ["브로커 제출 주문 수", account_sync.get("mirrored_order_count") or 0],
        ["보유 종목 일치", "예" if account_sync.get("positions_match") else "아니오"],
        ["현금 잔고 일치", "예" if account_sync.get("balance_match") else "아니오"],
        ["현금 차이", _money(account_sync.get("cash_gap"))],
    ]
    reconciliation_rows = [
        ["최근 점검 상태", paper_account_reconciliation.get("status") or "-"],
        ["차이 건수", paper_account_reconciliation.get("mismatch_count") or 0],
        ["보유 종목 일치", "예" if paper_account_reconciliation.get("positions_match") else "아니오"],
        ["예수금 일치", "예" if paper_account_reconciliation.get("balance_match") else "아니오"],
        ["예수금 차이", _money(paper_account_reconciliation.get("cash_gap"))],
        ["총자산 차이", _money(paper_account_reconciliation.get("total_asset_gap"))],
        ["최근 브로커 제출 시각", paper_account_reconciliation.get("latest_broker_submission_time") or "-"],
        ["최근 브로커 조회 시각", paper_account_reconciliation.get("latest_broker_fetch_time") or "-"],
    ]
    reconciliation_mismatch_rows = [
        [
            row.get("symbol"),
            row.get("symbol_name") or "-",
            row.get("status"),
            row.get("local_qty"),
            row.get("broker_qty"),
            row.get("qty_gap"),
            _money(row.get("local_market_value")),
            _money(row.get("broker_evaluation_amount")),
        ]
        for row in paper_account_reconciliation.get("mismatch_rows", [])
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
        f"KIS 품질: {(latest_kis_quality.get('assessment') or {}).get('status') or '-'}",
        f"KIS 최신일: {latest_kis_quality.get('latest_trade_date') or '-'}",
        f"소스 drift: {(latest_feature_source_drift.get('assessment') or {}).get('posture') or '-'}",
        f"KIS 피처 진단: {(latest_kis_feature_diagnostics.get('assessment') or {}).get('posture') or '-'}",
        f"오늘 학습: {len(payload.get('today_training_runs', []))}건",
        f"오늘 평가: {len(payload.get('today_evaluations', []))}건",
        f"누적 학습: {len(payload.get('recent_training_runs', []))}건 표시 / 전체 {ml_state.get('recent_training_count', 0)}건",
        f"누적 평가: {len(payload.get('recent_evaluations', []))}건 표시 / 전체 {ml_state.get('recent_evaluation_count', 0)}건",
        f"최신 학습 모델: {latest_training.get('model_version') or '-'}",
        f"활성 모델(15분): {active_model.get('model_version') or '-'}",
        f"활성 모델(60분): {active_model_h60.get('model_version') or '미설정'}",
        f"학습 validation 정확도: {_ratio_pct(latest_evaluation.get('accuracy'), 2) if latest_evaluation else '-'}",
        f"워크포워드 설정: {latest_walk_forward_setup.get('setup_status_label') or latest_walk_forward_setup.get('status_label') or '-'}",
        f"게이트 성능 판단: {latest_walk_forward_setup.get('gate_status_label') or '-'}",
        f"ML 상태: {ml_state.get('status') or '-'}",
    ]
    feature_drift_assessment = latest_feature_source_drift.get("assessment") or {}
    feature_drift_samples = latest_feature_source_drift.get("samples") or {}
    feature_drift_kis_sample = feature_drift_samples.get("kis_live") or {}
    feature_drift_cybos_sample = feature_drift_samples.get("cybos_historical") or {}
    feature_drift_findings = latest_feature_source_drift.get("drift_findings") or []
    feature_drift_key_findings = [
        f"{item.get('feature')}: {', '.join(item.get('flags') or [])}"
        for item in feature_drift_findings[:4]
    ]
    feature_source_drift_rows = [
        ["상태", feature_drift_assessment.get("posture") or "-"],
        ["생성 시각", latest_feature_source_drift.get("generated_at") or "-"],
        ["KIS 날짜 선택", latest_feature_source_drift.get("kis_date_selection") or "-"],
        ["KIS 거래일", ", ".join(latest_feature_source_drift.get("kis_trade_dates") or []) or "-"],
        ["KIS rows/symbols", f"{feature_drift_kis_sample.get('rows', 0)} / {feature_drift_kis_sample.get('symbols', 0)}"],
        ["KIS 기간", f"{feature_drift_kis_sample.get('first_event_time') or '-'}..{feature_drift_kis_sample.get('last_event_time') or '-'}"],
        [
            "KIS h15 labels",
            (
                f"down {(feature_drift_kis_sample.get('label_distribution_h15') or {}).get('down', 0)} / "
                f"flat {(feature_drift_kis_sample.get('label_distribution_h15') or {}).get('flat', 0)} / "
                f"up {(feature_drift_kis_sample.get('label_distribution_h15') or {}).get('up', 0)}"
            ),
        ],
        ["Cybos rows/symbols", f"{feature_drift_cybos_sample.get('rows', 0)} / {feature_drift_cybos_sample.get('symbols', 0)}"],
        ["Cybos 기간", f"{feature_drift_cybos_sample.get('first_event_time') or '-'}..{feature_drift_cybos_sample.get('last_event_time') or '-'}"],
        [
            "Cybos h15 labels",
            (
                f"down {(feature_drift_cybos_sample.get('label_distribution_h15') or {}).get('down', 0)} / "
                f"flat {(feature_drift_cybos_sample.get('label_distribution_h15') or {}).get('flat', 0)} / "
                f"up {(feature_drift_cybos_sample.get('label_distribution_h15') or {}).get('up', 0)}"
            ),
        ],
        ["호가 mismatch 피처", ", ".join(feature_drift_assessment.get("orderbook_mismatch_features") or []) or "-"],
        ["주요 drift", " / ".join(feature_drift_key_findings) or "-"],
        ["결론", feature_drift_assessment.get("conclusion") or "-"],
        ["리포트", "runtime-data/reports/data-quality/latest-feature-source-drift.json"],
    ]
    kis_feature_assessment = latest_kis_feature_diagnostics.get("assessment") or {}
    kis_feature_sample = latest_kis_feature_diagnostics.get("sample") or {}
    kis_feature_diagnostics = latest_kis_feature_diagnostics.get("feature_diagnostics") or []
    kis_feature_rank_rows = [
        [
            item.get("feature"),
            item.get("rows") or 0,
            item.get("pearson_future_return"),
            item.get("top_bottom_future_return_delta_pct"),
            item.get("top_bottom_up_ratio_delta"),
        ]
        for item in kis_feature_diagnostics[:6]
    ]
    kis_feature_diagnostic_rows = [
        ["상태", kis_feature_assessment.get("posture") or "-"],
        ["생성 시각", latest_kis_feature_diagnostics.get("generated_at") or "-"],
        ["날짜 선택", latest_kis_feature_diagnostics.get("date_selection") or "-"],
        ["거래일", ", ".join(latest_kis_feature_diagnostics.get("trade_dates") or []) or "-"],
        ["rows/symbols", f"{kis_feature_sample.get('rows', 0)} / {kis_feature_sample.get('symbols', 0)}"],
        ["label 닫힌 거래일", kis_feature_sample.get("trade_dates") or 0],
        ["기간", f"{kis_feature_sample.get('first_event_time') or '-'}..{kis_feature_sample.get('last_event_time') or '-'}"],
        [
            "h15 label 분포",
            (
                f"down {(kis_feature_sample.get('label_distribution') or {}).get('down', 0)} / "
                f"flat {(kis_feature_sample.get('label_distribution') or {}).get('flat', 0)} / "
                f"up {(kis_feature_sample.get('label_distribution') or {}).get('up', 0)}"
            ),
        ],
        ["평균 future return", kis_feature_sample.get("avg_future_return_pct") if kis_feature_sample.get("avg_future_return_pct") is not None else "-"],
        ["strongest feature", kis_feature_assessment.get("strongest_feature") or "-"],
        ["strongest Pearson", kis_feature_assessment.get("strongest_feature_pearson") if kis_feature_assessment.get("strongest_feature_pearson") is not None else "-"],
        [
            "strongest top-bottom delta",
            kis_feature_assessment.get("strongest_feature_top_bottom_delta_pct")
            if kis_feature_assessment.get("strongest_feature_top_bottom_delta_pct") is not None
            else "-",
        ],
        ["결론", kis_feature_assessment.get("conclusion") or "-"],
        ["리포트", "runtime-data/reports/data-quality/latest-kis-live-feature-diagnostics.json"],
    ]
    post_close_maintenance = lightgbm_status.get("latest_post_close_maintenance") or {}
    post_close_tasks = post_close_maintenance.get("tasks") or []
    post_close_has_training = any(
        keyword in str(task).lower()
        for task in post_close_tasks
        for keyword in ("train", "challenger", "walk-forward", "backtest")
    )
    post_close_rows = [
        ["상태", post_close_maintenance.get("status") or "-"],
        ["기준일", post_close_maintenance.get("maintenance_date") or "-"],
        ["시작 시각", post_close_maintenance.get("started_at") or "-"],
        ["완료 시각", post_close_maintenance.get("completed_at") or "-"],
        ["실행 모드", post_close_maintenance.get("mode") or "-"],
        ["학습/평가 수행", "예" if post_close_has_training else "아니오 (리포트/진단만)"],
        [
            "예측 수평선",
            f"{post_close_maintenance.get('horizon_min')}분"
            if post_close_maintenance.get("horizon_min") is not None
            else "-",
        ],
        ["작업", ", ".join(post_close_tasks) or "-"],
        ["프로세스 ID", post_close_maintenance.get("pid") or "-"],
        ["스냅샷 DB", post_close_maintenance.get("snapshot_path") or "-"],
        ["스냅샷 runtime", post_close_maintenance.get("snapshot_runtime_data_dir") or "-"],
        ["stdout 로그", post_close_maintenance.get("stdout_log_path") or "-"],
        ["stderr 로그", post_close_maintenance.get("stderr_log_path") or "-"],
        ["오류", post_close_maintenance.get("error") or "-"],
    ]
    post_close_label_refresh = lightgbm_status.get("latest_post_close_label_refresh") or {}
    post_close_label_rows = [
        ["상태", post_close_label_refresh.get("status") or "-"],
        ["기준일", post_close_label_refresh.get("maintenance_date") or "-"],
        ["완료 시각", post_close_label_refresh.get("completed_at") or "-"],
        ["실행 모드", post_close_label_refresh.get("mode") or "-"],
        ["recent days", post_close_label_refresh.get("recent_days") or "-"],
        ["feature/label rebuild 생략", "예" if post_close_label_refresh.get("skipped_feature_label_build") else "아니오"],
        ["작업", ", ".join(post_close_label_refresh.get("tasks") or []) or "-"],
        ["exit code", post_close_label_refresh.get("exit_code") if post_close_label_refresh.get("exit_code") is not None else "-"],
        ["상태 파일", "runtime-data/reports/ml-maintenance/state/latest-post-close-label-refresh.json"],
    ]
    lightgbm_rows = [
        ["프레임워크", lightgbm_status.get("framework") or "-"],
        ["최신 모델 버전", lightgbm_status.get("latest_model_version") or "-"],
        ["활성 모델 여부", "예" if lightgbm_status.get("is_active") else "아니오"],
        ["학습 행 수", lightgbm_status.get("train_rows") or 0],
        ["검증 행 수", lightgbm_status.get("validation_rows") or 0],
        ["학습 validation 정확도", _ratio_pct(lightgbm_status.get("validation_accuracy"), 2)],
        ["학습 validation split", lightgbm_status.get("validation_split_name") or "-"],
        ["학습 validation 평가 행", lightgbm_status.get("evaluated_rows") or "-"],
        ["특징 수", lightgbm_status.get("feature_count") or 0],
        ["실운용 특징 행", lightgbm_status.get("actual_feature_rows") or 0],
        ["실운용 라벨 행", lightgbm_status.get("actual_label_rows") or 0],
        ["오늘 학습 건수", lightgbm_status.get("today_training_count") or 0],
        ["오늘 평가 건수", lightgbm_status.get("today_evaluation_count") or 0],
        ["학습 창", lightgbm_status.get("training_window") or "-"],
        ["아티팩트 갱신 시각", lightgbm_status.get("artifact_updated_at") or "-"],
        ["아티팩트 정합성", lightgbm_status.get("artifact_lineage_label") or "-"],
        ["아티팩트 학습 run", lightgbm_status.get("artifact_training_run_id") or "-"],
        ["DB 최신 학습 run", lightgbm_status.get("expected_training_run_id") or "-"],
        [
            "최근 장후 재학습",
            (lightgbm_status.get("latest_post_close_maintenance") or {}).get("completed_at")
            or (lightgbm_status.get("latest_post_close_maintenance") or {}).get("started_at")
            or "-",
        ],
    ]
    walk_forward_gate_rows = [
        ["설정 상태", latest_walk_forward_setup.get("setup_status_label") or latest_walk_forward_setup.get("status_label") or "-"],
        ["게이트 성능 판단", latest_walk_forward_setup.get("gate_status_label") or "-"],
        ["게이트 판단 사유", latest_walk_forward_setup.get("gate_reason") or "-"],
        ["평가 시각", latest_walk_forward_setup.get("evaluated_at") or "-"],
        ["모델 버전", latest_walk_forward_setup.get("model_version") or "-"],
        ["reference 파일", latest_walk_forward_setup.get("reference_path") or "-"],
        ["fold 수", latest_walk_forward_setup.get("folds") or "-"],
        ["학습 행", latest_walk_forward_setup.get("min_train_rows") or "-"],
        ["검증 행", latest_walk_forward_setup.get("test_window_rows") or "-"],
        ["step 행", latest_walk_forward_setup.get("step_rows") or "-"],
        ["gap 행", latest_walk_forward_setup.get("gap_rows") or "-"],
        ["최대 학습 행", latest_walk_forward_setup.get("max_train_rows") or "-"],
        ["정확도", _ratio_pct(latest_walk_forward_setup.get("overall_accuracy"), 2)],
        ["거래 적중률", _ratio_pct(latest_walk_forward_setup.get("trade_hit_rate"), 2)],
        ["거래합산 순수익률", _pct(latest_walk_forward_setup.get("trade_sum_net_return_pct", latest_walk_forward_setup.get("cumulative_net_return_pct")), 2)],
        ["비용 차감 합계", _pct(latest_walk_forward_setup.get("estimated_cost_drag_pct"), 2)],
        ["수익률 집계 방식", latest_walk_forward_setup.get("return_aggregation") or "-"],
        ["설정 판단 메모", latest_walk_forward_setup.get("note") or "-"],
    ]
    latest_kis_quality_recent = {}
    if isinstance(latest_kis_quality.get("recent_days"), list) and latest_kis_quality.get("recent_days"):
        latest_kis_quality_recent = latest_kis_quality["recent_days"][-1] or {}
    latest_kis_quality_assessment = latest_kis_quality.get("assessment") or {}
    latest_kis_quality_label_dist = latest_kis_quality_recent.get("label_distribution_h15") or {}
    latest_kis_quality_coverage = latest_kis_quality.get("latest_intraday_coverage") or {}
    kis_quality_rows = [
        ["상태", latest_kis_quality_assessment.get("status") or "-"],
        ["생성 시각", latest_kis_quality.get("completed_at") or "-"],
        [
            "관측 기간",
            f"{latest_kis_quality.get('first_trade_date') or '-'}..{latest_kis_quality.get('latest_trade_date') or '-'}",
        ],
        ["최근 거래일", latest_kis_quality_recent.get("trade_date") or latest_kis_quality.get("latest_trade_date") or "-"],
        ["시장 체결 symbol-minute", (latest_kis_quality_recent.get("raw_market") or {}).get("symbol_minutes") or 0],
        ["호가 symbol-minute", (latest_kis_quality_recent.get("raw_orderbook") or {}).get("symbol_minutes") or 0],
        ["분봉 symbol-minute", (latest_kis_quality_recent.get("minute_bars") or {}).get("symbol_minutes") or 0],
        ["특징 symbol-minute", (latest_kis_quality_recent.get("features") or {}).get("symbol_minutes") or 0],
        ["15분 라벨 symbol-minute", (latest_kis_quality_recent.get("labels_h15") or {}).get("symbol_minutes") or 0],
        ["60분 라벨 symbol-minute", (latest_kis_quality_recent.get("labels_h60") or {}).get("symbol_minutes") or 0],
        ["특징/분봉 비율", latest_kis_quality_recent.get("feature_to_bar_symbol_minute_ratio") or "-"],
        ["15분 라벨/특징 비율", latest_kis_quality_recent.get("label_h15_to_feature_symbol_minute_ratio") or "-"],
        ["최근 raw minute", latest_kis_quality_coverage.get("latest_raw_minute") or "-"],
        ["최근 raw minute 지연", _duration_seconds_text(latest_kis_quality_coverage.get("latest_raw_minute_lag_seconds"))],
        ["장중 기대 symbol-minute", latest_kis_quality_coverage.get("expected_symbol_minutes") or "-"],
        ["닫힌 분 기대 symbol-minute", latest_kis_quality_coverage.get("closed_expected_symbol_minutes") or "-"],
        ["시장 체결 coverage", _ratio_pct(latest_kis_quality_coverage.get("raw_market_coverage_ratio"), 1)],
        ["호가 coverage", _ratio_pct(latest_kis_quality_coverage.get("raw_orderbook_coverage_ratio"), 1)],
        ["분봉 coverage(닫힌 분)", _ratio_pct(latest_kis_quality_coverage.get("minute_bar_closed_coverage_ratio"), 1)],
        ["특징 coverage(닫힌 분)", _ratio_pct(latest_kis_quality_coverage.get("feature_closed_coverage_ratio"), 1)],
        [
            "15분 라벨 분포",
            (
                f"down {latest_kis_quality_label_dist.get('down', 0)} / "
                f"flat {latest_kis_quality_label_dist.get('flat', 0)} / "
                f"up {latest_kis_quality_label_dist.get('up', 0)}"
            ),
        ],
        ["리포트", "runtime-data/reports/data-quality/latest-kis-live-data-quality.json"],
    ]
    runtime_rows = [
        ["원시 체결", runtime.get("raw_market_ticks", 0)],
        ["원시 호가", runtime.get("raw_orderbook_ticks", 0)],
        ["분봉", runtime.get("minute_bars", 0)],
        ["특징", runtime.get("feature_rows", 0)],
        ["라벨", runtime.get("labels", 0)],
        ["브로커 제출 주문", runtime.get("broker_order_submissions", 0)],
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
    def _tone_from_status(status: Any) -> str:
        normalized = str(status or "").strip().lower()
        if normalized in {"ok", "passed", "complete", "completed", "success", "matched", "aligned", "already_ok"}:
            return "is-ok"
        if normalized in {"blocked", "failed", "error", "mismatch", "stale", "unknown"}:
            return "is-danger"
        if normalized in {"", "-"}:
            return "is-muted"
        return "is-warn"

    def _tone_from_bool(value: Any) -> str:
        if value is True:
            return "is-ok"
        if value is False:
            return "is-danger"
        return "is-muted"

    readiness_phase = latest_live_readiness.get("phase") or live_readiness_run.get("phase") or "-"
    readiness_status = latest_live_readiness.get("status") or live_readiness_run.get("status") or "-"
    readiness_passed = live_readiness_run.get("passed")
    readiness_checked_at = latest_live_readiness.get("generated_at") or live_readiness_run.get("checked_at") or "-"
    readiness_extra_detail = (live_readiness_run.get("checks_json") or {}).get("extra_detail") or {}
    readiness_non_blocking = latest_live_readiness.get("non_blocking_reasons") or readiness_extra_detail.get("non_blocking_reasons") or []
    readiness_required_keys = (live_readiness_run.get("checks_json") or {}).get("required_check_keys") or []
    readiness_optional_keys = (live_readiness_run.get("checks_json") or {}).get("optional_check_keys") or []
    readiness_blocker_text = ", ".join(str(item) for item in live_readiness_blockers) if live_readiness_blockers else "없음"
    readiness_optional_text = ", ".join(str(item) for item in readiness_non_blocking) if readiness_non_blocking else "없음"
    readiness_key_text = (
        f"필수 {len(readiness_required_keys)}개 / 선택 {len(readiness_optional_keys)}개"
        if live_readiness_run
        else "readiness 기록 없음"
    )
    paper_reconciliation_ok = (
        bool(paper_account_reconciliation)
        and paper_account_reconciliation.get("positions_match") is True
        and paper_account_reconciliation.get("balance_match") is True
        and paper_account_reconciliation.get("total_asset_match") is True
    )
    paper_reconciliation_status = paper_account_reconciliation.get("status") or "-"
    paper_reconciliation_note = paper_account_reconciliation.get("note") or "최근 정합성 점검 기록을 확인하세요."
    post_close_status = post_close_maintenance.get("status") or "-"
    post_close_label_status = post_close_label_refresh.get("status") or "-"
    data_quality_status = latest_kis_quality_assessment.get("status") or "-"
    live_order_safety_ok = project.get("allow_live_orders") is False
    live_order_safety_value = "차단" if live_order_safety_ok else "확인 필요"
    live_runtime_label = "실행 중" if live_runtime.get("status") == "running" else "중지"
    watchdog_status = local_setup_watchdog.get("status") or "-"
    session_label = local_setup_watchdog.get("market_session_status") or local_setup_live_runtime.get("session_status") or latest_kis.get("session_status") or "-"
    runtime_expected = bool(local_setup_watchdog.get("live_runtime_should_run"))
    runtime_running = live_runtime.get("status") == "running"
    runtime_position_ok = runtime_running if runtime_expected else not runtime_running
    watchdog_errors = local_setup_watchdog.get("errors") or []
    operator_session_tone = "is-ok" if runtime_position_ok and not watchdog_errors else "is-warn"
    latest_lightgbm_candidate = next(
        (
            row
            for row in latest_challenger.get("candidates", [])
            if str(row.get("candidate_name") or "") == "latest_lightgbm"
        ),
        {},
    )
    challenger_action_label = {
        "keep_active": "유지",
        "promote": "승격 권장",
        "review_required": "검토 필요",
    }.get(str(latest_challenger.get("recommended_action") or ""), latest_challenger.get("recommended_action") or "-")
    latest_trade_date = latest_kis_quality_recent.get("trade_date") or latest_kis_quality.get("latest_trade_date") or "-"
    closed_feature_coverage = _ratio_pct(latest_kis_quality_coverage.get("feature_closed_coverage_ratio"), 1)
    raw_market_coverage = _ratio_pct(latest_kis_quality_coverage.get("raw_market_coverage_ratio"), 1)
    broker_total_asset = paper_account.get("total_asset_amount")
    broker_cash = paper_account.get("cash_balance")
    broker_profit_loss = paper_account.get("total_profit_loss_amount")
    operator_metrics = [
        (
            "런타임",
            live_runtime_label,
            f"장 {session_label} · watchdog {watchdog_status}",
            operator_session_tone,
        ),
        (
            "모의계좌 총자산",
            _money(broker_total_asset),
            f"예수금 {_money(broker_cash)} · 손익 {_money(broker_profit_loss)}",
            _tone_from_status(paper_account.get("status") or paper_account.get("status_text")),
        ),
        (
            "paper/KIS 정합성",
            "일치" if paper_reconciliation_ok else "확인",
            f"현금 차이 {_money(paper_account_reconciliation.get('cash_gap'))} · 총자산 차이 {_money(paper_account_reconciliation.get('total_asset_gap'))}",
            "is-ok" if paper_reconciliation_ok else "is-warn",
        ),
        (
            "데이터 품질",
            data_quality_status,
            f"{latest_trade_date} · raw {raw_market_coverage} · feature {closed_feature_coverage}",
            _tone_from_status(data_quality_status),
        ),
        (
            "활성 모델",
            active_model.get("model_version") or "-",
            f"LightGBM validation {_ratio_pct(lightgbm_status.get('validation_accuracy'), 2)}",
            "is-muted",
        ),
        (
            "챌린저 판단",
            challenger_action_label,
            f"거래 적중률 {_ratio_pct(latest_lightgbm_candidate.get('trade_hit_rate'), 2)} · 순수익률 {_pct(latest_lightgbm_candidate.get('cumulative_net_return_pct'), 2)}",
            "is-ok" if latest_challenger.get("recommended_action") == "promote" else "is-warn" if latest_challenger.get("recommended_action") == "review_required" else "is-muted",
        ),
        (
            "예측/주문",
            f"{runtime.get('predictions', 0)} / {runtime.get('signals', 0)}",
            f"주문 {runtime.get('orders', 0)} · 체결 {runtime.get('fills', 0)}",
            "is-muted",
        ),
        (
            "실전 주문",
            live_order_safety_value,
            f"mode={project.get('trading_mode') or '-'} · ALLOW_LIVE_ORDERS={'false' if live_order_safety_ok else 'true'}",
            "is-ok" if live_order_safety_ok else "is-danger",
        ),
    ]
    metrics_html = "".join(
        (
            f'<div class="metric-card {tone}">'
            f'<div class="metric-label">{_esc(label)}</div>'
            f'<div class="metric-value">{_esc(value)}</div>'
            f'<div class="metric-note">{_esc(note)}</div>'
            "</div>"
        )
        for label, value, note, tone in operator_metrics
    )
    tab_buttons = "".join(
        [
            _tab_button("tab-ops", "오늘", active=True),
            _tab_button("tab-accounts", "계좌"),
            _tab_button("tab-ml-data", "데이터/모델"),
            _tab_button("tab-orders", "예측/주문"),
            _tab_button("tab-reports-settings", "운영"),
        ]
    )
    paper_compare_rows = [
        ["브로커 상태", paper_account.get("status_text") or "-"],
        ["브로커 예수금", _money(paper_account.get("cash_balance"))],
        ["보유 종목 수", len(paper_account.get("positions") or [])],
        ["브로커 주문 자동 연동", "예" if project.get("enable_broker_paper_mirroring") else "아니오"],
        ["브로커 제출 주문 수", runtime.get("broker_order_submissions", 0)],
        ["로컬 가상계좌와 차이", "브로커 실제 모의투자 계좌 값은 프로그램 내부 가상 장부와 다를 수 있습니다."],
    ]
    live_compare_rows = [
        ["연결 상태", live_account.get("status_text") or "-"],
        ["실전 주문 허용", "예" if project.get("allow_live_orders") else "아니오"],
        ["보유 종목 수", len(live_account.get("positions") or [])],
        ["안내", "실 운용계좌는 현재 조회 중심이며, 주문 기능은 기본 비활성화 상태입니다."],
    ]
    live_fill_consistency = payload.get("live_fill_consistency", {}) or {}
    live_fill_consistency_rows = [
        ["거래일", live_fill_consistency.get("trading_day") or "-"],
        ["상태", live_fill_consistency.get("status") or "-"],
        ["확인 주문 수", live_fill_consistency.get("checked_order_count", 0)],
        ["불일치 수", live_fill_consistency.get("mismatch_count", 0)],
        ["오류", live_fill_consistency.get("error") or "없음"],
    ]
    live_fill_mismatch_rows = [
        [
            row.get("order_id") or "-",
            row.get("order_filled_qty", 0),
            row.get("live_fill_qty_sum", 0),
        ]
        for row in (live_fill_consistency.get("mismatches") or [])[:20]
    ]
    live_order_attention = payload.get("live_order_attention", {}) or {}
    live_order_attention_rows = [
        ["거래일", live_order_attention.get("trading_day") or "-"],
        ["상태", live_order_attention.get("status") or "-"],
        ["확인 주문 수", live_order_attention.get("checked_order_count", 0)],
        ["미해결 주문 수", live_order_attention.get("attention_count", 0)],
        ["열린 주문 수", live_order_attention.get("open_order_count", 0)],
        ["최장 경과(분)", live_order_attention.get("max_attention_age_minutes") or "-"],
        ["오류", live_order_attention.get("error") or "없음"],
    ]
    live_order_attention_detail_rows = [
        [
            row.get("order_id") or "-",
            row.get("status") or "-",
            row.get("symbol") or "-",
            row.get("side") or "-",
            row.get("remaining_qty", 0),
            row.get("age_minutes") if row.get("age_minutes") is not None else "-",
        ]
        for row in (live_order_attention.get("attention_orders") or [])[:20]
    ]
    live_phase2_parent_order_limit = payload.get("live_phase2_parent_order_limit", {}) or {}
    live_phase2_parent_order_limit_rows = [
        ["거래일", live_phase2_parent_order_limit.get("trading_day") or "-"],
        ["상태", live_phase2_parent_order_limit.get("status") or "-"],
        ["부모 주문 수", f"{live_phase2_parent_order_limit.get('parent_order_count', 0)} / {live_phase2_parent_order_limit.get('max_parent_orders_per_day', 1)}"],
        ["남은 부모 주문 수", live_phase2_parent_order_limit.get("remaining_parent_orders", 0)],
        ["차단 여부", "예" if live_phase2_parent_order_limit.get("blocked_by_limit") else "아니오"],
        ["차단된 부모 intent 수", live_phase2_parent_order_limit.get("blocked_parent_order_count", 0)],
        ["오류", live_phase2_parent_order_limit.get("error") or "없음"],
    ]
    live_phase2_parent_order_detail_rows = [
        [
            row.get("order_id") or "-",
            row.get("status") or "-",
            row.get("phase") or "-",
            row.get("symbol") or "-",
            row.get("side") or "-",
            row.get("qty", 0),
            row.get("created_at") or "-",
        ]
        for row in (live_phase2_parent_order_limit.get("parent_orders") or [])[:20]
    ]
    signal_fill_rows = [
        [row.get("event_time"), row.get("order_id"), _money(row.get("fill_price")), row.get("fill_qty"), _money(row.get("commission"))]
        for row in payload.get("recent_fills", [])
    ]
    broker_submission_rows = [
        [
            row.get("event_time"),
            row.get("local_order_id"),
            row.get("symbol"),
            _translate_signal_side(str(row.get("side", ""))),
            row.get("qty"),
            _money(row.get("limit_price")),
            row.get("status"),
            row.get("broker_order_no"),
        ]
        for row in payload.get("recent_broker_order_submissions", [])
    ]
    virtual_tab_html = _render_subtab_shell(
        "모의투자(가상)",
        "virtual-paper",
        [
            (
                "virtual-overview",
                "상태 설명",
                _stack_cards(
                    _section_card(
                        "운용 상태 요약",
                        _pill_row(virtual_account_pills)
                        + '<div class="pillrow" style="margin-top:12px;">'
                        + f'<span class="pill">열린 포지션: {virtual_account.get("open_positions", 0)}건</span>'
                        + f'<span class="pill">최근 종료 포지션: {virtual_account.get("closed_positions_count", 0)}건</span>'
                        + f'<span class="pill">총 주문: {virtual_account.get("orders_total", 0)}건</span>'
                        + f'<span class="pill">체결률: {_ratio_pct(virtual_account.get("fill_rate"), 1)}</span>'
                        + "</div>",
                        note=(
                            f"{_esc(virtual_account.get('status_note'))}<br>"
                            f"운용 방식: {_esc(virtual_account.get('strategy_summary'))}<br>"
                            f"최근 스냅샷 시각: {_esc(virtual_account.get('latest_snapshot_time'))}"
                        ),
                    ),
                    _section_card(
                        "설명",
                        '<div class="muted">이 계좌는 프로그램 내부의 가상 장부입니다. 실제 장중 데이터로 신호를 만들고, 우리 규칙에 따라 모의주문과 모의체결을 기록합니다. 브로커 모의계좌와 값이 다를 수 있어도 이상이 아닙니다.</div>',
                    ),
                ),
            ),
            (
                "virtual-holdings",
                "보유 종목",
                _stack_cards(
                    _section_card(
                        "현재 보유 종목",
                        _table(
                            ["종목", "수량", "평균 단가", "현재가", "평가 금액", "미실현 손익"],
                            virtual_position_rows,
                            "현재 열린 가상 포지션은 없습니다. 아래 최근 종료 포지션을 함께 확인해 주세요.",
                        ),
                    ),
                    _section_card(
                        "최근 종료 포지션",
                        _table(
                            ["종료 시각", "종목", "마지막 가격", "실현 손익"],
                            virtual_closed_position_rows,
                            "기록된 최근 종료 포지션이 없습니다.",
                        ),
                    ),
                ),
            ),
            (
                "virtual-activity",
                "매수/매도 및 체결현황",
                _pill_row(
                    [
                        f"총 주문: {virtual_account.get('orders_total', 0)}건",
                        f"매수 주문: {virtual_account.get('buy_orders', 0)}건",
                        f"매도 주문: {virtual_account.get('sell_orders', 0)}건",
                        f"체결: {virtual_account.get('fills', 0)}건",
                        f"체결 수량: {virtual_account.get('fill_qty', 0)}주",
                        f"포지션 비중: {_ratio_pct(virtual_account.get('capital_in_market_ratio'), 1)}",
                    ]
                )
                + '<div class="expand-tabs" role="tablist" aria-label="모의투자 가상 거래 세부 탭">'
                + _subtab_button("virtual-activity", "virtual-activity-buy", f"매수 주문 {len(virtual_buy_order_rows)}건", active=True)
                + _subtab_button("virtual-activity", "virtual-activity-sell", f"매도 주문 {len(virtual_sell_order_rows)}건")
                + _subtab_button("virtual-activity", "virtual-activity-fills", f"체결 {len(virtual_fill_activity_rows)}건")
                + _subtab_button("virtual-activity", "virtual-activity-signals", f"최근 신호 {len(virtual_signal_activity_rows)}건")
                + "</div>"
                + f'<div id="virtual-activity-buy" class="expand-panel is-active" data-subtab-panel="virtual-activity">{_table(["시각", "종목", "수량", "지정가", "상태"], virtual_buy_order_rows, "최근 매수 주문이 없습니다.")}</div>'
                + f'<div id="virtual-activity-sell" class="expand-panel" data-subtab-panel="virtual-activity">{_table(["시각", "종목", "수량", "지정가", "상태"], virtual_sell_order_rows, "최근 매도 주문이 없습니다.")}</div>'
                + f'<div id="virtual-activity-fills" class="expand-panel" data-subtab-panel="virtual-activity">{_table(["시각", "주문 ID", "체결가", "수량", "수수료"], virtual_fill_activity_rows, "최근 체결이 없습니다.")}</div>'
                + f'<div id="virtual-activity-signals" class="expand-panel" data-subtab-panel="virtual-activity">{_table(["시각", "종목", "방향", "허용 여부", "설명"], virtual_signal_activity_rows, "최근 신호가 없습니다.")}</div>'
                + '<div class="muted" style="margin-top:12px;">매도 주문과 매도 신호는 실제 숏 전략이 아니라, 보유 종목 청산 또는 하락 우세 판단에서 나온 내부 기록일 수 있습니다.</div>',
            ),
        ],
    )
    paper_tab_html = _render_subtab_shell(
        "모의계좌(실제)",
        "paper-broker",
        [
            (
                "paper-broker-overview",
                "상태 설명",
                _stack_cards(
                    _section_card(
                        "계좌 요약",
                        _pill_row(paper_account_pills),
                        note=(
                            f"최근 조회 시각: {_esc(paper_account.get('fetched_at'))}<br>"
                            f"조회 메모: {_esc(paper_account.get('account_note'))}<br>"
                            f"오류: {_esc(paper_account.get('error') or '없음')}"
                        ),
                    ),
                    _section_card(
                        "설명",
                        '<div class="muted">한국투자 모의투자 계좌에서 직접 조회한 실제 잔고입니다. 로컬 모의운용 계좌와 값이 다를 수 있습니다.</div>',
                    ),
                ),
            ),
            (
                "paper-broker-holdings",
                "보유 종목",
                _section_card(
                    "보유 종목",
                    _table(
                        ["종목", "종목명", "보유수량", "현재가", "평가금액", "평가손익"],
                        paper_position_rows,
                        "브로커 모의계좌 보유 종목이 없습니다.",
                    ),
                ),
            ),
            (
                "paper-broker-activity",
                "매수/매도 및 체결현황",
                _stack_cards(
                    _section_card("현재 제공 범위", _table(["항목", "값"], paper_compare_rows, "표시할 비교 정보가 없습니다.", scroll_height=280)),
                    _section_card("로컬 가상계좌 비교", _table(["항목", "값"], sync_rows, "비교할 정보가 없습니다.", scroll_height=280), note=_esc(account_sync.get("note"))),
                    _section_card(
                        "최근 동기화 점검",
                        _table(["항목", "값"], reconciliation_rows, "동기화 점검 정보가 없습니다.", scroll_height=280),
                        note=_esc(paper_account_reconciliation.get("note")),
                    ),
                    _section_card(
                        "차이 상세",
                        _table(
                            ["종목", "종목명", "상태", "로컬 수량", "브로커 수량", "수량 차이", "로컬 평가금액", "브로커 평가금액"],
                            reconciliation_mismatch_rows,
                            "현재 확인된 수량 차이는 없습니다.",
                        ),
                    ),
                    _section_card(
                        "최근 브로커 제출 주문",
                        _table(
                            ["시각", "로컬 주문 ID", "종목", "방향", "수량", "지정가", "상태", "브로커 주문번호"],
                            broker_submission_rows,
                            "최근 브로커 모의계좌 제출 주문이 없습니다.",
                        ),
                        note="로컬 가상 주문이 브로커 모의계좌에도 함께 제출된 기록입니다.",
                    ),
                    _section_card(
                        "안내",
                        '<div class="muted">현재는 브로커 제출 주문까지 연결되어 있습니다. 다만 브로커 체결 여부와 부분 체결 상세는 별도 조회로 확장할 여지가 있습니다.</div>',
                    ),
                ),
            ),
        ],
    )
    live_tab_html = _render_subtab_shell(
        "실 운용계좌",
        "live-broker",
        [
            (
                "live-broker-overview",
                "상태 설명",
                _stack_cards(
                    _section_card(
                        "계좌 요약",
                        _pill_row(live_account_pills),
                        note=(
                            f"최근 조회 시각: {_esc(live_account.get('fetched_at'))}<br>"
                            f"조회 메모: {_esc(live_account.get('account_note'))}<br>"
                            f"오류: {_esc(live_account.get('error') or '없음')}"
                        ),
                    ),
                    _section_card(
                        "설명",
                        '<div class="muted">실전 계좌가 연결되면 보유 종목과 잔고를 같은 틀로 비교할 수 있습니다. 현재는 실전 주문 기능을 켜지 않았습니다.</div>',
                    ),
                ),
            ),
            (
                "live-broker-holdings",
                "보유 종목",
                _section_card(
                    "보유 종목",
                    _table(
                        ["종목", "종목명", "보유수량", "현재가", "평가금액", "평가손익"],
                        live_position_rows,
                        "실 운용계좌 정보가 없거나 아직 조회되지 않았습니다.",
                    ),
                ),
            ),
            (
                "live-broker-activity",
                "매수/매도 및 체결현황",
                _stack_cards(
                    _section_card("현재 제공 범위", _table(["항목", "값"], live_compare_rows, "표시할 비교 정보가 없습니다.", scroll_height=280)),
                    _section_card(
                        "실전 fill 정합성",
                        _table(["항목", "값"], live_fill_consistency_rows, "실전 fill 정합성 정보가 없습니다.", scroll_height=220),
                        note="read-only SQLite 점검입니다. 실전 포지션, 회계, 세금, 정산 반영은 아직 연결하지 않았습니다.",
                    ),
                    _section_card(
                        "실전 fill 불일치 상세",
                        _table(
                            ["주문 ID", "주문 체결수량", "fill 합계"],
                            live_fill_mismatch_rows,
                            "현재 확인된 실전 fill 불일치는 없습니다.",
                            scroll_height=220,
                        ),
                    ),
                    _section_card(
                        "실전 미해결 주문",
                        _table(["항목", "값"], live_order_attention_rows, "실전 미해결 주문 정보가 없습니다.", scroll_height=220),
                        note="unknown/stuck 상태는 자동 복구가 아니라 브로커 재조회와 사람 확인이 필요한 상태로 취급합니다.",
                    ),
                    _section_card(
                        "실전 미해결 주문 상세",
                        _table(
                            ["주문 ID", "상태", "종목", "방향", "잔량", "경과(분)"],
                            live_order_attention_detail_rows,
                            "현재 확인 필요한 실전 주문은 없습니다.",
                            scroll_height=220,
                        ),
                    ),
                    _section_card(
                        "Phase 2 부모 주문 한도",
                        _table(["항목", "값"], live_phase2_parent_order_limit_rows, "Phase 2 부모 주문 한도 정보가 없습니다.", scroll_height=220),
                        note="Phase 2 기본 정책은 1거래일 1부모 주문서입니다. filled/cancelled/rejected 상태도 당일 한도 사용으로 봅니다.",
                    ),
                    _section_card(
                        "Phase 2 부모 주문 상세",
                        _table(
                            ["주문 ID", "상태", "단계", "종목", "방향", "수량", "생성 시각"],
                            live_phase2_parent_order_detail_rows,
                            "현재 한도에 포함되는 Phase 2 부모 주문은 없습니다.",
                            scroll_height=220,
                        ),
                    ),
                    _section_card(
                        "안내",
                        '<div class="muted">실전 계좌는 현재 조회 위주로만 표시합니다. 실전 자격정보를 넣지 않았거나 조회를 일부러 막아둔 경우 빈 상태가 정상입니다.</div>',
                    ),
                ),
            ),
        ],
    )
    ml_tab_html = _render_subtab_shell(
        "머신러닝 현황",
        "ml",
        [
            (
                "ml-overview",
                "현재 운용",
                _stack_cards(
                    _section_card(
                        "실운용 학습 상태",
                        _pill_row(ml_status_pills),
                        note=(
                            f"{_esc(learning_context.get('note'))}<br>"
                            f"{_esc(learning_context.get('active_status_note'))}<br>"
                            f"{_esc(ml_state.get('training_mode') or '-')}"
                        ),
                    ),
                    _section_card(
                        "KIS live 데이터 품질",
                        _table(["항목", "값"], kis_quality_rows, "표시할 KIS live 데이터 품질 리포트가 없습니다.", scroll_height=330),
                        note="KIS 체결/호가가 feature와 15분/60분 label까지 닫혔는지 확인합니다. 장전 호가나 REST snapshot 때문에 raw coverage는 100%를 넘을 수 있고, 분봉/특징 coverage 평가는 아직 닫히지 않은 마지막 1분을 제외한 기준입니다.",
                    ),
                    _section_card(
                        "KIS-Cybos feature drift",
                        _table(["항목", "값"], feature_source_drift_rows, "표시할 feature source drift 리포트가 없습니다.", scroll_height=330),
                        note="Cybos 5년치 연구 결과를 KIS live 성능 대리값으로 볼 수 있는지 확인하는 진단 카드입니다.",
                    ),
                    _section_card(
                        "KIS live feature-label 진단",
                        _table(["항목", "값"], kis_feature_diagnostic_rows, "표시할 KIS live feature 진단 리포트가 없습니다.", scroll_height=330)
                        + _table(
                            ["피처", "행", "Pearson", "상하위 미래수익 차이", "상하위 up 비율 차이"],
                            kis_feature_rank_rows,
                            "표시할 KIS live feature 순위가 없습니다.",
                            scroll_height=260,
                        ),
                        note="KIS live 표본 안에서 단일 피처와 h15 future return/label 관계를 보는 피처 탐색 카드입니다. 모델 승격 근거로 쓰지 않습니다.",
                    ),
                    _section_card(
                        "LightGBM 실제 현황",
                        _table(["항목", "값"], lightgbm_rows, "표시할 LightGBM 현황이 없습니다.", scroll_height=330),
                        note=_esc(lightgbm_status.get("description")),
                    ),
                    _section_card(
                        "게이트 기준 워크포워드",
                        _table(["항목", "값"], walk_forward_gate_rows, "표시할 게이트 기준 walk-forward가 없습니다.", scroll_height=330),
                        note="정본 저장소의 승격 게이트가 보는 보고서입니다. D드라이브 snapshot post-close 산출물과 별도로 표시합니다.",
                    ),
                    _section_card(
                        "장후 ML 유지보수 상태",
                        _table(["항목", "값"], post_close_rows, "표시할 장후 자동 학습 상태가 없습니다.", scroll_height=330),
                        note="quick-live-train은 리포트·품질 진단 뒤 제한된 최근 labeled row로 LightGBM 학습과 challenger 평가를 수행합니다. legacy quick-live-report는 학습/평가 row를 만들지 않습니다.",
                    ),
                    _section_card(
                        "장후 label refresh 상태",
                        _table(["항목", "값"], post_close_label_rows, "표시할 장후 label refresh 상태가 없습니다.", scroll_height=260),
                        note="quick maintenance 뒤 h15/h60 라벨까지 닫아 학습 가능한 상태로 만드는 별도 live DB 경로입니다.",
                    ),
                    _section_card("모델별 상태", _table(["구분", "모델 버전", "종류", "상태", "평가 점수", "메모"], model_rows, "표시할 모델 상태가 없습니다.")),
                ),
            ),
            (
                "ml-training",
                "학습 및 평가",
                _stack_cards(
                    _section_card(
                        "선택 기간 학습 결과",
                        _table(["완료 시각", "모델 버전", "학습 행 수", "검증 행 수", "특징 세트"], today_training_rows, "현재 범위에 학습 기록이 없습니다."),
                        note=f"최신 전체 학습 시각: {_esc(latest_training.get('completed_at') or '-')} / 신선도: {_esc(training_freshness.get('label') or '-')}",
                    ),
                    _section_card(
                        "최근 전체 학습 결과",
                        _table(["완료 시각", "모델 버전", "학습 행 수", "검증 행 수", "특징 세트"], recent_training_rows, "최근 전체 학습 기록이 없습니다."),
                        note="장중에는 새 학습이 생기지 않을 수 있습니다. 이 표는 현재 범위와 무관하게 가장 최근 학습 기록을 보여줍니다.",
                    ),
                    _section_card(
                        "선택 기간 평가 결과",
                        _table(["평가 시각", "분할 이름", "정확도", "행 수"], today_evaluation_rows, "현재 범위에 평가 기록이 없습니다."),
                        note=f"최신 전체 평가 시각: {_esc(latest_evaluation.get('evaluated_at') or '-')} / 신선도: {_esc(evaluation_freshness.get('label') or '-')}",
                    ),
                    _section_card(
                        "최근 전체 평가 결과",
                        _table(["평가 시각", "분할 이름", "정확도", "행 수"], recent_evaluation_rows, "최근 전체 평가 기록이 없습니다."),
                        note="오늘 평가가 없더라도 마지막 백테스트·워크포워드·챌린저 결과는 계속 비교 대상으로 유지합니다.",
                    ),
                    _section_card(
                        "최신 검증 요약",
                        _pill_row(
                            [
                                f"학습 validation 정확도: {_ratio_pct(latest_evaluation.get('accuracy'), 2) if latest_evaluation else '-'}",
                                f"백테스트 정확도: {_ratio_pct(latest_backtest.get('overall_accuracy'), 2) if latest_backtest else '-'}",
                                f"워크포워드 정확도: {_ratio_pct(latest_walk_forward.get('overall_accuracy'), 2) if latest_walk_forward else '-'}",
                                f"워크포워드 설정: {latest_walk_forward_setup.get('setup_status_label') or latest_walk_forward_setup.get('status_label') or '-'}",
                                f"게이트 성능: {latest_walk_forward_setup.get('gate_status_label') or '-'}",
                                f"챌린저 권장: {latest_challenger.get('recommended_action') or '-'}",
                            ]
                        ),
                    ),
                    _section_card(
                        "학습 설명",
                        '<div class="muted">LightGBM는 최근 60거래일과 오늘 장중 분봉·호가 기반 수치 특징을 이용해 다음 15분과 60분의 상승·보합·하락 확률을 학습합니다. 장중에는 추론만 계속하고, 재학습은 장후 또는 수동 재구성 시점에 수행합니다. 60분 활성 모델은 레지스트리가 비어 있어도 기본 baseline fallback으로 계속 예측을 수행할 수 있습니다.</div>',
                    ),
                ),
            ),
            (
                "ml-challenger",
                "챌린저 및 워크포워드",
                _stack_cards(
                    _section_card(
                        "챌린저 비교",
                        _table(
                            ["순위", "후보", "모델 버전", "정확도", "거래 적중률", "거래 수", "누적 순수익률", "평가 자격", "승격 판단", "독립성/아티팩트"],
                            challenger_rows,
                            "챌린저 비교 결과가 없습니다.",
                        ),
                        note=_esc(
                            latest_challenger.get("current_guard_note")
                            or "평가 자격은 독립 holdout/아티팩트 기준입니다. 실제 승격 여부는 승격 판단, 권장 조치, 워크포워드 게이트를 함께 봅니다."
                        ),
                    ),
                    _section_card("워크포워드 상세", _table(["fold", "정확도", "거래 수", "거래 적중률", "누적 순수익률"], walk_forward_rows, "워크포워드 상세 결과가 없습니다.")),
                ),
            ),
        ],
    )
    status_tab_html = _render_subtab_shell(
        "상태 및 설정",
        "status",
        [
            (
                "status-program",
                "현재 프로그램 상태",
                _stack_cards(
                    _section_card("현재 프로그램 상태", _table(["항목", "값"], status_rows, "상태 정보가 없습니다.", scroll_height=330), note=f"{_esc(system_status.get('operation_note'))}<br>{_esc(live_runtime.get('status_note'))}"),
                    _section_card(
                        "장전 readiness",
                        _table(["항목", "값"], local_setup_rows, "장전 점검 결과가 없습니다.", scroll_height=280),
                        note="check_local_setup.sh 최신 결과입니다.",
                    ),
                    _section_card(
                        "실전 전환 readiness dry-run",
                        _table(["항목", "값"], live_readiness_rows, "실전 전환 readiness dry-run 결과가 없습니다.", scroll_height=330),
                        note="Codex ops premarket report와 fixture 기반 live readiness dry-run 결과입니다. fixture가 없는 항목은 통과로 보지 않습니다.",
                    ),
                ),
            ),
            (
                "status-kis-settings",
                "연결 및 설정",
                _stack_cards(
                    _section_card(
                        "KIS 연결 상태",
                        _pill_row(
                            [
                                f"연결 준비: {'예' if latest_kis.get('connection_ready') else '아니오'}",
                                f"실데이터 수신: {'예' if latest_kis.get('market_data_flow_ok') else '아니오'}",
                                f"승인 키 발급: {'예' if latest_kis.get('approval_key_issued') else '아니오'}",
                                f"수신 프레임: {latest_kis.get('frames_received', 0)}",
                                f"제어 프레임: {latest_kis.get('control_frames', 0)}",
                            ]
                        ),
                        note=f"상태 메모: {_esc(latest_kis.get('status_note') or '-')}<br>검증 신선도: {_esc(kis_freshness.get('label') or '-')} / {_esc(kis_freshness.get('note') or '-')}",
                    ),
                    _section_card("운용 및 설정", _table(["항목", "값"], setting_rows, "표시할 설정이 없습니다.", scroll_height=330)),
                ),
            ),
            (
                "status-runtime",
                "집계 현황",
                _section_card("집계 현황", _table(["항목", "값"], runtime_rows, "표시할 집계가 없습니다.", scroll_height=330)),
            ),
        ],
    )
    predictions_tab_html = _render_subtab_shell(
        "예측현황",
        "predictions",
        [
            (
                "predictions-overview",
                "요약",
                _stack_cards(
                    _section_card("예측 요약", _pill_row(prediction_status_pills + [f"최근 예측 시각: {prediction_summary.get('latest_prediction_time') or '-'}"]), note="예측 성공률은 실제 결과가 확정된 예측만 기준으로 계산합니다. 선택 기간 전체 기준으로 집계합니다."),
                    _section_card(
                        "수익률 해석 분리",
                        _table(["구분", "표본", "결과", "해석"], return_interpretation_rows, "수익률 해석 데이터가 없습니다.", scroll_height=260),
                        note="승격 판단에서는 예측 정확도, 신호 기준 가상 수익률, 실제 paper 체결 수익률을 분리해서 봅니다.",
                    ),
                    _section_card(
                        "신호 replay 기준",
                        _table(["항목", "값"], signal_replay_rows, "신호 replay 결과가 없습니다.", scroll_height=330),
                        note="이 값은 주문 원장을 바꾸지 않는 대시보드용 가상 replay입니다. 미보유 상태의 매도 신호는 신규 숏이 아니라 진입 회피로 봅니다.",
                    ),
                    _section_card(
                        "수평선 및 방향별 집계",
                        _pill_row(
                            [f"{key}분: {value}건" for key, value in (prediction_summary.get("horizon_counts") or {}).items()]
                            + [
                                f"상승 예측: {(prediction_summary.get('predicted_label_counts') or {}).get('up', 0)}건",
                                f"하락 예측: {(prediction_summary.get('predicted_label_counts') or {}).get('down', 0)}건",
                                f"보합 예측: {(prediction_summary.get('predicted_label_counts') or {}).get('flat', 0)}건",
                            ]
                        ),
                    ),
                    _section_card(
                        "오전/오후 통계",
                        _table(["구간", "예측", "확정", "성공", "성공률", "평균 실제 변동"], prediction_session_rows, "선택 기간의 시간대별 예측 통계가 없습니다.", scroll_height=260),
                    ),
                    _section_card(
                        "시간대별 통계",
                        _table(["시간대", "예측", "확정", "성공", "성공률"], prediction_hour_rows, "선택 기간의 시간대별 예측 통계가 없습니다.", scroll_height=260),
                    ),
                    _section_card(
                        "상승/하락 예측 통계",
                        _table(["예측 방향", "예측", "확정", "성공", "성공률", "평균 예상 변동", "평균 실제 변동"], prediction_direction_rows, "선택 기간의 방향별 예측 통계가 없습니다.", scroll_height=260),
                    ),
                ),
            ),
            (
                "predictions-flow",
                "예측 흐름",
                _section_card(
                    "예측 흐름",
                    _table(
                        ["번호", "시각", "종목", "모델별 예측", "실제 결과", "신호", "주문", "체결", "수익", "연결 방식"],
                        prediction_flow_rows,
                        "현재 범위에 예측 흐름 기록이 없습니다.",
                        scroll_height=520,
                        table_class="prediction-flow-table",
                    ),
                    note=(
                        "일자 선택 화면에서는 하루 전체 흐름을 장 시작 시각부터 순서대로 보여줍니다. "
                        if prediction_flow_full_day
                        else "여러 날/전체 기간 화면에서는 화면 부하를 줄이기 위해 최신 흐름만 보여줍니다. "
                    )
                    + "신규 paper 주문은 prediction_id 또는 signal_id로 우선 연결합니다. 과거 주문처럼 추적 ID가 없는 기록은 동일 종목/동일 시각 기준으로 보조 연결하되, 포지션 관리용 청산 주문은 신호 주문과 별도로 표시합니다. 체결은 주문 ID 기준으로 연결합니다.",
                ),
            ),
            (
                "predictions-detail",
                "예측 상세",
                _section_card("예측 상세", _table(["시각", "종목", "수평선", "모델", "기준가", "예측 결과 및 예상 변동", "실제 결과", "성공 여부"], prediction_rows, "현재 범위에 예측 기록이 없습니다."), note="예측 상세는 선택한 기간의 최근 예측을 최신 순으로 보여줍니다. 전체 원장은 SQLite와 날짜별 JSONL에 보관됩니다."),
            ),
            (
                "predictions-notes",
                "해석 메모",
                _section_card("예측 해석 메모", '<div class="muted">예측 결과는 기준가 대비 예상 변동 금액과 실제 결과를 함께 보여줍니다. 실제 결과는 목표 시각과 정확히 같은 분봉이 없더라도, 그 이후 가장 가까운 같은 거래일 분봉을 찾아 계산합니다. 목표 시각 이후 같은 거래일 분봉이 아직 없으면 대기 중으로 남습니다.</div>'),
            ),
        ],
    )
    signal_orders_tab_html = _render_subtab_shell(
        "신호 & 주문현황",
        "signal-orders",
        [
            (
                "signal-orders-overview",
                "요약",
                _section_card(
                    "신호 & 주문 요약",
                    _pill_row(
                        signal_status_pills
                        + [
                            f"최근 신호 시각: {signal_order_summary.get('latest_signal_time') or '-'}",
                            f"최근 주문 시각: {signal_order_summary.get('latest_order_time') or '-'}",
                            f"최근 체결 시각: {signal_order_summary.get('latest_fill_time') or '-'}",
                        ]
                    ),
                    note="매도는 실제 매도 주문이라기보다, 모델이 하락 확률을 높게 본 원시 신호일 수 있습니다. 현재 기본 정책은 매수 전용이라 이런 매도 신호는 차단되는 것이 정상입니다.",
                ),
            ),
            (
                "signal-orders-signals",
                "신호 기록",
                _section_card("신호 기록", _table(["시각", "종목코드", "종목명", "기준", "방향", "허용 여부", "설명"], signal_rows, "현재 범위에 신호 기록이 없습니다.")),
            ),
            (
                "signal-orders-orders",
                "주문 및 체결",
                _stack_cards(
                    _section_card("주문 기록", _table(["시각", "종목코드", "방향", "수량", "지정가", "상태"], order_rows, "현재 범위에 주문 기록이 없습니다.")),
                    _section_card("체결 기록", _table(["시각", "주문 ID", "체결가", "수량", "수수료"], signal_fill_rows, "현재 범위에 체결 기록이 없습니다.")),
                ),
            ),
        ],
    )
    fills_bars_tab_html = _render_subtab_shell(
        "체결과 분봉",
        "fills-bars",
        [
            ("fills-bars-fills", "최근 체결", _section_card("최근 체결", _table(["시각", "주문 ID", "체결가", "수량", "수수료"], fill_rows, "현재 범위에 실제 체결 기록이 없습니다."))),
            ("fills-bars-bars", "최근 분봉", _section_card("최근 분봉", _table(["시각", "종목", "시가", "고가", "저가", "종가", "거래량"], bar_rows, "현재 범위에 분봉 기록이 없습니다."), note=_esc(system_status.get("minute_note")))),
            ("fills-bars-notes", "해석 메모", _section_card("해석 메모", '<div class="muted">최근 분봉은 실제 KIS 장중 데이터 기준으로 집계됩니다. 주문이나 체결이 없어도 시장 데이터만 들어오면 분봉은 계속 생성될 수 있습니다.</div>')),
        ],
    )
    daily_report_tab_html = _render_subtab_shell(
        "오늘의 리포트",
        "daily-report",
        [
            (
                "daily-report-summary",
                "요약",
                _section_card(
                    "오늘의 리포트",
                    _pill_row(
                        [
                            f"리포트 기준: {today_report.get('headline') or '-'}",
                            f"실현 손익: {_money(virtual_account.get('realized_pnl'))}",
                            f"브로커 예수금: {_money(paper_account.get('cash_balance'))}",
                            f"체결: {signal_order_summary.get('fills', 0)}건",
                            f"예측 성공률: {_ratio_pct(prediction_summary.get('success_rate'), 1)}",
                        ]
                    ),
                    note=_esc(today_report.get("summary")),
                ),
            ),
            ("daily-report-insights", "분석과 고찰", _section_card("분석과 고찰", _list([_esc(item) for item in today_report.get("insights", [])], "기록된 분석이 없습니다."))),
            ("daily-report-next", "향후 접근 방향", _section_card("향후 접근 방향", _list([_esc(item) for item in today_report.get("next_steps", [])], "기록된 다음 방향이 없습니다."))),
        ],
    )
    other_tab_html = _render_subtab_shell(
        "기타",
        "other",
        [
            ("other-summary", "자동 점검 요약", _section_card("자동 점검 요약", f'<div class="muted">{_esc(audit_progress.get("last_run_summary") or "자동 점검 요약이 아직 없습니다.")}</div>')),
            (
                "other-backlog",
                "우선순위 backlog",
                _stack_cards(
                    _section_card("우선순위 backlog", _list(backlog_items, "표시할 backlog 항목이 없습니다.")),
                    _section_card("다음 작업", _list(next_actions, "기록된 다음 작업이 없습니다.")),
                ),
            ),
            ("other-guide", "안내", _section_card("안내", '<div class="muted">이 화면은 실제 KIS 기반 운용 데이터만 보여줍니다. 샘플, synthetic, demo, replay 데이터는 제외됩니다. 조회 범위를 바꾸면 특정 날짜나 최근 기간 기준으로 데이터를 다시 볼 수 있습니다.</div>')),
        ],
    )
    ops_task_rows = [
        [
            "높음" if not paper_reconciliation_ok else "낮음",
            "계좌",
            "paper/KIS 정합성",
            "완료" if paper_reconciliation_ok else "확인 필요",
            f"현금 차이 {_money(paper_account_reconciliation.get('cash_gap'))}, 총자산 차이 {_money(paper_account_reconciliation.get('total_asset_gap'))}",
        ],
        [
            "중간" if data_quality_status == "watch" else "낮음",
            "데이터",
            "KIS live 품질",
            data_quality_status,
            f"{latest_trade_date} raw {raw_market_coverage}, feature {closed_feature_coverage}",
        ],
        [
            "중간" if post_close_label_status not in {"ok", "completed"} else "낮음",
            "학습",
            "장후 label refresh",
            post_close_label_status,
            post_close_label_refresh.get("completed_at") or "최신 완료 시각 확인",
        ],
        [
            "높음" if not live_order_safety_ok else "낮음",
            "실전 안전",
            "실전 주문 차단",
            live_order_safety_value,
            f"trading_mode={project.get('trading_mode') or '-'}, ALLOW_LIVE_ORDERS={'false' if live_order_safety_ok else 'true'}",
        ],
        [
            "중간" if latest_challenger.get("recommended_action") == "review_required" else "낮음",
            "모델",
            "챌린저 승격 판단",
            challenger_action_label,
            f"워크포워드 {_ratio_pct(latest_walk_forward.get('overall_accuracy'), 2)}, 순수익률 {_pct(latest_walk_forward.get('cumulative_net_return_pct'), 2)}",
        ],
    ]
    ops_health_rows = [
        ["시장/세션", session_label, "수집기 필요" if runtime_expected else "장외 대기", payload.get("generated_at") or "-"],
        ["실시간 수집기", live_runtime_label, live_runtime.get("status_note") or "-", system_status.get("latest_market_bar_time") or "-"],
        ["감시기", watchdog_status, ", ".join(str(item) for item in watchdog_errors) if watchdog_errors else "오류 없음", local_setup_watchdog.get("last_checked_at") or "-"],
        ["대시보드", "응답 중", dashboard_freshness.get("label") or "미확인", payload.get("generated_at") or "-"],
        ["KIS 검증", kis_freshness.get("label") or "미확인", latest_kis.get("status_note") or "-", latest_kis.get("verified_at") or "-"],
        ["장후 ML", post_close_status, post_close_maintenance.get("mode") or "-", post_close_maintenance.get("completed_at") or "-"],
    ]
    ops_account_rows = [
        ["브로커 모의계좌", "예수금", _money(paper_account.get("cash_balance")), paper_account.get("status_text") or "-"],
        ["브로커 모의계좌", "총자산", _money(paper_account.get("total_asset_amount")), "KIS 조회 기준"],
        ["브로커 모의계좌", "총손익", _money(paper_account.get("total_profit_loss_amount")), "KIS 조회 기준"],
        ["로컬 가상계좌", "현재 현금", _money(virtual_account.get("cash_balance")), virtual_account.get("status") or "-"],
        ["로컬 가상계좌", "평가 금액", _money(virtual_account.get("net_liquidation_value")), "프로그램 내부 장부"],
        ["정합성", "현금/총자산 차이", f"{_money(paper_account_reconciliation.get('cash_gap'))} / {_money(paper_account_reconciliation.get('total_asset_gap'))}", paper_reconciliation_status],
    ]
    ops_model_rows = [
        ["활성 모델(15분)", active_model.get("model_version") or "-", active_model.get("model_kind") or "-", "장중 신호 기준"],
        ["최신 LightGBM", lightgbm_status.get("latest_model_version") or "-", _ratio_pct(lightgbm_status.get("validation_accuracy"), 2), f"학습 {lightgbm_status.get('train_rows') or 0}행"],
        ["워크포워드", latest_walk_forward.get("model_version") or "-", _ratio_pct(latest_walk_forward.get("overall_accuracy"), 2), f"순수익률 {_pct(latest_walk_forward.get('cumulative_net_return_pct'), 2)}"],
        ["신호 replay", _signed_money(signal_replay_summary.get("estimated_net_pnl")), _format_signed_pct(signal_replay_summary.get("net_return_sum_pct")), f"청산 {signal_replay_summary.get('trades_closed', 0)}건"],
        ["실제 paper 체결", _signed_money(paper_fill_return_summary.get("net_pnl")), _format_signed_pct(paper_fill_return_summary.get("return_on_basis_pct")), f"청산 {paper_fill_return_summary.get('closed_trades', 0)}건"],
        ["챌린저 권장", challenger_action_label, latest_challenger.get("recommended_model_version") or "-", f"승격 적용 {'예' if latest_challenger.get('promotion_applied') else '아니오'}"],
    ]
    operator_console_html = f"""
      <section class="ops-layout">
        <div class="ops-primary">
          <div class="panel">
            <div class="panel-head">
              <h2>오늘 해야 할 일</h2>
              <span class="panel-meta">{_esc(period_filter.get('label') or '-')}</span>
            </div>
            {_table(["우선순위", "영역", "항목", "상태", "근거/권장"], ops_task_rows, "오늘 확인할 항목이 없습니다.", scroll_height=310)}
          </div>
          <div class="panel">
            <div class="panel-head">
              <h2>계좌 정합성 요약</h2>
              <span class="panel-meta">{_esc(paper_reconciliation_status)}</span>
            </div>
            {_table(["계정", "항목", "금액/값", "메모"], ops_account_rows, "표시할 계좌 요약이 없습니다.", scroll_height=300)}
            <div class="helper-text">{_esc(paper_reconciliation_note)}</div>
          </div>
        </div>
        <div class="ops-side">
          <div class="panel">
            <div class="panel-head">
              <h2>상태 요약</h2>
              <span class="panel-meta">{_esc(session_label)}</span>
            </div>
            {_table(["영역", "상태", "메모", "시각"], ops_health_rows, "상태 요약이 없습니다.", scroll_height=360)}
          </div>
          <div class="panel">
            <div class="panel-head">
              <h2>모델 판단</h2>
              <span class="panel-meta">{_esc(challenger_action_label)}</span>
            </div>
            {_table(["구분", "판단/손익", "지표", "메모"], ops_model_rows, "표시할 모델 요약이 없습니다.", scroll_height=260)}
          </div>
        </div>
      </section>
      <section class="panel wide-panel">
        <div class="panel-head">
          <h2>챌린저 비교</h2>
          <span class="panel-meta">수익률 단위 % · 금액 단위 원</span>
        </div>
        {_table(["순위", "후보", "모델 버전", "정확도", "거래 적중률", "거래 수", "누적 순수익률", "평가 자격", "승격 판단", "독립성/아티팩트"], challenger_rows, "챌린저 비교 결과가 없습니다.", scroll_height=280)}
        <div class="helper-text">{_esc(latest_challenger.get("current_guard_note") or "평가 자격은 독립 holdout/아티팩트 기준입니다. 실제 승격은 권장 조치, 워크포워드 게이트, 수익률을 함께 봅니다.")}</div>
      </section>
    """
    accounts_tab_html = _stack_cards(virtual_tab_html, paper_tab_html, live_tab_html)
    ml_data_tab_html = ml_tab_html
    orders_tab_html = _stack_cards(predictions_tab_html, signal_orders_tab_html, fills_bars_tab_html)
    reports_settings_tab_html = _stack_cards(daily_report_tab_html, status_tab_html, other_tab_html)

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {refresh_meta}
  <title>실시간 주가 예측 대시보드</title>
  <style>
    :root {{ color-scheme:light; --bg:#f4f6f8; --nav:#111827; --nav-soft:#1f2937; --surface:#ffffff; --surface-soft:#f8fafc; --line:#d9e1ea; --line-soft:#edf1f5; --text:#172033; --muted:#64748b; --muted-2:#8a97a8; --accent:#2563eb; --ok:#169443; --warn:#d97706; --danger:#dc2626; --shadow:0 8px 22px rgba(17,24,39,.06); }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font-family:"Segoe UI","Malgun Gothic",Arial,sans-serif; letter-spacing:0; }}
    .app-shell {{ min-height:100vh; display:grid; grid-template-columns:132px minmax(0,1fr); }}
    .side-nav {{ position:sticky; top:0; height:100vh; display:flex; flex-direction:column; gap:18px; padding:18px 12px; background:var(--nav); color:#fff; }}
    .brand {{ display:grid; gap:3px; padding:4px 6px 12px; border-bottom:1px solid rgba(255,255,255,.12); }}
    .brand-mark {{ width:34px; height:34px; display:grid; place-items:center; border-radius:8px; background:#2563eb; font-weight:900; }}
    .brand-title {{ font-size:16px; line-height:1.25; font-weight:850; }}
    .brand-sub {{ color:#a7b0c0; font-size:11px; }}
    .tabs {{ display:grid; gap:8px; }}
    .tab-button {{ appearance:none; border:1px solid transparent; border-radius:8px; background:transparent; color:#cbd5e1; min-height:42px; padding:10px 10px; font-size:14px; font-weight:800; text-align:left; cursor:pointer; }}
    .tab-button:hover {{ background:rgba(255,255,255,.08); color:#fff; }}
    .tab-button.is-active {{ background:#2563eb; color:#fff; border-color:#3b82f6; }}
    .side-footer {{ margin-top:auto; color:#9ca3af; font-size:11px; line-height:1.5; padding:10px 6px 0; border-top:1px solid rgba(255,255,255,.12); }}
    .main {{ min-width:0; padding:18px 22px 32px; }}
    .topbar {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:18px; align-items:start; margin-bottom:14px; }}
    .title-row {{ display:flex; align-items:flex-start; gap:14px; flex-wrap:wrap; }}
    h1 {{ margin:0; font-size:28px; line-height:1.18; font-weight:850; letter-spacing:0; }}
    h2 {{ margin:0; font-size:18px; line-height:1.25; font-weight:850; letter-spacing:0; }}
    h3 {{ margin:0 0 10px; font-size:15px; line-height:1.35; font-weight:820; letter-spacing:0; }}
    .muted, .helper-text {{ color:var(--muted); font-size:12px; line-height:1.55; }}
    .helper-text {{ margin-top:10px; }}
    .meta-line {{ margin-top:8px; color:var(--muted); font-size:12px; line-height:1.5; }}
    .badge-row, .pillrow {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; }}
    .badge, .pill {{ display:inline-flex; align-items:center; gap:6px; min-height:28px; padding:5px 9px; border:1px solid var(--line); border-radius:8px; background:var(--surface); color:var(--text); font-size:12px; font-weight:700; }}
    .badge.is-paper {{ background:#eff6ff; color:#1d4ed8; border-color:#bfdbfe; }}
    .badge.is-safe {{ background:#ecfdf5; color:#047857; border-color:#bbf7d0; }}
    .top-actions {{ display:flex; flex-direction:column; align-items:flex-end; gap:8px; }}
    .action-button {{ appearance:none; border:0; border-radius:8px; min-height:38px; padding:9px 14px; background:#2563eb; color:#fff; font-size:13px; font-weight:850; cursor:pointer; box-shadow:0 8px 18px rgba(37,99,235,.20); }}
    .action-button:disabled {{ opacity:.7; cursor:wait; }}
    .filter-form {{ display:flex; flex-wrap:wrap; justify-content:flex-end; gap:8px; align-items:center; }}
    .filter-form label {{ color:var(--muted); font-size:12px; }}
    .filter-form select, .filter-form input {{ height:34px; border:1px solid var(--line); border-radius:8px; padding:6px 9px; background:#fff; color:var(--text); font-size:12px; }}
    .filter-form button {{ height:34px; appearance:none; border:1px solid var(--line); border-radius:8px; background:#fff; color:var(--text); padding:6px 10px; font-size:12px; font-weight:750; cursor:pointer; }}
    .alert-list {{ display:grid; gap:8px; margin:0 0 12px; }}
    .alert-card {{ border:1px solid #bfdbfe; border-left:4px solid var(--accent); border-radius:8px; background:#eff6ff; padding:10px 12px; }}
    .alert-card.is-warning {{ border-color:#fed7aa; border-left-color:var(--warn); background:#fff7ed; }}
    .metrics {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:0 0 14px; }}
    .metric-card {{ min-height:104px; background:var(--surface); border:1px solid var(--line); border-top:3px solid #94a3b8; border-radius:8px; padding:12px; box-shadow:var(--shadow); }}
    .metric-card.is-ok {{ border-top-color:var(--ok); }}
    .metric-card.is-warn {{ border-top-color:var(--warn); }}
    .metric-card.is-danger {{ border-top-color:var(--danger); }}
    .metric-card.is-muted {{ border-top-color:#94a3b8; }}
    .metric-label {{ color:var(--muted); font-size:12px; font-weight:800; }}
    .metric-value {{ margin-top:7px; font-size:20px; line-height:1.2; font-weight:900; overflow-wrap:anywhere; }}
    .metric-note {{ margin-top:6px; color:var(--muted); font-size:11px; line-height:1.35; overflow-wrap:anywhere; }}
    .tab-panel {{ display:none; }}
    .tab-panel.is-active {{ display:block; }}
    .ops-layout {{ display:grid; grid-template-columns:minmax(0,1.35fr) minmax(380px,.9fr); gap:14px; align-items:start; }}
    .ops-primary, .ops-side, .stack {{ display:grid; gap:14px; }}
    .panel, .card, .section-shell {{ background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:14px; box-shadow:var(--shadow); }}
    .card.card-embedded {{ box-shadow:none; background:#fff; }}
    .wide-panel {{ margin-top:14px; }}
    .panel-head {{ display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:10px; }}
    .panel-meta {{ color:var(--muted); font-size:12px; font-weight:750; text-align:right; }}
    .subtab-shell {{ display:grid; grid-template-columns:210px minmax(0,1fr); gap:14px; }}
    .subtab-nav {{ display:grid; gap:8px; align-content:start; }}
    .subtab-button {{ appearance:none; width:100%; border:1px solid var(--line); border-radius:8px; background:#fff; color:var(--text); padding:10px 11px; font-size:13px; font-weight:800; text-align:left; cursor:pointer; }}
    .subtab-button.is-active {{ background:#172033; color:#fff; border-color:#172033; }}
    .subtab-panel, .expand-panel {{ display:none; }}
    .subtab-panel.is-active, .expand-panel.is-active {{ display:block; }}
    .expand-tabs {{ display:flex; flex-wrap:wrap; gap:7px; margin:8px 0 12px; }}
    .expand-tabs .subtab-button {{ width:auto; min-height:32px; padding:7px 10px; }}
    .expand-tabs .subtab-button.is-active {{ background:#2563eb; border-color:#2563eb; color:#fff; }}
    .data-scroll {{ overflow:auto; padding-right:2px; }}
    .data-scroll table {{ min-width:100%; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th, td {{ text-align:left; padding:9px 8px; border-top:1px solid var(--line-soft); vertical-align:top; line-height:1.35; }}
    thead th {{ position:sticky; top:0; z-index:1; background:#f8fafc; color:#64748b; border-top:0; font-size:11px; font-weight:850; }}
    tbody tr:hover {{ background:#f8fafc; }}
    .prediction-flow-table {{ min-width:1420px; }}
    .prediction-flow-table th, .prediction-flow-table td {{ white-space:pre-line; overflow-wrap:anywhere; }}
    .prediction-flow-table th:nth-child(4), .prediction-flow-table td:nth-child(4),
    .prediction-flow-table th:nth-child(5), .prediction-flow-table td:nth-child(5) {{ min-width:210px; }}
    .prediction-flow-table th:nth-child(6), .prediction-flow-table td:nth-child(6) {{ width:190px; max-width:210px; }}
    .prediction-flow-table th:nth-child(7), .prediction-flow-table td:nth-child(7),
    .prediction-flow-table th:nth-child(8), .prediction-flow-table td:nth-child(8),
    .prediction-flow-table th:nth-child(9), .prediction-flow-table td:nth-child(9) {{ min-width:160px; }}
    .empty {{ color:var(--muted); font-size:13px; padding:8px 0; }}
    ul {{ margin:0; padding-left:18px; }}
    li {{ margin:7px 0; }}
    @media (max-width: 1180px) {{ .app-shell {{ grid-template-columns:1fr; }} .side-nav {{ position:relative; height:auto; flex-direction:row; align-items:center; overflow:auto; }} .brand {{ border-bottom:0; border-right:1px solid rgba(255,255,255,.12); padding-right:14px; }} .tabs {{ display:flex; min-width:max-content; }} .tab-button {{ white-space:nowrap; }} .side-footer {{ display:none; }} .topbar, .ops-layout, .subtab-shell {{ grid-template-columns:1fr; }} .top-actions {{ align-items:flex-start; }} .filter-form {{ justify-content:flex-start; }} .metrics {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
    @media (max-width: 720px) {{ .main {{ padding:12px; }} .side-nav {{ padding:10px; gap:10px; }} .brand-title, .brand-sub {{ display:none; }} .metrics {{ grid-template-columns:1fr; }} .metric-card {{ min-height:88px; }} h1 {{ font-size:23px; }} .panel, .card, .section-shell {{ padding:12px; }} th, td {{ padding:8px 6px; }} }}
  </style>
</head>
<body>
  <div class="app-shell">
    <aside class="side-nav">
      <div class="brand">
        <div class="brand-mark">RT</div>
        <div class="brand-title">운영<br>대시보드</div>
        <div class="brand-sub">paper 검증</div>
      </div>
      <nav class="tabs" role="tablist" aria-label="대시보드 탭">{tab_buttons}</nav>
      <div class="side-footer">버전 {_esc(payload.get('version'))}<br>자동 새로고침 {refresh_text}</div>
    </aside>
    <main class="main">
      <header class="topbar">
        <div>
          <div class="title-row">
            <h1>운영 대시보드</h1>
            <span class="badge is-paper">모드 {project.get('trading_mode') or '-'}</span>
            <span class="badge is-safe">실전 주문 {live_order_safety_value}</span>
          </div>
          <div class="meta-line">
            업데이트 {_esc(payload.get('generated_at') or '-')} · 장 상태 {_esc(session_label)} · 범위 {_esc(period_filter.get('label') or '-')} · 실제 데이터 기준 {_esc(scope.get('actual_runtime_filter_note') or '-')}
          </div>
        </div>
        <div class="top-actions">
          <button id="refresh-dashboard-button" class="action-button" type="button">상태 업데이트</button>
          <form class="filter-form" method="get" action="/">
            <label>조회 범위 <select name="range">{option_html}</select></label>
            <label>기준 날짜 <input type="date" name="date" value="{_esc(period_filter.get('selected_date'))}"></label>
            <button type="submit">적용</button>
          </form>
        </div>
      </header>
      {_alert_list(status_alerts)}
      <section class="metrics">{metrics_html}</section>
      <section data-tab-id="tab-ops" class="tab-panel is-active">{operator_console_html}</section>
      <section data-tab-id="tab-accounts" class="tab-panel">{accounts_tab_html}</section>
      <section data-tab-id="tab-ml-data" class="tab-panel">{ml_data_tab_html}</section>
      <section data-tab-id="tab-orders" class="tab-panel">{orders_tab_html}</section>
      <section data-tab-id="tab-reports-settings" class="tab-panel">{reports_settings_tab_html}</section>
    </main>
  </div>
  <script>
    (() => {{
      const buttons = Array.from(document.querySelectorAll('[data-tab-target]'));
      const panels = Array.from(document.querySelectorAll('.tab-panel'));
      const refreshButton = document.getElementById('refresh-dashboard-button');
      const storageKey = 'realtime-stock-dashboard-active-tab';
      const subtabStoragePrefix = 'realtime-stock-dashboard-subtab-';
      const resetScroll = () => {{
        window.requestAnimationFrame(() => window.scrollTo({{ top: 0, left: 0, behavior: 'auto' }}));
      }};
      const activateSubtabGroup = (group, targetId) => {{
        const buttonsInGroup = Array.from(document.querySelectorAll(`[data-subtab-group="${{group}}"]`));
        const panelsInGroup = Array.from(document.querySelectorAll(`[data-subtab-panel="${{group}}"]`));
        const fallbackId = panelsInGroup.length ? panelsInGroup[0].id : '';
        const nextId = document.getElementById(targetId) ? targetId : fallbackId;
        if (!nextId) {{
          return;
        }}
        buttonsInGroup.forEach((button) => {{
          const active = button.dataset.subtabTarget === nextId;
          button.classList.toggle('is-active', active);
          button.setAttribute('aria-selected', active ? 'true' : 'false');
        }});
        panelsInGroup.forEach((panel) => {{
          panel.classList.toggle('is-active', panel.id === nextId);
        }});
        try {{
          window.localStorage.setItem(`${{subtabStoragePrefix}}${{group}}`, nextId);
        }} catch (error) {{}}
      }};
      const activate = (targetId) => {{
        const fallbackId = 'tab-ops';
        const panelIds = new Set(panels.map((panel) => panel.dataset.tabId).filter(Boolean));
        const nextId = panelIds.has(targetId) ? targetId : fallbackId;
        buttons.forEach((button) => {{
          const active = button.dataset.tabTarget === nextId;
          button.classList.toggle('is-active', active);
          button.setAttribute('aria-selected', active ? 'true' : 'false');
        }});
        panels.forEach((panel) => panel.classList.toggle('is-active', panel.dataset.tabId === nextId));
        if (window.location.hash !== `#${{nextId}}`) {{
          history.replaceState(null, '', `#${{nextId}}`);
        }}
        try {{
          window.localStorage.setItem(storageKey, nextId);
        }} catch (error) {{}}
        resetScroll();
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
      activate(initialTab || 'tab-ops');
      const subtabGroups = Array.from(new Set(Array.from(document.querySelectorAll('[data-subtab-group]')).map((button) => button.dataset.subtabGroup).filter(Boolean)));
      subtabGroups.forEach((group) => {{
        let initialSubtab = '';
        try {{
          initialSubtab = window.localStorage.getItem(`${{subtabStoragePrefix}}${{group}}`) || '';
        }} catch (error) {{
          initialSubtab = '';
        }}
        activateSubtabGroup(group, initialSubtab);
      }});
      window.addEventListener('hashchange', () => activate(window.location.hash.slice(1)));
      if (refreshButton) {{
        const triggerRefresh = () => {{
          refreshButton.disabled = true;
          refreshButton.textContent = '업데이트 중...';
          fetch('/api/refresh', {{ cache: 'no-store' }})
            .catch(() => null)
            .finally(() => window.location.reload());
        }};
        refreshButton.addEventListener('click', () => {{
          triggerRefresh();
        }});
        const refreshIntervalMs = {max(refresh_seconds, 1) * 1000};
        window.setTimeout(() => {{
          triggerRefresh();
        }}, refreshIntervalMs);
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
    refresh_seconds: int = 600,
    recent_limit: int = 100,
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
    _write_text_with_retries(json_path, json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_text_with_retries(
        html_path,
        _render_dashboard_html(payload, refresh_seconds=refresh_seconds, live_mode=False),
        encoding="utf-8",
    )
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
            refresh_requested = str(params.get("refresh", ["0"])[0] or "0").strip().lower() in {"1", "true", "yes"}
            try:
                use_cached_dashboard = _should_use_cached_dashboard(
                    path=parsed.path,
                    range_key=range_key,
                    selected_date=selected_date,
                    refresh_requested=refresh_requested,
                )
                if parsed.path in {"/", "/index.html"}:
                    if use_cached_dashboard:
                        cached_payload = _load_cached_dashboard_payload(project_root)
                        if cached_payload is not None:
                            self._write_html(_render_dashboard_html(cached_payload, refresh_seconds=refresh_seconds, live_mode=True))
                            return
                    payload = collect_dashboard_payload(
                        project_root=project_root,
                        recent_limit=recent_limit,
                        range_key=range_key,
                        selected_date=selected_date,
                    )
                    self._write_html(_render_dashboard_html(payload, refresh_seconds=refresh_seconds, live_mode=True))
                    return
                if parsed.path == "/api/dashboard.json":
                    if use_cached_dashboard:
                        cached_payload = _load_cached_dashboard_payload(project_root)
                        if cached_payload is not None:
                            self._write_json(cached_payload)
                            return
                    self._write_json(
                        collect_dashboard_payload(
                            project_root=project_root,
                            recent_limit=recent_limit,
                            range_key=range_key,
                            selected_date=selected_date,
                        )
                    )
                    return
                if parsed.path == "/api/refresh":
                    snapshot = build_dashboard_snapshot(
                        project_root=project_root,
                        refresh_seconds=refresh_seconds,
                        recent_limit=recent_limit,
                    )
                    self._write_json(
                        {
                            "ok": True,
                            "refreshed_at": snapshot.payload.get("generated_at"),
                            "snapshot_html_path": str(snapshot.snapshot_html_path),
                            "snapshot_json_path": str(snapshot.snapshot_json_path),
                        }
                    )
                    return
                if parsed.path == "/health":
                    self._write_json({"ok": True, "service": "dashboard"})
                    return
                self._write_json({"ok": False, "error": "not-found"}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:  # pragma: no cover - live serving fallback
                message = "\uc2e4\uc2dc\uac04 \uc218\uc9d1\uae30\uc640 \ub300\uc2dc\ubcf4\ub4dc\uac00 \uac19\uc740 \ub370\uc774\ud130 \ud30c\uc77c\uc744 \ub3d9\uc2dc\uc5d0 \uc0ac\uc6a9\ud574 \uc7a0\uc2dc \ucda9\ub3cc\ud588\uc2b5\ub2c8\ub2e4."
                cached_payload = _load_cached_dashboard_payload(project_root)
                if cached_payload is not None:
                    fallback_payload = _mark_dashboard_payload_stale(cached_payload, message=message, detail=str(exc))
                    if parsed.path == "/api/dashboard.json":
                        self._write_json(fallback_payload)
                        return
                    self._write_html(_render_dashboard_html(fallback_payload, refresh_seconds=refresh_seconds, live_mode=True))
                    return
                if parsed.path == "/api/dashboard.json":
                    self._write_json(
                        {
                            "ok": False,
                            "error": "dashboard-temporarily-unavailable",
                            "message": message,
                            "detail": str(exc),
                        },
                        status=HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return
                self._write_html(
                    _render_dashboard_error_html(message, detail=str(exc)),
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                )
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    return DashboardHandler


def prepare_dashboard_server(
    project_root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    refresh_seconds: int = 600,
    recent_limit: int = 100,
) -> tuple[ThreadingHTTPServer, DashboardServeInfo]:
    settings = load_settings(project_root=project_root)
    report_dir = settings.runtime_data_dir / "reports" / "dashboard"
    snapshot_html_path = report_dir / "latest-dashboard.html"
    snapshot_json_path = report_dir / "latest-dashboard.json"
    if not snapshot_html_path.exists() or not snapshot_json_path.exists():
        snapshot = build_dashboard_snapshot(
            project_root=project_root,
            refresh_seconds=refresh_seconds,
            recent_limit=recent_limit,
        )
        snapshot_html_path = snapshot.snapshot_html_path
        snapshot_json_path = snapshot.snapshot_json_path
    server = ThreadingHTTPServer((host, port), _make_dashboard_handler(project_root=project_root, refresh_seconds=refresh_seconds, recent_limit=recent_limit))
    actual_host, actual_port = server.server_address
    return server, DashboardServeInfo(
        host=str(actual_host),
        port=int(actual_port),
        refresh_seconds=refresh_seconds,
        url=f"http://{actual_host}:{actual_port}",
        snapshot_html_path=snapshot_html_path,
        snapshot_json_path=snapshot_json_path,
    )
