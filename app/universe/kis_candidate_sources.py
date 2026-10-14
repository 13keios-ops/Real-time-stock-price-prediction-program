"""Offline source binding using documented KIS master and index fields."""

import re
from app.universe.intraday_candidates import KST, _hash
from app.universe.kis_candidate_snapshot import _fresh, _numeric, _same_day

VERSION = "kis-candidate-source-binding-v2-reference-snapshot"
MASTER_MARKETS = {"kis-stock-master-kospi-v1": ("KOSPI", "0001"),
                  "kis-stock-master-kosdaq-v1": ("KOSDAQ", "1001")}

def _yn(value):
    if value not in ("Y", "N"):
        raise ValueError("Missing or unknown Y/N field")
    return value == "Y"

def _metadata(master, quote, *, as_of):
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Aware timestamp required")
    as_of = as_of.astimezone(KST)
    if master.get("source") not in MASTER_MARKETS:
        raise ValueError("Master source unverified")
    acquired_reference = master.get('reference_date') is None
    if acquired_reference:
        if (master.get('layout_version') != 'kis-fixed-width-stock-master-v1'
                or not re.fullmatch(r'[0-9a-f]{64}', master.get('source_hash', ''))):
            raise ValueError('Parsed acquisition reference required')
        _fresh(master['acquired_at'], as_of, 8*60*60)
    elif master['reference_date'] != as_of.date().isoformat():
        raise ValueError('Master reference date mismatch')
    _same_day(quote, as_of)
    observed = _fresh(quote["observed_at"], as_of, 60)
    row, live = master["output"], quote["output"]
    symbol = row["mksc_shrn_iscd"]
    if not isinstance(symbol, str) or not re.fullmatch(r"[0-9]{6}", symbol) or live["stck_shrn_iscd"] != symbol:
        raise ValueError("Symbol identity mismatch")
    if (row["scrt_grp_cls_code"] != "ST" or row["prst_cls_code"] != "0"
            or row["etp_prod_cls_code"] not in (('0', '') if acquired_reference else ('0',))
            or _yn(row["etpr_undt_objt_co_yn"])):
        raise ValueError("Not an ordinary non-SPAC stock")
    market, market_index = MASTER_MARKETS[master["source"]]
    sector = row["bstp_larg_div_code"]
    if not isinstance(sector, str) or not re.fullmatch(r"[0-9]{4}", sector) or sector in ("0000", "0001", "1001", "2001"):
        raise ValueError("Specific sector index unverified")
    warning = row["mrkt_alrm_cls_code"]
    if warning not in ("00", "01", "02", "03"):
        raise ValueError("Unknown master warning code")
    # REST warning field has a different name: only explicit no-warning is admitted.
    if live["mrkt_warn_cls_code"] != "00":
        raise ValueError("Live market warning or unknown code")
    overheat = row["short_over_cls_code"]
    if overheat not in ("0", "1", "2", "3"):
        raise ValueError("Unknown overheat code")
    master_flags = {k: _yn(row[k]) for k in ("trht_yn", "sltr_yn", "mang_issu_yn")}
    live_flags = {k: _yn(live[k]) for k in
                  ("temp_stop_yn", "sltr_yn", "mang_issu_cls_code", "invt_caful_yn", "short_over_yn")}
    caution = live_flags["invt_caful_yn"] or warning == "01"
    if market == "KOSDAQ":
        caution = _yn(row["invt_alrm_yn"]) or caution
    flags = dict(investment_caution=caution, investment_warning=warning == "02",
                 investment_risk=warning == "03", management=master_flags["mang_issu_yn"] or live_flags["mang_issu_cls_code"],
                 liquidation=master_flags["sltr_yn"] or live_flags["sltr_yn"],
                 trading_halt=master_flags["trht_yn"] or live_flags["temp_stop_yn"],
                 short_term_overheat=overheat != "0" or live_flags["short_over_yn"])
    evidence = dict(version=VERSION, symbol=symbol, master_source=master["source"],
                    reference_date=master["reference_date"], observed_at=observed.isoformat(),
                    master_reference_basis='same_day_acquired_snapshot' if acquired_reference else 'explicit_reference_date',
                    master_source_hash=master.get('source_hash'), master_acquired_at=master.get('acquired_at'),
                    master_etp_raw=row['etp_prod_cls_code'],
                    master_warning=warning, master_overheat=overheat,
                    master_flags=master_flags, live_flags=live_flags,
                    market=market, sector_index_code=sector)
    return dict(observed_at=observed.isoformat(), trade_date=as_of.date().isoformat(),
                market=market, instrument_type="common_stock", flags=flags,
                market_index_code=market_index, sector_index_code=sector,
                master_reference_basis=evidence['master_reference_basis'],
                master_etp_raw=row['etp_prod_cls_code'],
                master_effective_day_verified=bool(master.get('effective_day_verified', False)),
                source_version=VERSION, source_hash=_hash(evidence))

def _benchmark(metadata, market_quote, sector_quote, *, as_of):
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Aware timestamp required")
    as_of = as_of.astimezone(KST)
    if metadata.get("source_version") != VERSION:
        raise ValueError("Bound classification required")
    expected_market = {"KOSPI": "0001", "KOSDAQ": "1001"}.get(metadata.get("market"))
    if (expected_market is None or metadata.get("market_index_code") != expected_market
            or not re.fullmatch(r"[0-9a-f]{64}", metadata.get("source_hash", ""))):
        raise ValueError("Classification market/hash binding invalid")
    _same_day(metadata, as_of)
    _fresh(metadata["observed_at"], as_of, 60)
    values, times = [], []
    for quote, expected in ((market_quote, metadata["market_index_code"]),
                            (sector_quote, metadata["sector_index_code"])):
        _same_day(quote, as_of)
        times.append(_fresh(quote["observed_at"], as_of, 60))
        if quote.get("index_code") != expected:
            raise ValueError("Index does not match security classification")
        values.append(_numeric(quote["output"]["bstp_nmix_prdy_ctrt"]))
    result = dict(observed_at=min(times).isoformat(), trade_date=as_of.date().isoformat(),
                  market_return_pct=values[0], sector_return_pct=values[1],
                  market_index_code=metadata["market_index_code"], sector_index_code=metadata["sector_index_code"],
                  source_version=VERSION, metadata_source_hash=metadata["source_hash"])
    return {**result, "source_hash": _hash(result)}

def build_metadata(master, quote, *, as_of):
    try:
        return _metadata(master, quote, as_of=as_of)
    except (KeyError, TypeError, AttributeError):
        raise ValueError("Required source metadata is missing or invalid") from None

def build_benchmark(metadata, market_quote, sector_quote, *, as_of):
    try:
        return _benchmark(metadata, market_quote, sector_quote, as_of=as_of)
    except (KeyError, TypeError, AttributeError):
        raise ValueError("Required benchmark evidence is missing or invalid") from None
