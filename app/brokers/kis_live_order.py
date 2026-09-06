"""Guarded KIS live order adapter.

This module does not create a KIS client and does not call the network on
import. It wraps an already-created broker client and rechecks live-order
enable flags immediately before submit/cancel delegation.
"""

from __future__ import annotations

from typing import Any


class KisLiveOrderAdapterError(RuntimeError):
    pass


class KisLiveOrderAdapter:
    def __init__(self, client: Any, *, settings: Any, profile_mode: str = "live") -> None:
        self._client = client
        self._settings = settings
        self._profile_mode = profile_mode

    def describe(self) -> dict[str, Any]:
        describe = getattr(self._client, "describe", None)
        base = describe() if callable(describe) else {}
        payload = dict(base) if isinstance(base, dict) else {"delegate": type(self._client).__name__}
        payload["access"] = "live-order-guarded"
        payload["profile_mode"] = self._profile_mode
        return payload

    def submit_cash_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: int,
        order_type: str = "limit",
        limit_price: float = 0.0,
        idempotency_key: str = "",
    ) -> Any:
        self._assert_submit_enabled()
        if order_type.strip().lower() != "limit":
            raise KisLiveOrderAdapterError("KIS live order adapter only supports limit orders")
        return self._client.submit_cash_order(
            symbol=symbol,
            side=side,
            qty=qty,
            order_type="00",
            limit_price=limit_price,
        )

    def cancel_order(
        self,
        *,
        broker_order_no: str,
        broker_branch_no: str = "",
        order_qty: int,
        reason: str = "",
    ) -> Any:
        self._assert_live_profile()
        return self._client.cancel_order(
            broker_order_no=broker_order_no,
            broker_branch_no=broker_branch_no,
            order_qty=order_qty,
        )

    def _assert_submit_enabled(self) -> None:
        self._assert_live_profile()
        if not bool(getattr(self._settings, "allow_live_orders", False)):
            raise KisLiveOrderAdapterError("ALLOW_LIVE_ORDERS must be true before live order delegation")

    def _assert_live_profile(self) -> None:
        trading_mode = str(getattr(self._settings, "trading_mode", "")).strip().lower()
        profile_mode = str(self._profile_mode).strip().lower()
        if trading_mode != "live":
            raise KisLiveOrderAdapterError("TRADING_MODE must be live before live order delegation")
        if profile_mode != "live":
            raise KisLiveOrderAdapterError("KIS live order adapter requires live profile mode")
