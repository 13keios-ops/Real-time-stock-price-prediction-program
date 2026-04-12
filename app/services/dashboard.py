"""Local monitoring dashboard for runtime operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config.settings import load_settings
from app.models.registry import ModelRegistry
from app.observability.logging import configure_logging
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


def _recent_prediction_view(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
                "horizon_min": row["horizon_min"],
                "model_version": row["model_version"],
                "top_label": top_label,
                "top_confidence": round(top_confidence, 4),
                "probabilities": probabilities,
            }
        )
    return rendered


def _recent_signal_view(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "signal_id": row["signal_id"],
            "symbol": row["symbol"],
            "event_time": row["event_time"],
            "side": row["side"],
            "confidence": float(row["confidence"]),
            "allowed": bool(row["allowed"]),
            "reason": row["reason"],
        }
        for row in rows
    ]


def _recent_order_view(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "order_id": row["order_id"],
            "symbol": row["symbol"],
            "event_time": row["event_time"],
            "side": row["side"],
            "qty": row["qty"],
            "limit_price": row["limit_price"],
            "status": row["status"],
        }
        for row in rows
    ]


def _recent_fill_view(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "fill_id": row["fill_id"],
            "order_id": row["order_id"],
            "event_time": row["event_time"],
            "fill_price": row["fill_price"],
            "fill_qty": row["fill_qty"],
            "commission": row["commission"],
            "tax": row["tax"],
        }
        for row in rows
    ]


def _recent_bar_view(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "symbol": row["symbol"],
            "bar_time": row["bar_time"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
        }
        for row in rows
    ]


def _summarize_runtime(sqlite_store) -> dict[str, int]:
    evaluation_rows = sqlite_store.fetch_all_rows("ml_model_evaluations", "evaluated_at")
    return {
        "raw_market_ticks": sqlite_store.count_rows("raw_market_ticks"),
        "raw_orderbook_ticks": sqlite_store.count_rows("raw_orderbook_ticks"),
        "minute_bars": sqlite_store.count_rows("curated_minute_bars"),
        "feature_rows": sqlite_store.count_rows("feature_model_inputs"),
        "labels": sqlite_store.count_rows("feature_labels"),
        "predictions": sqlite_store.count_rows("serving_predictions"),
        "signals": sqlite_store.count_rows("serving_trade_signals"),
        "orders": sqlite_store.count_rows("paper_orders"),
        "fills": sqlite_store.count_rows("paper_fills"),
        "positions": sqlite_store.count_rows("paper_positions"),
        "portfolio_snapshots": sqlite_store.count_rows("paper_portfolio_snapshots"),
        "training_runs": sqlite_store.count_rows("ml_training_runs"),
        "evaluations": sqlite_store.count_rows("ml_model_evaluations"),
        "backtests": sum(1 for row in evaluation_rows if str(row["split_name"]).startswith("backtest_")),
        "walk_forward_runs": sum(1 for row in evaluation_rows if str(row["split_name"]).startswith("walk_forward_")),
        "challenger_runs": sum(1 for row in evaluation_rows if str(row["split_name"]).startswith("challenger_")),
    }


def collect_dashboard_payload(project_root: Path, *, recent_limit: int = 10) -> dict[str, Any]:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = get_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for the dashboard.")

    runtime_summary = _summarize_runtime(sqlite_store)
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

    latest_backtest_report = _safe_load_json(
        settings.runtime_data_dir / "reports" / "backtests" / "latest-backtest-h15.json"
    )
    latest_walk_forward_report = _safe_load_json(
        settings.runtime_data_dir / "reports" / "backtests" / "latest-walk-forward-h15.json"
    )
    latest_challenger_report = _safe_load_json(
        settings.runtime_data_dir / "reports" / "challengers" / "latest-challengers-h15.json"
    )
    latest_kis_verification = _safe_load_json(
        settings.runtime_data_dir / "reports" / "kis-ws" / "latest-verification.json"
    )
    latest_audit_progress = _safe_load_json(
        settings.runtime_data_dir / "reports" / "codex" / "automation" / "state" / "latest-progress.json"
    )
    latest_audit_backlog = _safe_load_json(
        settings.runtime_data_dir / "reports" / "codex" / "automation" / "backlog" / "latest-priority-backlog.json"
    )

    latest_snapshot = _serialize_row(sqlite_store.fetch_latest_row("paper_portfolio_snapshots", "event_time"))
    positions = [_serialize_row(row) for row in sqlite_store.fetch_all_rows("paper_positions", "symbol")]
    recent_predictions = _recent_prediction_view(
        [_serialize_row(row) for row in sqlite_store.fetch_recent_rows("serving_predictions", "event_time", recent_limit)]
    )
    recent_signals = _recent_signal_view(
        [_serialize_row(row) for row in sqlite_store.fetch_recent_rows("serving_trade_signals", "event_time", recent_limit)]
    )
    recent_orders = _recent_order_view(
        [_serialize_row(row) for row in sqlite_store.fetch_recent_rows("paper_orders", "event_time", recent_limit)]
    )
    recent_fills = _recent_fill_view(
        [_serialize_row(row) for row in sqlite_store.fetch_recent_rows("paper_fills", "event_time", recent_limit)]
    )
    recent_risk_events = [
        _serialize_row(row) for row in sqlite_store.fetch_recent_rows("ops_risk_events", "event_time", recent_limit)
    ]
    recent_minute_bars = _recent_bar_view(
        [_serialize_row(row) for row in sqlite_store.fetch_recent_rows("curated_minute_bars", "bar_time", recent_limit)]
    )

    active_model_entry: dict[str, Any] = {}
    active_models = active_registry.get("active_models", {})
    if isinstance(active_models, dict):
        active_model_entry = active_models.get("15", {}) or {}

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "project": {
            "name": settings.app_name,
            "environment": settings.app_env,
            "trading_mode": settings.trading_mode,
            "runtime_data_dir": str(settings.runtime_data_dir),
        },
        "runtime_summary": runtime_summary,
        "active_model": active_model_entry,
        "latest_training": latest_training,
        "latest_evaluation": latest_evaluation,
        "latest_backtest_report": latest_backtest_report,
        "latest_walk_forward_report": latest_walk_forward_report,
        "latest_challenger_report": latest_challenger_report,
        "latest_kis_verification": latest_kis_verification,
        "latest_portfolio_snapshot": latest_snapshot,
        "positions": positions,
        "recent_predictions": recent_predictions,
        "recent_signals": recent_signals,
        "recent_orders": recent_orders,
        "recent_fills": recent_fills,
        "recent_risk_events": recent_risk_events,
        "recent_minute_bars": recent_minute_bars,
        "audit": {
            "progress": latest_audit_progress,
            "backlog": latest_audit_backlog,
        },
    }


def _json_script(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _render_dashboard_html(payload: dict[str, Any], *, live_api_url: str | None, refresh_seconds: int) -> str:
    payload_json = _json_script(payload)
    live_api_value = json.dumps(live_api_url, ensure_ascii=False)
    refresh_ms = max(refresh_seconds, 1) * 1000
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>실시간 주식 예측 운영 대시보드</title>
  <style>
    :root {{
      --bg: #f3f0e8;
      --panel: rgba(255, 252, 245, 0.88);
      --ink: #1f2933;
      --muted: #5f6c7b;
      --line: rgba(31, 41, 51, 0.12);
      --good: #18794e;
      --warn: #b26a00;
      --bad: #ad2e24;
      --accent: #0d5c63;
      --accent-soft: rgba(13, 92, 99, 0.12);
      --shadow: 0 18px 40px rgba(31, 41, 51, 0.10);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Pretendard", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(13, 92, 99, 0.14), transparent 36%),
        radial-gradient(circle at top right, rgba(217, 119, 6, 0.12), transparent 30%),
        linear-gradient(180deg, #f7f3ea 0%, #eef2f4 100%);
      min-height: 100vh;
    }}
    .shell {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 28px 24px 60px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: 1.4fr 1fr;
      gap: 16px;
      margin-bottom: 18px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }}
    .hero-main {{
      padding: 24px 26px;
    }}
    .eyebrow {{
      display: inline-block;
      padding: 6px 10px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 14px 0 8px;
      font-size: 34px;
      line-height: 1.1;
    }}
    .subtext {{
      color: var(--muted);
      font-size: 15px;
      line-height: 1.65;
      margin: 0;
    }}
    .hero-side {{
      padding: 24px 26px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      justify-content: center;
    }}
    .status-grid, .metric-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .metric-card, .status-card {{
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.55);
    }}
    .metric-label, .status-label {{
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 8px;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }}
    .metric-value {{
      font-size: 28px;
      font-weight: 700;
    }}
    .metric-help {{
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
    }}
    .badge.good {{ background: rgba(24,121,78,0.14); color: var(--good); }}
    .badge.warn {{ background: rgba(178,106,0,0.16); color: var(--warn); }}
    .badge.bad {{ background: rgba(173,46,36,0.14); color: var(--bad); }}
    .sections {{
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 16px;
    }}
    .stack {{
      display: grid;
      gap: 16px;
    }}
    .section {{
      padding: 20px 22px;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 19px;
    }}
    .pill-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }}
    .soft-pill {{
      padding: 8px 10px;
      border-radius: 12px;
      background: rgba(255,255,255,0.65);
      border: 1px solid var(--line);
      font-size: 13px;
      color: var(--muted);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      text-align: left;
      padding: 10px 8px;
      border-top: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }}
    tr:first-child th, tr:first-child td {{
      border-top: none;
    }}
    .empty {{
      color: var(--muted);
      font-size: 14px;
      padding: 10px 0 2px;
    }}
    .two-col {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }}
    .note {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }}
    .list {{
      display: grid;
      gap: 10px;
      margin: 0;
      padding: 0;
      list-style: none;
    }}
    .list-item {{
      padding: 12px 14px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.58);
    }}
    .list-title {{
      font-weight: 700;
      margin-bottom: 4px;
    }}
    @media (max-width: 1120px) {{
      .hero, .sections {{ grid-template-columns: 1fr; }}
      .status-grid, .metric-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .two-col {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 640px) {{
      .shell {{ padding: 18px 14px 40px; }}
      .status-grid, .metric-grid {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 28px; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div class="panel hero-main">
        <span class="eyebrow">Monday Monitor</span>
        <h1>실시간 주식 예측 운영 대시보드</h1>
        <p class="subtext">장중 연결 상태, active 모델, 최근 예측·신호·주문·포지션, 자동 점검 backlog를 한 화면에서 확인하는 로컬 운영 화면입니다.</p>
      </div>
      <div class="panel hero-side">
        <div id="header-status" class="pill-row"></div>
        <div class="note" id="header-note"></div>
      </div>
    </section>
    <section class="metric-grid" id="metric-grid"></section>
    <section class="status-grid" id="status-grid"></section>
    <section class="sections">
      <div class="stack">
        <div class="panel section">
          <h2>모델과 검증 상태</h2>
          <div id="model-summary" class="two-col"></div>
          <div class="pill-row" id="model-pills"></div>
        </div>
        <div class="panel section">
          <h2>최근 예측</h2>
          <div id="predictions-table"></div>
        </div>
        <div class="panel section">
          <h2>최근 신호와 주문</h2>
          <div class="two-col">
            <div id="signals-table"></div>
            <div id="orders-table"></div>
          </div>
        </div>
        <div class="panel section">
          <h2>최근 체결과 분봉</h2>
          <div class="two-col">
            <div id="fills-table"></div>
            <div id="bars-table"></div>
          </div>
        </div>
      </div>
      <div class="stack">
        <div class="panel section">
          <h2>포트폴리오</h2>
          <div id="portfolio-card"></div>
        </div>
        <div class="panel section">
          <h2>KIS 연결 상태</h2>
          <div id="kis-card"></div>
        </div>
        <div class="panel section">
          <h2>자동 점검 backlog</h2>
          <div id="audit-card"></div>
        </div>
      </div>
    </section>
  </div>
  <script id="dashboard-bootstrap" type="application/json">{payload_json}</script>
  <script>
    const LIVE_API_URL = {live_api_value};
    const REFRESH_MS = {refresh_ms};

    function escapeHtml(value) {{
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }}

    function badgeTone(kind) {{
      if (kind === "good") return "good";
      if (kind === "bad") return "bad";
      return "warn";
    }}

    function badge(label, kind) {{
      return `<span class="badge ${{badgeTone(kind)}}">${{escapeHtml(label)}}</span>`;
    }}

    function money(value) {{
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
      return Number(value).toLocaleString("ko-KR", {{ maximumFractionDigits: 0 }});
    }}

    function pct(value) {{
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
      return `${{Number(value).toFixed(4)}}%`;
    }}

    function confidence(value) {{
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
      return Number(value).toFixed(4);
    }}

    function summaryCard(label, value, helpText) {{
      return `<div class="metric-card"><div class="metric-label">${{escapeHtml(label)}}</div><div class="metric-value">${{escapeHtml(value)}}</div><div class="metric-help">${{escapeHtml(helpText || "")}}</div></div>`;
    }}

    function statusCard(label, body, kind) {{
      return `<div class="status-card"><div class="status-label">${{escapeHtml(label)}}</div><div>${{badge(body, kind)}}</div></div>`;
    }}

    function renderTable(columns, rows, emptyText) {{
      if (!rows || rows.length === 0) {{
        return `<div class="empty">${{escapeHtml(emptyText)}}</div>`;
      }}
      const header = columns.map((column) => `<th>${{escapeHtml(column.label)}}</th>`).join("");
      const body = rows.map((row) => `<tr>${{columns.map((column) => `<td>${{column.render ? column.render(row) : escapeHtml(row[column.key])}}</td>`).join("")}}</tr>`).join("");
      return `<table><tr>${{header}}</tr>${{body}}</table>`;
    }}

    function renderList(items, emptyText) {{
      if (!items || items.length === 0) {{
        return `<div class="empty">${{escapeHtml(emptyText)}}</div>`;
      }}
      return `<ul class="list">${{items.join("")}}</ul>`;
    }}

    function render(data) {{
      const runtime = data.runtime_summary || {{}};
      const activeModel = data.active_model || {{}};
      const challenger = data.latest_challenger_report || {{}};
      const kis = data.latest_kis_verification || {{}};
      const portfolio = data.latest_portfolio_snapshot || {{}};
      const auditProgress = (data.audit || {{}}).progress || {{}};
      const auditBacklog = (data.audit || {{}}).backlog || {{}};

      document.getElementById("header-status").innerHTML = [
        badge(`모드: ${{data.project?.trading_mode || "-"}}`, "warn"),
        badge(`active: ${{activeModel.model_version || "-"}}`, "good"),
        badge(`challenger: ${{challenger.recommended_action || "-"}}`, challenger.recommended_action === "keep_active" ? "good" : "warn"),
        badge(`세션: ${{kis.session_status || "unknown"}}`, kis.market_data_flow_ok ? "good" : "warn"),
      ].join("");

      document.getElementById("header-note").textContent =
        `마지막 갱신: ${{data.generated_at || "-"}} | 연결 준비: ${{kis.connection_ready ? "완료" : "대기"}} | 시장 데이터 흐름: ${{kis.market_data_flow_ok ? "확인" : "미확인"}}`;

      document.getElementById("metric-grid").innerHTML = [
        summaryCard("예측", runtime.predictions ?? 0, "누적 예측 건수"),
        summaryCard("신호", runtime.signals ?? 0, "누적 거래 신호"),
        summaryCard("주문", runtime.orders ?? 0, "모의주문 누적"),
        summaryCard("순자산", money(portfolio.net_liquidation_value), "최신 포트폴리오 기준"),
      ].join("");

      document.getElementById("status-grid").innerHTML = [
        statusCard("KIS 연결 준비", kis.connection_ready ? "준비 완료" : "대기", kis.connection_ready ? "good" : "warn"),
        statusCard("시장 데이터 흐름", kis.market_data_flow_ok ? "수신 확인" : "아직 미확인", kis.market_data_flow_ok ? "good" : "warn"),
        statusCard("walk-forward gate", challenger.walk_forward_gate_status || "-", challenger.walk_forward_gate_status === "passed" ? "good" : "warn"),
        statusCard("자동 점검 open", String((auditProgress.open_items || []).length), (auditProgress.open_items || []).length === 0 ? "good" : "warn"),
      ].join("");

      const latestTraining = data.latest_training || {{}};
      const walkForward = data.latest_walk_forward_report || {{}};
      const walkForwardMetrics = walkForward.metrics || {{}};
      document.getElementById("model-summary").innerHTML = [
        `<div class="soft-pill"><strong>active 모델</strong><br>${{escapeHtml(activeModel.model_version || "-")}}</div>`,
        `<div class="soft-pill"><strong>최신 학습</strong><br>${{escapeHtml(latestTraining.model_version || "-")}}</div>`,
        `<div class="soft-pill"><strong>walk-forward 정확도</strong><br>${{pct(walkForwardMetrics.overall_accuracy ? Number(walkForwardMetrics.overall_accuracy) * 100 : null)}}</div>`,
        `<div class="soft-pill"><strong>추천 액션</strong><br>${{escapeHtml(challenger.recommended_action || "-")}}</div>`,
      ].join("");
      document.getElementById("model-pills").innerHTML = [
        `feature set: ${{activeModel.feature_set_version || "-"}}`,
        `challenger best: ${{challenger.best_model_version || "-"}}`,
        `walk-forward reason: ${{challenger.walk_forward_gate_reason || "-"}}`,
      ].map((text) => `<span class="soft-pill">${{escapeHtml(text)}}</span>`).join("");

      document.getElementById("predictions-table").innerHTML = renderTable(
        [
          {{ label: "시각", key: "event_time" }},
          {{ label: "종목", key: "symbol" }},
          {{ label: "모델", key: "model_version" }},
          {{ label: "판단", render: (row) => `${{escapeHtml(row.top_label)}} (${{confidence(row.top_confidence)}})` }},
          {{ label: "확률", render: (row) => `상 ${{confidence(row.probabilities.up)}} / 보합 ${{confidence(row.probabilities.flat)}} / 하 ${{confidence(row.probabilities.down)}}` }},
        ],
        data.recent_predictions || [],
        "최근 예측이 아직 없습니다."
      );

      document.getElementById("signals-table").innerHTML = renderTable(
        [
          {{ label: "시각", key: "event_time" }},
          {{ label: "종목", key: "symbol" }},
          {{ label: "방향", key: "side" }},
          {{ label: "허용", render: (row) => row.allowed ? badge("허용", "good") : badge("차단", "warn") }},
          {{ label: "사유", key: "reason" }},
        ],
        data.recent_signals || [],
        "최근 신호가 아직 없습니다."
      );

      document.getElementById("orders-table").innerHTML = renderTable(
        [
          {{ label: "시각", key: "event_time" }},
          {{ label: "종목", key: "symbol" }},
          {{ label: "방향", key: "side" }},
          {{ label: "수량", key: "qty" }},
          {{ label: "상태", key: "status" }},
        ],
        data.recent_orders || [],
        "최근 주문이 아직 없습니다."
      );

      document.getElementById("fills-table").innerHTML = renderTable(
        [
          {{ label: "시각", key: "event_time" }},
          {{ label: "주문", key: "order_id" }},
          {{ label: "체결가", render: (row) => money(row.fill_price) }},
          {{ label: "수량", key: "fill_qty" }},
          {{ label: "수수료", render: (row) => money(row.commission) }},
        ],
        data.recent_fills || [],
        "최근 체결이 아직 없습니다."
      );

      document.getElementById("bars-table").innerHTML = renderTable(
        [
          {{ label: "시각", key: "bar_time" }},
          {{ label: "종목", key: "symbol" }},
          {{ label: "종가", render: (row) => money(row.close) }},
          {{ label: "고저폭", render: (row) => `${{money(row.high)}} / ${{money(row.low)}}` }},
          {{ label: "거래량", render: (row) => money(row.volume) }},
        ],
        data.recent_minute_bars || [],
        "최근 분봉이 아직 없습니다."
      );

      const positions = data.positions || [];
      const positionTable = renderTable(
        [
          {{ label: "종목", key: "symbol" }},
          {{ label: "수량", key: "qty" }},
          {{ label: "평단", render: (row) => money(row.avg_price) }},
          {{ label: "현재가", render: (row) => money(row.last_price) }},
          {{ label: "평가손익", render: (row) => money(row.unrealized_pnl) }},
        ],
        positions,
        "현재 기록된 포지션이 없습니다."
      );
      document.getElementById("portfolio-card").innerHTML = `
        <div class="pill-row">
          <span class="soft-pill">순자산 ${{money(portfolio.net_liquidation_value)}}</span>
          <span class="soft-pill">현금 ${{money(portfolio.cash_balance)}}</span>
          <span class="soft-pill">미실현 ${{money(portfolio.unrealized_pnl)}}</span>
          <span class="soft-pill">실현 ${{money(portfolio.realized_pnl)}}</span>
        </div>
        <div class="note" style="margin-top:12px;">최신 스냅샷 시각: ${{escapeHtml(portfolio.event_time || "-")}}</div>
        <div style="margin-top:12px;">${{positionTable}}</div>
      `;

      document.getElementById("kis-card").innerHTML = `
        <div class="pill-row">
          ${{badge(kis.connection_ready ? "연결 준비 완료" : "연결 준비 대기", kis.connection_ready ? "good" : "warn")}}
          ${{badge(kis.market_data_flow_ok ? "실데이터 수신 확인" : "실데이터 미확인", kis.market_data_flow_ok ? "good" : "warn")}}
          ${{badge(`approval key: ${{kis.approval_key_issued ? "발급됨" : "미발급"}}`, kis.approval_key_issued ? "good" : "warn")}}
        </div>
        <div class="note" style="margin-top:12px;">
          세션 상태: ${{escapeHtml(kis.session_status || "-")}}<br>
          메모: ${{escapeHtml(kis.status_note || "-")}}<br>
          프레임: ${{escapeHtml(kis.frames_received ?? "-")}} / control: ${{escapeHtml(kis.control_frames ?? "-")}}
        </div>
      `;

      const backlogItems = ((auditBacklog.items || []).slice(0, 5)).map((item) => `
        <li class="list-item">
          <div class="list-title">${{escapeHtml(item.id)}} · ${{escapeHtml(item.priority || "-")}} · ${{escapeHtml(item.status || "-")}}</div>
          <div>${{escapeHtml(item.problem || "")}}</div>
          <div class="note" style="margin-top:6px;">권장 변경: ${{escapeHtml(item.recommended_change || "")}}</div>
        </li>
      `);
      const nextActions = (auditProgress.next_actions || []).map((item) => `<li class="list-item"><div>${{escapeHtml(item)}}</div></li>`);
      document.getElementById("audit-card").innerHTML = `
        <div class="note">${{escapeHtml(auditProgress.last_run_summary || "자동 점검 요약이 아직 없습니다.")}}</div>
        <h3 style="margin:16px 0 10px;">우선 backlog</h3>
        ${{renderList(backlogItems, "표시할 backlog 항목이 없습니다.")}}
        <h3 style="margin:16px 0 10px;">다음 액션</h3>
        ${{renderList(nextActions, "다음 액션이 아직 없습니다.")}}
      `;
    }}

    async function refreshFromApi() {{
      if (!LIVE_API_URL) return;
      try {{
        const response = await fetch(`${{LIVE_API_URL}}?ts=${{Date.now()}}`, {{ cache: "no-store" }});
        if (!response.ok) {{
          throw new Error(`dashboard api failed: ${{response.status}}`);
        }}
        const payload = await response.json();
        render(payload);
      }} catch (error) {{
        console.error(error);
      }}
    }}

    const bootstrap = JSON.parse(document.getElementById("dashboard-bootstrap").textContent);
    render(bootstrap);
    if (LIVE_API_URL) {{
      setInterval(refreshFromApi, REFRESH_MS);
    }}
  </script>
</body>
</html>
"""


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
    refresh_seconds: int = 5,
    recent_limit: int = 10,
) -> DashboardSnapshotResult:
    settings = load_settings(project_root=project_root)
    payload = collect_dashboard_payload(project_root=project_root, recent_limit=recent_limit)
    report_dir = settings.runtime_data_dir / "reports" / "dashboard"
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "latest-dashboard.json"
    html_path = report_dir / "latest-dashboard.html"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(
        _render_dashboard_html(payload, live_api_url=None, refresh_seconds=refresh_seconds),
        encoding="utf-8",
    )
    return DashboardSnapshotResult(
        snapshot_html_path=html_path,
        snapshot_json_path=json_path,
        payload=payload,
    )


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
                self._write_html(
                    _render_dashboard_html(payload, live_api_url="/api/dashboard.json", refresh_seconds=refresh_seconds)
                )
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


def prepare_dashboard_server(
    project_root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    refresh_seconds: int = 5,
    recent_limit: int = 10,
) -> tuple[ThreadingHTTPServer, DashboardServeInfo]:
    snapshot = build_dashboard_snapshot(
        project_root=project_root,
        refresh_seconds=refresh_seconds,
        recent_limit=recent_limit,
    )
    server = ThreadingHTTPServer(
        (host, port),
        _make_dashboard_handler(
            project_root=project_root,
            refresh_seconds=refresh_seconds,
            recent_limit=recent_limit,
        ),
    )
    actual_host, actual_port = server.server_address
    return server, DashboardServeInfo(
        host=str(actual_host),
        port=int(actual_port),
        refresh_seconds=refresh_seconds,
        url=f"http://{actual_host}:{actual_port}",
        snapshot_html_path=snapshot.snapshot_html_path,
        snapshot_json_path=snapshot.snapshot_json_path,
    )
