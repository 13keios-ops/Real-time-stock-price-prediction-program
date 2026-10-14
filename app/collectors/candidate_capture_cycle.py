"""Bounded read-only capture cycle; transport/source ports are not connected live."""

from datetime import time, timedelta
import re
from threading import RLock
import time as wall_time

from app.universe.intraday_candidates import KST, ScanPolicy, _bar_evidence
from app.universe.kis_candidate_sources import VERSION as SOURCE_BINDING_VERSION
from app.universe.kis_candidate_snapshot import (
    BLOCKING_FLAGS, _fresh, _numeric, _same_day, scan_kis_snapshot,
)
from app.utils.time import now_local


VERSION = "kr-bounded-capture-cycle-v1"
RANK_PATH = "/uapi/domestic-stock/v1/quotations/volume-rank"
PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-price"
QUOTE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
ALLOWED = {RANK_PATH: "FHPST01710000", PRICE_PATH: "FHKST01010100", QUOTE_PATH: "FHKST01010200"}


class CaptureFailure(ValueError):
    def __init__(self, code="", taxonomy="broker_unknown_error"):
        self.code = code if re.fullmatch(r"[A-Za-z0-9_-]{0,24}", str(code)) else "redacted"
        self.taxonomy = taxonomy


class CaptureCycle:
    """No scheduler, credentials, token issuance, retry, pagination or order surface.

    A reader supplies verified response envelopes: raw business fields PLUS an
    independently verified trade_date/provider_at. Receipt date is never substituted.
    Per-instance budgets do not prove coordination with the existing runtime account.
    """
    def __init__(self, reader=None, *, clock=None, sleep=None, holidays=()):
        self.reader = reader
        self.clock = clock or (lambda: now_local("Asia/Seoul"))
        self.sleep = sleep or wall_time.sleep
        self.holidays = tuple(holidays)
        self._last_finished = None
        self._response_finished = None
        self._lock = RLock()

    def _now(self):
        stamp = self.clock()
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("Aware clock required")
        return stamp.astimezone(KST)

    def _get(self, path, params, report, started):
        if path not in ALLOWED or report["request_attempts"] >= 11:
            raise CaptureFailure("", "capture_budget_exhausted")
        now = self._now()
        if self._response_finished:
            delay = 1.1 - (now-self._response_finished).total_seconds()
            if delay > 0:
                self.sleep(delay)
        if (self._now()-started).total_seconds() > 18:
            raise CaptureFailure("", "capture_deadline_exceeded")
        report["request_attempts"] += 1
        try:
            response = self.reader.get(path, ALLOWED[path], params, timeout_seconds=3, allow_retry=False)
        finally:
            self._response_finished = self._now()
        if (self._response_finished-started).total_seconds() > 18:
            raise CaptureFailure("", "capture_deadline_exceeded")
        if not isinstance(response, dict) or str(response.get("rt_cd")) != "0":
            code = str(response.get("msg_cd", "")) if isinstance(response, dict) else ""
            taxonomy = ("broker_rate_limited" if code == "EGW00201" else
                        "broker_auth_error" if code in ("EGW00121", "EGW00123") else "broker_unknown_error")
            raise CaptureFailure(code, taxonomy)
        _same_day(response, self._response_finished)
        return response, self._response_finished

    def _context(self, record, now):
        metadata, benchmark = record["metadata"], record["benchmark"]
        for item in (metadata, benchmark):
            _same_day(item, now)
            _fresh(item["observed_at"], now, 60)
            if (item.get('source_version') != SOURCE_BINDING_VERSION
                    or not re.fullmatch(r'[0-9a-f]{64}', item.get('source_hash', ''))):
                raise ValueError('Source chain unverified')
        if benchmark.get('metadata_source_hash') != metadata['source_hash']:
            raise ValueError('Benchmark classification chain mismatch')
        flags = metadata["flags"]
        if (not isinstance(flags, dict) or any(type(flags.get(k)) is not bool or flags[k] for k in BLOCKING_FLAGS)
                or metadata.get("market") not in ("KOSPI", "KOSDAQ")
                or metadata.get("instrument_type") != "common_stock"):
            raise ValueError("Unverified classification")
        bars = _bar_evidence(record["bars"], now)
        for sanitized, raw in zip(bars, record["bars"]):
            count = raw["trade_count"]
            if type(count) is not int or count <= 0:
                raise ValueError("Actual trade count required")
            sanitized["trade_count"] = count
        return dict(metadata=dict(observed_at=metadata["observed_at"], trade_date=metadata["trade_date"],
                                  market=metadata["market"], instrument_type="common_stock",
                                  flags={k: flags[k] for k in BLOCKING_FLAGS}),
                    benchmark=dict(observed_at=benchmark["observed_at"], trade_date=benchmark["trade_date"],
                                   market_return_pct=_numeric(benchmark["market_return_pct"]),
                                   sector_return_pct=_numeric(benchmark["sector_return_pct"])), bars=bars,
                    source_chain=dict(metadata_version=metadata['source_version'],metadata_hash=metadata['source_hash'],
                        benchmark_version=benchmark['source_version'],benchmark_hash=benchmark['source_hash']))

    def collect(self, *, evidence, execute=False, budget_authorized=False):
        with self._lock:
            now = self._now()
            report = dict(version=VERSION, status="dry_run", request_attempts=0, retry_count=0,
                          order_calls=0, runtime_attached=False, automatic_cycle_scheduling=False,
                          budget=dict(max_symbols=5, max_requests=11, minimum_cycle_gap_seconds=300,
                                      response_completion_gap_seconds=1.1, cycle_deadline_seconds=18),
                          rejected=[], failure_taxonomy=None)
            if not execute:
                return report
            if budget_authorized is not True:
                return {**report, "status": "network_authorization_required"}
            if self.reader is None:
                return {**report, "status": "transport_not_connected"}
            if (now.weekday() >= 5 or now.date().isoformat() in self.holidays
                    or not time(9, 30) <= now.time().replace(tzinfo=None) < time(14, 45)):
                return {**report, "status": "outside_entry_window"}
            if self._last_finished and now-self._last_finished < timedelta(seconds=300):
                return {**report, "status": "cycle_cooldown"}
            if not isinstance(evidence, dict):
                return {**report, "status": "invalid_evidence_map"}
            try:
                params = dict(FID_COND_MRKT_DIV_CODE="J", FID_COND_SCR_DIV_CODE="20171",
                              FID_INPUT_ISCD="0000", FID_DIV_CLS_CODE="1", FID_BLNG_CLS_CODE="3",
                              FID_TRGT_CLS_CODE="111111111", FID_TRGT_EXLS_CLS_CODE="1111111111",
                              FID_INPUT_PRICE_1="20000", FID_INPUT_PRICE_2="30000",
                              FID_VOL_CNT="", FID_INPUT_DATE_1="")
                ranking, received = self._get(RANK_PATH, params, report, now)
                rows = ranking.get("output")
                if not isinstance(rows, list) or len(rows) > 1000:
                    raise CaptureFailure()
                ids = [row.get("mksc_shrn_iscd") for row in rows if isinstance(row, dict)]
                if any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)):
                    raise CaptureFailure()
                capture = dict(source="kis-volume-rank-krx-v1", trade_date=ranking["trade_date"],
                               source_binding_version=SOURCE_BINDING_VERSION,
                               received_at=received.isoformat(), rows=[], observations={})
                for row in rows:
                    if len(capture["observations"]) >= 5:
                        break
                    symbol = row.get("mksc_shrn_iscd") if isinstance(row, dict) else None
                    if not isinstance(symbol, str) or not re.fullmatch(r"[0-9]{6}", symbol):
                        report["rejected"].append(dict(symbol=None, reason="unsupported_symbol_contract"))
                        continue
                    try:
                        context = self._context(evidence[symbol], self._now())
                        volume, previous = _numeric(row["acml_vol"]), _numeric(row["prdy_vol"])
                        if volume < 0 or previous <= 0:
                            raise ValueError("Missing volume basis")
                        policy = ScanPolicy()
                        rank_price = _numeric(row["stck_prpr"])
                        rank_return = _numeric(row["prdy_ctrt"])
                        value = _numeric(row["acml_tr_pbmn"])
                        excess = rank_return-max(context["benchmark"]["market_return_pct"],
                                                 context["benchmark"]["sector_return_pct"])
                        if (not policy.min_price <= rank_price <= policy.max_price
                                or value < policy.min_trading_value or rank_return <= 0
                                or excess < policy.min_excess_return_pct
                                or volume/previous < policy.min_volume_ratio):
                            report["rejected"].append(dict(symbol=symbol, reason="rank_prefilter"))
                            continue
                    except (KeyError, ValueError, TypeError):
                        report["rejected"].append(dict(symbol=symbol, reason="required_evidence_unverified"))
                        continue
                    query = dict(FID_COND_MRKT_DIV_CODE="J", FID_INPUT_ISCD=symbol)
                    price, price_at = self._get(PRICE_PATH, query, report, now)
                    output = price['output']
                    if (output.get('mrkt_warn_cls_code') != '00' or any(output.get(k) != 'N' for k in
                            ('temp_stop_yn','sltr_yn','mang_issu_cls_code','invt_caful_yn','short_over_yn'))):
                        raise CaptureFailure('', 'capture_current_market_flags_blocked')
                    quote, quote_at = self._get(QUOTE_PATH, query, report, now)
                    provider_at = _fresh(quote["provider_at"], quote_at, 20)
                    output, book = price["output"], quote["output1"]
                    context["price"] = dict(received_at=price_at.isoformat(), trade_date=price["trade_date"],
                                            output={k: _numeric(output[k]) for k in
                                                    ("stck_prpr", "prdy_ctrt", "acml_tr_pbmn")})
                    context["orderbook"] = dict(received_at=quote_at.isoformat(), provider_at=provider_at.isoformat(),
                                                output1={k: _numeric(book[k]) for k in ("askp1", "bidp1")})
                    chain = context.pop('source_chain')
                    context['metadata'].update(source_version=chain['metadata_version'],source_hash=chain['metadata_hash'])
                    context['benchmark'].update(source_version=chain['benchmark_version'],source_hash=chain['benchmark_hash'],
                        metadata_source_hash=chain['metadata_hash'])
                    capture["rows"].append(dict(mksc_shrn_iscd=symbol, acml_vol=volume, prdy_vol=previous))
                    capture["observations"][symbol] = context
                scan = scan_kis_snapshot(capture, as_of=self._now(), holidays=self.holidays)
                report.update(status="captured" if capture["observations"] else "blocked_missing_evidence",
                              capture=capture, scan=scan)
            except CaptureFailure as exc:
                report.update(status="failed_no_retry", failure_taxonomy=exc.taxonomy, sanitized_code=exc.code)
            except (OSError, TimeoutError):
                report.update(status="failed_no_retry", failure_taxonomy="broker_network_error")
            except Exception:
                report.update(status="failed_no_retry", failure_taxonomy="capture_evidence_invalid")
            finally:
                self._last_finished = self._now()
            return report
