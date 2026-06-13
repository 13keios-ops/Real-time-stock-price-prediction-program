# Cybos Rescue Experiment Plan

- 작성 시각: 2026-06-14 02:35 KST
- 목적: Cybos 5년치에서 `buy-avoid`, `buy-rescue`, `hold-rescue`를 어떤 순서와 기준으로 볼지 실행 전 고정한다.
- 상태: 실행 전 계획. 이 문서 자체는 모델, gate, 주문 정책을 바꾸지 않는다.
- 적용 범위: 장외 research-only 백테스트와 KIS live shadow 관측 계획.

## 1. 결론부터

권장안:

- Cybos 5년 백테스트에서는 `buy-avoid`와 `buy-rescue`를 같은 리포트에서 함께 비교한다.
- 단, 실행 전에 기준을 고정하고, 결과를 본 뒤 threshold 또는 지표를 바꾸지 않는다.
- KIS live shadow 에서는 지금처럼 `buy-avoid`부터 최소 10거래일 순차 관측한다.
- `hold-rescue`는 포지션 lifecycle 시뮬레이션이 필요하므로 별도 설계와 테스트 후 붙인다.

이유:

- Cybos 는 이미 과거 데이터와 fold 구조가 있으므로 장외에서 후보를 넓게 걸러내기 좋다.
- 그러나 같은 과거 데이터에서 여러 실험을 동시에 돌리면 우연히 좋아 보이는 결과를 고를 위험, 즉 다중 검정 위험이 커진다.
- 따라서 Cybos 결과는 `탐색 리포트`이고, KIS live 에서는 순차 검증으로만 승격 후보를 판단한다.

관련 문서/코드 경로:
`docs/Execution-Plan.md`,
`docs/Production-Transition-Progress.md`,
`scripts/summarize_cybos_buy_avoid_proxy.py`,
`runtime-data/reports/backtests/latest-cybos-buy-avoid-proxy-h15.json`

## 2. 용어 정리

### buy-avoid

뜻:

- 어떤 기준이 매수 후보라고 본 것 중에서, LightGBM 이 하락 위험이 높다고 본 후보를 매수하지 않는 실험이다.
- 목적은 수익 창출보다 손실 축소다.

현재 주의점:

- 최신 Cybos buy-avoid proxy 의 `baseline`은 실제 runtime baseline 모델의 주문 판단과 완전히 같은 뜻이 아니다.
- 현재 Cybos proxy 에서는 Cybos LightGBM 이 만든 매수 후보 집합을 기준 후보로 놓고, 그 안에서 하락확률이 높은 것을 거른다.
- 따라서 문서와 대시보드에서는 `runtime baseline 매수 판단`과 `Cybos proxy baseline candidate`를 구분해야 한다.
- 2026-06-14 cowork 재검토 기준으로, 기존 12/12 fold 개선 결과는 `LightGBM이 runtime baseline의 나쁜 매수를 막았다`가 아니라 `LightGBM이 자기 proxy 매수 후보 중 손실 후보를 자체 필터링했다`로만 해석한다.

권장안:

- 다음 리포트에서는 현재 방식 이름을 `lightgbm_self_filter_buy_avoid_proxy`로 더 명확히 둔다.
- 실제 runtime baseline 과 비교하려면 Cybos 에서 baseline 판단을 재현할 수 있는지 먼저 확인한다.

관련 문서/코드 경로:
`scripts/summarize_cybos_buy_avoid_proxy.py`,
`app/models/baseline.py`,
`app/services/research.py`

### buy-rescue

뜻:

- baseline 또는 proxy 기준이 매수하지 않았거나 하락/보합으로 본 후보 중에서, LightGBM 이 상승 확률이 높다고 본 것을 가상 매수하는 실험이다.
- 목적은 놓친 수익 기회를 LightGBM 이 찾아낼 수 있는지 확인하는 것이다.

주의점:

- 현재까지 LightGBM 이 강하게 보인 방향은 상승보다 하락/회피다.
- 따라서 buy-rescue 는 본실험이 아니라 `상승 신호 품질 확인용 탐색 실험`이다.

관련 문서/코드 경로:
`runtime-data/reports/challengers/latest-lightgbm-buy-signal-diagnostics-h15.json`,
`runtime-data/reports/challengers/latest-lightgbm-defensive-signal-candidates-h15.json`,
`runtime-data/reports/backtests/latest-cybos-buy-avoid-proxy-h15.json`

### hold-rescue

뜻:

- 이미 산 포지션을 baseline 이 팔거나 청산하려 할 때, LightGBM 이 상승 확률이 높다고 보면 더 보유했을 때 결과가 좋아지는지 보는 실험이다.

주의점:

- buy-avoid 와 buy-rescue 는 단일 시점 판단이다.
- hold-rescue 는 진입, 보유, 청산, 보유 기간, 포지션 크기, 강제청산 룰을 추적해야 한다.
- 따라서 같은 스크립트에 바로 끼워 넣지 않고 별도 lifecycle 시뮬레이션 설계가 필요하다.

관련 문서/코드 경로:
`app/paper_trading/`,
`app/portfolio/`,
`app/services/reporting.py`,
`runtime-data/reports/challengers/latest-lightgbm-defensive-shadow-h15.json`

## 3. 선행 확인

### 3.1 Cybos 쪽 baseline 판단 재현 가능성

확인할 것:

- Cybos 5년 데이터에서 runtime baseline 모델의 `매수`, `비매수`, `하락`, `보합` 판단을 재현할 수 있는지 확인한다.
- 재현 가능하면 buy-rescue 는 `baseline_no_buy + lightgbm_up_candidate` 구조로 본다.
- 재현이 어렵다면 `Cybos proxy baseline candidate`로만 명시하고, 실제 runtime baseline 비교처럼 말하지 않는다.

권장안:

- 첫 구현 전 `app.models.baseline.BaselineDirectionModel`이 Cybos bar feature row 에서 바로 예측 가능한지 코드로 확인한다.
- 가능하면 baseline prediction 을 Cybos fold test row 마다 함께 산출한다.
- 불가능하면 이 사실을 리포트 최상단에 `runtime_baseline_not_replayed`로 표시한다.

2026-06-14 Step 0 확인 결과:

- `BaselineDirectionModel`은 `return_1m_pct`, `bid_ask_imbalance`, `spread_bps`를 사용한다.
- Cybos bar row 는 `return_1m_pct`는 갖지만 live orderbook 피처인 `bid_ask_imbalance`, `spread_bps`를 갖지 않는다.
- 모델 함수 호출 자체는 누락 피처 기본값 `0.0` 때문에 가능하지만, 이것은 runtime baseline 재현이 아니다.
- 따라서 Cybos rescue 1차 실험은 `baseline_replay_buy_rescue`가 아니라 `proxy_buy_rescue`로 진행한다.
- `scripts/summarize_cybos_buy_avoid_proxy.py`는 이후 report 에 `runtime_baseline_replay.available=false`, `status=not_replayed_orderbook_features_missing`, `recommended_experiment_mode=proxy_buy_rescue`를 기록한다.
- 이 확인 없이 Step 1 실험으로 넘어가지 않는 것을 고정 gate 로 둔다. 이미 full 12 fold report 를 만들었더라도, 해석은 위 Step 0 결과에 의해 `proxy` 범위로 제한한다.

변경 전 / 변경 후 / 영향 범위 / 회귀 위험:

- 변경 전: Cybos proxy 의 `baseline`이 실제 runtime baseline 처럼 오해될 수 있다.
- 변경 후: baseline replay 가능 여부를 리포트에 명시하고, proxy baseline 과 runtime baseline 을 분리한다.
- 영향 범위: `scripts/summarize_cybos_buy_avoid_proxy.py`, 새 rescue 리포트, cowork 전달 문서.
- 회귀 위험: 이름이 바뀌면 기존 리포트와 비교할 때 혼동될 수 있다. 기존 key 는 보존하고 새 설명 필드를 추가한다.

관련 문서/코드 경로:
`app/models/baseline.py`,
`scripts/summarize_cybos_buy_avoid_proxy.py`

### 3.2 KIS live 쪽 비매수/차단 로그 가용성

확인할 것:

- KIS live runtime 이 `매수하지 않음`, `하락 판단`, `차단`, `매도 신호`를 충분히 로그로 남기는지 확인한다.
- buy-rescue live shadow 를 하려면 `symbol`, `event_time`, baseline 판단, LightGBM shadow 예측, 닫힌 label 이 같은 키로 연결되어야 한다.

권장안:

- 지금 당장 KIS live 에 buy-rescue shadow 를 붙이지 않는다.
- 먼저 read-only 로 `serving_predictions`, `paper_signals`, signal/order report 에 비매수 판단이 남는지 확인한다.
- 부족하면 나중에 장중 로직을 바꾸지 않고도 기록만 남기는 `no-trade decision ledger` 설계를 별도로 한다.

변경 전 / 변경 후 / 영향 범위 / 회귀 위험:

- 변경 전: 매수/주문이 발생한 경우만 잘 남고, 매수하지 않은 이유는 실험에 충분하지 않을 수 있다.
- 변경 후: buy-rescue shadow 가능 여부를 데이터 가용성 기준으로 판단한다.
- 영향 범위: read-only DB 점검, 향후 signal ledger 설계.
- 회귀 위험: 비매수 로그를 무분별하게 늘리면 DB 용량과 대시보드 부하가 커질 수 있다. 6개월 이상 보관 정책과 압축 요약이 필요하다.

관련 문서/코드 경로:
`runtime-data/dev.db`,
`app/services/streaming.py`,
`app/services/reporting.py`,
`app/storage/sqlite_store.py`

## 4. Cybos 동시 비교 설계

### 4.1 고정 split 과 비용 기준

고정 기준:

- source: `cybos-historical`
- horizon: `15`
- feature profile: `bar_context_momentum`
- fold 구조: 기존 Cybos proxy 와 같은 walk-forward 구조를 우선 사용
- trade cost: `0.13%`
- 자동 모델 승격: 없음
- gate 변경: 없음
- 주문 정책 변경: 없음

권장안:

- 기존 `scripts/summarize_cybos_buy_avoid_proxy.py`를 확장하거나 새 스크립트 `scripts/summarize_cybos_rescue_proxy.py`를 만든다.
- 기존 buy-avoid 리포트는 유지하고, 새 통합 리포트는 `latest-cybos-rescue-proxy-h15.{json,md}`로 별도 생성한다.

관련 문서/코드 경로:
`scripts/summarize_cybos_buy_avoid_proxy.py`,
`runtime-data/reports/backtests/`

### 4.2 buy-avoid 기준

목적:

- 나쁜 매수를 피해서 손실이 줄어드는지 확인한다.

고정 기준:

- skip-rate 후보: `0.20`, `0.30`, `0.3665`, `0.40`, `0.50`
- 실용 coverage: `20~50%`
- KIS shadow 비교 중심: `30~40%`
- 성공 후보:
  - 비용 `0.13%` 반영 뒤 net improvement 양수
  - 전체 fold 중 최소 `2/3` 이상 개선
  - coverage 가 `20~50%` 안에 있음
  - kept net 이 양수이면 강한 후보, kept net 이 음수이면 손실 축소 후보

현재 해석:

- 최신 Cybos 결과에서 target skip `0.3665`는 12/12 fold 개선이지만 kept net 은 음수다.
- 따라서 `손실 축소 후보`이지 `수익 창출 모델`은 아니다.

관련 문서/코드 경로:
`runtime-data/reports/backtests/latest-cybos-buy-avoid-proxy-h15.json`

### 4.3 buy-rescue 기준

목적:

- baseline 또는 proxy 가 버린 후보 중 LightGBM 이 상승 기회를 찾아내는지 확인한다.

후보 정의:

- 1순위 정의:
  - baseline replay 가 가능할 때:
    - `baseline_predicted_label != up` 또는 baseline 매수 신호 없음
    - 동시에 LightGBM `probability_up`이 높은 후보
  - 이 경우를 `baseline_replay_buy_rescue`로 부른다.
- 2순위 정의:
  - baseline replay 가 불가능할 때:
    - LightGBM 내부의 낮은 up-confidence 후보 또는 non-up predicted 후보를 기준으로 구조를 본다.
  - 이 경우를 `proxy_buy_rescue`로 부르며 runtime baseline 비교처럼 해석하지 않는다.

threshold / coverage 후보:

- up rescue coverage 후보: `0.05`, `0.10`, `0.20`, `0.30`
- 이유:
  - buy-rescue 는 원래 매수하지 않았을 후보를 되살리는 공격적 실험이다.
  - 따라서 처음부터 50% 가까이 되살리면 과잉 매수 위험이 크다.
  - 작은 coverage 에서 먼저 양수 기대값이 나와야 의미가 있다.

성공 후보:

- rescued trades 가 fold 전체 합산 최소 `500건` 이상
- 비용 `0.13%` 반영 뒤 rescued net 이 양수
- 전체 fold 중 최소 `2/3` 이상에서 rescued net 이 0 이상
- high-vol 구간에서 손실이 폭발하지 않음
- buy-avoid 와 같은 데이터에서 나온 결과임을 표시하고, `탐색 후보`로만 둠

실패 판단:

- rescued net 이 음수이면 KIS live buy-rescue shadow 로 올리지 않는다.
- rescued trades 가 너무 적으면 `표본 부족`으로 둔다.
- 특정 fold 1~2개가 전체 수익을 끌어올리면 `fold concentration risk`로 둔다.

관련 문서/코드 경로:
`scripts/summarize_cybos_buy_avoid_proxy.py`,
`app/services/research.py`

## 5. 다중 검정 방지 규칙

문제:

- 같은 Cybos 5년 데이터에서 buy-avoid, buy-rescue, hold-rescue, 여러 threshold 를 동시에 보면 우연히 좋아 보이는 결과가 나올 확률이 올라간다.

고정 규칙:

- 실행 전 threshold grid 를 고정한다.
- 결과가 나온 뒤 threshold 를 추가해서 가장 좋은 값만 강조하지 않는다.
- 모든 후보 결과를 리포트 표에 공개한다.
- `best`를 표시하더라도 `best after fixed grid`라고 명시한다.
- buy-avoid 는 1순위 가설, buy-rescue 는 2순위 탐색 가설, hold-rescue 는 별도 설계 가설로 구분한다.
- Cybos 결과가 좋더라도 KIS live shadow 없이 active model 승격 후보로 올리지 않는다.

권장안:

- 리포트에 `hypothesis_rank`와 `multiple_testing_guardrails` 섹션을 넣는다.
- 결론 label 은 아래 중 하나만 사용한다.
  - `follow_up_candidate_proxy_only`
  - `diagnostic_only_hold`
  - `sample_insufficient`
  - `coverage_out_of_bounds`
  - `fold_concentration_risk`

관련 문서/코드 경로:
`runtime-data/reports/backtests/latest-cybos-rescue-proxy-h15.json`

## 6. hold-rescue 별도 설계

hold-rescue 는 이번 1차 통합 실행에 바로 넣지 않는다.

필요한 설계:

- 진입 기준:
  - baseline 또는 proxy 가 언제 포지션을 열었는지 정의한다.
- 청산 기준:
  - baseline 이 언제 팔았는지 또는 horizon 만료로 청산했는지 정의한다.
- rescue 조건:
  - 청산 시점에 LightGBM `probability_up`이 높은 경우 보유를 연장한다.
- 최대 보유 시간:
  - 예: 15분 horizon 실험에서는 15분 추가, 또는 같은 날 장마감 전까지만.
- 위험 제한:
  - 손실이 더 커지는 경우를 막기 위해 최대 손실, 최대 보유 시간, 종가 청산을 둔다.
- 비교 기준:
  - 원래 청산 손익
  - 보류 후 청산 손익
  - 최대 낙폭
  - 기회비용
  - 손실 확대 fold 수

권장안:

- 1차 작업에서는 hold-rescue 를 결과 실험으로 바로 구현하지 않는다.
- 먼저 `hold_rescue_lifecycle_spec`을 리포트에 설계 섹션으로 넣는다.
- 그 다음 synthetic test 로 작은 포지션 시퀀스를 재현한 뒤 Cybos 전체 실행을 검토한다.

2026-06-14 구현 상태:

- `latest-cybos-rescue-proxy-h15` report 는 `hold_rescue_lifecycle_spec.status=not_executed_in_this_report`를 출력한다.
- required next steps 는 entry policy, baseline exit policy, hold extension rule, max holding time, drawdown/opportunity cost 비교, synthetic lifecycle test 순서로 기록한다.
- 아직 hold-rescue 결과 수익률은 계산하지 않는다.

변경 전 / 변경 후 / 영향 범위 / 회귀 위험:

- 변경 전: 조기청산 또는 청산 보류를 단일 시점 예측처럼 단순화할 위험이 있다.
- 변경 후: 포지션 lifecycle 을 기준으로 진입, 보유, 청산을 따로 추적한다.
- 영향 범위: 새 연구 스크립트, synthetic test, 향후 paper replay 분석.
- 회귀 위험: 포지션 시뮬레이션이 실제 paper 엔진과 다르면 잘못된 수익률을 만들 수 있다. 처음에는 연구용 proxy 로만 표시한다.

관련 문서/코드 경로:
`app/paper_trading/`,
`app/portfolio/`,
`tests/`,
`runtime-data/reports/backtests/`

## 7. KIS live 적용 계획

KIS live 에서는 동시에 늘리지 않는다.

현재 순서:

1. buy-avoid shadow 를 최소 10거래일 쌓는다.
2. 연결 표본 기준을 확인한다.
   - `matched_buy_shadow_rows >= 1,000`
   - `matched_trade_days >= 10`
   - 8거래일 이상 일별 `50`건 이상
   - `matched_symbols >= 5`
   - `avoid_candidate_rows >= 200`
3. Cybos buy-rescue 가 양수 후보로 나온 경우에만 KIS live buy-rescue shadow 를 설계한다.
4. KIS live buy-rescue shadow 를 붙이기 전, 비매수/차단 로그 가용성을 먼저 확인한다.
5. hold-rescue 는 KIS live 에 붙이지 않고, Cybos lifecycle 설계와 paper replay 결과를 먼저 본다.

금지:

- Cybos 결과만으로 active model 변경 금지.
- Cybos 결과만으로 gate 기준값 변경 금지.
- Cybos 결과만으로 paper/live 주문 판단 변경 금지.
- `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS` 변경 금지.

관련 문서/코드 경로:
`runtime-data/reports/challengers/latest-lightgbm-defensive-shadow-h15.json`,
`docs/Production-Transition-Progress.md`,
`docs/Execution-Plan.md`

## 8. 작업 단계

### Step 0. 용어와 리포트 의미 정리

작업:

- 현재 Cybos buy-avoid proxy 의 `baseline` 의미를 재검토한다.
- 실제 runtime baseline replay 가능 여부를 확인한다.
- 리포트 명칭과 key 설명을 보강한다.

완료 기준:

- `runtime_baseline_replay.available=false`와 `recommended_experiment_mode=proxy_buy_rescue`가 새 리포트에 들어간다.
- proxy baseline 과 runtime baseline 이 문서에서 구분된다.
- `tests/test_cybos_buy_avoid_proxy.py`가 orderbook 피처 누락 시 runtime baseline replay 를 금지한다.

관련 문서/코드 경로:
`scripts/summarize_cybos_buy_avoid_proxy.py`,
`app/models/baseline.py`

### Step 1. buy-rescue 계산 helper 설계

작업:

- buy-rescue 후보 생성 함수를 만든다.
- threshold coverage 를 고정한다.
- rescued net, fold consistency, coverage, concentration risk 를 계산한다.

완료 기준:

- 작은 synthetic data 에서 `baseline no-buy + LightGBM up` 후보가 correctly rescued 되는 단위 테스트가 있다.

관련 문서/코드 경로:
`scripts/summarize_cybos_buy_avoid_proxy.py` 또는 `scripts/summarize_cybos_rescue_proxy.py`,
`tests/test_cybos_buy_avoid_proxy.py` 또는 신규 `tests/test_cybos_rescue_proxy.py`

### Step 2. Cybos 통합 리포트 생성

작업:

- buy-avoid 와 buy-rescue 를 같은 fold 에서 계산한다.
- 모든 threshold 결과를 공개한다.
- 다중 검정 guardrail 을 리포트에 넣는다.
- hold-rescue 는 설계 섹션만 넣는다.

완료 기준:

- `runtime-data/reports/backtests/latest-cybos-rescue-proxy-h15.json`
- `runtime-data/reports/backtests/latest-cybos-rescue-proxy-h15.md`
- 12/12 fold 실행 완료

관련 문서/코드 경로:
`runtime-data/reports/backtests/`,
`scripts/summarize_cybos_rescue_proxy.py`

### Step 3. 결과 판정

판정 기준:

- buy-avoid 만 좋음:
  - LightGBM 은 방어 필터 후보.
  - KIS live buy-avoid shadow 를 계속 쌓는다.
- buy-avoid 와 buy-rescue 둘 다 좋음:
  - LightGBM 은 방어 필터 + 매수 보조 후보.
  - KIS live buy-rescue shadow 설계 후보로 올린다.
- buy-rescue 만 좋음:
  - 현재 증거와 충돌하므로 fold concentration 과 다중 검정 위험을 먼저 본다.
  - 바로 KIS live 로 올리지 않는다.
- 둘 다 약함:
  - LightGBM rescue 방향 우선순위를 낮춘다.

관련 문서/코드 경로:
`runtime-data/reports/backtests/latest-cybos-rescue-proxy-h15.json`,
`docs/Production-Transition-Progress.md`

### Step 4. 문서와 cowork 전달

작업:

- 결과를 `docs/Execution-Plan.md`와 `docs/Production-Transition-Progress.md`에 반영한다.
- cowork 전달용 `work_ver_20-3` 또는 다음 버전 파일을 작성한다.

완료 기준:

- 결과 해석에 `탐색`, `shadow 후보`, `실제 적용 아님`이 명시되어 있다.

관련 문서/코드 경로:
`docs/cowork-reports/`,
`docs/Execution-Plan.md`,
`docs/Production-Transition-Progress.md`

## 9. 검증 계획

최소 검증:

```bash
python -m py_compile scripts/summarize_cybos_buy_avoid_proxy.py
python -m unittest tests.test_cybos_buy_avoid_proxy -q
git diff --check
```

코드 확장 시 권장 검증:

```bash
python -m unittest tests.test_cybos_buy_avoid_proxy tests.test_cybos_research_suite_summary tests.test_expected_value_stability -q
python -m unittest discover -s tests -p "test_*.py" -q
```

장중에는 전체 테스트와 heavy Cybos 실행을 하지 않는다.
주말/장외에만 전체 Cybos 12 fold 를 실행한다.

관련 문서/코드 경로:
`tests/`,
`scripts/summarize_cybos_buy_avoid_proxy.py`

## 10. 이번 계획의 최종 권장안

바로 다음 작업 권장안:

1. 코드 실행 전에 현재 Cybos buy-avoid proxy 의 baseline 의미를 정리한다.
2. baseline replay 가능 여부를 read-only 로 확인한다.
3. 가능하면 `baseline_replay_buy_rescue`, 불가능하면 `proxy_buy_rescue`로 분리해 구현한다.
4. buy-avoid 와 buy-rescue 를 같은 Cybos 리포트에 묶되, 다중 검정 guardrail 을 넣는다.
5. hold-rescue 는 이번 실행에서 결과 실험으로 넣지 않고 lifecycle 설계만 남긴다.
6. KIS live 에는 buy-rescue 를 아직 붙이지 않는다.

관련 문서/코드 경로:
`docs/Execution-Plan.md`,
`docs/Production-Transition-Progress.md`,
`scripts/summarize_cybos_buy_avoid_proxy.py`
