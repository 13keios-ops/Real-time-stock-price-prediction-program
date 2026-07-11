# Rescue/Avoid Profitability Review work_ver_30-10

## 1. 결론

현재 구조는 `나쁜 후보가 실전에 들어가지 않도록 막는 연구·안전 시스템`으로는 제대로 작동한다. 그러나 `수익을 내는 전략 시스템`으로는 아직 미완성이다.

- LightGBM buy-avoid: KIS live에서 역선별이라 현재 후보가 아니다.
- Cybos buy-avoid: 장기 proxy 내부 선택성은 있으나 필터 후에도 적자다.
- buy-rescue: Cybos는 실패했고 KIS 소규모 양수는 경제적·통계적으로 약하다.
- hold-rescue: 최신 실제 paper replay에서 손실이므로 현재 규칙은 기각한다.
- early-exit: threshold 0.58 결과만 양수처럼 보이지만 체결·기간·사후선택 편향 때문에 아직 유효 후보가 아니다.
- active baseline과 모든 challenger도 비용 후 양수 기대값을 입증하지 못했다.

따라서 지금 필요한 것은 rescue/avoid threshold를 더 찾는 일이 아니라 평가 정본과 모델 목표를 수익 중심으로 다시 세우는 일이다.

## 2. 확인한 최신 증거

### KIS LightGBM buy-avoid

- 기간: 2026-06-11~2026-07-10, 22거래일.
- baseline allowed-buy 신호: 33,007행.
- threshold 0.40 skip: 9,002행, 27.27%.
- baseline 평균 순손익: `-0.120451%p/행`.
- 필터 후 평균 순손익: `-0.130377%p/행`.
- 실제 skip 합: `-846.0341%p`.
- 같은 수 무작위 skip 기대: `-1,084.2999%p`.
- excess: `+238.2658%p`, z-score `+4.1266`.
- 판정: `filter_worse_than_random_p95`, gate fail.

쉬운 해석: LightGBM이 골라서 뺀 행보다 무작위로 뺀 행이 더 손실이 컸다. 즉 현재 LightGBM 하락 확률은 나쁜 매수를 골라내는 데 실패했고 오히려 상대적으로 덜 나쁜 행을 뺐다.

### Cybos 5년 buy-avoid proxy

- 199종목, 1,249거래일, 약 604만 labeled row, 12 fold.
- reference target skip 0.3665, 실제 skip 0.3617.
- random-control z `-6.3607`, Cybos 내부에서는 선택성 통과.
- baseline net `-538.0404%p`, kept net `-170.3252%p`.

쉬운 해석: 과거 Cybos에서는 나쁜 후보를 무작위보다 잘 골랐지만, 남긴 후보도 비용 후 적자다. 또한 같은 효과가 KIS live에서는 반대로 나왔으므로 주문 정책으로 전이할 수 없다.

### buy-rescue

- Cybos rescue grid의 평균 순손익은 모두 음수다. target 5%에서 33,135건, 평균 `-0.10644%p`; target 20%에서 130,233건, 평균 `-0.11115%p`다.
- KIS model overlay의 `both_models_up_rescue_0.40`은 34,183개 non-baseline-buy 행 중 160행만 선택했다.
- 합계 `+0.631798%p`, 평균 약 `+0.00395%p`, 손실 행 50.625%다.
- overlay는 2026-07-03 생성본이며 day/fold consistency와 random-control이 없다.

쉬운 해석: KIS의 작은 양수는 거래당 약 0.4bp 수준이라 현재 증거로는 잡음과 구분할 수 없다. 실제 gate/allocator/order 제약을 포함한 no-trade ledger도 아니므로 buy-rescue를 시작하면 안 된다.

### hold-rescue

- 최신 생성: 2026-07-11.
- closed lot 210, eligible 161.
- threshold 0.40 적용 37 lot.
- baseline cash delta 합 `814,041원`, rescue 적용 시 `787,654원`.
- 차이 `-26,387원`.
- 개선 13건(35.14%), 악화 22건(59.46%), 비음수 거래일 21.43%.

쉬운 해석: 현재 상승확률 기반 보유 연장은 실제 청산보다 결과를 악화시켰다. 표본 부족이 아니라 현재 규칙 자체가 실패한 상태다.

### early-exit 예외

- threshold 0.58에서 eligible 304 lot 중 189 lot를 조기청산한다.
- 실제 청산 cash delta `384,154원`, 조기청산 `700,948원`, 차이 `+316,794원`이다.
- threshold 0.54는 반대로 `-210,784원`, 0.50은 `-324,382원`이라 결과가 임계값에 매우 민감하다.
- 다섯 threshold 중 0.58을 같은 표본에서 사후 선택했다.
- 코드는 예측이 생성된 `event_time`의 같은 minute-bar close를 가상 체결가로 쓴다. 실제로는 그 bar가 닫힌 뒤 예측하므로 같은 종가 체결을 보장할 수 없다.
- `build_summary`의 start/end date 필터는 buy-avoid row에만 적용되고 early-exit closed lot/prediction에는 적용되지 않는다.
- broker queue, bid/ask, 부분체결, 추가 슬리피지도 없다.

판정: 버릴 결과는 아니지만 현재 숫자를 수익 증거로 쓰면 안 된다. threshold 0.58을 새 미래 구간에 고정하고, 다음 bar의 실제 매도 가능 가격과 portfolio 제약으로 재생해야 한다.

## 3. P0 문제점

### P0-1. 상대적 손실 감소를 후보로 부른다

- `scripts/summarize_lightgbm_defensive_shadow.py:544`는 baseline 대비 delta가 가장 큰 threshold를 고른다.
- 같은 파일 557~560행은 delta가 양수면 legacy status를 candidate로 만든 뒤 random-control fail을 별도 필드에만 둔다.
- `scripts/summarize_model_overlay_comparison.py:699`는 filtered net이 계속 음수여도 delta가 양수면 buy-avoid candidate로 둔다.
- `scripts/summarize_meta_policy_shadow.py:187`은 negative policy net도 primary shadow candidate로 전달한다.

결과: `덜 잃었다`가 `수익 후보`처럼 보인다. candidate 조건은 absolute policy net/EV 양수와 random-control/day consistency를 모두 통과해야 한다.

### P0-2. 33,007개 신호 행을 33,007개 독립 거래처럼 계산한다

- KIS buy-avoid 모집단은 allowed-buy signal 33,007행이다.
- 실제 같은 기간 buy order는 258건, 전체 fill event는 425건이다.
- allowed-buy 연속 episode로 묶어도 약 15,711개로 줄어든다.
- 매분 신호의 15분 미래수익은 서로 겹치므로 독립 표본도 아니다.
- `cumulative_net_return_pct`는 단순 합이며 max drawdown도 이 합산열에서 계산한다.

결과: `-3975%`, `+846% 개선`, `MDD 4133%`는 계좌 수익률이 아니라 겹치는 신호 수익률 포인트 합이다. 포트폴리오 자본, 동시 보유, 주문 체결, turnover를 반영한 equity curve가 필요하다.

### P0-3. meta-policy가 stale·불완전 입력을 정상으로 본다

- model overlay와 meta report는 2026-07-03 생성본이다.
- defensive shadow는 2026-07-10, hold-rescue는 2026-07-11까지 갱신됐다.
- meta report는 input 존재 여부만 보고 freshness/data end/model lineage를 비교하지 않는다.
- 핵심 defensive random-control report 자체를 meta input으로 받지 않는다.

결과: random-control에서 실패한 후보와 음수 policy net을 계속 `primary shadow candidate`로 표시할 수 있다.

### P0-4. early-exit replay가 같은 bar 종가 체결과 범위 누락으로 낙관적이다

`scripts/summarize_lightgbm_defensive_shadow.py:451~475`는 lot 안의 첫 하락 예측 행을 찾고 그 행의 `curated_minute_bars.close`를 즉시 청산 가격으로 쓴다. 예측이 해당 minute bar 완성 후 만들어졌다면 실행 가능한 최초 가격은 다음 호가/틱이다. 또한 498~523행의 start/end 필터는 buy-avoid에만 적용되고 early-exit 원장에는 적용되지 않는다. 따라서 `+316,794원`은 future-only next-bar 실행으로 재검증하기 전까지 낙관 편향 가능성이 크다.

### P0-5. 실제 손익 정본도 아직 닫히지 않았다

Phase 0 paper/KIS mismatch 4종목과 총자산 gap 약 1,346,941원이 남아 있다. 로컬 PnL과 KIS 계좌 PnL 중 어느 쪽도 현재 전략 수익 정본으로 단정할 수 없다.

## 4. P1 문제점

### P1-1. LightGBM shadow lineage가 없다

2026-06-11 이후 `lightgbm-h15-v1` serving prediction 82,583개 전부 `training_run_id`, `artifact_id`, `artifact_sha256`가 비어 있다. 현재 artifact는 lineage를 갖지만 과거 저장 예측은 여러 재학습 세대를 하나의 model_version으로 섞어 본다. 재현과 세대별 성능 분리가 불가능하다.

### P1-2. buy-rescue 모집단이 실제 no-trade 결정 원장이 아니다

현재 `not_baseline_buy`는 allowed-buy가 아닌 모든 공통 행이다. baseline sell, confidence/time/spread 차단, allocator의 현금·보유한도, 주문 거절/미체결을 분리하지 않는다. rescue가 무엇을 뒤집는지 명확하지 않다.

### P1-3. challenger ranking이 작은 표본과 class collapse를 앞세운다

fresh centroid는 거래 4건 수익 때문에 1위지만 거의 모든 행을 down으로 예측한다. 3분류 정확도 31.47%이고 up/flat 적중률은 사실상 0이다. `promotable`도 수익 승격 가능이 아니라 독립 holdout 평가 자격 의미다. ranking 전에 최소 거래 수, class coverage, majority baseline 초과를 강제해야 한다.

### P1-4. 비용 기준이 리포트마다 다르고 execution 비용이 불완전하다

KIS shadow/model overlay는 0.108%p, Cybos/hold-rescue는 0.13%p를 쓴다. 연구 목적 차이는 문서화돼 있지만 meta 비교에서는 같은 표에 섞인다. hold-rescue의 delta cash는 broker queue, partial fill, order type, 실제 slippage를 포함하지 않는다.

## 5. 제대로 되고 있는 부분

- random-control을 도입해 positive delta 착시를 실제로 잡아냈다.
- Cybos와 KIS 결론이 다르면 전이를 차단한다.
- buy-rescue/hold-rescue가 실패했을 때 주문 정책과 active model을 바꾸지 않는다.
- 2026-07-20 E1/E5 사전등록으로 threshold 사후 튜닝을 동결했다.
- 실전 주문은 fail-closed 상태다.

즉 안전성과 자기비판 장치는 살아 있다. 문제는 사용자에게 보이는 candidate/status와 최종 수익 평가 정본이 그 안전 판정보다 느슨하다는 점이다.

## 6. 권장 실행 순서

### 즉시 가능한 평가 체계 교정

1. random-control fail이면 candidate status 자체를 fail/rejected로 통일한다.
2. candidate 필수 조건을 absolute net positive, average EV positive, day/fold consistency, 최소 episode 수로 바꾼다.
3. `cumulative_net_return_pct`를 `sum_net_return_pct_points`로 명확히 이름 바꾸고 account return과 분리한다. early-exit은 다음 bar bid/실제 체결 가능 가격과 명시한 날짜 범위만 사용한다.
4. meta report에 defensive random-control을 필수 입력으로 추가하고 stale/lineage/data-window mismatch를 blocker로 만든다.
5. challenger 순위를 min trades, class coverage, majority baseline 초과 뒤에 계산한다.
6. prediction lineage가 있는 새 관측 구간을 별도로 시작한다.

### 수익 평가 정본 구현

1. 분 단위 신호를 decision episode로 묶는다.
2. baseline/LightGBM/linear-score의 확률과 artifact lineage를 같은 decision id에 저장한다.
3. time/spread/risk/allocator/cash/position/order/fill 결과를 단계별로 기록한다.
4. 동일 현금, 동일 포지션 한도, 수수료, 세금, 슬리피지, 부분체결, 장마감 청산으로 정책별 portfolio replay를 수행한다.
5. 일별 return, net PnL, turnover, max drawdown, loss streak, exposure와 confidence interval을 계산한다.
6. 이 결과만 promotion/Phase 2 gate에 사용한다.

### 모델 개선

- 현재 hold-rescue 규칙은 종료한다. early-exit threshold 0.58은 미래 구간·next-bar 실행·고정 threshold 검증 전까지 진단으로만 남긴다.
- buy-rescue는 실제 no-trade decision ledger가 생긴 뒤 다시 본다.
- buy-avoid는 2026-07-20 E1/E5 역발상 관찰까지만 유지하고 재현 실패 시 현재 `probability_down` veto를 폐기한다.
- 다음 entry 모델은 3분류 정확도만 최적화하지 않고 비용 후 기대수익, 하방 quantile, no-trade zone을 직접 다룬다.
- exit/hold는 entry 모델 확률을 재사용하지 않고 별도 lifecycle 모델로 설계한다.
- h15와 h60은 동일 portfolio replay에서 비용 후 성과로 비교한다.

## 7. 최종 판단

- 지금 Phase 2 실전 canary로 가면 안 된다.
- 현재 rescue/avoid는 실전 적용할 후보가 없다.
- 프로그램이 실패한 것은 아니다. 잘못된 후보를 막는 연구 기반은 갖춰졌다.
- 그러나 앞으로도 데이터만 쌓고 같은 리포트만 반복하면 사용자의 우려대로 `학습은 하지만 수익을 못 내는 프로그램`에서 멈춘다.
- 다음 개발의 중심을 모델 수 증가가 아니라 `정확한 수익 평가 정본 + 직접적인 비용 후 기대값 모델`로 옮겨야 한다.

## 8. 외부 검증 기준

- Bailey et al., The Probability of Backtest Overfitting: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- Bailey and Lopez de Prado, The Deflated Sharpe Ratio: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

다수 후보 중 가장 좋아 보이는 결과를 고르는 과정 자체가 성과를 부풀릴 수 있으므로, 현재 사전등록·전체 결과 공개는 유지하고 portfolio replay 뒤에도 다중 비교 보정을 적용한다.

## 9. 이번 작업 범위

- read-only DB/JSON/code review만 수행했다.
- 신규 모델 학습, threshold 탐색, E1/E5 조기 실행, 주문/계좌 변경은 하지 않았다.
- active model, gate, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, NAS 백업 변경 없음.
