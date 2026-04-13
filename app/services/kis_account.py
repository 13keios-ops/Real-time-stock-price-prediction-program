"""KIS account snapshot refresh and report helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from app.brokers.kis_auth import KisApiError, KisTokenManager, get_active_kis_profile
from app.brokers.kis_quote_rest import KisAccountBalanceSnapshot, KisRestQuoteClient
from app.config.settings import load_settings
from app.observability.logging import configure_logging
from app.utils.time import now_local


@dataclass(slots=True)
class KisAccountReportResult:
    ok: bool
    trading_mode: str
    fetched_at: str
    cache_used: bool
    cache_age_seconds: int | None
    error: str | None
    source: str
    account_snapshot: dict[str, Any] | None
    report_markdown_path: Path
    report_json_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "trading_mode": self.trading_mode,
            "fetched_at": self.fetched_at,
            "cache_used": self.cache_used,
            "cache_age_seconds": self.cache_age_seconds,
            "error": self.error,
            "source": self.source,
            "account_snapshot": self.account_snapshot,
            "report_markdown_path": str(self.report_markdown_path),
            "report_json_path": str(self.report_json_path),
        }


def _report_paths(runtime_data_dir: Path) -> tuple[Path, Path]:
    report_dir = runtime_data_dir / "reports" / "kis-account"
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir / "latest-account.md", report_dir / "latest-account.json"


def _load_cached_payload(json_path: Path) -> dict[str, Any] | None:
    if not json_path.exists():
        return None
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _cache_age_seconds(payload: dict[str, Any] | None, timezone_name: str) -> int | None:
    if not payload:
        return None
    fetched_at = payload.get("fetched_at")
    if not fetched_at:
        return None
    try:
        snapshot_time = datetime.fromisoformat(str(fetched_at))
    except ValueError:
        return None
    return max(int((now_local(timezone_name) - snapshot_time).total_seconds()), 0)


def _write_report(markdown_path: Path, json_path: Path, payload: dict[str, Any]) -> None:
    account_snapshot = payload.get("account_snapshot") or {}
    positions = account_snapshot.get("positions") or []
    markdown_lines = [
        "# KIS Account Balance",
        "",
        "## Summary",
        "",
        f"- `ok`: {payload.get('ok')}",
        f"- `trading_mode`: {payload.get('trading_mode')}",
        f"- `source`: {payload.get('source')}",
        f"- `fetched_at`: {payload.get('fetched_at')}",
        f"- `cache_used`: {payload.get('cache_used')}",
        f"- `cache_age_seconds`: {payload.get('cache_age_seconds')}",
        f"- `error`: {payload.get('error') or 'none'}",
        "",
        "## Broker Account Snapshot",
        "",
    ]
    if account_snapshot:
        markdown_lines.extend(
            [
                f"- `account_no_masked`: {account_snapshot.get('account_no_masked')}",
                f"- `cash_balance`: {account_snapshot.get('cash_balance')}",
                f"- `stock_evaluation_amount`: {account_snapshot.get('stock_evaluation_amount')}",
                f"- `total_evaluation_amount`: {account_snapshot.get('total_evaluation_amount')}",
                f"- `total_purchase_amount`: {account_snapshot.get('total_purchase_amount')}",
                f"- `total_profit_loss_amount`: {account_snapshot.get('total_profit_loss_amount')}",
                f"- `total_asset_amount`: {account_snapshot.get('total_asset_amount')}",
                f"- `position_row_count`: {account_snapshot.get('position_row_count')}",
            ]
        )
    else:
        markdown_lines.append("- unavailable")
    markdown_lines.extend(["", "## Positions", ""])
    if positions:
        for position in positions:
            markdown_lines.append(
                f"- `{position.get('symbol')}` / {_safe_text(position.get('name'))} / qty={position.get('holding_qty')} / eval={position.get('evaluation_amount')}"
            )
    else:
        markdown_lines.append("- none")
    markdown_path.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_text(value: Any) -> str:
    return str(value) if value is not None else "-"


def _snapshot_to_dict(snapshot: KisAccountBalanceSnapshot) -> dict[str, Any]:
    payload = asdict(snapshot)
    payload["positions"] = [asdict(position) for position in snapshot.positions]
    return payload


def refresh_kis_account_report(
    project_root: Path,
    *,
    force_refresh: bool = False,
    max_age_seconds: int = 60,
) -> KisAccountReportResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    markdown_path, json_path = _report_paths(settings.runtime_data_dir)
    cached_payload = _load_cached_payload(json_path)
    age_seconds = _cache_age_seconds(cached_payload, settings.timezone)

    if not force_refresh and cached_payload is not None and age_seconds is not None and age_seconds <= max_age_seconds:
        return KisAccountReportResult(
            ok=bool(cached_payload.get("ok")),
            trading_mode=str(cached_payload.get("trading_mode", settings.trading_mode)),
            fetched_at=str(cached_payload.get("fetched_at")),
            cache_used=True,
            cache_age_seconds=age_seconds,
            error=cached_payload.get("error"),
            source=str(cached_payload.get("source", "kis-broker")),
            account_snapshot=cached_payload.get("account_snapshot"),
            report_markdown_path=markdown_path,
            report_json_path=json_path,
        )

    profile = get_active_kis_profile(settings)
    fetched_at = now_local(settings.timezone).isoformat()

    if not profile.is_configured:
        payload = {
            "ok": False,
            "trading_mode": settings.trading_mode,
            "fetched_at": fetched_at,
            "cache_used": False,
            "cache_age_seconds": None,
            "error": "KIS account credentials are not fully configured.",
            "source": "kis-broker",
            "account_snapshot": None,
        }
        _write_report(markdown_path, json_path, payload)
        return KisAccountReportResult(
            ok=False,
            trading_mode=settings.trading_mode,
            fetched_at=fetched_at,
            cache_used=False,
            cache_age_seconds=None,
            error=str(payload["error"]),
            source="kis-broker",
            account_snapshot=None,
            report_markdown_path=markdown_path,
            report_json_path=json_path,
        )

    try:
        client = KisRestQuoteClient(profile=profile, token_manager=KisTokenManager(profile))
        snapshot = client.get_account_balance()
        payload = {
            "ok": True,
            "trading_mode": settings.trading_mode,
            "fetched_at": fetched_at,
            "cache_used": False,
            "cache_age_seconds": 0,
            "error": None,
            "source": "kis-broker",
            "account_snapshot": _snapshot_to_dict(snapshot),
        }
        _write_report(markdown_path, json_path, payload)
        return KisAccountReportResult(
            ok=True,
            trading_mode=settings.trading_mode,
            fetched_at=fetched_at,
            cache_used=False,
            cache_age_seconds=0,
            error=None,
            source="kis-broker",
            account_snapshot=payload["account_snapshot"],
            report_markdown_path=markdown_path,
            report_json_path=json_path,
        )
    except KisApiError as exc:
        error = str(exc)
        if cached_payload:
            cached_payload["error"] = error
            cached_payload["cache_used"] = True
            cached_payload["cache_age_seconds"] = _cache_age_seconds(cached_payload, settings.timezone)
            _write_report(markdown_path, json_path, cached_payload)
            return KisAccountReportResult(
                ok=bool(cached_payload.get("ok")),
                trading_mode=str(cached_payload.get("trading_mode", settings.trading_mode)),
                fetched_at=str(cached_payload.get("fetched_at")),
                cache_used=True,
                cache_age_seconds=cached_payload.get("cache_age_seconds"),
                error=error,
                source=str(cached_payload.get("source", "kis-broker")),
                account_snapshot=cached_payload.get("account_snapshot"),
                report_markdown_path=markdown_path,
                report_json_path=json_path,
            )
        payload = {
            "ok": False,
            "trading_mode": settings.trading_mode,
            "fetched_at": fetched_at,
            "cache_used": False,
            "cache_age_seconds": None,
            "error": error,
            "source": "kis-broker",
            "account_snapshot": None,
        }
        _write_report(markdown_path, json_path, payload)
        return KisAccountReportResult(
            ok=False,
            trading_mode=settings.trading_mode,
            fetched_at=fetched_at,
            cache_used=False,
            cache_age_seconds=None,
            error=error,
            source="kis-broker",
            account_snapshot=None,
            report_markdown_path=markdown_path,
            report_json_path=json_path,
        )
