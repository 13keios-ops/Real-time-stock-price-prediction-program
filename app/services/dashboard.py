"""Local monitoring dashboard for runtime operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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


def _safe_load_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
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


def _prediction_view(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for row in rows:
        probabilities = {
            "up": float(row["probability_up"]),
            "flat": float(row["probability_flat"]),
            "down": float(row["probability_down"]),
        }
        top_label, top_confidence = max(probabilities.items(), key=lambda item: item[1])
        rendered.append(
            {
                "prediction_id": row["prediction_id"],
                "symbol": row["symbol"],
                "event_time": row["event_time"],
                "model_version": row["model_version"],
                "top_label": top_label,
                "top_confidence": round(top_confidence, 4),
            }
        )
    return rendered


def collect_dashboard_payload(project_root: Path, *, recent_limit: int = 10) -> dict[str, Any]:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = get_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for the dashboard.")

    scope = build_runtime_scope(sqlite_store, settings)
    runtime_summary = _summarize_runtime(sqlite_store, scope)
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
    recent_predictions = _prediction_view(_filtered_rows(sqlite_store, "serving_predictions", "event_time", scope)[-recent_limit:])
    recent_signals = _filtered_rows(sqlite_store, "serving_trade_signals", "event_time", scope)[-recent_limit:]
    recent_orders = _filtered_rows(sqlite_store, "paper_orders", "event_time", scope)[-recent_limit:]
    recent_fills = _filtered_rows(sqlite_store, "paper_fills", "event_time", scope)[-recent_limit:]
    recent_bars = _filtered_rows(sqlite_store, "curated_minute_bars", "bar_time", scope)[-recent_limit:]
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
        },
        "runtime_summary": runtime_summary,
        "active_model": active_model_entry,
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
    challenger = payload.get("latest_challenger_report", {}) or {}
    kis = payload.get("latest_kis_verification", {}) or {}
    portfolio = payload.get("latest_portfolio_snapshot", {}) or {}
    broker_account_report = payload.get("broker_account_report", {}) or {}
    broker_account = broker_account_report.get("account_snapshot") or {}
    latest_training = payload.get("latest_training", {}) or {}
    latest_evaluation = payload.get("latest_evaluation", {}) or {}
    latest_backtest = payload.get("latest_backtest_report", {}) or {}
    latest_walk_forward = payload.get("latest_walk_forward_report", {}) or {}
    learning_context = payload.get("learning_context", {}) or {}
    audit_progress = (payload.get("audit") or {}).get("progress") or {}
    audit_backlog = (payload.get("audit") or {}).get("backlog") or {}
    scope = payload.get("dashboard_scope", {})
    refresh_meta = f'<meta http-equiv="refresh" content="{max(refresh_seconds, 1)}">' if live_mode else ""

    prediction_rows = [
        [row["event_time"], row["symbol"], row["model_version"], f'{row["top_label"]} ({row["top_confidence"]})']
        for row in payload.get("recent_predictions", [])
    ]
    signal_rows = [
        [row["event_time"], row["symbol"], row["side"], "allowed" if row.get("allowed") else "blocked"]
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
        </div>
        <div class="muted" style="margin-top:12px;">업데이트 시각: {_esc(payload.get('generated_at'))}<br>실운용 필터: {'켜짐' if scope.get('actual_runtime_only') else '꺼짐'}<br>실데이터 minute 수: {_esc(scope.get('actual_symbol_minutes'))}</div>
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
            <h2>최근 예측</h2>
            {_table(['시각','종목','모델','가장 높은 확률'], prediction_rows, '최근 실제 운용 예측이 없습니다.')}
          </div>
          <div class="card">
            <h2>최근 신호</h2>
            {_table(['시각','종목','방향','허용 여부'], signal_rows, '최근 실제 운용 신호가 없습니다.')}
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
            <div class="muted" style="margin-top:12px;">최근 스냅샷 시각: {_esc(portfolio.get('event_time'))}</div>
            <div style="margin-top:12px;">{_table(['종목','수량','평균 단가','현재가','미실현 손익'], position_rows, '현재 기록된 포지션이 없습니다.')}</div>
            <div class="muted" style="margin-top:12px;">프로그램 내부 모의주문 엔진이 기록한 가상 포트폴리오입니다. 우리 전략이 실제로 어떤 주문을 냈는지 추적하는 용도입니다.</div>
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


def build_dashboard_snapshot(project_root: Path, *, refresh_seconds: int = 5, recent_limit: int = 10) -> DashboardSnapshotResult:
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


def prepare_dashboard_server(project_root: Path, *, host: str = "127.0.0.1", port: int = 8765, refresh_seconds: int = 5, recent_limit: int = 10) -> tuple[ThreadingHTTPServer, DashboardServeInfo]:
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
