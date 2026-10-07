"""Versioned diagnostic price view; never repairs the ledger or permits E7."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from types import MappingProxyType
from typing import Mapping, Sequence

from app.features.minute_bars import aggregate_ticks_to_minute_bar
from app.services.e7_daily_evidence import _connect_readonly
from app.services.e7_portfolio_evaluator import E7_PORTFOLIO_REPLAY_MANIFEST
from app.services.portfolio_replay import ReplayBar
from app.storage.contracts import MarketTickEvent


PRICE_INPUT_SOURCE_VERSION = "e7-captured-raw-price-view-v1"


class PriceInputViewError(ValueError):
    """The captured source cannot substantiate a diagnostic price correction."""


@dataclass(frozen=True, slots=True)
class VerifiedPriceInputView:
    bars_by_symbol: Mapping[str, tuple[ReplayBar, ...]]
    _evidence_json: str

    def to_dict(self) -> dict:
        return json.loads(self._evidence_json)


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _bar_fingerprint(bars: Mapping[str, Sequence[ReplayBar]]) -> str:
    return _digest([
        [symbol, bar.bar_time.isoformat(), bar.open_price, bar.close_price]
        for symbol in sorted(bars)
        for bar in sorted(bars[symbol], key=lambda item: item.bar_time)
    ])


def _captured_context(connection, symbol, minute):
    bounds = connection.execute(
        """SELECT MIN(rowid), MAX(rowid) FROM raw_market_ticks
           WHERE source=? AND symbol=? AND event_time>=? AND event_time<?""",
        ("kis-ws", symbol, minute.isoformat(), (minute + timedelta(minutes=1)).isoformat()),
    ).fetchone()
    if bounds[0] is None:
        return []
    # Keep every same-symbol boundary between first and last target capture,
    # even if its event time jumped outside the requested minute neighborhood.
    return connection.execute(
        """SELECT rowid AS capture_rowid, symbol, event_time, price, volume, source
           FROM raw_market_ticks WHERE rowid>=? AND rowid<=? AND source=? AND symbol=?
           ORDER BY rowid""",
        (*bounds, "kis-ws", symbol),
    ).fetchall()


def build_verified_price_input_view(
    database_path: Path,
    *,
    runtime_root: Path,
    bars_by_symbol: Mapping[str, Sequence[ReplayBar]],
    requested_minutes: Sequence[tuple[str, datetime]],
) -> VerifiedPriceInputView:
    """Verify captured fragments, then overlay only explicitly requested prices.

    Full captured-minute aggregation is a separately versioned diagnostic input,
    not a recovered historical prediction or a claim of exchange completeness.
    """
    manifest = E7_PORTFOLIO_REPLAY_MANIFEST
    requested = []
    for symbol, minute in requested_minutes:
        if not symbol or minute.tzinfo is None or minute.utcoffset() is None or minute.second or minute.microsecond:
            raise PriceInputViewError("invalid aware minute identity")
        minute = minute.astimezone(manifest.future_evaluation_start.tzinfo)
        if minute < manifest.future_evaluation_start:
            raise PriceInputViewError("minute before E7 future window")
        requested.append((symbol, minute))
    if not requested or len(set(requested)) != len(requested):
        raise PriceInputViewError("requested minutes must be nonempty and unique")
    original = {symbol: tuple(bars) for symbol, bars in bars_by_symbol.items()}
    for symbol, bars in original.items():
        for bar in bars:
            if (bar.symbol != symbol or bar.bar_time.tzinfo is None or bar.bar_time.utcoffset() is None
                    or bar.bar_time.second or bar.bar_time.microsecond
                    or any(not isinstance(price, (int, float)) or isinstance(price, bool)
                           or not math.isfinite(price) or price <= 0
                           for price in (bar.open_price, bar.close_price))):
                raise PriceInputViewError("invalid baseline price bar")
    corrected = dict(original)
    corrections = []
    generation_files: dict[Path, bytes] = {}
    try:
        with closing(_connect_readonly(database_path)) as connection:
            for symbol, minute in sorted(requested):
                candidates = [bar for bar in original.get(symbol, ()) if bar.bar_time == minute]
                if len(candidates) != 1 or candidates[0].symbol != symbol:
                    raise PriceInputViewError("baseline price identity missing or ambiguous")
                stored = connection.execute(
                    "SELECT * FROM curated_minute_bars WHERE symbol=? AND bar_time=?",
                    (symbol, minute.isoformat()),
                ).fetchone()
                if stored is None:
                    raise PriceInputViewError("stored minute missing")
                stored = dict(stored)
                baseline = candidates[0]
                if (baseline.open_price, baseline.close_price) != (stored["open"], stored["close"]):
                    raise PriceInputViewError("baseline price differs from stored minute")
                path = runtime_root / "curated" / minute.date().isoformat() / "minute_bars.jsonl"
                if path not in generation_files:
                    generation_files[path] = path.read_bytes()
                generations = []
                for line_number, line in enumerate(generation_files[path].splitlines(), 1):
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise PriceInputViewError("malformed generation record")
                    if record.get("symbol") == symbol and record.get("bar_time") == minute.isoformat():
                        generations.append((line_number, record))
                if not generations or generations[-1][1] != stored:
                    raise PriceInputViewError("preserved last fragment differs from stored minute")
                raw = _captured_context(connection, symbol, minute)
                chunks = []
                for row in raw:
                    timestamp = datetime.fromisoformat(row["event_time"])
                    if timestamp.tzinfo is None or not math.isfinite(row["price"]) or row["price"] <= 0 or type(row["volume"]) is not int or row["volume"] < 0:
                        raise PriceInputViewError("invalid captured tick")
                    key = timestamp.replace(second=0, microsecond=0)
                    if not chunks or chunks[-1][0] != key:
                        chunks.append((key, []))
                    chunks[-1][1].append(row)
                fragments = [rows for key, rows in chunks if key == minute]
                if not fragments or len(fragments) != len(generations):
                    raise PriceInputViewError("captured fragment count differs from generations")
                captured_ticks = []
                fragment_proof = []
                for rows, (line_number, recorded) in zip(fragments, generations):
                    ticks = [MarketTickEvent(row["symbol"], datetime.fromisoformat(row["event_time"]),
                                             row["price"], row["volume"], row["source"]) for row in rows]
                    if aggregate_ticks_to_minute_bar(symbol, ticks).to_record() != recorded:
                        raise PriceInputViewError("captured fragment differs from preserved generation")
                    captured_ticks.extend(ticks)
                    fragment_proof.append({"generation_line": line_number, "first_capture_rowid": rows[0]["capture_rowid"],
                                           "last_capture_rowid": rows[-1]["capture_rowid"], "tick_count": len(rows)})
                rebuilt = aggregate_ticks_to_minute_bar(symbol, captured_ticks)
                replacement = replace(baseline, open_price=rebuilt.open, close_price=rebuilt.close)
                corrected[symbol] = tuple(replacement if bar.bar_time == minute else bar for bar in corrected[symbol])
                corrections.append({
                    "symbol": symbol, "minute": minute.isoformat(), "source": "kis-ws",
                    "captured_tick_count": len(captured_ticks), "stored_bar": stored,
                    "captured_bar": rebuilt.to_record(), "fragments": fragment_proof,
                    "capture_context_sha256": _digest([dict(row) for row in raw]),
                    "generation_file": str(path.relative_to(runtime_root)),
                    "generation_file_sha256": hashlib.sha256(generation_files[path]).hexdigest(),
                })
        with closing(_connect_readonly(database_path)) as connection:
            for correction in corrections:
                symbol, minute = correction["symbol"], datetime.fromisoformat(correction["minute"])
                stored = connection.execute(
                    "SELECT * FROM curated_minute_bars WHERE symbol=? AND bar_time=?",
                    (symbol, minute.isoformat()),
                ).fetchone()
                raw = _captured_context(connection, symbol, minute)
                if (stored is None or dict(stored) != correction["stored_bar"]
                        or _digest([dict(row) for row in raw]) != correction["capture_context_sha256"]):
                    raise PriceInputViewError("database source changed during validation")
        for path, content in generation_files.items():
            if path.read_bytes() != content:
                raise PriceInputViewError("generation file changed during validation")
    except PriceInputViewError:
        raise
    except (OSError, sqlite3.Error, TypeError, KeyError, ValueError) as exc:
        raise PriceInputViewError("price source unavailable or malformed") from exc
    evidence = {
        "schema_version": 1, "input_source_version": PRICE_INPUT_SOURCE_VERSION,
        "mode": "diagnostic_only_not_official_e7", "official_evaluation_permitted": False,
        "evaluator_version": manifest.evaluator_version, "manifest_hash": manifest.sha256,
        "original_bar_fingerprint": _bar_fingerprint(original),
        "corrected_bar_fingerprint": _bar_fingerprint(corrected), "corrections": corrections,
        "database_access": "read-only", "database_mutation": False,
        "price_basis": "all_captured_ticks_ordered_by_event_time_then_capture_rowid",
        "capture_scope": "requested_minute_first_to_last_capture_rowid_same_symbol_source",
        "historical_predictions_recovered": False,
        "exchange_feed_completeness_proven": False,
    }
    evidence["input_fingerprint"] = _digest(evidence)
    return VerifiedPriceInputView(MappingProxyType(corrected), json.dumps(evidence, sort_keys=True))
