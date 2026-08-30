# Model Research Pre-Registration

이 문서는 2026-07-18 전까지 KIS live 판정을 동결한 상태에서, 이후 어떤 연구 질문을 어떤 기준으로 검증할지 미리 고정하는 문서다. 목적은 좋은 결과가 나온 조합만 사후 선택하는 것을 막고, Cybos 장기 데이터와 KIS live 데이터의 차이를 분리해 해석하는 것이다.

## 1. 현재 결론

- E6 legacy key `cybos_historical`은 source column이 없는 `feature_labels`를 날짜로 나눈 `mixed_pre_kis_approximation_not_pure_cybos`다. 순수 Cybos 5년 결과로 해석하거나 KIS 전이 증거로 사용하지 않는다.
- 최신 `latest-walk-forward-h15.json`은 왕복비용 `0.108%`인 구형 산출물이다. 정확도 gate 진단은 참고할 수 있지만 현행 `0.29%` 수익성 판정에는 쓰지 않는다.
- 수익 후보는 동일 비용 세대, regular-session decision episode, 완전 lineage, 비중복 시간구간, random control, 실제 portfolio replay를 함께 통과해야 한다.

- KIS live 주문 판단, active model, gate, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`는 2026-07-18 전까지 바꾸지 않는다.
- Cybos-KIS transfer review 기준 공통 bar 피처에서 `source_stable_candidate`는 0개다.
- 2026-07-12 비용 정본 `krx-common-stock-2026-v1`의 왕복 연구 비용은 `0.29%`, 보수적 2배 비용 여유 기준은 `0.58%`다.
- KIS live 근사 h15 `median_abs=0.376648%`와 baseline-buy join `median_abs=0.365344%`는 `0.58%`보다 작아 비용 여유 경고가 켜졌다. 다만 h15 상위 25% 절대변동은 `0.721772%`이므로 h15 전체의 수익 가능성을 구조적으로 부정하지 않고, 저빈도 선별 후보와 실제 신호 품질을 별도로 검증한다.
- h60은 KIS live 근사 `median_abs=0.739523%`, baseline-buy join `median_abs=0.718133%`로 `0.58%`를 넘는다. 상대 연구 우선순위는 높아졌지만 신호·체결·보유 lifecycle·h15 충돌은 아직 검증되지 않았다.
- 현재 병목은 h15 비용 구조 단정이 아니라 신호 정보량이다. `probability_down` daily IC는 `mean_daily_ic=0.004754`, `t_stat=0.367342`로 사전 기준을 통과하지 못했다.
- E6의 `breakeven_win_rate_long_reference`와 변동폭 분포는 구조 진단일 뿐 모델 수익성 증거가 아니다. h15 폐기나 h60 주문 정책 전환 근거로 단독 사용하지 않는다.
- KIS live 전체 long-only 손익분기 참고 승률은 h15 `0.724041`, h60 `0.624676`이고 baseline-buy join은 각각 `0.748325`, `0.646466`이다. 이는 현재 관측 평균 이익·손실과 비용을 고정한 동적 기준선이며 모델 3분류 정확도나 long/short 방향 거래 적중률과 직접 비교하지 않는다.
- 넓은 KIS 근사 표본의 관측 시작은 `2026-06-11 08:30 KST`라 장전 구간이 포함된다. 실행 후보는 `09:15 KST`부터 시작하는 baseline-buy join 또는 별도 사전등록 regular-session decision episode에서 다시 평가한다.
- 2026-08-15 완결 E1/E5 라운드는 E1 후보 재현 `0/3`, E5 random 대비 excess `-96.7921%`로 기존 가설을 기각했다. 이 실패를 threshold/EV 또는 종목별 정책 조정으로 구제하지 않는다.

관련 문서/코드 경로: `runtime-data/reports/research/latest-cybos-kis-transfer-review.md`, `runtime-data/reports/research/latest-cost-horizon-diagnostics.md`, `runtime-data/reports/research/latest-signal-ic-h15.md`

## 2. Cybos-KIS 격차 원인 가설

1. 데이터 원천 차이: Cybos historical은 bar 중심이고, KIS live는 실시간 체결·호가 기반이다. `bid_ask_imbalance`, `spread_bps`는 Cybos 쪽에서 구조적으로 0에 가까워 Cybos backtest로 직접 검증할 수 없다.
2. 시장 미시구조 차이: KIS live는 실제 watchlist 10종목의 장중 호가, 스프레드, VI/동시호가 영향, 체결 가능성, 모의계좌 체결 제약을 함께 받는다. Cybos bar-only 결과는 이 실행 제약을 포함하지 않는다.
3. 표본 창 차이: Cybos proxy는 긴 역사 구간의 많은 종목을 보지만, 현재 KIS live는 최근 약 1~2개월 watchlist 중심이다. source split 없이 전체 평균을 보면 Cybos historical이 표본을 지배한다.
4. 비용/라벨 차이: source split 없이 전체 평균을 보면 Cybos historical이 구조 판단을 지배한다. KIS live만 분리해도 h15 중위 변동폭은 왕복 비용 `0.29%`는 넘지만 보수적 2배 비용 기준 `0.58%`에는 못 미치며, 실제 신호 품질도 부족하다.
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

h60은 신 비용 E6에서 KIS live 중위 절대변동 `0.739523%`로 2배 비용 기준 `0.58%`를 넘고, h15 `0.376648%`보다 상대 비용 여유가 크다. 하지만 h60 예측이 실제 주문·체결·보유 정책으로도 더 나은지는 별도 질문이다. h60은 h15의 단순 대체가 아니라 별도 horizon track으로 검증한다.

### 입력 데이터

- KIS live h60 label이 닫힌 `feature_model_inputs`/label rows.
- 같은 시각의 baseline, LightGBM, linear-score shadow 예측이 있으면 병기한다.
- 체결/포지션 평가는 paper-only replay로만 본다. 실전 주문, gate, active model에는 연결하지 않는다.

### 1차 측정 항목

- h60 3분류 정확도와 class별 precision/recall.
- `probability_up`, `probability_down`, `probability_flat`의 daily IC.
- h60 가상 방향 거래 순손익과 random-control 대비 excess.
- h60 baseline buy join의 비용 차감 기대값.
- 현재 broad KIS long-only 손익분기 참고 승률은 h60 `0.624676`, baseline-buy join은 `0.646466`이다. 매 고정 평가구간에서 평균 이익·평균 손실·비용으로 다시 계산하고, 3분류 정확도 또는 long/short 방향 거래 적중률과 직접 비교하지 않는다.
- p75 절대변동은 미래에 실현된 값이므로 entry 시점 필터로 사용할 수 없다. 사전에 계산 가능한 score가 해당 고변동 구간을 재현성 있게 찾는지 별도로 검증한다.
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

## 6. 다음 entry 모델 사전 등록 초안

### 연구 질문

정규장 entry 시점에 알 수 있는 정보만으로 비용 후 기대값이 양수인 거래와 거래하지 않을 구간을 구분할 수 있는가를 본다. 3분류 정확도 자체보다 실행 가능한 decision episode의 비용 후 손익과 하방 위험을 정본으로 둔다.

### 현재 기준선

- 손익분기 참고 승률은 `p_be = (평균 손실 + 왕복 비용) / (평균 이익 + 평균 손실)`로 계산한다.
- broad KIS 기준 h15 `0.724041`, h60 `0.624676`은 현재 관측 분포를 고정한 long-only 구조 참고값이다.
- baseline-buy join 기준 h15 `0.748325`, h60 `0.646466`이 실제 entry 모집단에 더 가깝지만, 이 값도 새 고정 구간마다 다시 계산한다.
- 위 승률은 모델 3분류 정확도, class hit rate, long/short 가상 방향 win rate와 모집단·행동이 다르므로 서로 빼거나 우열을 직접 비교하지 않는다.

### 평가 모집단

- 완전한 `training_run_id`, `artifact_id`, `artifact_sha256`가 있는 미래 serving decision ledger만 후보 근거로 사용한다.
- 정규장 안의 실행 가능한 decision episode를 사용하고, broad E6의 `08:30` 장전 행은 구조 참고로만 둔다.
- baseline 판단, gate, allocator, 현금·보유·pending 제약, 주문·체결 여부를 분리해서 기록한다.
- 실현된 p75 미래 변동을 entry 필터로 사용하지 않는다. entry 시점에 존재하는 score가 이후 고변동·유리한 손익 구간을 찾았는지만 본다.

### 필수 측정

- 후보별 평균 이익, 평균 손실, 왕복 비용, 동적 손익분기 승률, 실제 조건부 승률과 불확실성 구간.
- 비용 후 평균 거래 기대값, 누적 portfolio return, 최대 낙폭, 비음수 거래일 비율.
- no-trade coverage, decision episode 수, 실제 체결 수, 종목·시간대 집중도.
- 같은 coverage random control과 비중복 미래 평가구간 최소 2개 재현성.
- h15/h60을 같은 초기 현금, 비중, 최대 보유 수, 다음 분봉 실행가, 장마감 청산 조건으로 비교.

### 후보 해석 기준

- 실제 조건부 승률이 동적 손익분기선을 넘거나 평균 이익/손실 비대칭이 개선되더라도, 비용 후 평균 기대값과 portfolio return이 모두 양수여야 한다.
- 거래 빈도를 무작위로 4분의 1로 줄이는 것은 총손실 횟수만 줄일 뿐 거래당 기대값을 개선하지 않으므로 후보 근거가 아니다.
- 표본·random control·비중복 기간 재현성·기존 challenger 승격 조건을 모두 통과하기 전에는 `research_candidate` 이상으로 올리지 않는다.
- 2026-07-20 E1/E5 결과 전에는 이 초안으로 새 threshold, feature 조합, h60 주문 정책을 실행하지 않는다.

관련 문서/코드 경로: `docs/Execution-Plan.md`, `docs/Buy-Avoid-Random-Control-Methodology.md`, `app/services/portfolio_replay.py`

## 6-1. E7 LightGBM buy-rescue 미래 검증 사전등록

### 연구 질문

2026-08-28까지의 serving no-trade decision ledger에서 탐색적으로 양수였던 LightGBM buy-rescue가, 사후 선택 효과가 아닌 미래의 실행 가능한 비용 후 알파인가를 검증한다. 현재 관측은 threshold `0.55`에서 76건, 9거래일, 누적 신호행 순손익 `+13.073707%p`, 평균 `+0.172022%p`, precision `0.578947`이다. 이 값은 겹치는 신호행의 합이고 실제 계좌 수익률이 아니므로 `research_lead`로만 둔다.

### 고정 입력과 구간

- 모델은 `lightgbm-h15-v1`, score는 entry 시점의 `probability_up`, threshold는 `0.55`로 고정한다.
- 모집단은 baseline이 매수를 허용하지 않았고, 완전한 artifact lineage가 있으며, 정규장 decision episode로 묶을 수 있는 serving ledger다.
- 독립 미래 구간은 `2026-08-31 09:15 KST` 이후로 시작한다. 이 날짜 이전 행은 설계·기준선 설명에만 쓰고 통과 판정에 재사용하지 않는다.
- 현행 비용 모델 `krx-common-stock-2026-v1`, 왕복 `0.29%`를 고정하고 2배 비용 `0.58%` 민감도도 함께 계산한다.
- active model, gate, threshold 설정, 주문 정책은 바꾸지 않으며 paper-only 오프라인 재생으로만 평가한다.
- 공식 evaluator는 `portfolio-replay-v2-minute-mtm`으로 고정한다. 시각 T의 보유 포지션은 T-1분 completed close로 평가하며 exact minute mark가 없으면 전체 평가를 invalid 처리한다. 기존 `portfolio-replay-v1-entry-mark` 결과와 수익률/MDD를 섞지 않는다.
- evaluator manifest는 모델, threshold, horizon, 미래 시작, 비용, 포트폴리오 제약, random 1,000회/seed/strata, 두 구간 규칙을 하나의 hash로 잠근다. 실제 두 구간 경계는 판정 전에 고정하고 겹치면 거부한다.

### 필수 평가

- 같은 초기 현금, 최대 보유 수, 현금·보유·pending 제약, 다음 실행 가능한 분봉 가격, 장마감 `15:20 KST` 강제청산을 적용한 decision-episode portfolio replay.
- 동일 거래일·종목·시간대 층 안에서 같은 episode 수를 뽑는 random control 1,000회와 empirical percentile.
- 비용 후 누적 portfolio return, 거래당 기대값, 최대 낙폭, 비음수 거래일 비율, 종목·시간대 집중도.
- lineage completion `100%`, 최소 `10`거래일, 최소 `100`개 rescue episode, 최소 `5`종목.
- 첫 판정 구간 뒤 서로 겹치지 않는 두 번째 미래 구간 재현. 첫 구간 통과만으로 승격하지 않는다.

### 통과와 중단 기준

- 현행 비용과 2배 비용에서 모두 portfolio return과 평균 거래 기대값이 `> 0`이어야 한다.
- random control 상위 `5%`를 넘어야 하고, 비음수 거래일 비율은 `>= 2/3`이어야 한다.
- 최대 낙폭이 baseline보다 나빠지거나 한 종목 또는 한 거래일이 총이익의 `50%`를 초과하면 탈락한다.
- 최소 표본 미달은 `observe_more`, 조건 실패는 `rejected`, 두 비중복 미래 구간을 모두 통과한 경우에만 `research_candidate`다.
- 세 번의 고정 미래 평가에서 개선이 없으면 이 가설을 종료하고 h60 또는 entry/exit 분리 가설로 이동한다. 같은 데이터에서 threshold를 다시 탐색해 구제하지 않는다.

관련 문서/코드 경로: `runtime-data/reports/challengers/latest-model-overlay-comparison-h15.json`, `app/services/portfolio_replay_v2.py`, `app/services/e7_portfolio_evaluator.py`, `docs/Portfolio-Replay-Evaluator.md`, `docs/Execution-Plan.md`

## 7. 다음 작업 순서

1. E1/E5 완결 라운드는 2026-08-15 승인 실행으로 종료했다. 같은 고정 라운드를 자동 또는 수동 재실행하지 않는다.
2. 다음 거래일마다 raw→분봉→feature→decision ledger와 complete lineage, WebSocket reconnect/storm을 함께 확인한다.
3. Phase 0은 승인 clean baseline 뒤 새 기준선 10개 유효 거래일의 전일 matched를 누적한다.
4. 실패한 E1/E5를 신규 threshold/EV tuning, 종목별·h60 주문 정책으로 구제하지 않는다.
5. E7 LightGBM buy-rescue는 threshold `0.55`와 2026-08-31 이후 미래 구간을 고정하고, 최소 표본·portfolio replay·random control을 충족할 때만 판정한다.
6. 저빈도 entry 후보는 entry 시점에 존재하는 score만 사용한다. 실현 p75 미래변동은 선별 변수가 아니다.
7. h15/h60과 exit/hold 모델은 같은 초기 현금, 비용, 다음 분봉 실행가, 최대 보유 수, 장마감 청산의 portfolio replay에서 비교한다.
8. 후보는 절대 비용 후 기대값과 portfolio return 양수, same-count random control 우위, 비중복 2구간, 최소 표본과 일별 일관성을 모두 통과해야 한다.
9. 새 사전등록 결과가 기준을 통과하거나 3회 연속 개선이 없을 때 cowork 리뷰를 요청한다.

## 8. 2026-08-09 실행 상태

- wrapper gate와 label refresh는 통과했다.
- 25GB SQLite snapshot은 180초 안에 끝나지 않아 `snapshot_failed/research_snapshot_timeout`으로 종료됐다.
- final snapshot 교체, KIS 네트워크 호출, 주문 호출은 모두 0회다.
- 다음 실행기의 snapshot 기본 경로와 partial cleanup은 보강했지만 유효 연구 결과가 아니므로 E1/E5 판정과 연구 분기는 계속 보류한다.

관련 문서/코드 경로: `runtime-data/reports/research/preregistered-e1-e5-20260718/latest-attempt.json`, `scripts/create_research_db_snapshot.sh`, `docs/Execution-Plan.md`, `docs/Production-Transition-Progress.md`

## 9. 2026-08-15 완결 실행과 판정

- 계좌 소유자 승인으로 `--snapshot-timeout-seconds 1800 --execute`를 장외에 정확히 1회 실행했다. 26GB snapshot은 830.5초, `quick_check=ok`였고 라운드는 `status=ok`다.
- E1은 14,004행/9거래일, 후보 재현 `0/3`, 전체 probability_down 일평균 IC `-0.019927`, t `-0.730524`로 `signal_quality_insufficient`, E2/E3 진행 불가다.
- `105560` p_down/p_up daily IC Pearson `0.897613`, same-sign 7/9일이며 p_flat도 근거가 없다. 세 class 확률 제약 또는 공통 regime 영향 가능성이 커 방향 후보로 유지하지 않는다.
- E5는 검증된 temporal lineage 6,195행/4거래일에서 threshold 0.40의 random 대비 excess `-96.7921%`, z `-3.4051`로 `reverse_selection_not_reproduced_second_interval`이다.
- 네트워크·주문·학습 호출, 자동 정책 변경, active model/gate 변경은 모두 0회다. 기존 후보는 종료하고 다음 새 가설 사전등록 전까지 추가 탐색하지 않는다.

관련 문서/코드 경로: `runtime-data/reports/research/preregistered-e1-e5-20260718/latest-completed-round.json`, `runtime-data/reports/research/preregistered-e1-e5-20260718/runs/20260815-015049-710415/preregistered-e1-e5-round.md`
