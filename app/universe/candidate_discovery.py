"""Broad rank screening is not quote validation, a signal, or trade permission."""
from datetime import datetime,timedelta
import json
import math
from pathlib import Path
import re

from app.universe.intraday_candidates import KST,_hash

SPEC=dict(version='kr-rank-discovery-50-v1',target_count=50,markets=['KOSPI','KOSDAQ'],
          interval_seconds=300,max_gets_per_cycle=2,shared_daily_get_limit=2500,
          broker_orders_allowed=False,changes_wallet_universe=False)


def read_discovery_registration(folder):
    path=Path(folder).absolute()/'discovery-enabled.json'
    try:
        if path.resolve()!=path or not path.is_file() or path.stat().st_size>8192 or path.stat().st_nlink!=1:return False
        value=json.loads(path.read_text(encoding='utf-8'))
        return (isinstance(value,dict) and type(value.get('enabled')) is bool and value['enabled']
            and value.get('spec')==SPEC and value.get('spec_hash')==_hash(SPEC)
            and _hash(value['spec'])==_hash(SPEC))
    except (OSError,ValueError):return False


def screen_rankings(snapshots,*,as_of):
    if as_of.tzinfo is None or set(snapshots)!=set(SPEC['markets']):raise ValueError('Two dated market snapshots required')
    as_of=as_of.astimezone(KST);rows={};invalid=duplicates=0
    for market,snapshot in snapshots.items():
        stamp=datetime.fromisoformat(snapshot['received_at'])
        if (stamp.tzinfo is None or snapshot.get('rt_cd')!='0'
                or snapshot.get('trade_date')!=as_of.date().isoformat()
                or snapshot.get('verification_scope')!='market_trading_day_context_only'
                or not timedelta(0)<=as_of-stamp<=timedelta(seconds=20)):
            raise ValueError('Unverified discovery market context')
        output=snapshot.get('output')
        if not isinstance(output,list) or len(output)>1000:raise ValueError('Rank response budget exceeded')
        for raw in output:
            try:
                symbol=raw['mksc_shrn_iscd']
                if not isinstance(symbol,str) or not re.fullmatch(r'[0-9]{6}',symbol):raise ValueError('Unsupported symbol')
                price,change,volume,previous,value=[float(raw[k]) for k in (
                    'stck_prpr','prdy_ctrt','acml_vol','prdy_vol','acml_tr_pbmn')]
                if (not all(math.isfinite(v) for v in (price,change,volume,previous,value))
                        or price<=0 or min(volume,previous,value)<0):raise ValueError('Invalid rank values')
                if symbol in rows:duplicates+=1;continue
                preferred=20000<=price<=30000
                rows[symbol]=dict(symbol=symbol,name=str(raw.get('hts_kor_isnm',''))[:80],market=market,
                    price=price,return_pct=change,trading_value=value,accumulated_volume=volume,
                    previous_day_volume=previous,volume_ratio=volume/previous if previous>0 else None,
                    preferred_price_band=preferred,stage='rank_screen_only',
                    entry_blocking_reason='requires_fresh_quote_flags_benchmark_and_21_bars' if preferred else 'outside_existing_price_band')
            except (KeyError,TypeError,ValueError,OverflowError):invalid+=1
    ranked=sorted(rows.values(),key=lambda row:(-row['trading_value'],row['symbol']))
    candidates=ranked[:SPEC['target_count']]
    return dict(version=SPEC['version'],day=as_of.date().isoformat(),observed_at=as_of.isoformat(),
        target_count=SPEC['target_count'],unique_returned_count=len(rows),inspected_count=len(candidates),
        coverage_met=len(candidates)>=SPEC['target_count'],status='screened' if len(candidates)>=50 else 'insufficient_unique_symbols',
        trade_ready_count=0,proof_scope='market_day_context_not_per_symbol_quote_freshness',
        preferred_price_count=sum(r['preferred_price_band'] for r in candidates),
        invalid_row_count=invalid,duplicate_row_count=duplicates,candidates=candidates,
        source_hash=_hash(dict(day=as_of.date().isoformat(),candidates=candidates)),order_calls=0)
