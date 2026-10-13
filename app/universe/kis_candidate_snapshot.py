"""Normalize captured KIS inputs offline; never infer missing trading evidence."""

from datetime import datetime, timedelta
import math
import re

from app.universe.intraday_candidates import KST, _bar_evidence, _hash, _stamp, scan_candidates


VERSION = "kis-intraday-snapshot-adapter-v1"
VOLUME_BASIS = "accumulated_volume_over_previous_day_volume"
BLOCKING_FLAGS = ("investment_caution", "investment_warning", "investment_risk",
                  "management", "liquidation", "trading_halt", "short_term_overheat")


class EvidenceError(ValueError):
    pass


def _numeric(value):
    if isinstance(value, bool):
        raise EvidenceError("invalid_numeric_evidence")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise EvidenceError("invalid_numeric_evidence") from exc
    if not math.isfinite(number) or abs(number) > 1e18:
        raise EvidenceError("invalid_numeric_evidence")
    return number


def _fresh(value, as_of, seconds):
    try:
        stamp = _stamp(value)
    except (ValueError, TypeError) as exc:
        raise EvidenceError("provider_time_unverified") from exc
    if stamp.date() != as_of.date() or not timedelta(0) <= as_of-stamp <= timedelta(seconds=seconds):
        raise EvidenceError("provider_time_stale_or_future")
    return stamp


def _same_day(record, as_of):
    if not isinstance(record, dict) or record.get("trade_date") != as_of.date().isoformat():
        raise EvidenceError("source_trade_date_unverified")


def scan_kis_snapshot(snapshot, *, as_of: datetime, holidays=()):
    """Consume an explicitly dated capture, not raw ranking rows alone.

    Metadata flags must be actual booleans from independently verified classification.
    Mask parameters, margin codes and fetch time alone cannot certify eligibility.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Timezone required")
    as_of = as_of.astimezone(KST)
    if as_of.date().isoformat() in holidays:
        raise ValueError("Closed trading date")
    if not isinstance(snapshot, dict) or snapshot.get("source") != "kis-volume-rank-krx-v1":
        raise ValueError("Unsupported capture source")
    _same_day(snapshot, as_of)
    received = _fresh(snapshot.get("received_at"), as_of, 60)
    rows, observations = snapshot.get("rows"), snapshot.get("observations", {})
    if not isinstance(rows, list) or len(rows) > 1000 or not isinstance(observations, dict):
        raise ValueError("Invalid bounded capture")
    symbols = [row.get("mksc_shrn_iscd") if isinstance(row, dict) else None for row in rows]
    valid_ids = [s for s in symbols if isinstance(s, str) and re.fullmatch(r"[0-9A-Z]{6}", s)]
    if len(set(valid_ids)) != len(valid_ids):
        raise ValueError("Duplicate capture identity")
    normalized, provenance, rejections = [], [], []
    for row, symbol in zip(rows, symbols):
        safe_symbol = symbol if isinstance(symbol, str) and re.fullmatch(r"[0-9A-Z]{6}", symbol) else None
        if safe_symbol is None or not re.fullmatch(r"[0-9]{6}", safe_symbol):
            rejections.append(dict(symbol=safe_symbol, reason="unsupported_symbol_contract"))
            continue
        try:
            observation = observations[symbol]
            price, quote = observation["price"], observation["orderbook"]
            metadata, benchmark = observation["metadata"], observation["benchmark"]
            for record in (price, metadata, benchmark):
                _same_day(record, as_of)
            times = dict(price=_fresh(price["received_at"], as_of, 60),
                         quote_received=_fresh(quote["received_at"], as_of, 20),
                         quote_provider=_fresh(quote["provider_at"], as_of, 20),
                         metadata=_fresh(metadata["observed_at"], as_of, 60),
                         benchmark=_fresh(benchmark["observed_at"], as_of, 60))
            if times["quote_provider"] > times["quote_received"]:
                raise EvidenceError("quote_provider_after_receipt")
            flags = metadata.get("flags", {})
            if not isinstance(flags, dict) or any(type(flags.get(key)) is not bool for key in BLOCKING_FLAGS):
                raise EvidenceError("market_flags_unverified")
            if any(flags[key] for key in BLOCKING_FLAGS):
                raise EvidenceError("market_flags_blocked")
            if metadata.get("market") not in ("KOSPI", "KOSDAQ") or metadata.get("instrument_type") != "common_stock":
                raise EvidenceError("unsupported_instrument")
            previous_volume = _numeric(row["prdy_vol"])
            volume = _numeric(row["acml_vol"])
            if previous_volume <= 0 or volume < 0:
                raise EvidenceError("previous_day_volume_unusable")
            output, book = price["output"], quote["output1"]
            bars = _bar_evidence(observation["bars"], as_of)
            candidate = dict(symbol=symbol, market=metadata["market"],
                             instrument_type="common_stock", market_status="normal",
                             price=_numeric(output["stck_prpr"]), bid=_numeric(book["bidp1"]),
                             ask=_numeric(book["askp1"]), trading_value=_numeric(output["acml_tr_pbmn"]),
                             return_pct=_numeric(output["prdy_ctrt"]),
                             market_return_pct=_numeric(benchmark["market_return_pct"]),
                             sector_return_pct=_numeric(benchmark["sector_return_pct"]),
                             volume_ratio=volume/previous_volume,
                             observed_at=min(received, times["price"], times["metadata"], times["benchmark"]).isoformat(),
                             quote_at=times["quote_provider"].isoformat(), bars=bars)
            normalized.append(candidate)
            provenance.append(dict(symbol=symbol, times={k: v.isoformat() for k, v in times.items()},
                                   flags={key: flags[key] for key in BLOCKING_FLAGS},
                                   accumulated_volume=volume, previous_day_volume=previous_volume,
                                   normalized_input=candidate))
        except EvidenceError as exc:
            rejections.append(dict(symbol=safe_symbol, reason=str(exc)))
        except (KeyError, TypeError, ValueError, OverflowError):
            rejections.append(dict(symbol=safe_symbol, reason="required_evidence_missing_or_invalid"))
    scanner = scan_candidates(normalized, as_of=as_of)
    provenance.sort(key=lambda row: row["symbol"])
    rejections.sort(key=lambda row: (row["symbol"] or "", row["reason"]))
    # Fingerprint only explicit normalized evidence, never arbitrary provider secrets.
    fingerprint = _hash(dict(adapter_version=VERSION, volume_basis=VOLUME_BASIS,
                             source=snapshot["source"], trade_date=snapshot["trade_date"],
                             received_at=received.isoformat(), provenance=provenance, rejections=rejections))
    return dict(adapter_version=VERSION, source_hash=fingerprint,
                source_hash_scope="normalized_supported_evidence_and_rejection_taxonomy",
                volume_ratio_basis=VOLUME_BASIS, execution_enabled=False,
                network_calls=0, order_calls=0, scanner=scanner, adapter_rejections=rejections)
