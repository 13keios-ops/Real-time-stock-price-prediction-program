# 30만원 독립 일일 수익 가상 서브미션

## 목적과 경계

- 운영자 수동 요청(2026-10-13): 국장에서 30만원으로 거래 비용 차감 후 하루 최소 1만원을 도전한다.
- 시작 거래일: 2026-10-14. 1만원은 성공 관측 목표이지 수익 보장, 거래 강제 조건 또는 이익 상한이 아니다.
- 기존 paper/KIS 운용, Phase 0, active model, signal/gate/allocator 및 E7 계약/원장과 분리한다.
- 사진의 ATR 그리드와 QLD RSI/스토캐스틱 규칙은 참고자료이며 그대로 구현하거나 유효성이 확인됐다고 주장하지 않는다.
- 이번 후보는 `kr-volume-breakout-atr-trailing-v1`이다. 작전주를 판별했다고 주장하지 않으며 공개 시세의 가격·거래량만 관측한다.
- 기존 수집 10개 ordinary KOSPI/KOSDAQ 주식만 사용한다. 전체 국장 스캐너나 추가 시세 API를 켠 것이 아니다.

## 고정된 후보 규칙

1. 연속된 완료 분봉 20개와 Wilder ATR(14)을 준비한다. 휴장일·시작 전·역행·미완료·120초 초과 stale 분봉은 거래하지 않는다. 분봉 공백 후 진입용 warmup은 다시 시작한다.
2. 이전 20개 분봉의 최고가를 현재 종가가 0.25~3 ATR 초과하고, 양의 1분 수익률이 3% 이내이며, 거래량이 이전 20분 평균의 1.5배 이상일 때만 신규 진입 후보를 만든다.
3. 20초 이내 유효 호가와 30bp 이하 스프레드가 필요하다. 사용 가능한 현금/당일 시작 현금의 최대 95%, 일손실 예산, 이전 평균 분당 거래량의 1% 및 정수 주 수량으로 크기를 제한한다.
4. 동시에 보유하는 종목은 최대 1개다. 물타기, 신용, 레버리지 상품, 공매도, 현금 재충전은 없다.
5. 손절 폭은 진입 당시 2 ATR 또는 가격의 0.6% 중 큰 값이다. 완료 종가의 최고값을 따라 추적한다. 청산 비용 포함 평가이익이 목표 이상이면 추적 폭을 75%로 줄이지만 목표 도달 자체로 매도하지 않는다.
6. 최대 보유 시간은 60분이다. 신규 진입 판단은 09:30~14:45 KST로 제한하며, 15:14부터 청산 판단을 만들고 15:15 시가 모의청산을 목표로 한다. 예상 종가 동시호가 공백 전이다.
7. 청산 비용 포함 일손실 6천원은 신규 진입 중단/청산을 유발하는 soft limit이다. 다음 가격의 gap 때문에 실제 모의손실이 이를 넘을 수 있으며 손실을 6천원으로 잘라 보고하지 않는다.
8. 보유가 모두 청산되고 당일 시작 현금 대비 비용 후 확정 순이익이 1만원 이상일 때만 `target_reached`다. 이후 신규 진입은 중단한다. 상승 중에는 추적 청산으로 1만원 초과 수익도 가능하다.
9. 다음 날에는 실제 남은 가상 현금으로 이어간다. overnight 보유가 남으면 해당 일의 수익 기준을 invalid로 표시하고 신규 진입을 차단한다.

위 수치들은 검증되지 않은 별도 후보의 시작 규칙이다. E7 threshold 0.55 및 기존 전략 숫자를 변경한 것이 아니다. 첫 미래 결과를 보고 사후에 유리한 체결 가격이나 매수 시각을 골라 성공을 만들지 않는다.

## 비용과 모의체결

- 편도 수수료 0.147%: 한국투자증권 공시 일반 영업점계좌의 KRX 온라인 요율을 가정한다. 사용자의 실제 계좌 요율이나 할인/뱅키스 적용 여부는 확인하지 않았다.
- ordinary KOSPI/KOSDAQ 매도세 합계 0.20%: 2026 기준. ETF/ETN 세제를 이 계좌에 혼합하지 않는다.
- 편도 스프레드 allowance 15bp: 허용하는 최대 30bp 호가 스프레드의 절반을 보수적으로 차감한다. 실측 평균 스프레드라고 주장하지 않는다.
- 편도 추가 슬리피지 3bp: 연구 가정으로 실제 fill calibration이 아니다.
- 동일 가격 왕복 기준 비용 가정은 약 0.854%다. 수수료와 세금은 체결별 원 단위 올림으로 차감한다. 공시 요율에 포함된 유관기관 비용을 다시 중복 차감하지 않는다.
- 스프레드/슬리피지는 매수 가격을 높이고 매도 가격을 낮추는 방식으로 가격에 한 번만 반영한다. 별도 비용 합계는 설명용이며 현금에서 두 번 빼지 않는다.
- 신호가 만들어진 분봉이나 이미 열린 분봉의 시가로 체결하지 않는다. 실제 판단 가용 시각 이후 다음 분 시작을 예약하고, 해당 분봉이 완료되어 원천 시가를 확인했을 때만 모의체결을 기록한다.
- 예약 분봉이 없으면 과거 가격으로 소급 체결하지 않는다. 가격 gap·현금 부족·거래량 부족·호가 부재는 진입을 취소한다.
- 현재/미래 분봉의 고가를 익절 체결로 쓰지 않는다. 이 모델은 open-price proxy이며 실제 주문 대기열, 부분체결, 체결 보장을 재현하지 않는다.

공식 참고:
- [한국투자증권 수수료·매매세 안내](https://www.truefriend.com/main/customer/guide/_static/TF04ae010000.jsp?templet-bypass=true)
- [Fidelity ATR 설명](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr): ATR은 방향 예측 자체가 아니라 변동성 지표다.

## 구현과 저장

- 엔진: `app/paper_trading/daily_mission.py`. 기존 `PaperTradingEngine`과 `PaperPortfolioBook`을 재사용하며 broker client/RuntimeWriter는 쓰지 않는다.
- 연결: 실제 `kis-ws`/`paper` pipeline의 기존 분봉·decision 기록이 완료된 뒤 별도 관측만 수행한다. 계약 파일이 없거나 비활성이면 별도 폴더/DB를 만들지 않는다. live/synthetic source에서는 붙지 않는다.
- 오류는 새 트랙을 fail-closed하고 기존 수집을 계속한다. thread lock과 SQLite 상태 CAS로 worker 경계 및 동시 writer 덮어쓰기를 막는다.
- 저장 루트: `runtime-data/paper-missions/krw-300k-daily-10k/` (물리적 D드라이브).
- `contract.json`: 명시 enabled flag, 시작일/종목/달력/자본/비용의 독립 계약.
- `mission.db`: 새 계좌의 input identity, decision→virtual fill, 현금/보유/일별 상태. 기존 `dev.db`에는 접근하지 않는다.
- `latest.json`, `days/YYYY-MM-DD.json`: 비용별 합계, 확정/청산추정 PnL, 목표 여부, pending/open, 원천 오류와 일별 이력.
- 계약 hash가 다르면 재초기화/장부 혼합을 거부한다. duplicate bar는 무시하고 conflicting identity는 진입을 차단한다. 기존 계좌나 E7 파일에 대한 링크/외부 DB schema도 거부한다.
- 기존 runtime watchdog의 정상 다음 시작을 이용한다. 새 Codex 예약, 추가 background daemon, 시세 호출, runtime 장외 시작은 필요하지 않다.

## 운영 명령

장외이며 runtime이 정지한 상태에서 명시 초기화한다. 기존 장부가 있으면 같은 계약만 허용하고 자본을 다시 넣지 않는다.

```bash
python3 scripts/run_daily_profit_mission.py --initialize --start-date 2026-10-14
python3 scripts/run_daily_profit_mission.py --status
```

상태 조회는 저장된 리포트를 읽으며 새 체결이나 과거 수익을 생성하지 않는다. 관측일/생성 시각이 이전이면 당일 결과로 해석하지 않는다.
실제 첫 세션에서 source_bar_count 증가, 가상 체결의 decision/fill 시각, 비용, 남은 현금, 목표 여부를 확인한다. 0건은 전략 성공도 실패도 아니며 원천 공백·warmup·필터·고가 종목의 수량 0을 구분한다.

## 검증 순서

### 두 후보 가상계좌 연결 준비 (격리 worktree)

`app/paper_trading/candidate_comparison.py`의 `CandidateComparison(folder, MissionContract(...))`는 돌파/눌림목에 각각 별도 `mission.db`/현금/보유/보고서를 둔다. 공통 계약과 두 전략의 버전은 `comparison.json`으로 고정하며 임의 종목 교체, 자본 초기화, 다른 계좌 폴더 재사용, symlink를 거부한다. 비교 지갑의 현금을 합쳐 단일 투자금이나 수익률로 보고하지 않는다.

- `observe(MinuteBar, observed_at=..., quote_spread_bps=..., capture=...)`: signal 판단에는 검증된 KIS capture가 필요하며 마지막 완료 분봉의 시간/OHLCV를 직접 대조한다. capture 없이 전달된 실제 시장 분봉은 warmup/기존 보유 mark·청산 및 이미 결정한 미래 모의체결에만 쓰고 새 entry를 만들지 않는다. `trade_count`를 포함한 실제 MinuteBar 공급은 아직 연결하지 않았다. 부재한 trade_count나 과거 provider 날짜를 합성하지 않는다.
- 각 전략은 선정기 순위 중 해당 신호가 있는 계약 내 최고 순위 종목만 고른다. 도착 순서에 따라 낮은 순위 후보를 먼저 매수하지 않는다. 진입은 기존 accounting engine의 20분 warmup/Wilder ATR/가용 시각 다음 분 체결/비용/손실 예산/volume 제한을 그대로 통과해야 한다. 선정기의 ATR SMA는 admission signal, 계좌의 Wilder ATR은 공통 sizing·청산이므로 평가 manifest에서 구분한다.
- core 기존 `_step`의 진입 판정을 `_entry_reason` hook으로 분리했다. 기존 DailyProfitMission의 기본 조건·계약 직렬화는 유지하고 비교 지갑만 검증된 외부 signal을 사용한다. 루트 코드에는 아직 이 refactor를 적용하지 않았다.
- comparison/strategy prefix가 있는 decision ID에 candidate_id/capture_hash를 저장하고 fill은 같은 decision ID로 연결한다. 지갑별 기존 SQLite transaction/CAS/중복 bar 처리를 재사용한다. 두 DB 사이의 원자적 동시 commit을 주장하지 않으며 source count 차이는 `partial_wallet_processing`으로 보고한다. 부분 처리 후 같은 입력을 재생하면 완료 지갑은 중복 처리하지 않는다.
- `report(as_of=...)`는 두 지갑의 cost/pnl/mark health를 각각 보여준다. `runtime_attached=false`, `profitability_validated=false`, `real_trading_enabled=false`다. 초기화와 fixture 테스트는 worktree `.tmp-tests`만 사용했고 운영 지갑을 켠 것이 아니다.

수집 연결의 다음 경계: 공식 source에서 당일 market/sector 수익률과 경보/보통주 metadata를 보존하고, 기존 paper REST/WS 예산과 충돌하지 않는 호출·subscription 한도를 확정한다. 기존 1회 승인으로 상시 polling을 켜지 않는다. 선정/구독 교체 시 보유·pending 종목 feed를 잃지 않아야 하며 별도 collector 장애는 기존 수집을 중단시키지 않아야 한다. 보호 세션에서는 새 network/구독/루트 적용 없이 구현만 준비한다.

### 당일 강세 종목 확장 (오프라인 단계)

기존 활성 계약을 바꾸지 않고 별도 후보 선정기를 구현했다. `app/universe/intraday_candidates.py`와 `scripts/scan_intraday_candidates.py`는 네트워크/DB/가상체결에 접근하지 않는다. 후보와 신호는 실행 주문이 아니며 `execution_enabled=false`다.

- 초기 정책: 주가 20,000~30,000원, 당일 누적 거래대금 10억원 이상, 양의 수익률 및 시장/업종 수익률 중 큰 값보다 +0.5%p 이상, volume ratio 1.5 이상, spread 30bp 이하, 최대 5종목. 동일 입력은 상대강도/거래량 비율/거래대금/종목코드 순으로 결정적으로 정렬한다. 수치는 최적화나 수익성 검증 결과가 아니다.
- 입력: JSON 배열의 각 행에 `symbol`, `market`(KOSPI/KOSDAQ), `instrument_type=common_stock`, `market_status=normal`, `price/bid/ask/trading_value/return_pct/market_return_pct/sector_return_pct/volume_ratio`, timezone-aware `observed_at/quote_at`, `bars` 21개를 요구한다. 정상 상태는 실제 공급자의 검증된 eligibility를 매핑해야 하며 누락을 정상으로 채우지 않는다. volume_ratio의 기준 기간은 실제 수집 adapter 계약에서 고정해야 한다.
- bars는 동일 당일의 연속 완료 분봉이며 각각 `bar_time/available_at/open/high/low/close/volume`을 가진다. 데이터 가용 시각 이후에만 사용한다. 입력 시각 60초/호가 20초 이내, 마지막 완료 분봉 120초 이내를 요구한다. 평일 09:30~14:45 창만 지원하며 실제 거래일 판정은 향후 collector에서 기존 달력을 적용해야 한다.
- 신호 비교: 돌파는 직전 20분 최고가를 0.25~3 ATR 초과/1분 상승 3% 이하/분 거래량 1.5배 조건이다. 눌림목은 최근 10분 고점이 앞선 10분보다 높고, 직전 종가 조정 후 양봉 회복, 최근 고점에서 0.25~2 ATR 이내, 분 거래량 평균 이상 및 closed-bar VWAP proxy 위를 요구한다. 후보 선정과 진입 신호는 별개여서 후보의 신호가 0개일 수 있다.
- 여기서 ATR은 현재 분봉 전 14개 true range의 단순 평균 `atr14_sma`이며 기존 미션의 Wilder ATR과 동일하다고 주장하지 않는다. VWAP은 21개 완료 분봉 typical-price/volume proxy이지 실제 체결별/당일 VWAP이 아니다. 양 전략의 손익 비교는 아직 실행하지 않았다.
- 출력은 allowlist 숫자/종목/시각 및 정규화 입력 hash/정책 hash/안정 ID와 제외 taxonomy다. 임의 응답/자격정보/테마명을 출력하지 않는다. `theme_classification=not_available`; 테마/작전주 식별 기능은 없다.

읽기 전용 실행 (자격정보 불필요):

```bash
python3 scripts/scan_intraday_candidates.py --snapshot /path/to/sanitized-snapshot.json --as-of 2026-10-14T10:00:00+09:00
```

후속 연결 순서: (1) 공식 KIS 거래대금 순위의 실제 지원 환경과 입력/제외 필드 검증, market/sector/경보 metadata provenance 고정 (2) 기존 10종목 WS 구독을 보존하며 별도 bounded 시세 수집 및 지연·단절·한도 검사 (3) 당일 선정 시각/유효기간/교체 규칙 고정, 돌파·눌림목 각각 새 30만원 가상계좌/원장에 연결 (4) 동일 비용/체결/손실 예산의 독립 미래 비교. 현금·손익을 계좌끼리 합치지 않고 기존 미션/E7을 변경하지 않는다. 풀매수를 강제하지 않으며 sizing/청산에는 기존 비용·손실 위험 검사를 재사용한다.

`kis-intraday-snapshot-adapter-v1`은 (1)의 오프라인 입력 경계를 구현한 것이다. `scan_intraday_candidates.py --format kis-capture --snapshot ... --as-of ...`로 실행한다. 자동 API 조회/WS 구독/가상 체결을 켜는 옵션은 없다.

- capture envelope: `source=kis-volume-rank-krx-v1`, 검증된 `trade_date`, timezone-aware `received_at`, 원래 순위 `rows`, symbol-keyed `observations`다. rows의 `mksc_shrn_iscd/acml_vol/prdy_vol`을 사용한다. `0009K0`처럼 숫자형 기존 계약 밖의 코드는 한 행만 제외하며 전체 숫자형 모집단을 중단하지 않는다. 같은 코드가 중복이면 원천 전체를 차단한다.
- observations[symbol]은 price(`received_at/trade_date/output`), orderbook(`received_at/provider_at/output1`), metadata(`observed_at/trade_date/market/instrument_type/flags`), benchmark(`observed_at/trade_date/market_return_pct/sector_return_pct`), bars를 요구한다. bars의 동일 종목 연결은 envelope 생산자의 책임이며 실제 수집기는 direct source identity를 보존해야 한다. 완전한 fixture는 `tests/test_kis_candidate_snapshot.py`에 있다.
- 경보 flags는 investment_caution/warning/risk, management, liquidation, trading_halt, short_term_overheat가 모두 실제 bool false여야 한다. margin/종목 상태 코드 `55`, 제외 mask 성공, 임의 기본값 N/0은 정상 거래 가능 증거가 아니다. 경보/분류의 독립적인 실제 공급원 연결은 아직 없다.
- 거래량 배수의 고정 기준은 `acml_vol / prdy_vol`(당일 누적/전일 전체 거래량)이며 같은 시각 대비 또는 분봉 평균 대비 증가율이 아니다. KIS `vol_inrt` 보고 숫자는 사용하지 않고, 전일 분모 누락/0이면 차단한다. scanner 1.5 조건은 이 기준으로 평가하며 장초반에 충족하기 어려울 수 있다. 지표의 수익성을 검증한 것이 아니다.
- price/ranking/metadata/benchmark는 같은 검증 거래일에 60초 이내, quote provider/received는 20초 이내이고 provider가 receipt보다 미래이면 차단한다. HHMMSS만으로 거래일을 임의 조립하지 않는다. `holidays`는 Python entrypoint에서 공급할 수 있고 실제 collector는 기존 달력을 적용해야 한다; CLI는 검증용이며 거래일 운용 서비스를 대신하지 않는다.
- adapter source_hash는 버전/volume basis/정규화 입력/가용 시각/실제 flags/제외 taxonomy의 hash다. 임의 원본 응답 전체 hash 또는 공급원 인증 서명이 아니다. 비밀값/임의 추가 필드는 출력과 정규화 hash에서 제외한다. 원본 파일의 보존 hash는 별도 capture 호환 보고가 소유한다.
- 앞선 장외 연결 capture는 envelope를 충족하지 않으며 새로운 입력으로 가장하지 않는다. 원천 날짜·분모·경보·benchmark·분봉·호가 날짜 누락을 모두 별도 남겼다. 기존 1회 조회 승인을 반복 API 호출이나 상시 collector 승인으로 확대하지 않는다.

공식 API 검토 근거: https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/volume_rank/volume_rank.py (`FHPST01710000`, `FID_BLNG_CLS_CODE=3` 거래금액순). 공식 예제에는 대상 mask 길이 설명과 구현 불일치 주석이 있어 문서만 보고 지원/실제 제외 동작을 확정하지 않는다. 사용자 승인 1회 연결 조회는 성공했지만 상시 수집이나 mask의 실제 안전 분류 검증은 아니며 현재 결과는 STATUS와 보존 capture를 따른다.

1. 신규 회계/시각/비용/재시작/동시성/원천 경계 focused tests.
2. 활성화 전후 기존 decision/order/fill 원장 및 pipeline counter 불변 비교.
3. 기존 전체 unittest 및 구조 audit.
4. 실제 계약 초기화와 장외 status 확인.
5. 첫 미래 세션의 실제 실행 확인. 모의 수익 목표는 실전 승격 조건이 아니다.
