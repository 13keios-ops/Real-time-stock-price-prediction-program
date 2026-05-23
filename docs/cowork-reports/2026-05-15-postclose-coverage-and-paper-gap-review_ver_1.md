# Claude cowork 리뷰: 2026-05-15 장후 KIS coverage watch + paper dual account gap 운영 판단

## 검토 대상

- KIS live data quality: `runtime-data/reports/data-quality/latest-kis-live-data-quality.{json,md}`
- Paper dual account match: `runtime-data/reports/reconciliation/latest-paper-dual-account-match.{json,md}`
- 운영자 질문 두 가지:
  - Q1: 09:28 시작 공백 때문에 KIS live coverage가 watch가 된 해석이 맞는지
  - Q2: 현대차 1주 보유 상태에서 cash_gap 200,575.39 / total_asset_gap 61,275.39를 자동 align하지 않고 운영자 확인으로 둔 판단이 안전한지

## 요약

두 판단 모두 **운영 안전 측면에서 적절하다.** 단 Q1에 추가 검증이 한 가지 필요하고, Q2는 안전한 판단이지만 운영 부담을 줄이려면 임계 정책 한 줄을 합의해 두는 게 좋다.

## Q1: 09:28 시작 공백 때문에 watch가 됐다는 해석이 맞는가

**거의 맞다. 80% 정도 설명되고 나머지 20%는 별도 검증이 필요하다.**

먼저 숫자로 검증한다. 2026-05-15 데이터:

- expected_symbol_minutes: 3,910 (09:00~15:30 = 391분 × 10종목)
- closed_expected_symbol_minutes: 3,900 (마지막 닫히지 않은 1분 제외)
- market_symbol_minutes: 3,496
- orderbook_symbol_minutes: 3,606
- bars: 3,456, features: 3,456
- coverage: market 89.4%, orderbook 92.2%, bar/feature 88.6% (closed 기준)
- assessment: watch (95% 미만 → watch, 80% 미만 → needs_attention)

비교: 정상 거래일(2026-05-12, 5/13, 5/14)의 market_symbol_minutes는 모두 3,766~3,802 범위다. 5/15는 3,496이라 약 270~310 symbol-minutes가 부족하다.

**09:28 공백 가설 검증:**

- 만약 09:00~09:28까지 28분 공백이라면 손실량은 28 × 10 = 280 symbol-minutes
- 실제 부족분 270~310 범위와 거의 일치 → **가설 정합성 높음**
- closed coverage 88.6%로 환산하면 28/390 = 7.2% 손실 → 92.8% 예상이지만 실제 88.6%
- 즉 **28분 공백 외에 추가 5분 정도의 분산 손실이 있을 가능성**

따라서 watch 판정 자체는 정확히 임계 기준(95% 미만)대로 작동했고, "09:28 시작 공백이 주 원인"이라는 해석도 맞다. 단 **남은 5분 분산 손실의 원인은 별도 확인이 필요하다.** 가능한 후보:

- 09:28 이후에도 일부 종목/시각이 추가로 빠졌을 가능성
- 장중 일시 dropout (1~2분 단위 끊김)
- 특정 종목의 stream 불안정

추가 의문 한 가지: **orderbook coverage(92.2%)와 market coverage(89.4%)의 격차가 평소보다 작다.** 정상 거래일에는 orderbook이 market보다 약 7%p 높은 패턴(2026-05-14는 4030 vs 3766, 약 7%p)인데 5/15는 3.5%p 차이밖에 안 난다. 두 가지 해석이 가능하다:

- (a) 09:28 공백이 두 stream에 동일하게 영향을 줬고 정상 — 그러나 이러면 격차는 유지되어야 함
- (b) orderbook stream에도 추가 dropout이 있어 격차가 줄어듬 — silent bug 가능성

**결론: watch 판정과 09:28 가설은 정확하지만, 다음 두 가지를 별도 확인해야 같은 사고가 안 반복된다.**

1. **watchdog pre-open warmup이 정상 작동했는지.** 5/15 09:00 전 60분간 live runtime이 켜졌는지, 켜졌다면 09:00 정시에 KIS WS 구독이 됐는지. `runtime-data/reports/runtime-watchdog/state/`와 `live-runtime.stderr.log`의 5/15 09:00 전후 로그 확인.
2. **5분 분산 손실의 원천**과 orderbook 격차 축소가 같은 원인인지. live-runtime stderr에서 5/15 장중 reconnect/timeout 패턴 확인.

## Q2: 현대차 1주 보유 + cash_gap 200,575 + total_asset_gap 61,275를 자동 align하지 않고 운영자 확인으로 둔 판단이 안전한가

**안전한 판단이다.** 다섯 가지 이유.

먼저 데이터부터 정확히 본다:

- broker: 현대차 1주, average_buy_price 691,000, current_price 700,000 (평가 700k), cash_balance 9,826,689, total_asset 9,678,339 (수상함 — cash + stock = 10,526k인데 total은 9,678k로 적음. KIS 모의계좌의 total_asset 계산 정의가 cash + stock 단순합이 아닌 듯. effective_cash = total - stock = 8,978,339로 reconcile에서 사용됨)
- local: 현대차 1주, avg_price 691,228.03, last_price 691,000 (평가 691k), cash_balance 9,178,914.39, net_liquidation 9,739,614.39
- positions_match: **true** (수량 1주 정확히 일치)
- mismatch_count: 0
- cash_gap: broker 유효현금 8,978,339 - local 9,178,914 = **-200,575원**(절대값 200,575)
- total_asset_gap: 61,275원 (평가 가격 차이 + 누적 회계 차이)
- raw_cash_gap: -647,774원 (KIS raw cash가 stock 평가 합산을 포함하기 때문에 발생하는 자연 차이)

### 안전한 이유 다섯 가지

**첫째, positions_match=true이므로 가장 위험한 "수량 불일치" 시나리오는 없다.** 가장 위험한 사고 경로는 broker는 5주 보유, local은 1주만 안다는 식의 수량 격차 → 잘못된 PnL 계산 → 잘못된 게이트 판정 → 잘못된 신규 주문 — 이 경로가 닫혀 있다. 차이는 가격 평가와 누적 회계뿐이다.

**둘째, 200,575원 차이의 원인이 명확하지 않은 상태에서 자동 align은 silent fix가 된다.** align은 broker 기준으로 local baseline을 덮어쓰는 작업이다. 원인을 모르고 align하면 다음 거래일에 같은 차이가 또 발생하고, 매일 align만 누적된다. **차이의 원인 파악이 align보다 우선이다.** 자동 align을 거부한 정책이 이걸 강제한다.

**셋째, 200,575원의 가능한 원인은 단순 가격 시점 차이부터 silent bug까지 범위가 넓다.** 빠른 분석:

- 평가 금액 차이: broker 700k vs local 691k. 9,000원/주 차이. broker last_price가 17:40 조회 시점이고 local snapshot이 15:01 시점이라 시간차로 인한 가격 변동 가능성이 큼. 시장이 마감 후 지표 조정이나 reference price 갱신이 있었을 가능성.
- avg_price 차이: broker 691,000 vs local 691,228.03. 228원/주 차이. 누적 매수 평균 산정 방식 차이일 가능성(broker는 round?, local은 정확한 가중평균?).
- realized_pnl 누적: local -55,789.49(전체), 그 중 005380에서만 -12,910.48. broker는 누적 realized를 별도 추적하지 않음 → 직접 비교 불가.
- 누적 수수료/세금 차이: 568건 주문, 157건 체결. 거래당 수십~수백 원의 차이가 누적되면 200k 도달 가능.

**자동 align은 이 분석 자체를 차단한다.** 운영자 확인 정책은 분석 기회를 보존한다.

**넷째, raw_cash_gap이 -647,774원으로 cash_gap과 다른 점이 broker 모의계좌의 cash 표시 정의 차이를 시사한다.** KIS 모의계좌 total_asset_amount(9,678,339)와 cash + stock 단순합(10,526,689)이 약 848k 다르다. 이게 KIS 모의계좌 내부 회계의 특이점인지 silent bug인지 모르는 상태에서 자동 align은 위험. effective_cash 계산(total - stock = 8,978,339)으로 200k까지 줄였지만 broker side의 정본 정확도 자체가 의문스러운 상태.

**다섯째, paper 단계라 200k 차이는 실제 자금 손실 위험이 0이다.** 즉 분석 시간을 충분히 가질 수 있다. 실전 단계라면 200k 차이는 운영 즉시 차단 사유가 되지만, paper에서는 "정확한 원인 파악 후 진행"이 가능하다. 운영자 확인 정책은 이 여유를 활용한다.

### 보강 권장 한 가지

운영자가 매일 200k 단위 차이를 직접 보고 판단하는 부담이 있다. **임계 분기 정책 합의**가 다음 라운드에 도움이 된다:

- 차이 < N원 (예: 1,000원): 자동 align 허용, 사유 audit 기록
- 차이 N~M원 (예: 1,000~10,000원): 자동 align 보류, dashboard 경고만 표시, 운영자 확인 권장
- 차이 > M원 (예: 10,000원 이상): 자동 align 차단, 신규 주문 차단(safety), 운영자 확인 필수

현재 200,575원은 어떤 정책에서도 자동 align 대상이 아니다. 운영자 확인 판단이 정책상 옳다.

### 단기 후속 행동 권장

이번 200k 차이의 원인을 분리 진단한다.

1. **가격 시점 차이만으로 설명 가능한가**: broker 17:40 조회의 last_price와 local 15:01 snapshot의 last_price 차이가 평가 금액 차이를 얼마나 만드는지 계산. 9,000원/주 × 1주 = 9,000원 정도가 평가 금액 격차. 이건 total_asset_gap 61,275의 일부.
2. **누적 회계 차이**: 568건 주문 / 157건 체결의 수수료·세금 누적이 200,575원과 일치하는 범위인지. 거래당 1,300원 평균 차이 = 0.18% 정도. 한국 주식 수수료/세금 합 0.3~0.4% 수준이라 절반 정도가 누적 차이로 들어왔다는 가설은 plausible.
3. **silent mirror 누락**: 568 vs 156 broker_order_submissions 차이. 412건의 로컬 주문이 broker에 미러링되지 않은 셈. 그 중 일부가 체결되었다면 broker 잔고에는 반영되지 않고 local에만 반영 → cash_gap 발생. **이게 가장 가능성 높은 silent bug 후보다.** broker_paper sync 로그 확인 필요.

특히 마지막 항목(412건 mirror 누락)은 **cash_gap 200k를 거의 다 설명할 수 있는 후보**다. 만약 412건 중 일부가 reject가 아니라 silent skip이라면 같은 패턴이 매일 누적되어 차이가 점점 커질 것이다. 자동 align했다면 이걸 못 봤을 것이다.

## 종합 판단

| 항목 | 판단 |
|---|---|
| Q1 09:28 공백 → watch 해석 | 80% 맞음. watchdog pre-open 동작과 5분 분산 손실 + orderbook 격차 축소 확인 필요 |
| Q2 자동 align 거부 | 안전한 판단. 단 임계 분기 정책 합의 권장 |
| 추가 우선 행동 | broker_paper mirror 412건 누락 원인 확인 (silent bug 가능성 가장 높음) |

## 다음 단계 권장

1. **5/15 09:00~09:28 watchdog/live-runtime 로그 확인**: pre-open warmup 동작 여부, KIS WS 구독 시각, 첫 raw tick 수신 시각.
2. **broker_paper sync 412건 mismatch 분석**: `runtime-data/reports/broker-paper/`와 sync 로그에서 568 - 156 = 412건의 미러링 누락 분류. silent skip vs reject vs rate limit cooldown.
3. **paper dual account 자동 align 임계 정책 합의**: 위 N/M 분기 후보를 운영자가 결정하면 dashboard와 verify wrapper에 반영.
4. **broker total_asset 계산 정의 검증**: KIS 모의계좌의 total_asset_amount가 cash + stock 단순합이 아닌 이유 확인. KIS 문서 또는 추가 reconcile 점검.

이 4개 항목 중 (2)번이 가장 시급하다. silent mirror 누락이 누적 패턴이라면 다음 거래일에도 같은 차이가 발생하고, 진짜 사고는 그 차이가 일정 임계를 넘는 시점에 터진다.
