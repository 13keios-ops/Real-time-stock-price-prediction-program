"""Offline intraday candidate evidence. No network, broker or wallet access."""

from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
import hashlib
import json
import math

from app.utils.time import get_timezone


VERSION = "kr-intraday-candidate-scan-v1"
KST = get_timezone("Asia/Seoul")


def _hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Invalid numeric evidence")
    return float(value)


def _stamp(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Timezone required")
    return stamp.astimezone(KST)


@dataclass(frozen=True)
class ScanPolicy:
    min_price: float = 20000
    max_price: float = 30000
    min_trading_value: float = 1_000_000_000
    min_excess_return_pct: float = 0.5
    min_volume_ratio: float = 1.5
    max_spread_bps: float = 30
    max_candidates: int = 5

    def __post_init__(self):
        for key, value in asdict(self).items():
            if _number(value) <= 0:
                raise ValueError(f"Invalid policy {key}")
        if self.min_price > self.max_price or type(self.max_candidates) is not int:
            raise ValueError("Invalid policy bounds")


def _bar_evidence(rows, as_of):
    if not isinstance(rows, list) or len(rows) != 21:
        raise ValueError("Exactly 21 consecutive closed bars required")
    bars = []
    previous = None
    for row in rows:
        stamp = _stamp(row["bar_time"])
        available = _stamp(row["available_at"])
        if (stamp.second or stamp.microsecond or stamp.date() != as_of.date()
                or not time(9) <= stamp.time().replace(tzinfo=None) < time(15, 20)
                or not stamp + timedelta(minutes=1) <= available <= as_of
                or (previous is not None and stamp != previous + timedelta(minutes=1))):
            raise ValueError("Invalid bar timing")
        values = {key: _number(row[key]) for key in ("open", "high", "low", "close", "volume")}
        if (min(values[k] for k in ("open", "high", "low", "close")) <= 0
                or values["volume"] <= 0
                or not values["low"] <= min(values["open"], values["close"])
                <= max(values["open"], values["close"]) <= values["high"]):
            raise ValueError("Invalid OHLCV")
        bars.append(dict(**values, bar_time=stamp.isoformat(), available_at=available.isoformat()))
        previous = stamp
    if as_of - previous - timedelta(minutes=1) > timedelta(seconds=120):
        raise ValueError("Stale bars")
    return bars


def scan_candidates(rows, *, as_of: datetime, policy: ScanPolicy | None = None):
    """Return point-in-time shortlist and explicit rejections, never executable orders.

    Metadata and market/sector returns must be supplied with their observed timestamp.
    'normal' is an explicit provider eligibility assertion, not an inferred default.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Timezone required")
    as_of = as_of.astimezone(KST)
    if as_of.weekday() >= 5 or not time(9, 30) <= as_of.time().replace(tzinfo=None) < time(14, 45):
        raise ValueError("Scanner only accepts weekday intraday entry windows")
    policy = policy or ScanPolicy()
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("A bounded snapshot list is required")
    symbols = [r.get("symbol") if isinstance(r, dict) else None for r in rows]
    if any(not isinstance(s, str) or len(s) != 6 or not s.isascii() or not s.isdigit() for s in symbols):
        raise ValueError("Invalid domestic stock identity")
    if len(set(symbols)) != len(symbols):
        raise ValueError("Duplicate symbols: refusing ambiguous snapshot")
    selected, rejected = [], []
    for row in rows:
        reasons = []
        if row.get("market") not in ("KOSPI", "KOSDAQ") or row.get("instrument_type") != "common_stock":
            reasons.append("unsupported_instrument")
        if row.get("market_status") != "normal":
            reasons.append("market_status_unverified" if "market_status" not in row else "market_status_blocked")
        try:
            observed = _stamp(row["observed_at"])
            quote = _stamp(row["quote_at"])
            if not timedelta(0) <= as_of - observed <= timedelta(seconds=60):
                reasons.append("snapshot_stale_or_future")
            if not timedelta(0) <= as_of - quote <= timedelta(seconds=20):
                reasons.append("quote_stale_or_future")
            values = {key: _number(row[key]) for key in
                      ("price", "bid", "ask", "trading_value", "return_pct",
                       "market_return_pct", "sector_return_pct", "volume_ratio")}
            if min(values[k] for k in ("price", "bid", "ask")) <= 0 or values["ask"] < values["bid"]:
                raise ValueError("Invalid quote")
            spread = (values["ask"] - values["bid"]) / ((values["ask"] + values["bid"]) / 2) * 10000
            excess = values["return_pct"] - max(values["market_return_pct"], values["sector_return_pct"])
            if not policy.min_price <= values["price"] <= policy.max_price:
                reasons.append("price_band")
            if spread > policy.max_spread_bps:
                reasons.append("wide_spread")
            if values["trading_value"] < policy.min_trading_value:
                reasons.append("liquidity")
            if values["return_pct"] <= 0 or excess < policy.min_excess_return_pct:
                reasons.append("relative_strength")
            if values["volume_ratio"] < policy.min_volume_ratio:
                reasons.append("volume_ratio")
        except (ValueError, TypeError, KeyError, OverflowError):
            reasons.append("snapshot_evidence_invalid")
        try:
            bars = _bar_evidence(row.get("bars"), as_of)
        except (ValueError, TypeError, KeyError, OverflowError):
            reasons.append("bar_evidence_invalid")
        if reasons:
            rejected.append(dict(symbol=row["symbol"], reasons=sorted(set(reasons))))
            continue
        current, past = bars[-1], bars[:-1]
        ranges = [max(bars[i]["high"] - bars[i]["low"],
                      abs(bars[i]["high"] - bars[i-1]["close"]),
                      abs(bars[i]["low"] - bars[i-1]["close"])) for i in range(1, 21)]
        atr = sum(ranges[-15:-1]) / 14
        mean_volume = sum(b["volume"] for b in past) / 20
        # Closed-bar typical-price VWAP proxy; not exchange trade-level VWAP.
        vwap = sum((b["high"]+b["low"]+b["close"])/3*b["volume"] for b in bars) / sum(b["volume"] for b in bars)
        extension = current["close"] - max(b["high"] for b in past)
        signals = []
        if (atr > 0 and 0.25*atr <= extension <= 3*atr
                and 0 < (current["close"]/current["open"]-1)*100 <= 3
                and current["volume"] >= 1.5*mean_volume):
            signals.append("breakout")
        if (atr > 0 and max(b["high"] for b in past[-10:]) > max(b["high"] for b in past[:10])
                and past[-1]["close"] < past[-2]["close"]
                and current["close"] > max(current["open"], past[-1]["close"], vwap)
                and 0.25*atr <= max(b["high"] for b in past[-10:])-current["close"] <= 2*atr
                and current["volume"] >= mean_volume):
            signals.append("trend_pullback")
        evidence = dict(symbol=row["symbol"], market=row["market"],
                        market_status=row["market_status"], observed_at=observed.isoformat(),
                        quote_at=quote.isoformat(), values=values, bars=bars)
        evidence_hash = _hash(evidence)
        selected.append(dict(symbol=row["symbol"], price=values["price"],
                             excess_return_pct=excess, volume_ratio=values["volume_ratio"],
                             trading_value=values["trading_value"], spread_bps=spread,
                             signals=signals, atr14_sma=atr, closed_bar_vwap_proxy=vwap,
                             evidence_hash=evidence_hash,
                             candidate_id=_hash(dict(version=VERSION, policy=asdict(policy),
                                                     as_of=as_of.isoformat(), evidence_hash=evidence_hash))))
    selected.sort(key=lambda r: (-r["excess_return_pct"], -r["volume_ratio"], -r["trading_value"], r["symbol"]))
    for row in selected[policy.max_candidates:]:
        rejected.append(dict(symbol=row["symbol"], reasons=["shortlist_limit"]))
    return dict(version=VERSION, policy=asdict(policy), policy_hash=_hash(asdict(policy)),
                as_of=as_of.isoformat(), status="candidate_evidence_only",
                execution_enabled=False, network_calls=0, order_calls=0,
                theme_classification="not_available", selected=selected[:policy.max_candidates],
                rejected=sorted(rejected, key=lambda r: r["symbol"]))
