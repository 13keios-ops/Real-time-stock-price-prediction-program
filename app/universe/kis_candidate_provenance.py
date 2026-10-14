"""Offline KIS master parsing and same-symbol dated-minute evidence.

Download time and HTTP Date never establish a master effective day or quote day.
These helpers do not authorize collection or generate cross-symbol freshness proofs.
"""
import hashlib
import re
from datetime import datetime, timedelta

from app.universe.intraday_candidates import KST, _hash

# Byte offsets follow the official kis_kospi/kosdaq_code_mst.py fixed-width schemas.
COMMON = {'scrt_grp_cls_code': (0, 2), 'bstp_larg_div_code': (3, 4)}
SCHEMAS = {
    'KOSPI': (227, {**COMMON, 'etp_prod_cls_code': (22, 1), 'etpr_undt_objt_co_yn': (29, 1),
        'short_over_cls_code': (32, 1), 'trht_yn': (60, 1), 'sltr_yn': (61, 1),
        'mang_issu_yn': (62, 1), 'mrkt_alrm_cls_code': (63, 2), 'prdy_vol': (81, 12),
        'prst_cls_code': (158, 1)}),
    'KOSDAQ': (221, {**COMMON, 'etp_prod_cls_code': (18, 1), 'etpr_undt_objt_co_yn': (24, 1),
        'short_over_cls_code': (27, 1), 'invt_alrm_yn': (30, 1), 'trht_yn': (55, 1),
        'sltr_yn': (56, 1), 'mang_issu_yn': (57, 1), 'mrkt_alrm_cls_code': (58, 2),
        'prdy_vol': (76, 12), 'prst_cls_code': (153, 1)}),
}


def parse_stock_master(data, *, market):
    if market not in SCHEMAS or not isinstance(data, bytes) or not 0 < len(data) <= 10_000_000:
        raise ValueError('Invalid master source or size')
    width, fields = SCHEMAS[market]
    rows, excluded = {}, 0
    for line in data.splitlines():
        if len(line) < 21 + width:
            raise ValueError('Truncated master record')
        try:
            symbol = line[:9].decode('ascii').strip()
            line[9:-width].decode('cp949')
            tail = line[-width:].decode('ascii')
        except UnicodeDecodeError:
            raise ValueError('Invalid master record encoding') from None
        if not re.fullmatch(r'[0-9]{6}', symbol):
            excluded += 1
            continue
        if symbol in rows:
            raise ValueError('Duplicate master symbol')
        rows[symbol] = {'mksc_shrn_iscd': symbol,
            **{key: tail[offset:offset+size].strip() for key, (offset, size) in fields.items()}}
    return {'source': f'kis-stock-master-{market.lower()}-v1', 'reference_date': None,
        'layout_version': 'kis-fixed-width-stock-master-v1',
        'effective_day_verified': False, 'source_hash': hashlib.sha256(data).hexdigest(),
        'rows': rows, 'unsupported_symbol_rows': excluded}


def build_minute_day_anchor(payload, *, symbol, received_at, as_of, holidays=()):
    try:
        if (not isinstance(symbol, str) or not re.fullmatch(r'[0-9]{6}', symbol)
                or as_of.tzinfo is None or as_of.utcoffset() is None
                or received_at.tzinfo is None or received_at.utcoffset() is None):
            raise ValueError('Aware clocks and numeric symbol required')
        now, received = as_of.astimezone(KST), received_at.astimezone(KST)
        if now.weekday() >= 5 or now.date().isoformat() in holidays:
            raise ValueError('Trading-day context required')
        if not timedelta(0) <= now-received <= timedelta(seconds=20):
            raise ValueError('Minute receipt stale or future')
        rows = payload['output2']
        if str(payload.get('rt_cd')) != '0' or not isinstance(rows, list) or not 0 < len(rows) <= 30:
            raise ValueError('Successful bounded minute response required')
        normalized, times = [], []
        for row in rows:
            day, hour = row['stck_bsop_date'], row['stck_cntg_hour']
            if (not isinstance(day, str) or not isinstance(hour, str)
                    or not re.fullmatch(r'[0-9]{8}', day) or not re.fullmatch(r'[0-9]{6}', hour)):
                raise ValueError('Explicit exchange date/time required')
            stamp = datetime.strptime(day+hour, '%Y%m%d%H%M%S').replace(tzinfo=KST)
            if stamp.date() != now.date() or stamp > now or not '090000' <= hour <= '153000':
                raise ValueError('Minute exchange date/time invalid')
            if row.get('stck_shrn_iscd', symbol) != symbol:
                raise ValueError('Minute symbol mismatch')
            if stamp in times:
                raise ValueError('Duplicate dated minute')
            normalized.append({'stck_bsop_date': day, 'stck_cntg_hour': hour})
            times.append(stamp)
        latest = max(times)
        if now-latest > timedelta(seconds=180):
            raise ValueError('Latest dated minute is stale')
        source = {'path': '/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice',
            'tr_id': 'FHKST03010200', 'symbol': symbol, 'minutes': normalized}
        return {'version': 'kis-dated-minute-anchor-v1', 'symbol': symbol,
            'trade_date': latest.date().isoformat(), 'provider_at': latest.isoformat(),
            'received_at': received.isoformat(), 'source_hash': _hash(source),
            'scope': 'same_symbol_minute_response_only'}
    except (KeyError, TypeError, AttributeError):
        raise ValueError('Missing or invalid dated-minute evidence') from None


def make_master_reference(data, *, market, symbol, acquired_at):
    if acquired_at.tzinfo is None or acquired_at.utcoffset() is None:
        raise ValueError('Aware acquisition timestamp required')
    snapshot = parse_stock_master(data, market=market)
    if symbol not in snapshot['rows']:
        raise ValueError('Symbol absent from parsed master')
    return {k: snapshot[k] for k in ('source', 'source_hash', 'layout_version',
            'reference_date', 'effective_day_verified')} | {
        'acquired_at': acquired_at.astimezone(KST).isoformat(), 'output': snapshot['rows'][symbol]}


class DatedMinuteVerifier:
    """Trading-day context for ranking, own-symbol dated context for quotes.

    Inputs must come from the trusted request/response capture producer. This
    does not authenticate arbitrary JSON or authorize any additional API calls.
    """
    def __init__(self, minute_responses, *, market_anchor_symbol, clock, holidays=()):
        self.responses = minute_responses
        self.market_anchor_symbol = market_anchor_symbol
        self.clock = clock
        self.holidays = tuple(holidays)

    def preflight(self, path, params):
        ranking = path == '/uapi/domestic-stock/v1/quotations/volume-rank'
        index = path == '/uapi/domestic-stock/v1/quotations/inquire-index-price'
        price = path == '/uapi/domestic-stock/v1/quotations/inquire-price'
        book = path == '/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn'
        if not any((ranking, index, price, book)):
            raise ValueError('Unsupported verified quote path')
        symbol = self.market_anchor_symbol if ranking or index else params.get('FID_INPUT_ISCD')
        try:
            record = self.responses[symbol]
            if record['request_symbol'] != symbol:
                raise ValueError('Dated request owner mismatch')
            now = self.clock()
            anchor = build_minute_day_anchor(record['payload'], symbol=symbol,
                received_at=datetime.fromisoformat(record['received_at']), as_of=now, holidays=self.holidays)
            now = now.astimezone(KST)
            return symbol, anchor, now
        except (KeyError, TypeError, AttributeError):
            raise ValueError('Required dated quote context missing') from None

    def __call__(self, path, params, response):
        symbol, anchor, now = self.preflight(path, params)
        ranking = path.endswith('volume-rank')
        index = path.endswith('inquire-index-price')
        price = path.endswith('inquire-price')
        book = path.endswith('inquire-asking-price-exp-ccn')
        try:
            if price and response['output']['stck_shrn_iscd'] != symbol:
                raise ValueError('Price response owner mismatch')
            proof = {'verification_version': 'kis-exchange-day-anchor-v1',
                'trade_date': anchor['trade_date'], 'verified_at': now.isoformat(),
                'verification_scope': 'index_market_day_context_only' if index else
                    'market_trading_day_context_only' if ranking else 'same_symbol_dated_minute'}
            if book:
                hour = response['output1']['aspr_acpt_hour']
                if not isinstance(hour, str) or not re.fullmatch(r'[0-9]{6}', hour):
                    raise ValueError('Reported book time required')
                provider = datetime.strptime(anchor['trade_date']+hour, '%Y-%m-%d%H%M%S').replace(tzinfo=KST)
                if not timedelta(0) <= now-provider <= timedelta(seconds=20):
                    raise ValueError('Book provider time stale or future')
                if provider < datetime.fromisoformat(anchor['provider_at']):
                    raise ValueError('Book predates latest dated minute')
                proof['provider_at'] = provider.isoformat()
            proof['source_hash'] = _hash({'anchor': anchor, 'path': path, 'symbol': symbol,
                'scope': proof['verification_scope'], 'provider_at': proof.get('provider_at')})
            return proof
        except (KeyError, TypeError, AttributeError):
            raise ValueError('Required dated quote context missing') from None
