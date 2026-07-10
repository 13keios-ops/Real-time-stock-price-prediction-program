# Model Research Pre-Registration

이 문서는 2026-07-18 전까지 KIS live 판정을 동결한 상태에서, 이후 어떤 연구 질문을 어떤 기준으로 검증할지 미리 고정하는 문서다. 목적은 좋은 결과가 나온 조합만 사후 선택하는 것을 막고, Cybos 장기 데이터와 KIS live 데이터의 차이를 분리해 해석하는 것이다.

## 1. 현재 결론

- KIS live 주문 판단, active model, gate, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`는 2026-07-18 전까지 바꾸지 않는다.
- Cybos-KIS transfer review 기준 공통 bar 피처에서 `source_stable_candidate`는 0개다.
- KIS live h15는 비용 구조만으로 배제할 수 없다. KIS live 근사 h15 `median_abs=0.361446`은 `2 * trade_cost_pct=0.216`보다 크다.
- h60은 KIS live 근사 `median_abs=0.717274`로 비용 여유가 더 커 보이지만, 신호·체결·포지션 정책은 아직 검증되지 않았다.
- 현재 병목은 h15 비용 구조 단정이 아니라 신호 정보량이다. `probability_down` daily IC는 `mean_daily_ic=0.004754`, `t_stat=0.367342`로 사전 기준을 통과하지 못했다.

관련 문서/코드 경로: `runtime-data/reports/research/latest-cybos-kis-transfer-review.md`, `runtime-data/reports/research/latest-cost-horizon-diagnostics.md`, `runtime-data/reports/research/latest-signal-ic-h15.md`

## 2. Cybos-KIS 격차 원인 가설

1. 데이터 원천 차이: Cybos historical은 bar 중심이고, KIS live는 실시간 체결·호가 기반이다. `bid_ask_imbalance`, `spread_bps`는 Cybos 쪽에서 구조적으로 0에 가까워 Cybos backtest로 직접 검증할 수 없다.
2. 시장 미시구조 차이: KIS live는 실제 watchlist 10종목의 장중 호가, 스프레드, VI/동시호가 영향, 체결 가능성, 모의계좌 체결 제약을 함께 받는다. Cybos bar-only 결과는 이 실행 제약을 포함하지 않는다.
3. 표본 창 차이: Cybos proxy는 긴 역사 구간의 많은 종목을 보지만, 현재 KIS live는 최근 약 1~2개월 watchlist 중심이다. source split 없이 전체 평균을 보면 Cybos historical이 표본을 지배한다.
4. 비용/라벨 차이: h15 전체 표본의 비용 경고는 Cybos historical 지배 표본의 착시일 수 있다. KIS live만 분리하면 h15 중위 변동폭은 비용을 넘지만, 실제 신호 품질이 부족하다.
5. 실행 로그 차이: KIS live에는 paper 주문, 체결, rejected close, 계좌 snapshot mismatch 같은 운영 노이즈가 들어간다. 연구 지표와 실제 paper 손익을 섞으면 원인이 흐려진다.

관련 문서/코드 경로: `runtime-data/reports/data-quality/latest-feature-source-drift.md`, `runtime-data/reports/backtests/latest-cybos-buy-avoid-proxy-h15.json`, `runtime-data/reports/challengers/latest-lightgbm-defensive-shadow-h15.json`, `runtime-data/reports/reconciliation/latest-paper-kis-mismatch-trace.md`

## 3. Orderbook 피처 가설

### OB-1. spread_bps는 거래비용/유동성 스트레스 후보

가설: `spread_bps`가 높은 구간은 명목 예측이 좋아도 실제 체결 비용과 슬리피지 때문에 순손익이 나빠질 수 있다. 따라서 방향 모델이 아니라 no-trade 또는 size-down 후보로 먼저 본다.

검증 기준: 2026-07-18 이후 KIS live에서 `spread_bps` decile별 h15/h60 future return, 가상 방향 순손익, paper 체결 슬리피지 proxy를 함께 본다. 이번 1차 라운드의 다중 비교 수는 `k=12`로 사전 고정한다. 구성은 `h15/h60 × daily IC/가상 방향 순손익/paper 슬리피지 proxy × 전체/오전/오후`다. `k=12` 안에서 같은 방향이 최소 5거래일 이상 반복되고, 공통 기준보다 보수적인 `abs(t_stat) >= 2.8`을 통과해야 관찰 후보가 된다.

관련 문서/코드 경로: `runtime-data/reports/research/latest-cybos-kis-transfer-review.md`, `runtime-data/reports/data-quality/latest-feature-source-drift.md`

### OB-2. bid_ask_imbalance는 방향 신호가 아니라 종목/시간대별 압력 후보

가설: `bid_ask_imbalance`는 매수·매도 압력을 나타낼 수 있지만, 종목별로 의미가 뒤집히거나 변동성 proxy처럼 작동할 수 있다. 단일 global threshold로 쓰지 않는다.

검증 기준: 종목별, 시간대별, 변동성 bucket별로 top/bottom decile의 future return 차이와 daily IC를 따로 계산한다. 이번 1차 라운드의 다중 비교 수는 `k=24`로 사전 고정한다. 구성은 `후보 3종목(005380/035420/105560) × 방향 2개(up/down) × 시간대 2개(오전/오후) × horizon 2개(h15/h60)`이다. `k=24` 안에서 같은 종목·같은 방향으로 07-18 이후 재현되고, `abs(t_stat) >= 3.0`을 통과할 때만 shadow 후보로 둔다. 이 범위를 넘는 종목·bucket 탐색은 다음 라운드 사전등록 전까지 하지 않는다.

관련 문서/코드 경로: `scripts/summarize_cybos_kis_transfer_review.py`, `scripts/summarize_signal_ic.py`

### OB-3. orderbook freshness는 피처 이전의 안전 조건

가설: orderbook 값이 오래됐거나 coverage가 낮은 구간에서는 피처 값 자체가 의미를 잃는다. 신호가 좋아 보이더라도 freshness가 깨지면 실전/Phase 2 후보에서 제외한다.

검증 기준: orderbook freshness, raw market coverage, feature/bar ratio를 같이 기록한다. stale 또는 reconnect 직후 구간은 성능 후보가 아니라 데이터 품질 경고로 분류한다.

관련 문서/코드 경로: `runtime-data/reports/data-quality/latest-kis-live-data-quality.json`, `app/services/live_phase_readiness.py`, `docs/Production-Architecture.md`

### OB-4. orderbook x regime 상호작용

가설: `spread_bps`와 `bid_ask_imbalance`는 전체 평균보다 시간대, 단기 모멘텀, 변동성 regime과 결합될 때 의미가 있을 수 있다. 특히 `midday`, `short_up` caution 후보는 거래 회피/축소 후보로만 본다.

검증 기준: 07-18 이후에는 `midday`, `short_up`, volatility bucket별로 orderbook 피처 daily IC와 순손익을 병기한다. 단, E2/E3 threshold/EV tuning은 재현성 확인 전까지 하지 않는다.

관련 문서/코드 경로: `runtime-data/reports/research/latest-cybos-kis-transfer-review.md`, `docs/Execution-Plan.md`

## 4. 07-18 이후 검증 원칙

- 2026-07-18 전에는 KIS live 정책 판정, E2/E3 threshold/EV tuning, 종목별 주문 정책, h60 주문 정책을 만들지 않는다.
- 2026-07-18은 토요일이므로 실제 재측정은 07-18 이후 첫 거래일 장후 label refresh가 끝난 뒤 진행한다.
- 사전 등록 기준을 먼저 적용하고, 결과가 나온 뒤 기준을 바꾸지 않는다.
- 최소 공통 기준은 `abs(mean_daily_ic) >= 0.03`, `abs(t_stat) >= 2.5`, `days_usable >= 5`다. 단, 07-18 재측정의 후보 3건 재현성 관문은 cowork review_ver_27 기준 `같은 종목·같은 방향·abs(t_stat) >= 2.0`을 병기한다.
- `105560 probability_down` 후보는 `probability_up`도 같이 양수였으므로, 재측정 때 `probability_flat` IC와 `p_down/p_up` daily IC 관계를 함께 기록한다.
- 모든 결과는 random-control, 표본 수, 거래일 수, 종목 수를 같이 표시한다. 표본 부족은 실패가 아니라 관측 연장으로 분류한다.
- 07-18 이후 1차 라운드에서 사전등록하지 않은 조합을 추가로 발견하더라도, 해당 결과는 `exploratory_only`로만 표시하고 주문 정책 후보로 올리지 않는다.

관련 문서/코드 경로: `docs/cowork-reports/2026-07-05-buy-avoid-validation-verification-review_ver_27.md`, `scripts/summarize_signal_ic.py`, `scripts/summarize_lightgbm_defensive_shadow.py`

## 5. h60 트랙 사전 등록 초안

### 연구 질문

h60은 h15보다 가격 변동폭이 커서 비용 여유가 있다. 하지만 h60 예측이 실제 주문·체결·보유 정책으로도 더 나은지는 별도 질문이다. h60은 h15의 단순 대체가 아니라 별도 horizon track으로 검증한다.

### 입력 데이터

- KIS live h60 label이 닫힌 `feature_model_inputs`/label rows.
- 같은 시각의 baseline, LightGBM, linear-score shadow 예측이 있으면 병기한다.
- 체결/포지션 평가는 paper-only replay로만 본다. 실전 주문, gate, active model에는 연결하지 않는다.

### 1차 측정 항목

- h60 3분류 정확도와 class별 precision/recall.
- `probability_up`, `probability_down`, `probability_flat`의 daily IC.
- h60 가상 방향 거래 순손익과 random-control 대비 excess.
- h60 baseline buy join의 비용 차감 기대값.
- h60 신호가 h15 신호와 충돌할 때의 결과: h15 매수 허용 + h60 하락, h15 하락 + h60 상승 같은 교차표.
- h60 보유 기간 동안의 최대 역행폭, 장마감 강제청산 필요 여부, 종가 동시호가/시간외 구간 영향.

### 후보 통과 기준

- 비용 구조: KIS live h60 `median_abs_future_return_pct`가 `2 * trade_cost_pct`를 계속 초과해야 한다.
- 신호 품질: 방향별 daily IC 중 최소 한 방향이 사전 기준을 통과하고, 종목/시간대 한두 곳의 우연 후보로만 설명되지 않아야 한다.
- 수익성: 비용 차감 가상 방향 순손익이 random-control보다 좋아야 하며, `z_score <= -2.5` 또는 `z_score >= 2.5` 중 사전 정의한 좋은 방향을 통과해야 한다. 같은 coverage random-control 100회 기준 empirical percentile이 상위/하위 5% 밖으로 벗어나야 하며, 한두 거래일이 평균을 끌어올리는 구조면 탈락한다.
- 최소 표본: h60 1차 판정은 `days_usable >= 10`, `symbols >= 5`, `virtual_trades >= 100`을 모두 만족해야 한다. 미달이면 통과/실패가 아니라 `observe_more`로 둔다.
- 실행 가능성: h60 신호가 장마감 전 충분한 의사결정 시간을 주고, 보유 중 h15 risk exit와 충돌하지 않는 설명이 있어야 한다.

### 금지선

- h60 비용 구조가 좋아 보여도 h60 주문 정책을 바로 만들지 않는다.
- h60 결과로 h15 gate 기준값, active model, `config/`, `app/risk/`를 변경하지 않는다.
- h60 paper replay가 좋아도 Phase 1 read-only와 Phase 2 canary 안전 조건을 건너뛰지 않는다.

관련 문서/코드 경로: `runtime-data/reports/research/latest-cost-horizon-diagnostics.md`, `runtime-data/reports/backtests/latest-walk-forward-h15.json`, `docs/Production-Implementation-Blueprint.md`

## 6. 다음 작업 순서

1. 07-18 전까지는 신규 KIS live 판정과 threshold tuning을 동결한다.
2. 다음 거래일 장후 paper/KIS mismatch가 같은 root_cause_scope로 유지되는지 다시 본다.
3. 07-18 이후 첫 거래일인 2026-07-20 장후 `./scripts/run_preregistered_e1_e5_round.sh --execute`로 E1 재측정과 E5 역발상 관찰을 한 라운드로 실행한다. 이 실행기는 `2026-07-20 15:30 KST` 이전과 장중을 차단하며, 고정 구간 `2026-07-04~2026-07-18`을 D드라이브 연구 스냅샷에서 read-only로 측정한다. E1은 후보 3건의 같은 종목·같은 방향·`abs(t_stat) >= 2.0` 재현성과 `105560`의 p_flat 및 p_down/p_up 일별 IC 관계를 기록한다. E5는 threshold `0.40`의 random-control excess 부호와 z를 기록하며, 결과와 무관하게 정책/model/gate/order 변경은 하지 않는다.
4. 같은 라운드에서 orderbook 피처 daily IC와 h60 1차 측정표를 생성할 수 있는지 확인하되, 결과 해석은 사전 등록 기준을 따른다.
5. cowork 리뷰는 07-18 이후 재측정 결과가 나온 뒤 요청한다.

관련 문서/코드 경로: `docs/Execution-Plan.md`, `docs/Production-Transition-Progress.md`, `docs/cowork-reports/`
