"""Read-only, bounded view of the two isolated candidate wallets."""
from html import escape
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
from time import monotonic

from app.brokers.kis_paper_registration import SUBDIRECTORY
from app.universe.candidate_discovery import read_discovery_registration

READ_BUDGET_SECONDS=0.05

STRATEGIES={'breakout':'돌파','trend_pullback':'눌림목'}
NAMES={'001440':'대한전선','006800':'미래에셋증권'}
EVENT_FIELDS=('kind','event_time','symbol','side','qty','price','commission','tax',
              'slippage_cost','spread_cost','reason','decision_id','execute_at','source_bar_id')


def _read(path):
    try:
        if path.resolve()!=path or not path.is_file() or path.stat().st_size>2_000_000 or path.stat().st_nlink!=1:return {}
        data=json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data,dict) else {}
    except (OSError,ValueError):return {}


def _day(report):
    value=report.get('day') or str(report.get('updated_at',''))[:10]
    return value if re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(value)) else None


def archive_candidate_report(runtime_root):
    folder=Path(runtime_root).absolute()/SUBDIRECTORY
    report=_read(folder/'latest-runtime.json');day=_day(report)
    if not day:raise ValueError('Dated runtime report required')
    path=folder/'days'/(day+'.json')
    if path.resolve()!=path:raise ValueError('Linked report archive')
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        with path.open('x',encoding='utf-8') as handle:json.dump(report,handle,ensure_ascii=True,sort_keys=True)
    return path


def load_candidate_dashboard(runtime_root,selected_date=None):
    folder=Path(runtime_root).absolute()/SUBDIRECTORY
    latest=_read(folder/'latest-runtime.json');day=_day(latest)
    history=[]
    for p in sorted((folder/'days').glob('????-??-??.json'))[-20:]:
        item=_read(p)
        if item:history.append(item)
    if selected_date and selected_date!=day:
        latest=_read(folder/'days'/(str(selected_date)+'.json')) if re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(selected_date)) else {}
        day=_day(latest)
    data=dict(status='not_available',conclusion='운용 기록 없음',day=day,report=latest,
              events=[],positions=[],observations=[],history=history,warnings=[],event_limit_per_wallet=200,
              discovery_enabled=read_discovery_registration(folder),discovery={})
    if not latest:return data
    discovery=latest.get('discovery',{})
    if isinstance(discovery,dict) and discovery.get('day')==day:data['discovery']=discovery
    wallets={}
    for strategy,wallet in latest.get('comparison',{}).get('wallets',{}).items():
        stats=wallet.get('daily_history',{}).get(day,{})
        current=wallet.get('trade_date')==day
        wallets[strategy]={**wallet,'day_source_bar_count':stats.get('source_bars',0),
            'day_virtual_fill_count':stats.get('fills',0),
            'daily_net_pnl':wallet.get('daily_net_pnl') if current else None,
            'day_status':wallet.get('day_status') if current else 'awaiting_first_bar'}
    data['wallets']=wallets
    source_count=max((w['day_source_bar_count'] for w in wallets.values()),default=0)
    fills=sum(w['day_virtual_fill_count'] for w in wallets.values())
    rejections=latest.get('record_rejections',0)
    unexpected_rejections=rejections-latest.get('rejection_reasons',{}).get('outside_session',0)
    if source_count==0 and unexpected_rejections>0:
        data.update(status='input_failed',conclusion='입력 실패 · 가상매매 평가 불가')
    elif latest.get('status')=='blocked' or latest.get('http_blocked'):
        data.update(status='blocked',conclusion='원천/실행 차단 · 신규 진입 보류')
    elif source_count==0:data.update(status='warming_up',conclusion='완료 분봉 축적 대기')
    elif fills==0:data.update(status='observing',conclusion='관측 완료 · 체결 없음 · 수익성 미판정')
    else:data.update(status='paper_results',conclusion='가상체결 결과 · 실전 수익성 미검증')
    for strategy in STRATEGIES:
        database=folder/'wallets'/strategy/'mission.db'
        if database.resolve()!=database or not database.is_file():continue
        if database.stat().st_nlink!=1 or database.stat().st_size>200_000_000:
            data['warnings'].append(strategy+': 원장 읽기 제한');continue
        try:
            with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=0.2)) as con:
                deadline=monotonic()+READ_BUDGET_SECONDS
                con.set_progress_handler(lambda:int(monotonic()>deadline),1000)
                rows=con.execute("SELECT payload FROM mission_events WHERE kind IN ('decision','fill','cancel') AND json_valid(payload) AND substr(json_extract(payload,'$.event_time'),1,10)=? ORDER BY seq DESC LIMIT 200",(day,)).fetchall()
                for row, in rows:
                    if len(row)>16000:continue
                    item=json.loads(row)
                    data['events'].append({'strategy':strategy,**{k:item[k] for k in EVENT_FIELDS if k in item}})
                rows=con.execute("SELECT payload FROM mission_events WHERE kind='observation' AND json_valid(payload) AND substr(json_extract(payload,'$.event_time'),1,10)=? ORDER BY seq DESC LIMIT 200",(day,)).fetchall()
                for row, in rows:
                    if len(row)>16000:continue
                    item=json.loads(row)
                    data['observations'].append({'strategy':strategy,**{k:item[k] for k in ('event_time','symbol','reason','close') if k in item}})
                try:
                    row=con.execute('SELECT payload FROM mission_state WHERE singleton=1').fetchone()
                    state=json.loads(row[0]) if row and len(row[0])<2_000_000 else {}
                    if state.get('trade_date')==day:
                        for symbol,position in state.get('positions',{}).items():
                            data['positions'].append({'strategy':strategy,'symbol':symbol,
                                **{k:position.get(k) for k in ('qty','avg_price','opened_at')},
                                'mark_price':position.get('last_price'),
                                **{k:state.get('position_meta',{}).get(symbol,{}).get(k) for k in ('peak_close','stop_distance')}})
                except sqlite3.Error:pass
        except (sqlite3.Error,ValueError,OSError):data['warnings'].append(strategy+': 원장 읽기 실패/조회 예산 초과 · 상세 일부 미표시')
    data['events'].sort(key=lambda e:str(e.get('event_time','')),reverse=True)
    data['events']=data['events'][:200]
    return data


def render_candidate_dashboard(data):
    def text(v):return escape('-' if v is None else str(v),quote=True)
    def number(v):
        if v is None:return '-'
        try:return f'{float(v):,.2f}'.removesuffix('.00')
        except (ValueError,TypeError):return text(v)
    def table(headers,rows):
        body=''.join('<tr>'+''.join('<td>'+text(c)+'</td>' for c in row)+'</tr>' for row in rows)
        if not body:body='<tr><td colspan="'+str(len(headers))+'">기록 없음</td></tr>'
        width=str(max(600,len(headers)*90))+'px' if len(headers)>2 else '100%'
        return '<div class="data-scroll"><table style="min-width:'+width+'"><thead><tr>'+''.join('<th>'+text(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+body+'</tbody></table></div>'
    report=data.get('report',{});wallets=data.get('wallets',{})
    parts=['<style>[data-tab-id="tab-candidate"]{min-width:0}[data-tab-id="tab-candidate"] td{overflow-wrap:anywhere;max-width:360px}[data-tab-id="tab-candidate"] th{white-space:nowrap}</style>',
        '<h2>새 가상매매</h2>', '<h3>'+text(data.get('conclusion'))+'</h3>',
        '<p>기준일 '+text(data.get('day'))+' · 마지막 관측 '+text(report.get('updated_at'))+' · 독립 가상계좌 · KIS 주문/취소 없음</p>']
    discovery=data.get('discovery',{})
    parts.append('<h3>광역 탐색 · 목표 50종목</h3>')
    parts.append(table(['탐색 지표','값'],[
        ['현재 광역 탐색 등록','활성' if data.get('discovery_enabled') else '비활성'],
        ['선택일 실제 탐색 / 목표',str(discovery.get('inspected_count',0))+' / 50'],
        ['반환 고유 종목',discovery.get('unique_returned_count')],
        ['선택일 탐색 상태',discovery.get('status','선택일 탐색 기록 없음')],
        ['최근 탐색 시각',discovery.get('observed_at')],
        ['2~3만원 가격대',discovery.get('preferred_price_count')],
        ['정밀 관측 종목',len(report.get('symbols',[]))],
        ['순위만으로 매매 허용',0]]))
    parts.append(table(['종목','이름','시장','가격','등락률 %','거래대금','전일 대비 누적량 배수','가격대','단계/진입 차단'],[
        [r.get('symbol'),r.get('name'),r.get('market'),number(r.get('price')),number(r.get('return_pct')),
         number(r.get('trading_value')),number(r.get('volume_ratio')),'2~3만원' if r.get('preferred_price_band') else '가격대 밖',
         r.get('entry_blocking_reason')] for r in discovery.get('candidates',[])[:50]]))
    parts.append(table(['운영 지표','값'],[
        ['관측 상태',report.get('status')],['현재 차단/대기 이유',report.get('reason')],
        ['회차 / 예약 GET',str(report.get('cycle_count',0))+' / '+str(report.get('reserved_gets',0))],
        ['수신 거부 / 실제 분 공백',f"{report.get('record_rejections',0):,} / {report.get('feed_gap_count',0):,}"],
        ['누적량 차이 관측',report.get('cumulative_jump_count')],['거부 사유',json.dumps(report.get('rejection_reasons',{}),ensure_ascii=False)],
        ['표본 계약',report.get('volume_scope','구버전: 원인별 수신 진단 미기록')],
        ['계약 hash',report.get('spec_hash')]]))
    if report.get('rejection_samples'):
        parts.append(table(['입력 거부 사유','비밀값 제외 원천 표본'],[
            [reason,json.dumps(sample,ensure_ascii=False)] for reason,sample in report['rejection_samples'].items()]))
    parts.append('<h3>전략별 계좌 · 비용 후 결과</h3>')
    rows=[]
    for strategy,label in STRATEGIES.items():
        w=wallets.get(strategy,{})
        rows.append([label,number(w.get('initial_cash')),number(w.get('cash_balance')),number(w.get('daily_net_pnl')),
            number(w.get('realized_net_pnl')),number(w.get('net_liquidation_after_exit_costs')),w.get('day_source_bar_count'),w.get('day_virtual_fill_count'),w.get('source_bar_count'),
            w.get('virtual_fill_count'),w.get('open_positions'),w.get('pending_order_count'),w.get('day_status')])
    parts.append(table(['전략','최초 현금','남은 현금','당일 순손익','누적 실현손익','청산비용 후 평가액','당일 분봉','당일 체결','누적 입력 분봉','누적 가상체결','보유','대기','결과'],rows))
    parts.append(table(['전략','누적 수수료','누적 매도세','누적 슬리피지','누적 스프레드','목표','손실 soft limit'],[
        [label,*[number(wallets.get(s,{}).get(k)) for k in ('commission','sell_tax','slippage_cost','spread_cost','daily_net_target','daily_loss_limit')]] for s,label in STRATEGIES.items()]))
    parts.append('<p>돌파: 가격·거래량 돌파 / 눌림목: 추세 내 회복. ATR 추적손절·최대 보유시간·장마감 청산. 비용은 고정 연구 가정이며 실제 계좌 요율은 미확인입니다. 두 계좌의 현금과 손익은 합산하지 않습니다.</p>')
    parts.append('<h3>종목별 수신 · 진입 판단</h3>')
    rows=[]
    for symbol in report.get('symbols',[]):
        p=report.get('symbol_progress',{}).get(symbol,{})
        rows.append([symbol,NAMES.get(symbol,'-'),report.get('warmup_bars',{}).get(symbol),p.get('accepted_trade_records'),
            p.get('accepted_book_records'),p.get('last_trade_received_at'),p.get('last_book_received_at'),p.get('last_rejection','구버전 상세 사유 없음')])
    parts.append(table(['종목','이름','연속 완료 분','체결 수신','호가 수신','최근 체결 수신','최근 호가 수신','입력 차단'],rows))
    scan=report.get('last_scan') or {}
    selected=(scan.get('scanner') or {}).get('selected',[])
    rejected=scan.get('adapter_rejections',[])+(scan.get('scanner') or {}).get('rejected',[])
    parts.append(table(['후보 판정','원천 증거'],[['선정',json.dumps(selected,ensure_ascii=False)[:10000]],['제외',json.dumps(rejected,ensure_ascii=False)[:10000]]]))
    parts.append('<h3>현재 보유</h3>')
    parts.append(table(['전략','종목','수량','평균가','평가가','진입 시각','최고 종가','손절 간격'],[
        [STRATEGIES.get(p['strategy']),p['symbol'],p.get('qty'),number(p.get('avg_price')),number(p.get('mark_price')),
         p.get('opened_at'),number(p.get('peak_close')),number(p.get('stop_distance'))] for p in data.get('positions',[])]))
    parts.append('<h3>판단 → 가상체결 · 최근 200건</h3>')
    parts.append(table(['시각','전략','종목','단계','방향','수량','체결가','수수료','세금','이유','결정 ID'],[
        [e.get('event_time'),STRATEGIES.get(e['strategy']),e.get('symbol'),e.get('kind'),e.get('side'),e.get('qty'),number(e.get('price')),
         number(e.get('commission')),number(e.get('tax')),e.get('reason'),e.get('decision_id')] for e in data.get('events',[])]))
    observations=data.get('observations',[])
    parts.append('<h3>최근 종목 판단 · 전략별 최대 200건</h3>')
    parts.append(table(['시각','전략','종목','관측 종가','보류/판단 이유'],[
        [e.get('event_time'),STRATEGIES.get(e['strategy']),e.get('symbol'),number(e.get('close')),e.get('reason')] for e in observations]))
    parts.append('<h3>일별 원장</h3>')
    history=[]
    for item in data.get('history',[]):
        for s,w in item.get('comparison',{}).get('wallets',{}).items():
            daily=w.get('daily_history',{}).get(_day(item),{})
            net=w.get('daily_net_pnl') if w.get('trade_date')==_day(item) else None
            history.append([_day(item),STRATEGIES.get(s,s),item.get('status'),daily.get('source_bars'),daily.get('fills'),number(net),number(w.get('cash_balance'))])
    parts.append(table(['날짜','전략','원천 상태','분봉','가상체결','당일 순손익','현금'],history))
    if data.get('warnings'):parts.append('<p>'+text(' / '.join(data['warnings']))+'</p>')
    return '\n'.join(parts)
