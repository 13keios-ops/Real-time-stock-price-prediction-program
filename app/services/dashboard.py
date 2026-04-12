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

    scope = build_runtime_scope(sqlite_store)
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
    recent_predictions = _prediction_view(_filtered_rows(sqlite_store, "serving_predictions", "event_time", scope)[-recent_limit:])
    recent_signals = _filtered_rows(sqlite_store, "serving_trade_signals", "event_time", scope)[-recent_limit:]
    recent_orders = _filtered_rows(sqlite_store, "paper_orders", "event_time", scope)[-recent_limit:]
    recent_fills = _filtered_rows(sqlite_store, "paper_fills", "event_time", scope)[-recent_limit:]
    recent_bars = _filtered_rows(sqlite_store, "curated_minute_bars", "bar_time", scope)[-recent_limit:]

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
        "latest_training": latest_training,
        "latest_evaluation": latest_evaluation,
        "latest_backtest_report": _safe_load_json(settings.runtime_data_dir / "reports" / "backtests" / "latest-backtest-h15.json"),
        "latest_walk_forward_report": _safe_load_json(settings.runtime_data_dir / "reports" / "backtests" / "latest-walk-forward-h15.json"),
        "latest_challenger_report": _safe_load_json(settings.runtime_data_dir / "reports" / "challengers" / "latest-challengers-h15.json"),
        "latest_kis_verification": _safe_load_json(settings.runtime_data_dir / "reports" / "kis-ws" / "latest-verification.json"),
        "latest_portfolio_snapshot": latest_snapshot_rows[-1] if latest_snapshot_rows else None,
        "positions": positions,
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
    backlog_items = [
        f"<strong>{_esc(item.get('id'))}</strong> / {_esc(item.get('priority'))} / {_esc(item.get('status'))}<br>{_esc(item.get('problem'))}<br><span class=\"muted\">Suggested change: {_esc(item.get('recommended_change'))}</span>"
        for item in (audit_backlog.get("items") or [])[:5]
    ]
    next_actions = [_esc(item) for item in (audit_progress.get("next_actions") or [])]

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {refresh_meta}
  <title>Realtime Stock Runtime Dashboard</title>
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
    .muted {{ color:#5f6c7b; font-size:14px; line-height:1.6; }}
    .pillrow {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }}
    .pill {{ padding:8px 10px; border-radius:999px; background:#fff; border:1px solid rgba(31,41,51,.12); font-size:13px; }}
    .metric {{ font-size:28px; font-weight:700; margin-top:6px; }}
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
        <span class="eyebrow">Actual Runtime Only</span>
        <h1>Realtime Stock Runtime Dashboard</h1>
        <div class="muted">Sample, synthetic, and demo rows are excluded by default. This view keeps only actual KIS-based runtime data.</div>
      </div>
      <div class="card">
        <div class="pillrow">
          <span class="pill">Mode: {_esc(payload.get('project', {}).get('trading_mode'))}</span>
          <span class="pill">Active: {_esc(active_model.get('model_version'))}</span>
          <span class="pill">Session: {_esc(kis.get('session_status'))}</span>
        </div>
        <div class="muted" style="margin-top:12px;">Updated: {_esc(payload.get('generated_at'))}<br>Actual-only filter: {'on' if scope.get('actual_runtime_only') else 'off'}<br>Actual minute keys: {_esc(scope.get('actual_symbol_minutes'))}</div>
      </div>
    </section>
    <section class="grid">
      <div class="card"><div class="muted">Predictions</div><div class="metric">{_esc(runtime.get('predictions', 0))}</div></div>
      <div class="card"><div class="muted">Signals</div><div class="metric">{_esc(runtime.get('signals', 0))}</div></div>
      <div class="card"><div class="muted">Orders</div><div class="metric">{_esc(runtime.get('orders', 0))}</div></div>
      <div class="card"><div class="muted">Equity</div><div class="metric">{_money(portfolio.get('net_liquidation_value'))}</div></div>
    </section>
    <section class="cols">
      <div class="stack">
        <div class="card">
          <h2>Model and validation state</h2>
          <div class="pillrow">
            <span class="pill">Active model: {_esc(active_model.get('model_version'))}</span>
            <span class="pill">Latest training: {_esc((payload.get('latest_training') or {}).get('model_version'))}</span>
            <span class="pill">Recommended action: {_esc(challenger.get('recommended_action'))}</span>
            <span class="pill">Walk-forward gate: {_esc(challenger.get('walk_forward_gate_status'))}</span>
          </div>
          <div class="muted" style="margin-top:12px;">{_esc(challenger.get('walk_forward_gate_reason'))}</div>
        </div>
        <div class="card"><h2>Recent predictions</h2>{_table(['Time','Symbol','Model','Top probability'], prediction_rows, 'No recent actual-runtime predictions.')}</div>
        <div class="card"><h2>Recent signals</h2>{_table(['Time','Symbol','Side','Allowed'], signal_rows, 'No recent actual-runtime signals.')}</div>
        <div class="card"><h2>Recent orders</h2>{_table(['Time','Symbol','Side','Qty','Status'], order_rows, 'No recent actual-runtime orders.')}</div>
        <div class="card"><h2>Recent fills and minute bars</h2>{_table(['Time','Order','Fill price','Qty'], fill_rows, 'No recent actual-runtime fills.')}<div style="height:10px"></div>{_table(['Time','Symbol','Close','Volume'], bar_rows, 'No recent actual-runtime minute bars.')}</div>
      </div>
      <div class="stack">
        <div class="card">
          <h2>Portfolio</h2>
          <div class="pillrow">
            <span class="pill">Equity {_money(portfolio.get('net_liquidation_value'))}</span>
            <span class="pill">Cash {_money(portfolio.get('cash_balance'))}</span>
            <span class="pill">Unrealized {_money(portfolio.get('unrealized_pnl'))}</span>
            <span class="pill">Realized {_money(portfolio.get('realized_pnl'))}</span>
          </div>
          <div class="muted" style="margin-top:12px;">Latest snapshot time: {_esc(portfolio.get('event_time'))}</div>
          <div style="margin-top:12px;">{_table(['Symbol','Qty','Average','Last','Unrealized PnL'], position_rows, 'No live portfolio position is currently recorded.')}</div>
        </div>
        <div class="card">
          <h2>KIS connection state</h2>
          <div class="pillrow">
            <span class="pill">Connection ready: {'yes' if kis.get('connection_ready') else 'no'}</span>
            <span class="pill">Live data flow: {'yes' if kis.get('market_data_flow_ok') else 'no'}</span>
            <span class="pill">Approval key: {'issued' if kis.get('approval_key_issued') else 'missing'}</span>
          </div>
          <div class="muted" style="margin-top:12px;">Session: {_esc(kis.get('session_status'))}<br>Note: {_esc(kis.get('status_note'))}<br>Frames: {_esc(kis.get('frames_received'))} / control: {_esc(kis.get('control_frames'))}</div>
        </div>
        <div class="card">
          <h2>Automation backlog</h2>
          <div class="muted">{_esc(audit_progress.get('last_run_summary') or 'No automation summary yet.')}</div>
          <h3 style="margin:16px 0 8px;">Priority backlog</h3>
          {_list(backlog_items, 'No backlog items to display.')}
          <h3 style="margin:16px 0 8px;">Next actions</h3>
          {_list(next_actions, 'No next action is currently recorded.')}
        </div>
      </div>
    </section>
  </div>
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
