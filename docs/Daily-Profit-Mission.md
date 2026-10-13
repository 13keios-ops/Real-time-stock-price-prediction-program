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

1. 신규 회계/시각/비용/재시작/동시성/원천 경계 focused tests.
2. 활성화 전후 기존 decision/order/fill 원장 및 pipeline counter 불변 비교.
3. 기존 전체 unittest 및 구조 audit.
4. 실제 계약 초기화와 장외 status 확인.
5. 첫 미래 세션의 실제 실행 확인. 모의 수익 목표는 실전 승격 조건이 아니다.
