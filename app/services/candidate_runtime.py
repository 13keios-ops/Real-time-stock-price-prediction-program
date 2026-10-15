"""Bounded read-only source collection and two isolated virtual wallets."""
from datetime import datetime, timedelta, time
import hashlib
import io
import json
import logging
import os
import fcntl
import stat
from pathlib import Path
from threading import Event, Thread
from urllib.request import urlopen
import zipfile
from collections import Counter

from app.brokers.kis_auth import get_kis_profile, KisTokenManager
from app.brokers.kis_candidate_reader import CandidateRestReader, PATHS, RANK_QUERY
from app.brokers.kis_paper_coordinator import PaperCoordinatorBusy
from app.brokers.kis_paper_registration import SUBDIRECTORY, VERSION, read_registration, coordinator_for_profile
from app.collectors.candidate_live_feed import CandidateLiveFeed
from app.paper_trading.candidate_comparison import CandidateComparison
from app.paper_trading.daily_mission import MissionContract, _json
from app.services.candidate_pipeline import prepare_candidate_context
from app.storage.contracts import MinuteBar
from app.universe.intraday_candidates import _hash
from app.universe.kis_candidate_provenance import make_master_reference
from app.universe.kis_candidate_sources import VERSION as SOURCE_VERSION
from app.universe.kis_candidate_snapshot import scan_kis_snapshot
from app.utils.time import now_local

LOGGER = logging.getLogger(__name__)
SYMBOLS = ('001440', '006800')
PREFIX = '/uapi/domestic-stock/v1/quotations/'
MASTER_URL = 'https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip'


def _store(path, value):
    path = Path(path).absolute()
    if path.resolve() != path or path.exists() and path.stat().st_nlink != 1:
        raise ValueError('Linked candidate runtime file forbidden')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name+'.tmp')
    if temporary.exists() and (temporary.resolve()!=temporary or temporary.stat().st_nlink!=1):
        raise ValueError('Linked temporary runtime file forbidden')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        handle.write(_json(value)+'\n');handle.flush();os.fsync(handle.fileno())
    os.replace(temporary, path)


def _spec(contract):
    return dict(version=VERSION, symbols=list(SYMBOLS), max_gets_per_cycle=6,
        max_gets_per_day=2500, cycle_interval_seconds=60, broker_orders_allowed=False,
        ws_connection='existing_primary', max_additional_symbols=2,
        wallet_contract=contract.to_dict(), source_binding_version=SOURCE_VERSION)


def initialize_candidate_runtime(settings, *, start_date):
    if settings.trading_mode != 'paper':
        raise ValueError('Paper-only runtime')
    contract = MissionContract(start_date=start_date, symbols=SYMBOLS, holidays=settings.market_calendar.holidays)
    spec = _spec(contract);folder = settings.runtime_data_dir/SUBDIRECTORY
    flag = folder/'enabled.json'
    if flag.exists():
        previous = read_registration(settings.runtime_data_dir)
        if previous is None or previous['spec_hash'] != _hash(spec):
            raise ValueError('Runtime contract drift; never reset accounts')
    comparison = CandidateComparison(folder/'wallets', contract)
    try:
        report = dict(version=VERSION, status='armed_awaiting_market_session',
            spec_hash=_hash(spec), symbols=list(SYMBOLS), runtime_attached=False,
            comparison=comparison.report(), order_calls=0, network_calls=0,
            fees_verified=False, profitability_validated=False)
        if not flag.exists():
            _store(flag, dict(enabled=True, spec=spec, spec_hash=_hash(spec)))
        _store(folder/'latest-runtime.json', report)
        return report
    finally:
        comparison.close()


def acquire_master(folder, symbols, *, clock):
    # Read only the documented member; no extractall or disabled TLS validation.
    with urlopen(MASTER_URL, timeout=5) as response:
        compressed = response.read(2_000_001)
    if len(compressed) > 2_000_000:
        raise ValueError('Master download budget exceeded')
    with zipfile.ZipFile(io.BytesIO(compressed)) as archive:
        info = archive.getinfo('kospi_code.mst')
        if info.file_size > 10_000_000:
            raise ValueError('Master uncompressed budget exceeded')
        with archive.open(info) as member:
            raw = member.read(10_000_001)
    if len(raw) > 10_000_000:
        raise ValueError('Master content budget exceeded')
    acquired = clock()
    references = {s:make_master_reference(raw, market='KOSPI', symbol=s, acquired_at=acquired) for s in symbols}
    digest = hashlib.sha256(raw).hexdigest()
    directory = folder/'source-master';directory.mkdir(parents=True, exist_ok=True)
    path = directory/(digest+'.mst')
    if path.resolve() != path or path.is_symlink():
        raise ValueError('Linked master storage')
    if not path.exists():
        with path.open('xb') as handle:handle.write(raw)
    _store(directory/(acquired.strftime('%Y%m%dT%H%M%S')+'.json'),
           dict(source=MASTER_URL, acquired_at=acquired.isoformat(), sha256=digest, effective_day_verified=False))
    return references


class CandidateRuntime:
    def __init__(self, settings, registration, *, clock=None):
        self.clock = clock or (lambda:now_local('Asia/Seoul'))
        self.folder = settings.runtime_data_dir/SUBDIRECTORY
        self.spec = registration['spec'];self.spec_hash = registration['spec_hash']
        self.contract = MissionContract.from_dict(self.spec['wallet_contract'])
        self.symbols = self.contract.symbols
        self.feed = CandidateLiveFeed(self.symbols, clock=self.clock, holidays=self.contract.holidays)
        profile = get_kis_profile(settings)
        self.coordinator = coordinator_for_profile(profile)
        if self.coordinator is None:raise ValueError('Shared registration required')
        self.token_manager = KisTokenManager(profile, request_coordinator=self.coordinator)
        self.reader = CandidateRestReader(profile, self.token_manager, verifier=self.feed,
                                         clock=self.clock, request_coordinator=self.coordinator)
        self.stop = Event();self.thread = None;self.status = 'warmup';self.reason = 'awaiting_actual_ws_evidence'
        self.http_blocked = False;self.request_count = 0;self.cycle_count = 0
        self.day = self.clock().date().isoformat();self.last_cycle = None;self.master = None
        self.last_delivered = {};self.record_rejections = 0;self.last_scan = None
        self.rejection_reasons=Counter();self.rejection_samples={}
        self.symbol_progress={s:{'accepted_trade_records':0,'accepted_book_records':0,'rejected_records':0} for s in self.symbols}
        self.owner_fd = os.open(self.folder/'runtime.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info=os.fstat(self.owner_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('Regular runtime lock required')
            fcntl.flock(self.owner_fd,fcntl.LOCK_EX | fcntl.LOCK_NB)
            budget = self.folder/'http-budget.json'
            if budget.exists():
                if budget.resolve()!=budget or budget.stat().st_size>4096 or budget.stat().st_nlink!=1:
                    raise ValueError('Invalid budget storage')
                stored = json.loads(budget.read_text())
                if stored.get('day') == self.day:
                    self.request_count = stored['reserved_gets'];self.http_blocked = stored['blocked']
                    if type(self.request_count) is not int or not 0<=self.request_count<=2500 or type(self.http_blocked) is not bool:
                        raise ValueError('Invalid persisted budget')
            self.comparison = CandidateComparison(self.folder/'wallets', self.contract)
            if self.comparison.report()['status']!='consistent':
                self.comparison.close()
                raise ValueError('Partial comparison write requires investigation')
        except Exception:
            os.close(self.owner_fd);self.owner_fd=None
            raise

    def observe_record(self, tr_id, record):
        symbol=record.get('MKSC_SHRN_ISCD')
        if symbol not in self.symbols:return
        progress=self.symbol_progress[symbol]
        try:
            accepted=self.feed.observe_record(tr_id, record)
            if accepted:
                kind='trade' if tr_id=='H0STCNT0' else 'book'
                progress['accepted_'+kind+'_records']+=1
                progress['last_'+kind+'_received_at']=self.clock().isoformat()
        except Exception as exc:
            self.record_rejections+=1;progress['rejected_records']+=1
            now=self.clock()
            reason=('outside_session' if not '090000'<=now.strftime('%H%M%S')<='153000' else
                    'missing_field' if isinstance(exc,KeyError) else
                    'source_validation_failed')
            self.rejection_reasons[reason]+=1;progress['last_rejection']=reason
            if reason not in self.rejection_samples:
                fields=('MKSC_SHRN_ISCD','BSOP_DATE','STCK_CNTG_HOUR','BSOP_HOUR','STCK_PRPR','CNTG_VOL','ACML_VOL','ASKP1','BIDP1')
                import re
                self.rejection_samples[reason]={k:str(record[k]) for k in fields
                    if k in record and re.fullmatch(r'[-+0-9.]{1,24}',str(record[k]))}

    def _budget(self):
        _store(self.folder/'http-budget.json',dict(day=self.day,reserved_gets=self.request_count,blocked=self.http_blocked))

    def read(self, path, params):
        if self.http_blocked or self.request_count >= 2500:
            raise ValueError('Candidate HTTP unavailable for session')
        self.request_count += 1;self._budget()
        try:
            result = self.reader.get(path, PATHS[path], params, timeout_seconds=3, allow_retry=False)
            if str(result.get('rt_cd')) != '0':
                self.reason = 'kis_business_error:'+str(result.get('msg_cd',''))
                raise ValueError('Candidate business error')
            return result
        except PaperCoordinatorBusy:
            self.request_count -= 1;self._budget();self.reason = 'primary_priority_deferred'
            raise
        except Exception:
            self.http_blocked = True
            if not self.reason.startswith('kis_business_error:'):self.reason = 'read_failed_no_retry'
            self._budget()
            raise ValueError('Candidate read stopped for session') from None

    def capture(self):
        calls = 0
        def get(endpoint, params):
            nonlocal calls
            if calls >= 6 or self.stop.is_set():raise ValueError('Cycle read budget exhausted')
            if calls and self.stop.wait(1.12):raise ValueError('Runtime stopping')
            calls += 1
            return self.read(PREFIX+endpoint, params)
        rank = get('volume-rank', dict(RANK_QUERY))
        sectors = {s:self.master[s]['output']['bstp_larg_div_code'] for s in self.symbols}
        if set(sectors.values()) != {'0027','0021'}:raise ValueError('Seed sector contract drift')
        indices = {code:get('inquire-index-price',dict(FID_COND_MRKT_DIV_CODE='U', FID_INPUT_ISCD=code))
                   for code in sorted({'0001', *sectors.values()})}
        prices = {s:get('inquire-price',dict(FID_COND_MRKT_DIV_CODE='J', FID_INPUT_ISCD=s)) for s in self.symbols}
        now = self.clock()
        observations = {}
        for symbol in self.symbols:
            bars = self.feed.bars(symbol);book = self.feed.quote(symbol)
            context = prepare_candidate_context(self.master[symbol],prices[symbol],indices['0001'],
                indices[sectors[symbol]],bars,as_of=now)
            observations[symbol] = dict(price=prices[symbol],orderbook=book,**context)
        capture = dict(source='kis-volume-rank-krx-v1', source_binding_version=SOURCE_VERSION,
            received_at=rank['received_at'],trade_date=rank['trade_date'],rows=rank['output'],observations=observations)
        self.last_scan = scan_kis_snapshot(capture,as_of=now,holidays=self.contract.holidays)
        self.cycle_count += 1
        return capture

    def deliver(self, bar, *, quote_spread_bps, capture):
        now = self.clock()
        if not 0 <= (now-bar.bar_time-timedelta(minutes=1)).total_seconds() <= 120:
            return
        event = dict(observed_at=now.isoformat(),bar=bar.to_record(),quote_spread_bps=quote_spread_bps,capture=capture)
        path = self.folder/'events.jsonl'
        if path.resolve()!=path or path.exists() and path.stat().st_nlink!=1:raise ValueError('Linked event journal')
        with path.open('a',encoding='utf-8') as handle:
            handle.write(_json(event)+'\n');handle.flush();os.fsync(handle.fileno())
        self.comparison.observe(bar,observed_at=now,quote_spread_bps=quote_spread_bps,capture=capture)
        self.last_delivered[bar.symbol] = bar.bar_time.isoformat()

    def step(self):
        now = self.clock();day = now.date().isoformat()
        if day != self.day:
            self.day=day;self.request_count=0;self.http_blocked=False;self.master=None;self.last_cycle=None
            self.rejection_reasons.clear();self.rejection_samples.clear()
            self._budget()
        if now.weekday()>=5 or day in self.contract.holidays or not time(9)<=now.time().replace(tzinfo=None)<=time(15,30):
            return
        bars = {s:self.feed.bars(s) for s in self.symbols}
        new = any(rows and rows[-1]['bar_time']>self.last_delivered.get(s,'') for s,rows in bars.items())
        if not new:return
        capture = None
        due = self.last_cycle is None or (now-self.last_cycle).total_seconds()>=60
        eligible_time = time(9,30)<=now.time().replace(tzinfo=None)<time(14,45)
        if due and eligible_time and all(len(b)==21 for b in bars.values()) and not self.http_blocked:
            self.last_cycle=now
            try:
                for symbol in self.symbols:self.feed.quote(symbol)
                if self.master is None:self.master=acquire_master(self.folder,self.symbols,clock=self.clock)
                capture=self.capture();self.status='running';self.reason='observing_no_forced_trades'
            except PaperCoordinatorBusy:pass
            except Exception:
                if not self.http_blocked:self.reason='source_context_blocked'
                self.http_blocked=True;self._budget()
            self.last_cycle=self.clock()
        for symbol,rows in bars.items():
            if capture is not None:rows=capture['observations'][symbol]['bars']
            try:
                quote=self.feed.quote(symbol);book=quote['output1']
                spread=(book['askp1']-book['bidp1'])/((book['askp1']+book['bidp1'])/2)*10000
            except ValueError:spread=None
            for row in rows:
                if row['bar_time']<=self.last_delivered.get(symbol,''):continue
                bar=MinuteBar(symbol=symbol,bar_time=datetime.fromisoformat(row['bar_time']),
                    **{k:row[k] for k in ('open','high','low','close','volume','trade_count')})
                self.deliver(bar,quote_spread_bps=spread,capture=capture if row is rows[-1] else None)
        self.write_report()

    def report(self):
        return dict(version=VERSION,spec_hash=self.spec_hash,status=self.status,
            updated_at=self.clock().isoformat(),
            reason=self.reason, runtime_attached=self.thread is not None and self.thread.is_alive(),
            symbols=list(self.symbols),day=self.day,reserved_gets=self.request_count,
            reserved_gets_scope='conservative_before_dispatch_includes_failed_attempts',
            cycle_count=self.cycle_count,http_blocked=self.http_blocked,record_rejections=self.record_rejections,
            feed_gap_count=self.feed.gap_count,warmup_bars={s:len(self.feed.bars(s)) for s in self.symbols},
            feed_version='observed-ws-minute-v2',volume_scope='captured_ws_records_only',
            cumulative_jump_count=getattr(self.feed,'cumulative_jump_count',0),
            rejection_reasons=dict(self.rejection_reasons),rejection_samples=dict(self.rejection_samples),
            symbol_progress={symbol:dict(progress) for symbol,progress in self.symbol_progress.items()},
            last_scan=self.last_scan,comparison=self.comparison.report(as_of=self.clock()),
            order_calls=0,real_trading_enabled=False,fees_verified=False,profitability_validated=False)

    def write_report(self):
        report=self.report()
        _store(self.folder/'latest-runtime.json',report)
        _store(self.folder/'days'/self.clock().strftime('%Y-%m-%d.json'),report)

    def start(self):
        if self.thread is not None:raise ValueError('Runtime already attached')
        def run():
            last_report=None
            try:
                while not self.stop.wait(1):
                    self.step()
                    now=self.clock()
                    if last_report is None or (now-last_report).total_seconds()>=30:
                        self.write_report();last_report=now
            except Exception:
                self.status='blocked';self.reason='local_runtime_failure';self.http_blocked=True
                LOGGER.error('Isolated candidate worker stopped; primary pipeline continues')
                try:self.write_report()
                except Exception:LOGGER.error('Candidate report unavailable')
        self.thread=Thread(target=run,name='candidate-paper',daemon=True);self.thread.start()
        self.write_report()

    def close(self):
        if self.owner_fd is None:return
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=30)
            if self.thread.is_alive():
                LOGGER.error('Candidate worker still stopping; wallet storage kept open')
                return
        self.status='stopped'
        try:self.write_report()
        finally:
            self.comparison.close()
            os.close(self.owner_fd);self.owner_fd=None


def load_candidate_runtime(settings, *, primary_symbols, clock=None):
    if getattr(settings,'trading_mode',None) != 'paper':return None
    registration=read_registration(settings.runtime_data_dir)
    if registration is None:return None
    try:
        contract=MissionContract.from_dict(registration['spec']['wallet_contract'])
        expected = MissionContract(start_date=contract.start_date, symbols=SYMBOLS,
                                   holidays=settings.market_calendar.holidays)
        if (_hash(_spec(expected))!=registration['spec_hash'] or contract.symbols!=SYMBOLS
                or contract.holidays!=settings.market_calendar.holidays
                or len(set(primary_symbols)|set(SYMBOLS))*2>40):
            raise ValueError('Runtime scope drift or subscription budget exceeded')
        return CandidateRuntime(settings,registration,clock=clock)
    except Exception:
        LOGGER.error('Candidate runtime activation rejected; primary subscriptions unchanged')
        return None
