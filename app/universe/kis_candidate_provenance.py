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
