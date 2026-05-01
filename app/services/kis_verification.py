"""KIS WebSocket readiness and live verification helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.brokers.kis_auth import KisApiError, KisTokenManager, get_active_kis_profile
from app.brokers.kis_quote_ws import KisWebSocketQuoteClient, websockets
from app.config.settings import load_settings
from app.observability.logging import configure_logging
from app.services.streaming import OnlinePipelineResult, run_kis_ws_listener_sync
from app.universe.watchlist import load_watchlist
from app.utils.time import get_market_session_status, now_local


@dataclass(slots=True)
class KisWsVerificationResult:
    ok: bool
    trading_mode: str
    endpoint: str
    symbols: list[str]
    connection_ready: bool
    market_data_flow_ok: bool
    market_data_expected: bool
    session_status: str
    status_note: str
    dotenv_present: bool
    websockets_available: bool
    credentials_ready: bool
    approval_key_issued: bool
    max_frames: int
    frames_received: int
    control_frames: int
    raw_trade_events: int
    raw_orderbook_events: int
    minute_bars_written: int
    predictions_written: int
    signals_written: int
    orders_written: int
    missing_requirements: list[str]
    error: str | None
    report_markdown_path: Path
    report_json_path: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "trading_mode": self.trading_mode,
            "endpoint": self.endpoint,
            "symbols": self.symbols,
            "connection_ready": self.connection_ready,
            "market_data_flow_ok": self.market_data_flow_ok,
            "market_data_expected": self.market_data_expected,
            "session_status": self.session_status,
            "status_note": self.status_note,
            "dotenv_present": self.dotenv_present,
            "websockets_available": self.websockets_available,
            "credentials_ready": self.credentials_ready,
            "approval_key_issued": self.approval_key_issued,
            "max_frames": self.max_frames,
            "frames_received": self.frames_received,
            "control_frames": self.control_frames,
            "raw_trade_events": self.raw_trade_events,
            "raw_orderbook_events": self.raw_orderbook_events,
            "minute_bars_written": self.minute_bars_written,
            "predictions_written": self.predictions_written,
            "signals_written": self.signals_written,
            "orders_written": self.orders_written,
            "missing_requirements": self.missing_requirements,
            "error": self.error,
            "report_markdown_path": str(self.report_markdown_path),
            "report_json_path": str(self.report_json_path),
        }


def _market_session_context(settings, timestamp) -> tuple[str, bool, str]:
    session_status = get_market_session_status(settings.market_calendar, timestamp)
    if session_status == "weekend":
        return "weekend", False, "Weekend or holiday-like timing. Control frames without market data can be normal."
    if session_status == "holiday":
        return "holiday", False, "Configured market holiday. Live market data is not expected."
    if session_status == "pre-open":
        return "pre-open", False, "Before the regular session open. Market data flow may not be active yet."
    if session_status == "post-close":
        return "post-close", False, "After the regular session close. Control frames only can be normal."
    return "regular-session", True, "Regular session window. Trade or orderbook events should normally appear."


def verify_kis_websocket_runtime(
    project_root: Path,
    symbols: list[str] | None = None,
    watchlist_path: str | Path | None = None,
    max_frames: int = 20,
    max_reconnects: int = 1,
) -> KisWsVerificationResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    profile = get_active_kis_profile(settings)
    resolved_symbols = symbols or load_watchlist(project_root=project_root, watchlist_path=watchlist_path)
    timestamp = now_local(settings.timezone)
    session_status, market_data_expected, status_note = _market_session_context(settings, timestamp)
    missing_requirements: list[str] = []
    dotenv_present = (project_root / ".env").exists()
    websockets_available = websockets is not None
    credentials_ready = profile.is_ready_for_quotes
    approval_key_issued = False
    pipeline_result: OnlinePipelineResult | None = None
    error: str | None = None

    if not resolved_symbols:
        missing_requirements.append("watchlist symbols")
    if not credentials_ready:
        missing_requirements.append("KIS credentials")
    if not websockets_available:
        missing_requirements.append("python websockets package")

    if credentials_ready:
        try:
            token_manager = KisTokenManager(profile)
            ws_client = KisWebSocketQuoteClient(profile=profile, token_manager=token_manager)
            approval_key_issued = bool(ws_client.issue_approval_key())
        except KisApiError as exc:
            error = str(exc)
            missing_requirements.append("approval key issuance")

    if not missing_requirements:
        try:
            pipeline_result = run_kis_ws_listener_sync(
                project_root=project_root,
                symbols=resolved_symbols,
                watchlist_path=watchlist_path,
                include_trade=True,
                include_orderbook=True,
                max_frames=max_frames,
                max_reconnects=max_reconnects,
            )
        except (KisApiError, ValueError) as exc:
            error = str(exc)

    report_dir = settings.runtime_data_dir / "reports" / "kis-ws"
    report_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = report_dir / "latest-verification.md"
    json_path = report_dir / "latest-verification.json"
    connection_ready = pipeline_result is not None and error is None and not missing_requirements and pipeline_result.frames_received > 0
    market_data_flow_ok = connection_ready and (
        (pipeline_result.raw_trade_events > 0) or (pipeline_result.raw_orderbook_events > 0)
    )
    if connection_ready and not market_data_flow_ok and market_data_expected:
        status_note = "Connected during the regular session, but no trade or orderbook events were parsed."
    ok = connection_ready
    payload = {
        "verified_at": timestamp.isoformat(),
        "ok": ok,
        "trading_mode": settings.trading_mode,
        "endpoint": profile.websocket_tryitout_url,
        "symbols": resolved_symbols,
        "connection_ready": connection_ready,
        "market_data_flow_ok": market_data_flow_ok,
        "market_data_expected": market_data_expected,
        "session_status": session_status,
        "status_note": status_note,
        "dotenv_present": dotenv_present,
        "websockets_available": websockets_available,
        "credentials_ready": credentials_ready,
        "approval_key_issued": approval_key_issued,
        "max_frames": max_frames,
        "frames_received": pipeline_result.frames_received if pipeline_result else 0,
        "control_frames": pipeline_result.control_frames if pipeline_result else 0,
        "raw_trade_events": pipeline_result.raw_trade_events if pipeline_result else 0,
        "raw_orderbook_events": pipeline_result.raw_orderbook_events if pipeline_result else 0,
        "minute_bars_written": pipeline_result.minute_bars_written if pipeline_result else 0,
        "predictions_written": pipeline_result.predictions_written if pipeline_result else 0,
        "signals_written": pipeline_result.signals_written if pipeline_result else 0,
        "orders_written": pipeline_result.orders_written if pipeline_result else 0,
        "missing_requirements": missing_requirements,
        "error": error,
    }
    markdown_lines = [
        "# KIS WebSocket Verification",
        "",
        "## Summary",
        "",
        f"- `ok`: {ok}",
        f"- `trading_mode`: {settings.trading_mode}",
        f"- `endpoint`: {profile.websocket_tryitout_url}",
        f"- `symbols`: {resolved_symbols}",
        f"- `connection_ready`: {connection_ready}",
        f"- `market_data_flow_ok`: {market_data_flow_ok}",
        f"- `market_data_expected`: {market_data_expected}",
        f"- `session_status`: {session_status}",
        f"- `dotenv_present`: {dotenv_present}",
        f"- `websockets_available`: {websockets_available}",
        f"- `credentials_ready`: {credentials_ready}",
        f"- `approval_key_issued`: {approval_key_issued}",
        f"- `frames_received`: {pipeline_result.frames_received if pipeline_result else 0}",
        f"- `control_frames`: {pipeline_result.control_frames if pipeline_result else 0}",
        f"- `raw_trade_events`: {pipeline_result.raw_trade_events if pipeline_result else 0}",
        f"- `raw_orderbook_events`: {pipeline_result.raw_orderbook_events if pipeline_result else 0}",
        f"- `minute_bars_written`: {pipeline_result.minute_bars_written if pipeline_result else 0}",
        f"- `predictions_written`: {pipeline_result.predictions_written if pipeline_result else 0}",
        f"- `signals_written`: {pipeline_result.signals_written if pipeline_result else 0}",
        f"- `orders_written`: {pipeline_result.orders_written if pipeline_result else 0}",
        "",
        "## Missing Requirements",
        "",
    ]
    if missing_requirements:
        markdown_lines.extend(f"- {item}" for item in missing_requirements)
    else:
        markdown_lines.append("- none")
    markdown_lines.extend(["", "## Interpretation", "", f"- {status_note}", "", "## Error", ""])
    markdown_lines.append(f"- {error}" if error else "- none")

    markdown_path.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return KisWsVerificationResult(
        ok=ok,
        trading_mode=settings.trading_mode,
        endpoint=profile.websocket_tryitout_url,
        symbols=resolved_symbols,
        connection_ready=connection_ready,
        market_data_flow_ok=market_data_flow_ok,
        market_data_expected=market_data_expected,
        session_status=session_status,
        status_note=status_note,
        dotenv_present=dotenv_present,
        websockets_available=websockets_available,
        credentials_ready=credentials_ready,
        approval_key_issued=approval_key_issued,
        max_frames=max_frames,
        frames_received=pipeline_result.frames_received if pipeline_result else 0,
        control_frames=pipeline_result.control_frames if pipeline_result else 0,
        raw_trade_events=pipeline_result.raw_trade_events if pipeline_result else 0,
        raw_orderbook_events=pipeline_result.raw_orderbook_events if pipeline_result else 0,
        minute_bars_written=pipeline_result.minute_bars_written if pipeline_result else 0,
        predictions_written=pipeline_result.predictions_written if pipeline_result else 0,
        signals_written=pipeline_result.signals_written if pipeline_result else 0,
        orders_written=pipeline_result.orders_written if pipeline_result else 0,
        missing_requirements=missing_requirements,
        error=error,
        report_markdown_path=markdown_path,
        report_json_path=json_path,
    )
