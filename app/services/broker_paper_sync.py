"""Synchronize broker paper-order status and fills back into the local virtual book."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
import math
import os
from pathlib import Path
from typing import Any, Callable
import uuid

from app.brokers.kis_auth import KisApiError
from app.config.settings import AppSettings, load_settings
from app.observability.logging import configure_logging
from app.paper_trading.book import PaperPortfolioBook
from app.paper_trading.engine import PaperTradingEngine
from app.services.broker_paper import BrokerPaperMirror, is_kis_rate_limit_error
from app.services.paper_alignment import (
    adjust_snapshot_for_fills_after_snapshot,
    apply_alignment_baseline,
    filter_rows_after_alignment,
)
from app.storage.contracts import BrokerOrderStatusSnapshot, Fill, OrderEvent
from app.storage.runtime_writer import RuntimeWriter
from app.utils.time import now_local


EXPIRED_BROKER_ORDER_STATUSES = {"expired", "expired_partial"}
FINAL_BROKER_ORDER_STATUSES = {"filled", "cancelled", "cancelled_partial", "rejected"} | EXPIRED_BROKER_ORDER_STATUSES
OPEN_BROKER_ORDER_STATUSES = {"submitted", "pending_lookup", "open", "partially_filled"}
BATCH_ORDER_FILL_RATE_LIMIT_RETRY_DELAYS_SECONDS = (10.0, 30.0, 60.0, 120.0)
BATCH_ORDER_FILL_RATE_LIMIT_COOLDOWN_SECONDS = 2.0 * 60.0 * 60.0


@dataclass(slots=True)
class BrokerPaperSyncResult:
    ok: bool
    synced_at: str
    status: str
    total_submissions: int
    matched_orders: int
    updated_orders: int
    applied_fill_events: int
    applied_fill_qty: int
    open_order_count: int
    final_order_count: int
    pending_symbols: list[str]
    report_markdown_path: Path
    report_json_path: Path
    error: str | None = None
    rate_limited_at: str | None = None
    cooldown_active: bool = False
    skipped_broker_call: bool = False
    retry_after_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "ok": self.ok,
            "synced_at": self.synced_at,
            "status": self.status,
            "total_submissions": self.total_submissions,
            "matched_orders": self.matched_orders,
            "updated_orders": self.updated_orders,
            "applied_fill_events": self.applied_fill_events,
            "applied_fill_qty": self.applied_fill_qty,
            "open_order_count": self.open_order_count,
            "final_order_count": self.final_order_count,
            "pending_symbols": self.pending_symbols,
            "report_markdown_path": str(self.report_markdown_path),
            "report_json_path": str(self.report_json_path),
        }
        if self.error:
            payload["error"] = self.error
        if self.rate_limited_at:
            payload["rate_limited_at"] = self.rate_limited_at
        if self.cooldown_active:
            payload["cooldown_active"] = self.cooldown_active
        if self.skipped_broker_call:
            payload["skipped_broker_call"] = self.skipped_broker_call
        if self.retry_after_seconds is not None:
            payload["retry_after_seconds"] = self.retry_after_seconds
        return payload


def _report_paths(runtime_data_dir: Path) -> tuple[Path, Path]:
    report_dir = runtime_data_dir / "reports" / "broker-paper"
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir / "latest-sync.md", report_dir / "latest-sync.json"


def _normalize_order_date(value: str) -> str:
    return str(value or "").replace("-", "").strip()


def _parse_order_date(value: Any) -> date | None:
    normalized = _normalize_order_date(str(value or ""))
    if len(normalized) < 8:
        return None
    try:
        return datetime.strptime(normalized[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _is_prior_day_order(order_date: Any, synced_at: datetime | None) -> bool:
    if synced_at is None:
        return False
    parsed = _parse_order_date(order_date)
    return parsed is not None and parsed < synced_at.date()


def _expire_stale_open_status(
    *,
    status: str,
    order_date: Any,
    synced_at: datetime,
    filled_qty: int,
    remaining_qty: int,
) -> str:
    if status not in OPEN_BROKER_ORDER_STATUSES:
        return status
    if remaining_qty <= 0:
        return status
    if not _is_prior_day_order(order_date, synced_at):
        return status
    return "expired_partial" if filled_qty > 0 else "expired"


def _to_side_text(side_code: str, fallback_side: str = "") -> str:
    normalized = str(side_code or "").strip().lower()
    if normalized in {"02", "buy", "b"}:
        return "buy"
    if normalized in {"01", "sell", "s"}:
        return "sell"
    return fallback_side or normalized or "buy"


def _derive_broker_status(
    *,
    matched: bool,
    order_qty: int,
    filled_qty: int,
    remaining_qty: int,
    reject_qty: int,
    cancel_yn: bool,
    cancel_confirm_qty: int,
    order_date: Any = "",
    synced_at: datetime | None = None,
) -> str:
    if not matched:
        if order_qty > 0 and filled_qty >= order_qty:
            return "filled"
        if remaining_qty <= 0 and order_qty > 0:
            return "filled"
        if remaining_qty > 0 and _is_prior_day_order(order_date, synced_at):
            return "expired_partial" if filled_qty > 0 else "expired"
        return "pending_lookup"
    if reject_qty >= max(order_qty, 1):
        return "rejected"
    if cancel_yn and filled_qty > 0:
        return "cancelled_partial"
    if cancel_yn or cancel_confirm_qty > 0:
        return "cancelled"
    if order_qty > 0 and filled_qty >= order_qty:
        return "filled"
    if remaining_qty > 0 and _is_prior_day_order(order_date, synced_at):
        return "expired_partial" if filled_qty > 0 else "expired"
    if filled_qty > 0:
        return "partially_filled"
    if remaining_qty > 0:
        return "open"
    return "submitted"


def _write_report(markdown_path: Path, json_path: Path, payload: dict[str, Any]) -> None:
    pending_symbols = payload.get("pending_symbols") or []
    lines = [
        "# Broker Paper Sync",
        "",
        "## Summary",
        "",
        f"- `ok`: {payload.get('ok')}",
        f"- `synced_at`: {payload.get('synced_at')}",
        f"- `status`: {payload.get('status')}",
        f"- `total_submissions`: {payload.get('total_submissions')}",
        f"- `matched_orders`: {payload.get('matched_orders')}",
        f"- `updated_orders`: {payload.get('updated_orders')}",
        f"- `applied_fill_events`: {payload.get('applied_fill_events')}",
        f"- `applied_fill_qty`: {payload.get('applied_fill_qty')}",
        f"- `open_order_count`: {payload.get('open_order_count')}",
        f"- `final_order_count`: {payload.get('final_order_count')}",
        "",
        "## Pending Symbols",
        "",
    ]
    if payload.get("error"):
        lines.insert(10, f"- `error`: {payload.get('error')}")
    if payload.get("cooldown_active"):
        lines.insert(11, f"- `cooldown_active`: {payload.get('cooldown_active')}")
        lines.insert(12, f"- `skipped_broker_call`: {payload.get('skipped_broker_call')}")
        lines.insert(13, f"- `retry_after_seconds`: {payload.get('retry_after_seconds')}")
    if pending_symbols:
        lines.extend(f"- `{symbol}`" for symbol in pending_symbols)
    else:
        lines.append("- none")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_report_datetime(value: Any, fallback_tz: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None and fallback_tz is not None:
        return parsed.replace(tzinfo=fallback_tz)
    return parsed


def _load_previous_rate_limit(
    json_path: Path,
    *,
    synced_at: datetime,
    cooldown_seconds: float,
) -> tuple[str, int] | None:
    if cooldown_seconds <= 0 or not json_path.exists():
        return None
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("status") != "rate_limited":
        return None
    rate_limited_at_text = str(payload.get("rate_limited_at") or payload.get("synced_at") or "")
    rate_limited_at = _parse_report_datetime(rate_limited_at_text, synced_at.tzinfo)
    if rate_limited_at is None:
        return None
    elapsed_seconds = (synced_at - rate_limited_at).total_seconds()
    if elapsed_seconds >= cooldown_seconds:
        return None
    retry_after_seconds = max(int(math.ceil(cooldown_seconds - elapsed_seconds)), 0)
    return rate_limited_at_text, retry_after_seconds


class BrokerPaperExecutionSync:
    def __init__(
        self,
        settings: AppSettings,
        *,
        writer: RuntimeWriter | None = None,
        portfolio_book: PaperPortfolioBook | None = None,
        engine: PaperTradingEngine | None = None,
        id_factory: Callable[[str], str] | None = None,
    ) -> None:
        self.settings = settings
        self.writer = writer or RuntimeWriter.from_settings(settings)
        self.portfolio_book = portfolio_book or PaperPortfolioBook(
            initial_cash=settings.strategy.paper_initial_cash,
            max_open_positions=settings.strategy.max_open_positions,
        )
        self.engine = engine or PaperTradingEngine(slippage_bps=settings.strategy.slippage_bps)
        self.id_factory = id_factory
        self.broker_mirror = BrokerPaperMirror(settings)
        timestamp = now_local(self.settings.timezone).strftime("%Y%m%d%H%M%S")
        self._run_namespace = f"{timestamp}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._sequence = 0
        if portfolio_book is None:
            self._restore_portfolio_state()

    def _restore_portfolio_state(self) -> None:
        sqlite_store = self.writer.sqlite_store
        if sqlite_store is None:
            return
        latest_snapshot = sqlite_store.fetch_latest_row("paper_portfolio_snapshots", "event_time")
        position_rows = [dict(row) for row in sqlite_store.fetch_all_rows("paper_positions", "symbol")]
        latest_snapshot_row = dict(latest_snapshot) if latest_snapshot is not None else None
        latest_snapshot_row, position_rows, _ = apply_alignment_baseline(
            latest_snapshot=latest_snapshot_row,
            position_rows=position_rows,
            runtime_data_dir=self.settings.runtime_data_dir,
        )
        open_positions = [row for row in position_rows if int(row.get("qty", 0) or 0) > 0]
        order_rows = filter_rows_after_alignment(
            [dict(row) for row in sqlite_store.fetch_all_rows("paper_orders", "event_time")],
            runtime_data_dir=self.settings.runtime_data_dir,
            time_fields=("event_time",),
        )
        fill_rows = filter_rows_after_alignment(
            [dict(row) for row in sqlite_store.fetch_all_rows("paper_fills", "event_time")],
            runtime_data_dir=self.settings.runtime_data_dir,
            time_fields=("event_time",),
        )
        latest_snapshot_row = adjust_snapshot_for_fills_after_snapshot(
            latest_snapshot_row,
            order_rows=order_rows,
            fill_rows=fill_rows,
            open_positions=open_positions,
        )
        self.portfolio_book.restore_from_runtime(
            latest_snapshot=latest_snapshot_row,
            position_rows=position_rows,
        )

    def _next_id(self, prefix: str) -> str:
        if self.id_factory is not None:
            return self.id_factory(prefix)
        self._sequence += 1
        return f"{prefix}-{self._run_namespace}-{self._sequence:06d}"

    def sync_recent_orders(
        self,
        *,
        lookback_days: int = 3,
        retry_delays_seconds: tuple[float, ...] | None = None,
        rate_limit_cooldown_seconds: float = BATCH_ORDER_FILL_RATE_LIMIT_COOLDOWN_SECONDS,
    ) -> BrokerPaperSyncResult:
        synced_at = now_local(self.settings.timezone)
        markdown_path, json_path = _report_paths(self.settings.runtime_data_dir)

        if not self.broker_mirror.profile.is_configured:
            payload = {
                "ok": False,
                "synced_at": synced_at.isoformat(),
                "status": "broker_not_configured",
                "total_submissions": 0,
                "matched_orders": 0,
                "updated_orders": 0,
                "applied_fill_events": 0,
                "applied_fill_qty": 0,
                "open_order_count": 0,
                "final_order_count": 0,
                "pending_symbols": [],
            }
            _write_report(markdown_path, json_path, payload)
            return BrokerPaperSyncResult(
                report_markdown_path=markdown_path,
                report_json_path=json_path,
                **payload,
            )

        sqlite_store = self.writer.sqlite_store
        if sqlite_store is None:
            payload = {
                "ok": False,
                "synced_at": synced_at.isoformat(),
                "status": "sqlite_unavailable",
                "total_submissions": 0,
                "matched_orders": 0,
                "updated_orders": 0,
                "applied_fill_events": 0,
                "applied_fill_qty": 0,
                "open_order_count": 0,
                "final_order_count": 0,
                "pending_symbols": [],
            }
            _write_report(markdown_path, json_path, payload)
            return BrokerPaperSyncResult(
                report_markdown_path=markdown_path,
                report_json_path=json_path,
                **payload,
            )

        submission_rows = filter_rows_after_alignment(
            [dict(row) for row in sqlite_store.fetch_all_rows("broker_paper_order_submissions", "event_time")],
            runtime_data_dir=self.settings.runtime_data_dir,
            time_fields=("event_time",),
        )
        if not submission_rows:
            payload = {
                "ok": True,
                "synced_at": synced_at.isoformat(),
                "status": "no_submissions",
                "total_submissions": 0,
                "matched_orders": 0,
                "updated_orders": 0,
                "applied_fill_events": 0,
                "applied_fill_qty": 0,
                "open_order_count": 0,
                "final_order_count": 0,
                "pending_symbols": [],
            }
            _write_report(markdown_path, json_path, payload)
            return BrokerPaperSyncResult(
                report_markdown_path=markdown_path,
                report_json_path=json_path,
                **payload,
            )

        paper_orders = {
            str(row["order_id"]): dict(row)
            for row in sqlite_store.fetch_all_rows("paper_orders", "event_time")
        }
        latest_status_by_order = {}
        for row in sqlite_store.fetch_all_rows("broker_paper_order_status_snapshots", "synced_at"):
            latest_status_by_order[str(row["local_order_id"])] = dict(row)

        def build_rate_limited_payload(
            *,
            error: str,
            rate_limited_at: str,
            cooldown_active: bool = False,
            skipped_broker_call: bool = False,
            retry_after_seconds: int | None = None,
        ) -> dict[str, Any]:
            pending_symbols: set[str] = set()
            open_order_count = 0
            final_order_count = 0
            for submission in submission_rows:
                local_order_id = str(submission["local_order_id"])
                paper_order = paper_orders.get(local_order_id, {})
                previous_snapshot = latest_status_by_order.get(local_order_id) or {}
                status = str(previous_snapshot.get("status") or paper_order.get("status") or submission.get("status") or "submitted")
                if previous_snapshot:
                    status = _expire_stale_open_status(
                        status=status,
                        order_date=previous_snapshot.get("order_date"),
                        synced_at=synced_at,
                        filled_qty=int(previous_snapshot.get("filled_qty", 0) or 0),
                        remaining_qty=int(previous_snapshot.get("remaining_qty", 0) or 0),
                    )
                if status in FINAL_BROKER_ORDER_STATUSES:
                    final_order_count += 1
                    continue
                open_order_count += 1
                pending_symbols.add(str(submission.get("symbol") or paper_order.get("symbol") or ""))
            pending_symbols.discard("")
            payload: dict[str, Any] = {
                "ok": False,
                "synced_at": synced_at.isoformat(),
                "status": "rate_limited",
                "error": error,
                "rate_limited_at": rate_limited_at,
                "total_submissions": len(submission_rows),
                "matched_orders": 0,
                "updated_orders": 0,
                "applied_fill_events": 0,
                "applied_fill_qty": 0,
                "open_order_count": open_order_count,
                "final_order_count": final_order_count,
                "pending_symbols": sorted(pending_symbols),
            }
            if cooldown_active:
                payload["cooldown_active"] = True
            if skipped_broker_call:
                payload["skipped_broker_call"] = True
            if retry_after_seconds is not None:
                payload["retry_after_seconds"] = retry_after_seconds
            return payload

        previous_rate_limit = _load_previous_rate_limit(
            json_path,
            synced_at=synced_at,
            cooldown_seconds=rate_limit_cooldown_seconds,
        )
        if previous_rate_limit is not None:
            rate_limited_at, retry_after_seconds = previous_rate_limit
            payload = build_rate_limited_payload(
                error="KIS order-fill query skipped because rate-limit cooldown is active.",
                rate_limited_at=rate_limited_at,
                cooldown_active=True,
                skipped_broker_call=True,
                retry_after_seconds=retry_after_seconds,
            )
            _write_report(markdown_path, json_path, payload)
            return BrokerPaperSyncResult(
                report_markdown_path=markdown_path,
                report_json_path=json_path,
                **payload,
            )

        try:
            broker_rows = self.broker_mirror.fetch_recent_order_fills(
                lookback_days=lookback_days,
                retry_delays_seconds=retry_delays_seconds,
            )
        except KisApiError as exc:
            if not is_kis_rate_limit_error(exc):
                raise
            payload = build_rate_limited_payload(
                error=str(exc),
                rate_limited_at=synced_at.isoformat(),
            )
            _write_report(markdown_path, json_path, payload)
            return BrokerPaperSyncResult(
                report_markdown_path=markdown_path,
                report_json_path=json_path,
                **payload,
            )
        broker_lookup: dict[tuple[str, str, str], Any] = {}
        broker_lookup_fallback: dict[tuple[str, str], Any] = {}
        for row in broker_rows:
            key = (_normalize_order_date(row.order_date), row.broker_branch_no, row.broker_order_no)
            broker_lookup[key] = row
            broker_lookup_fallback[(row.broker_branch_no, row.broker_order_no)] = row

        updated_orders = 0
        matched_orders = 0
        applied_fill_events = 0
        applied_fill_qty = 0
        open_order_count = 0
        final_order_count = 0
        pending_symbols: set[str] = set()

        for submission in submission_rows:
            local_order_id = str(submission["local_order_id"])
            paper_order = paper_orders.get(local_order_id, {})
            previous_snapshot = latest_status_by_order.get(local_order_id) or {}
            previous_applied_fill_qty = int(previous_snapshot.get("applied_fill_qty", 0) or 0)
            previous_status = str(previous_snapshot.get("status") or "")
            order_date_key = _normalize_order_date(str(submission.get("event_time", ""))[:10])
            broker_row = broker_lookup.get(
                (
                    order_date_key,
                    str(submission.get("broker_branch_no") or ""),
                    str(submission.get("broker_order_no") or ""),
                )
            )
            if broker_row is None:
                broker_row = broker_lookup_fallback.get(
                    (
                        str(submission.get("broker_branch_no") or ""),
                        str(submission.get("broker_order_no") or ""),
                    )
                )

            matched = broker_row is not None
            if matched:
                matched_orders += 1
            side = _to_side_text(
                broker_row.side if broker_row is not None else str(submission.get("side") or paper_order.get("side") or ""),
                fallback_side=str(submission.get("side") or paper_order.get("side") or "buy"),
            )
            order_qty = int((broker_row.order_qty if broker_row is not None else previous_snapshot.get("order_qty") or submission.get("qty")) or 0)
            filled_qty = int(
                (
                    broker_row.filled_qty
                    if broker_row is not None
                    else previous_applied_fill_qty or previous_snapshot.get("filled_qty") or 0
                )
                or 0
            )
            remaining_qty = int(
                (
                    broker_row.remaining_qty
                    if broker_row is not None
                    else max(order_qty - filled_qty, 0)
                )
                or 0
            )
            avg_fill_price = float(
                (
                    broker_row.avg_fill_price
                    if broker_row is not None
                    else previous_snapshot.get("avg_fill_price") or paper_order.get("limit_price") or 0.0
                )
                or 0.0
            )
            reject_qty = int((broker_row.reject_qty if broker_row is not None else previous_snapshot.get("reject_qty") or 0) or 0)
            cancel_confirm_qty = int(
                (broker_row.cancel_confirm_qty if broker_row is not None else previous_snapshot.get("cancel_confirm_qty") or 0)
                or 0
            )
            cancel_yn = bool(broker_row.cancel_yn) if broker_row is not None else bool(previous_snapshot.get("cancel_yn", False))
            if broker_row is None and previous_status in FINAL_BROKER_ORDER_STATUSES:
                status = previous_status
            else:
                status = _derive_broker_status(
                    matched=matched,
                    order_qty=order_qty,
                    filled_qty=filled_qty,
                    remaining_qty=remaining_qty,
                    reject_qty=reject_qty,
                    cancel_yn=cancel_yn,
                    cancel_confirm_qty=cancel_confirm_qty,
                    order_date=(broker_row.order_date if broker_row is not None else previous_snapshot.get("order_date") or order_date_key),
                    synced_at=synced_at,
                )
            if status in OPEN_BROKER_ORDER_STATUSES:
                open_order_count += 1
                pending_symbols.add(str(submission.get("symbol") or paper_order.get("symbol") or ""))
            if status in FINAL_BROKER_ORDER_STATUSES:
                final_order_count += 1

            delta_fill_qty = max(filled_qty - previous_applied_fill_qty, 0)
            next_applied_fill_qty = previous_applied_fill_qty

            sqlite_store.update_paper_order_status(local_order_id, status)

            if delta_fill_qty > 0:
                fill_time = synced_at
                fill_price = avg_fill_price or float(paper_order.get("limit_price", 0.0) or 0.0)
                commission = fill_price * delta_fill_qty * self.engine.commission_rate
                tax = fill_price * delta_fill_qty * self.engine.tax_rate
                fill = Fill(
                    fill_id=self._next_id("fill-broker-sync"),
                    order_id=local_order_id,
                    event_time=fill_time,
                    fill_price=fill_price,
                    fill_qty=delta_fill_qty,
                    commission=commission,
                    tax=tax,
                )
                fill_event = OrderEvent(
                    order_event_id=self._next_id("order-event-broker-sync"),
                    order_id=local_order_id,
                    event_time=fill_time,
                    event_type="broker_fill_sync",
                    detail=f"filled_qty={delta_fill_qty};avg_fill_price={fill_price:.2f};broker_order_no={submission.get('broker_order_no')}",
                )
                self.writer.write_fill(fill)
                self.writer.write_order_event(fill_event)
                symbol = str(submission.get("symbol") or paper_order.get("symbol") or "")
                if side == "buy":
                    self.portfolio_book.apply_buy_fill(symbol=symbol, fill=fill, fill_price=fill_price)
                else:
                    self.portfolio_book.close_position(symbol=symbol, fill=fill, fill_price=fill_price)
                self.writer.write_paper_position(self.portfolio_book.to_position_record(symbol, updated_at=fill.event_time))
                self.writer.write_portfolio_snapshot(
                    self.portfolio_book.to_portfolio_snapshot(
                        snapshot_id=self._next_id("portfolio-broker-sync"),
                        event_time=fill.event_time,
                    )
                )
                next_applied_fill_qty = filled_qty
                applied_fill_events += 1
                applied_fill_qty += delta_fill_qty

            previous_status = str(previous_snapshot.get("status") or "")
            if previous_status != status or delta_fill_qty > 0:
                updated_orders += 1
                status_event = OrderEvent(
                    order_event_id=self._next_id("order-event-broker-status"),
                    order_id=local_order_id,
                    event_time=synced_at,
                    event_type="broker_status_sync",
                    detail=f"status={status};filled_qty={filled_qty};remaining_qty={remaining_qty};matched={matched}",
                )
                self.writer.write_order_event(status_event)

            snapshot = BrokerOrderStatusSnapshot(
                sync_id=self._next_id("broker-sync"),
                local_order_id=local_order_id,
                broker_mode=str(submission.get("broker_mode") or "paper"),
                symbol=str(submission.get("symbol") or paper_order.get("symbol") or ""),
                synced_at=synced_at,
                order_date=(broker_row.order_date if broker_row is not None else order_date_key),
                side=side,
                order_qty=order_qty,
                filled_qty=filled_qty,
                remaining_qty=remaining_qty,
                avg_fill_price=avg_fill_price,
                status=status,
                broker_order_no=str(submission.get("broker_order_no") or ""),
                broker_branch_no=str(submission.get("broker_branch_no") or ""),
                reject_qty=reject_qty,
                cancel_confirm_qty=cancel_confirm_qty,
                cancel_yn=cancel_yn,
                matched=matched,
                applied_fill_qty=next_applied_fill_qty,
                detail=(broker_row.raw_output if broker_row is not None else {"status": "pending_lookup"}),
            )
            self.writer.write_broker_order_status_snapshot(snapshot)
            latest_status_by_order[local_order_id] = snapshot.to_record()

        payload = {
            "ok": True,
            "synced_at": synced_at.isoformat(),
            "status": "ok",
            "total_submissions": len(submission_rows),
            "matched_orders": matched_orders,
            "updated_orders": updated_orders,
            "applied_fill_events": applied_fill_events,
            "applied_fill_qty": applied_fill_qty,
            "open_order_count": open_order_count,
            "final_order_count": final_order_count,
            "pending_symbols": sorted(symbol for symbol in pending_symbols if symbol),
        }
        _write_report(markdown_path, json_path, payload)
        return BrokerPaperSyncResult(
            report_markdown_path=markdown_path,
            report_json_path=json_path,
            **payload,
        )


def sync_broker_paper_orders(
    project_root: Path,
    *,
    lookback_days: int = 3,
    retry_delays_seconds: tuple[float, ...] | None = None,
    rate_limit_cooldown_seconds: float = BATCH_ORDER_FILL_RATE_LIMIT_COOLDOWN_SECONDS,
) -> BrokerPaperSyncResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    service = BrokerPaperExecutionSync(settings)
    effective_retry_delays = (
        BATCH_ORDER_FILL_RATE_LIMIT_RETRY_DELAYS_SECONDS
        if retry_delays_seconds is None
        else retry_delays_seconds
    )
    return service.sync_recent_orders(
        lookback_days=lookback_days,
        retry_delays_seconds=effective_retry_delays,
        rate_limit_cooldown_seconds=rate_limit_cooldown_seconds,
    )
