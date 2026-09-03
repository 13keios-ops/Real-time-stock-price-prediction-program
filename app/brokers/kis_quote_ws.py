"""KIS WebSocket quote helpers and optional client."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, Callable

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


def _now_local() -> datetime:
    return datetime.now().astimezone()


def _reconnect_delay_seconds(base_seconds: int, consecutive_reconnects: int, maximum_seconds: int) -> int:
    """Return a bounded exponential delay for consecutive connection failures."""
    base = max(int(base_seconds), 1)
    maximum = max(int(maximum_seconds), base)
    exponent = min(max(int(consecutive_reconnects) - 1, 0), 8)
    return min(base * (2**exponent), maximum)


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


@dataclass(frozen=True, slots=True)
class KisWebSocketReconnectSnapshot:
    state: str
    observed_at: datetime
    cumulative_reconnects: int
    consecutive_reconnects: int
    frames_seen_total: int
    frames_since_connect: int
    stable_connection_seen: bool
    reconnect_storm: bool
    last_reconnect_at: datetime | None = None
    last_stable_at: datetime | None = None
    storm_active_since: datetime | None = None
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "observed_at": self.observed_at.isoformat(),
            "cumulative_reconnects": self.cumulative_reconnects,
            "consecutive_reconnects": self.consecutive_reconnects,
            "frames_seen_total": self.frames_seen_total,
            "frames_since_connect": self.frames_since_connect,
            "stable_connection_seen": self.stable_connection_seen,
            "reconnect_storm": self.reconnect_storm,
            "last_reconnect_at": _datetime_iso_or_none(self.last_reconnect_at),
            "last_stable_at": _datetime_iso_or_none(self.last_stable_at),
            "storm_active_since": _datetime_iso_or_none(self.storm_active_since),
            "last_error": self.last_error,
        }



@dataclass(slots=True)
class KisWebSocketReconnectMetrics:
    stable_frame_reset_threshold: int = 5
    reconnect_storm_threshold: int = 3
    cumulative_reconnects: int = 0
    consecutive_reconnects: int = 0
    frames_seen_total: int = 0
    frames_since_connect: int = 0
    stable_connection_seen: bool = False
    last_reconnect_at: datetime | None = None
    last_stable_at: datetime | None = None
    storm_active_since: datetime | None = None
    last_error: str = ""
    clock: Callable[[], datetime] = _now_local

    def record_connected(self) -> KisWebSocketReconnectSnapshot:
        observed_at = self.clock()
        self.frames_since_connect = 0
        self.stable_connection_seen = False
        return self.snapshot("connected", observed_at=observed_at)

    def record_frame(self) -> KisWebSocketReconnectSnapshot | None:
        observed_at = self.clock()
        self.frames_seen_total += 1
        self.frames_since_connect += 1
        threshold = max(int(self.stable_frame_reset_threshold), 1)
        if not self.stable_connection_seen and self.frames_since_connect >= threshold:
            self.stable_connection_seen = True
            self.consecutive_reconnects = 0
            self.last_stable_at = observed_at
            self.storm_active_since = None
            return self.snapshot("stable", observed_at=observed_at)
        return None

    def record_disconnected(self, error: Exception | str) -> KisWebSocketReconnectSnapshot:
        observed_at = self.clock()
        self.cumulative_reconnects += 1
        self.consecutive_reconnects += 1
        self.last_reconnect_at = observed_at
        self.last_error = str(error)
        if _is_reconnect_storm(self.consecutive_reconnects, threshold=self.reconnect_storm_threshold):
            self.storm_active_since = self.storm_active_since or observed_at
        else:
            self.storm_active_since = None
        return self.snapshot("disconnected", observed_at=observed_at)

    def snapshot(self, state: str, *, observed_at: datetime | None = None) -> KisWebSocketReconnectSnapshot:
        return KisWebSocketReconnectSnapshot(
            state=state,
            observed_at=observed_at or self.clock(),
            cumulative_reconnects=self.cumulative_reconnects,
            consecutive_reconnects=self.consecutive_reconnects,
            frames_seen_total=self.frames_seen_total,
            frames_since_connect=self.frames_since_connect,
            stable_connection_seen=self.stable_connection_seen,
            reconnect_storm=_is_reconnect_storm(
                self.consecutive_reconnects,
                threshold=self.reconnect_storm_threshold,
            ),
            last_reconnect_at=self.last_reconnect_at,
            last_stable_at=self.last_stable_at,
            storm_active_since=self.storm_active_since,
            last_error=self.last_error,
        )


@dataclass(slots=True)
class KisWebSocketQuoteClient:
    profile: KisAuthProfile
    token_manager: KisTokenManager
    reconnect_backoff_seconds: int = 5
    max_reconnect_backoff_seconds: int = 60
    frame_timeout_seconds: int = 30
    subscription_delay_seconds: float = 0.1
    stable_frame_reset_threshold: int = 5
    reconnect_storm_threshold: int = 3

    def describe(self) -> dict[str, str | int]:
        return {
            "transport": "websocket",
            "endpoint": self.profile.websocket_tryitout_url,
            "reconnect_backoff_seconds": self.reconnect_backoff_seconds,
            "max_reconnect_backoff_seconds": self.max_reconnect_backoff_seconds,
            "frame_timeout_seconds": self.frame_timeout_seconds,
            "stable_frame_reset_threshold": self.stable_frame_reset_threshold,
            "reconnect_storm_threshold": self.reconnect_storm_threshold,
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

    @staticmethod
    def _connection_kwargs() -> dict[str, Any]:
        return {
            "ping_interval": None,
            "ping_timeout": None,
            "close_timeout": 10,
            "open_timeout": 15,
        }

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
        async with websockets.connect(  # type: ignore[union-attr]
            self.profile.websocket_tryitout_url,
            **self._connection_kwargs(),
        ) as connection:
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
        metrics_callback: Callable[[KisWebSocketReconnectSnapshot], None] | None = None,
    ):
        """Yield raw WebSocket frames and optionally emit lightweight reconnect snapshots.

        ``metrics_callback`` is called synchronously on connect, stable, and
        disconnect events. Keep it limited to in-memory updates or enqueue work
        for another worker; database, file, or network I/O here can delay quote
        processing. Callback exceptions are logged and ignored so observability
        failures do not stop the stream.
        """
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
        metrics = KisWebSocketReconnectMetrics(
            stable_frame_reset_threshold=self.stable_frame_reset_threshold,
            reconnect_storm_threshold=self.reconnect_storm_threshold,
        )
        unbounded = max_frames <= 0

        while unbounded or frames_seen < max_frames:
            try:
                # Approval-key issuance is part of connection establishment. If KIS
                # drops this REST call, keep it on the same bounded retry path as
                # a WebSocket connect failure instead of terminating the listener.
                approval_key = self.issue_approval_key()
                async with websockets.connect(  # type: ignore[union-attr]
                    self.profile.websocket_tryitout_url,
                    **self._connection_kwargs(),
                ) as connection:
                    LOGGER.info(
                        "Connected to KIS WebSocket endpoint=%s symbols=%s subscriptions=%s",
                        self.profile.websocket_tryitout_url,
                        ",".join(symbols),
                        len(subscriptions),
                    )
                    _emit_reconnect_snapshot(metrics_callback, metrics.record_connected())
                    for index, subscription in enumerate(subscriptions):
                        await connection.send(
                            json.dumps(
                                subscription.to_message(
                                    approval_key=approval_key,
                                    customer_type=self.profile.customer_type,
                                ),
                                ensure_ascii=False,
                            )
                        )
                        if self.subscription_delay_seconds > 0 and index < len(subscriptions) - 1:
                            await asyncio.sleep(self.subscription_delay_seconds)
                    restoring_subscriptions = metrics.cumulative_reconnects > 0
                    if restoring_subscriptions:
                        LOGGER.info(
                            (
                                "KIS WebSocket subscriptions restored "
                                "symbols=%s subscriptions=%s cumulative_reconnects=%s"
                            ),
                            len(symbols),
                            len(subscriptions),
                            metrics.cumulative_reconnects,
                        )
                    else:
                        LOGGER.info(
                            "KIS WebSocket subscriptions established symbols=%s subscriptions=%s",
                            len(symbols),
                            len(subscriptions),
                        )
                    first_frame_after_subscription = True
                    while unbounded or frames_seen < max_frames:
                        try:
                            frame = await asyncio.wait_for(
                                connection.recv(),
                                timeout=self.frame_timeout_seconds,
                            )
                        except asyncio.TimeoutError as exc:
                            message = (
                                "KIS WebSocket produced no frames for "
                                f"{self.frame_timeout_seconds}s after subscription."
                            )
                            raise KisApiError(message) from exc
                        frames_seen += 1
                        if first_frame_after_subscription:
                            if restoring_subscriptions:
                                LOGGER.info(
                                    (
                                        "KIS WebSocket first frame received after subscription restore "
                                        "frames_seen=%s cumulative_reconnects=%s"
                                    ),
                                    frames_seen,
                                    metrics.cumulative_reconnects,
                                )
                            else:
                                LOGGER.info(
                                    "KIS WebSocket first frame received after subscription establishment "
                                    "frames_seen=%s",
                                    frames_seen,
                                )
                            first_frame_after_subscription = False
                        stable_snapshot = metrics.record_frame()
                        if stable_snapshot is not None:
                            _emit_reconnect_snapshot(metrics_callback, stable_snapshot)
                        yield frame
                break
            except Exception as exc:
                if metrics.cumulative_reconnects >= max_reconnects:
                    raise KisApiError(
                        f"KIS WebSocket listen failed after {metrics.cumulative_reconnects} reconnects: {exc}"
                    ) from exc
                reconnect_snapshot = metrics.record_disconnected(exc)
                _emit_reconnect_snapshot(metrics_callback, reconnect_snapshot)
                delay_seconds = _reconnect_delay_seconds(
                    self.reconnect_backoff_seconds,
                    reconnect_snapshot.consecutive_reconnects,
                    self.max_reconnect_backoff_seconds,
                )
                LOGGER.warning(
                    (
                        "KIS WebSocket disconnected; reconnecting in %ss "
                        "(attempt %s/%s, consecutive=%s, storm=%s): %s"
                    ),
                    delay_seconds,
                    reconnect_snapshot.cumulative_reconnects,
                    max_reconnects,
                    reconnect_snapshot.consecutive_reconnects,
                    reconnect_snapshot.reconnect_storm,
                    exc,
                )
                await asyncio.sleep(delay_seconds)


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


def _is_reconnect_storm(consecutive_reconnects: int, *, threshold: int) -> bool:
    return threshold > 0 and consecutive_reconnects >= threshold


def _datetime_iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _emit_reconnect_snapshot(
    metrics_callback: Callable[[KisWebSocketReconnectSnapshot], None] | None,
    snapshot: KisWebSocketReconnectSnapshot,
) -> None:
    if metrics_callback is not None:
        try:
            metrics_callback(snapshot)
        except Exception:
            LOGGER.warning("KIS WebSocket reconnect metrics callback failed", exc_info=True)
