"""KIS WebSocket quote helpers and optional client."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
import logging
from typing import Any

from app.brokers.kis_auth import KisApiError, KisAuthProfile, KisTokenManager


DOMESTIC_TRADE_TR_ID = "H0STCNT0"
DOMESTIC_ORDERBOOK_TR_ID = "H0STASP0"

DOMESTIC_TRADE_COLUMNS = [
    "MKSC_SHRN_ISCD",
    "STCK_CNTG_HOUR",
    "STCK_PRPR",
    "PRDY_VRSS_SIGN",
    "PRDY_VRSS",
    "PRDY_CTRT",
    "WGHN_AVRG_STCK_PRC",
    "STCK_OPRC",
    "STCK_HGPR",
    "STCK_LWPR",
    "ASKP1",
    "BIDP1",
    "CNTG_VOL",
    "ACML_VOL",
    "ACML_TR_PBMN",
    "SELN_CNTG_CSNU",
    "SHNU_CNTG_CSNU",
    "NTBY_CNTG_CSNU",
    "CTTR",
    "SELN_CNTG_SMTN",
    "SHNU_CNTG_SMTN",
    "CCLD_DVSN",
    "SHNU_RATE",
    "PRDY_VOL_VRSS_ACML_VOL_RATE",
    "OPRC_HOUR",
    "OPRC_VRSS_PRPR_SIGN",
    "OPRC_VRSS_PRPR",
    "HGPR_HOUR",
    "HGPR_VRSS_PRPR_SIGN",
    "HGPR_VRSS_PRPR",
    "LWPR_HOUR",
    "LWPR_VRSS_PRPR_SIGN",
    "LWPR_VRSS_PRPR",
    "BSOP_DATE",
    "NEW_MKOP_CLS_CODE",
    "TRHT_YN",
    "ASKP_RSQN1",
    "BIDP_RSQN1",
    "TOTAL_ASKP_RSQN",
    "TOTAL_BIDP_RSQN",
    "VOL_TNRT",
    "PRDY_SMNS_HOUR_ACML_VOL",
    "PRDY_SMNS_HOUR_ACML_VOL_RATE",
    "HOUR_CLS_CODE",
    "MRKT_TRTM_CLS_CODE",
    "VI_STND_PRC",
]

DOMESTIC_ORDERBOOK_COLUMNS = [
    "MKSC_SHRN_ISCD",
    "BSOP_HOUR",
    "HOUR_CLS_CODE",
    "ASKP1",
    "ASKP2",
    "ASKP3",
    "ASKP4",
    "ASKP5",
    "ASKP6",
    "ASKP7",
    "ASKP8",
    "ASKP9",
    "ASKP10",
    "BIDP1",
    "BIDP2",
    "BIDP3",
    "BIDP4",
    "BIDP5",
    "BIDP6",
    "BIDP7",
    "BIDP8",
    "BIDP9",
    "BIDP10",
    "ASKP_RSQN1",
    "ASKP_RSQN2",
    "ASKP_RSQN3",
    "ASKP_RSQN4",
    "ASKP_RSQN5",
    "ASKP_RSQN6",
    "ASKP_RSQN7",
    "ASKP_RSQN8",
    "ASKP_RSQN9",
    "ASKP_RSQN10",
    "BIDP_RSQN1",
    "BIDP_RSQN2",
    "BIDP_RSQN3",
    "BIDP_RSQN4",
    "BIDP_RSQN5",
    "BIDP_RSQN6",
    "BIDP_RSQN7",
    "BIDP_RSQN8",
    "BIDP_RSQN9",
    "BIDP_RSQN10",
    "TOTAL_ASKP_RSQN",
    "TOTAL_BIDP_RSQN",
    "OVTM_TOTAL_ASKP_RSQN",
    "OVTM_TOTAL_BIDP_RSQN",
    "ANTC_CNPR",
    "ANTC_CNQN",
    "ANTC_VOL",
    "ANTC_CNTG_VRSS",
    "ANTC_CNTG_VRSS_SIGN",
    "ANTC_CNTG_PRDY_CTRT",
    "ACML_VOL",
    "TOTAL_ASKP_RSQN_ICDC",
    "TOTAL_BIDP_RSQN_ICDC",
    "OVTM_TOTAL_ASKP_ICDC",
    "OVTM_TOTAL_BIDP_ICDC",
    "STCK_DEAL_CLS_CODE",
]


try:
    import websockets  # type: ignore
except ImportError:  # pragma: no cover - optional runtime dependency
    websockets = None


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class KisWebSocketSubscription:
    tr_id: str
    tr_key: str
    tr_type: str = "1"

    def to_message(self, approval_key: str, customer_type: str = "P") -> dict[str, Any]:
        return {
            "header": {
                "approval_key": approval_key,
                "custtype": customer_type,
                "tr_type": self.tr_type,
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": self.tr_id,
                    "tr_key": self.tr_key,
                }
            },
        }


@dataclass(slots=True)
class KisWebSocketQuoteClient:
    profile: KisAuthProfile
    token_manager: KisTokenManager
    reconnect_backoff_seconds: int = 5

    def describe(self) -> dict[str, str | int]:
        return {
            "transport": "websocket",
            "endpoint": self.profile.websocket_tryitout_url,
            "reconnect_backoff_seconds": self.reconnect_backoff_seconds,
            "status": "active",
        }

    def issue_approval_key(self) -> str:
        return self.token_manager.issue_approval_key()

    def build_domestic_trade_subscription(self, symbol: str) -> KisWebSocketSubscription:
        return KisWebSocketSubscription(tr_id=DOMESTIC_TRADE_TR_ID, tr_key=symbol)

    def build_domestic_orderbook_subscription(self, symbol: str) -> KisWebSocketSubscription:
        return KisWebSocketSubscription(tr_id=DOMESTIC_ORDERBOOK_TR_ID, tr_key=symbol)

    def build_subscriptions(
        self,
        symbols: list[str],
        include_trade: bool = True,
        include_orderbook: bool = True,
    ) -> list[KisWebSocketSubscription]:
        subscriptions: list[KisWebSocketSubscription] = []
        for symbol in symbols:
            if include_trade:
                subscriptions.append(self.build_domestic_trade_subscription(symbol))
            if include_orderbook:
                subscriptions.append(self.build_domestic_orderbook_subscription(symbol))
        return subscriptions

    async def subscribe(self, symbol: str, channel: str = "trade") -> list[str]:
        if websockets is None:
            raise KisApiError("WebSocket support requires the optional 'websockets' package.")

        approval_key = self.issue_approval_key()
        subscription = (
            self.build_domestic_trade_subscription(symbol)
            if channel == "trade"
            else self.build_domestic_orderbook_subscription(symbol)
        )
        request_message = subscription.to_message(
            approval_key=approval_key,
            customer_type=self.profile.customer_type,
        )

        frames: list[str] = []
        async with websockets.connect(self.profile.websocket_tryitout_url) as connection:  # type: ignore[union-attr]
            await connection.send(json.dumps(request_message, ensure_ascii=False))
            for _ in range(2):
                frames.append(await connection.recv())
        return frames

    async def listen(
        self,
        symbols: list[str],
        include_trade: bool = True,
        include_orderbook: bool = True,
        max_frames: int = 50,
        max_reconnects: int = 2,
    ):
        if websockets is None:
            raise KisApiError("WebSocket support requires the optional 'websockets' package.")
        if not symbols:
            raise KisApiError("At least one symbol is required for WebSocket listening.")
        subscriptions = self.build_subscriptions(
            symbols=symbols,
            include_trade=include_trade,
            include_orderbook=include_orderbook,
        )
        frames_seen = 0
        reconnect_attempt = 0
        unbounded = max_frames <= 0

        while unbounded or frames_seen < max_frames:
            approval_key = self.issue_approval_key()
            try:
                async with websockets.connect(  # type: ignore[union-attr]
                    self.profile.websocket_tryitout_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                ) as connection:
                    LOGGER.info(
                        "Connected to KIS WebSocket endpoint=%s symbols=%s",
                        self.profile.websocket_tryitout_url,
                        ",".join(symbols),
                    )
                    for subscription in subscriptions:
                        await connection.send(
                            json.dumps(
                                subscription.to_message(
                                    approval_key=approval_key,
                                    customer_type=self.profile.customer_type,
                                ),
                                ensure_ascii=False,
                            )
                        )
                    while unbounded or frames_seen < max_frames:
                        frame = await connection.recv()
                        frames_seen += 1
                        yield frame
                break
            except Exception as exc:
                if reconnect_attempt >= max_reconnects:
                    raise KisApiError(
                        f"KIS WebSocket listen failed after {reconnect_attempt} reconnects: {exc}"
                    ) from exc
                reconnect_attempt += 1
                LOGGER.warning(
                    "KIS WebSocket disconnected; reconnecting in %ss (attempt %s/%s): %s",
                    self.reconnect_backoff_seconds,
                    reconnect_attempt,
                    max_reconnects,
                    exc,
                )
                await asyncio.sleep(self.reconnect_backoff_seconds)


def parse_kis_ws_frame(frame: str) -> dict[str, Any]:
    """Return a lightweight parsed representation of a KIS WebSocket frame."""

    if frame.startswith("{"):
        return json.loads(frame)
    parts = frame.split("|")
    parsed: dict[str, Any] = {
        "raw": frame,
        "parts": parts,
        "frame_type": "pipe-delimited",
    }
    if len(parts) < 4:
        return parsed

    tr_id = parts[1]
    record_count = int(parts[2]) if parts[2].isdigit() else 1
    payload = parts[3]
    columns = _columns_for_tr_id(tr_id)
    tokens = payload.split("^")

    parsed.update(
        {
            "message_kind": parts[0],
            "tr_id": tr_id,
            "record_count": record_count,
            "records": _build_records(tokens=tokens, columns=columns, record_count=record_count),
        }
    )
    return parsed


def _columns_for_tr_id(tr_id: str) -> list[str]:
    if tr_id == DOMESTIC_TRADE_TR_ID:
        return DOMESTIC_TRADE_COLUMNS
    if tr_id == DOMESTIC_ORDERBOOK_TR_ID:
        return DOMESTIC_ORDERBOOK_COLUMNS
    return []


def _build_records(tokens: list[str], columns: list[str], record_count: int) -> list[dict[str, str]]:
    if not columns:
        return [{"value": token} for token in tokens if token]
    chunk_size = len(columns)
    records: list[dict[str, str]] = []
    for index in range(record_count):
        start = index * chunk_size
        chunk = tokens[start : start + chunk_size]
        if not chunk:
            continue
        mapped = {column: chunk[offset] if offset < len(chunk) else "" for offset, column in enumerate(columns)}
        records.append(mapped)
    return records
