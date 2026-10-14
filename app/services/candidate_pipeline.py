"""Connect explicit source evidence, paper-only reader and independent replay."""
from datetime import datetime, timedelta, time
import math

from app.brokers.kis_candidate_reader import CandidateRestReader
from app.collectors.candidate_capture_cycle import CaptureCycle
from app.paper_trading.candidate_comparison import CandidateComparison
from app.storage.contracts import MinuteBar
from app.universe.kis_candidate_provenance import DatedMinuteVerifier
from app.universe.kis_candidate_snapshot import scan_kis_snapshot
from app.universe.kis_candidate_sources import build_metadata, build_benchmark, VERSION as SOURCE_BINDING_VERSION
from app.universe.intraday_candidates import KST
from app.utils.time import now_local


def prepare_candidate_context(master, price, market_index, sector_index, bars, *, as_of):
    """Bind explicit captured inputs without fetching or inventing bar evidence."""
    quotes = []
    for envelope in (price, market_index, sector_index):
        if not isinstance(envelope, dict) or str(envelope.get('rt_cd')) != '0':
            raise ValueError('Successful source response required')
        quotes.append({**envelope, 'observed_at': envelope.get('received_at')})
    if not isinstance(bars, list):
        raise ValueError('Explicit source bars required')
    metadata = build_metadata(master, quotes[0], as_of=as_of)
    benchmark = build_benchmark(metadata, quotes[1], quotes[2], as_of=as_of)
    return {'metadata': metadata, 'benchmark': benchmark, 'bars': bars}


def make_capture_cycle(profile, token_manager, *, minute_responses, market_anchor_symbol, clock=None, holidays=()):
    clock = clock or (lambda: now_local('Asia/Seoul'))
    verifier = DatedMinuteVerifier(minute_responses, market_anchor_symbol=market_anchor_symbol,
        clock=clock, holidays=holidays)
    reader = CandidateRestReader(profile, token_manager, verifier=verifier, clock=clock)
    return CaptureCycle(reader, clock=clock, holidays=holidays)


def replay_comparison(events, folder, contract, *, execute_paper=False):
    if not isinstance(events, list) or not 0 < len(events) <= 10000:
        raise ValueError('Bounded explicit event list required')
    prepared, previous = [], None
    for event in events:
        raw = event['bar']
        if raw['symbol'] not in contract.symbols or type(raw['trade_count']) is not int or raw['trade_count'] <= 0:
            raise ValueError('Contract symbol and actual trade count required')
        observed = datetime.fromisoformat(event['observed_at'])
        stamp = datetime.fromisoformat(raw['bar_time'])
        if (observed.tzinfo is None or observed.utcoffset() is None or stamp.tzinfo is None
                or stamp.utcoffset() is None or previous is not None and observed < previous):
            raise ValueError('Aware chronological replay required')
        if any(type(raw[k]) not in (int, float) or not math.isfinite(raw[k]) for k in ('open','high','low','close','volume')):
            raise ValueError('Finite bar evidence required')
        stamp, observed = stamp.astimezone(KST), observed.astimezone(KST)
        prices = (raw['open'],raw['high'],raw['low'],raw['close'])
        age = (observed-(stamp+timedelta(minutes=1))).total_seconds()
        if (not all(p>0 for p in prices) or raw['volume']<0
                or not raw['low'] <= min(raw['open'],raw['close']) <= max(raw['open'],raw['close']) <= raw['high']
                or stamp.second or stamp.microsecond or not 0<=age<=120
                or not time(9)<=stamp.time().replace(tzinfo=None)<time(15,30)
                or stamp.weekday()>=5 or stamp.date().isoformat() in contract.holidays
                or stamp.date().isoformat()<contract.start_date):
            raise ValueError('Closed valid trading-session bar required')
        bar = MinuteBar(symbol=raw['symbol'], bar_time=stamp,
            **{k:raw[k] for k in ('open','high','low','close','volume','trade_count')})
        capture = event.get('capture')
        if capture is not None:
            if capture.get('source_binding_version') != SOURCE_BINDING_VERSION:
                raise ValueError('Comparison source contract mismatch')
            scan_kis_snapshot(capture, as_of=observed, holidays=contract.holidays)
            source = capture.get('observations', {}).get(bar.symbol, {}).get('bars', [])
            if (not source or datetime.fromisoformat(source[-1]['bar_time']) != bar.bar_time
                    or any(source[-1][k] != getattr(bar,k) for k in ('open','high','low','close','volume'))):
                raise ValueError('Capture event identity mismatch')
        spread = event.get('quote_spread_bps')
        if spread is not None and (type(spread) not in (int, float) or not math.isfinite(spread) or spread < 0):
            raise ValueError('Explicit spread evidence invalid')
        prepared.append((bar, observed, spread, capture));previous=observed
    if execute_paper is not True:
        return {'status':'validated_no_execution','events':len(prepared),'network_calls':0,
            'order_calls':0,'runtime_attached':False,'wallets_created':False}
    comparison = CandidateComparison(folder, contract)
    try:
        for bar, observed, spread, capture in prepared:
            comparison.observe(bar, observed_at=observed, quote_spread_bps=spread, capture=capture)
        return comparison.report(as_of=previous)
    finally:
        comparison.close()
