"""Bounded same-connection WS inputs for isolated candidate paper operation."""
from collections import deque
from datetime import datetime,timedelta
import math
import re
from threading import RLock

from app.features.minute_bars import aggregate_ticks_to_minute_bar
from app.storage.contracts import MarketTickEvent
from app.universe.intraday_candidates import KST, _hash
from app.utils.time import now_local


class CandidateLiveFeed:
    def __init__(self,symbols,*,clock=None,holidays=()):
        self.symbols=tuple(symbols)
        if (not 1<=len(self.symbols)<=2 or len(set(self.symbols))!=len(self.symbols)
                or any(not isinstance(s,str) or not re.fullmatch(r'[0-9]{6}',s) for s in self.symbols)):
            raise ValueError('One or two frozen domestic symbols required')
        self.clock=clock or (lambda:now_local('Asia/Seoul'))
        self.holidays=tuple(holidays)
        self.states={};self.gap_count=0;self.cumulative_jump_count=0;self._lock=RLock()

    def _now(self):
        now=self.clock()
        if now.tzinfo is None or now.utcoffset() is None:raise ValueError('Aware feed clock required')
        return now.astimezone(KST)

    def _stamp(self,day,hour,now):
        if not isinstance(day,str) or not re.fullmatch(r'[0-9]{8}',day) or not re.fullmatch(r'[0-9]{6}',str(hour)):
            raise ValueError('Actual WS business date and time required')
        stamp=datetime.strptime(day+hour,'%Y%m%d%H%M%S').replace(tzinfo=KST)
        if (stamp.date()!=now.date() or now.weekday()>=5 or now.date().isoformat() in self.holidays
                or not '090000'<=hour<='153000' or not timedelta(0)<=now-stamp<=timedelta(seconds=20)):
            raise ValueError('WS provider date/time stale, future or outside session')
        return stamp

    def observe_record(self,tr_id,record):
        symbol=record.get('MKSC_SHRN_ISCD')
        if symbol not in self.symbols or tr_id not in ('H0STCNT0','H0STASP0'):return False
        with self._lock:
            now=self._now()
            if tr_id=='H0STCNT0':
                stamp=self._stamp(record.get('BSOP_DATE'),record.get('STCK_CNTG_HOUR'),now)
                price=float(record['STCK_PRPR']);qty=int(record['CNTG_VOL']);cumulative=int(record['ACML_VOL'])
                if not math.isfinite(price) or price<=0 or qty<=0 or cumulative<qty:raise ValueError('Invalid actual execution')
                minute=stamp.replace(second=0,microsecond=0)
                state=self.states.get(symbol)
                if state is None or state['minute'].date()!=minute.date():
                    state={'minute':minute,'ticks':[],'bars':deque(maxlen=21),'good':False,'cumulative':None}
                    self.states[symbol]=state
                previous=state['cumulative']
                if minute<state['minute'] or previous is not None and cumulative<=previous:return False
                # This subscription is an observed record stream, not a full exchange tape.
                # Never fabricate missing executions from an accumulated-volume delta.
                if previous is not None and cumulative-previous!=qty:
                    self.cumulative_jump_count+=1
                gap=minute>state['minute']+timedelta(minutes=1)
                if minute>state['minute']:
                    if state['good'] and state['ticks'] and minute==state['minute']+timedelta(minutes=1) and not gap:
                        bar=aggregate_ticks_to_minute_bar(symbol,state['ticks'])
                        state['bars'].append({k:v for k,v in bar.to_record().items() if k!='symbol'} | {
                            'available_at':now.isoformat(),'trade_count_scope':'captured_ws_records_only',
                            'volume_scope':'captured_ws_records_only'})
                    else:
                        state['bars'].clear()
                    state.update(minute=minute,ticks=[],good=not gap)
                if gap:
                    self.gap_count+=1;state['good']=False;state['bars'].clear()
                if len(state['ticks'])>=10000:raise ValueError('Candidate minute tick budget exceeded')
                state['ticks'].append(MarketTickEvent(symbol,stamp,price,qty,'kis-ws'))
                state.update(cumulative=cumulative,provider_at=stamp,received_at=now,
                             day=record['BSOP_DATE'],hour=record['STCK_CNTG_HOUR'])
            else:
                proof=self._anchor(symbol,now)
                stamp=self._stamp(proof['trade_date'].replace('-',''),record.get('BSOP_HOUR'),now)
                ask,bid=float(record['ASKP1']),float(record['BIDP1'])
                if not all(math.isfinite(v) and v>0 for v in (ask,bid)) or ask<bid:raise ValueError('Invalid WS book')
                self.states[symbol]['quote']={'rt_cd':'0','trade_date':proof['trade_date'],
                    'received_at':now.isoformat(),'provider_at':stamp.isoformat(),
                    'provider_source_hash':_hash({'anchor':proof,'hour':record['BSOP_HOUR'],'ask':ask,'bid':bid}),
                    'output1':{'askp1':ask,'bidp1':bid,'aspr_acpt_hour':record['BSOP_HOUR']}}
            return True

    def _anchor(self,symbol,now):
        state=self.states.get(symbol)
        if not state or 'provider_at' not in state:raise ValueError('Own WS business-date evidence missing')
        stamp=self._stamp(state['day'],state['hour'],now)
        if not timedelta(0)<=now-state['received_at']<=timedelta(seconds=20):raise ValueError('WS receipt stale')
        return {'symbol':symbol,'trade_date':stamp.date().isoformat(),'provider_at':stamp.isoformat(),
                'received_at':state['received_at'].isoformat(),'source':'kis-ws-business-day-v1'}

    def bars(self,symbol):
        with self._lock:return [dict(b) for b in self.states.get(symbol,{}).get('bars',())]

    def quote(self,symbol):
        with self._lock:
            now=self._now();self._anchor(symbol,now)
            quote=self.states.get(symbol,{}).get('quote')
            if not quote:raise ValueError('Fresh WS quote missing')
            for key in ('provider_at','received_at'):
                if not timedelta(0)<=now-datetime.fromisoformat(quote[key])<=timedelta(seconds=20):raise ValueError('WS book stale')
            return {**quote,'output1':dict(quote['output1'])}

    def preflight(self,path,params):
        with self._lock:
            now=self._now()
            if path.endswith(('volume-rank','inquire-index-price')):
                for symbol in self.symbols:
                    try:return symbol,self._anchor(symbol,now),now
                    except ValueError:continue
                raise ValueError('Current observed WS business date missing')
            if not path.endswith(('inquire-price','inquire-asking-price-exp-ccn')):raise ValueError('Unsupported read path')
            symbol=params.get('FID_INPUT_ISCD')
            return symbol,self._anchor(symbol,now),now

    def __call__(self,path,params,response):
        symbol,anchor,now=self.preflight(path,params)
        scope=('market_trading_day_context_only' if path.endswith('volume-rank') else
               'index_market_day_context_only' if path.endswith('inquire-index-price') else 'same_symbol_ws_business_day')
        if path.endswith('inquire-price') and response['output'].get('stck_shrn_iscd')!=symbol:raise ValueError('Price owner mismatch')
        proof={'verification_version':'kis-exchange-day-anchor-v1','trade_date':anchor['trade_date'],
               'verified_at':now.isoformat(),'verification_scope':scope}
        if path.endswith('inquire-asking-price-exp-ccn'):
            proof['provider_at']=self._stamp(anchor['trade_date'].replace('-',''),response['output1']['aspr_acpt_hour'],now).isoformat()
        proof['source_hash']=_hash({'anchor':anchor,'path':path,'scope':scope,'provider_at':proof.get('provider_at')})
        return proof
