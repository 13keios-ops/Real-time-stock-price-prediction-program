# 2026-07-05 buy-avoid validation verification work_ver_25

## 1. 이번 입력과 결론

- 입력 리뷰: `docs/cowork-reports/2026-07-05-buy-avoid-validation-verification-review_ver_24.md`
- 관련 계획: `docs/cowork-reports/2026-07-05-alternative-approaches-validation-plan.md`
- 결론:
  - review_ver_24의 지적은 타당하다. work_ver_24의 유일한 미완은 `검증 예정`을 실제 실행 결과로 닫지 않은 점이었다.
  - buy-avoid 해석 잠금은 완료로 본다.
  - 이어서 계획서 Phase 1의 E1/E6을 read-only 진단으로 실행했다.
  - E1/E6 결과상 지금 h15에서 바로 E2/E3 threshold/EV 필터 튜닝으로 가는 것은 부적절하다.

## 2. review_ver_24 대응

### 2.1 검증 미보고 보완

아래 검증을 실제 실행했다.

| 검증 | 결과 |
|---|---|
| `python3 -m py_compile scripts/buy_avoid_random_control.py scripts/summarize_lightgbm_defensive_shadow.py scripts/summarize_cybos_buy_avoid_proxy.py` | 통과 |
| `python3 -m pytest tests/test_buy_avoid_random_control.py tests/test_lightgbm_defensive_shadow.py tests/test_cybos_buy_avoid_proxy.py -q` | `30 passed` |
| `git diff --check` | 통과 |

### 2.2 문서 이중화 보완

- `docs/Buy-Avoid-Random-Control-Methodology.md` §8에 방법론 문서의 KIS-Cybos 비교표가 정본이라는 문장을 추가했다.
- `docs/cowork-reports/`의 work/review 표는 당시 스냅샷으로만 본다.

## 3. Phase 1 E1 — Signal IC 결과

- 실행 명령: `python3 scripts/summarize_signal_ic.py --horizon-min 15`
- 산출물:
  - `runtime-data/reports/research/latest-signal-ic-h15.json`
  - `runtime-data/reports/research/latest-signal-ic-h15.md`
- 신규 파일:
  - `scripts/summarize_signal_ic.py`
  - `tests/test_signal_ic.py`

| 항목 | 값 |
|---|---:|
| joined_rows | `25,198` |
| trade_days | `17` |
| probability_down mean_daily_ic | `0.004754` |
| probability_down t_stat | `0.367342` |
| probability_up mean_daily_ic | `0.021684` |
| probability_up t_stat | `1.947040` |
| decision | `signal_quality_insufficient` |
| proceed_to_e2_e3 | `false` |

사전 등록 기준은 `probability_down`이 미래 수익률과 음의 순위상관을 보여야 한다는 것이었다. 즉 하락확률이 높을수록 미래 수익률이 낮아야 한다. 그런데 실제 평균 IC는 거의 0에 가깝고 t-stat도 약하다. 따라서 `down_threshold`를 더 만지는 실험으로 바로 가면 안 된다.

Codex 의견: KIS live에서 LightGBM 하락확률은 현재 baseline 매수 후보를 선별할 만큼 안정적인 정보량이 확인되지 않았다. buy-avoid 실패는 threshold 선택 문제가 아니라 신호 품질 문제일 가능성이 크다.

## 4. Phase 1 E6 — Cost/Horizon 결과

- 실행 명령: `python3 scripts/summarize_cost_horizon_diagnostics.py --horizons 15 30 60`
- 산출물:
  - `runtime-data/reports/research/latest-cost-horizon-diagnostics.json`
  - `runtime-data/reports/research/latest-cost-horizon-diagnostics.md`
- 신규 파일:
  - `scripts/summarize_cost_horizon_diagnostics.py`
  - `tests/test_cost_horizon_diagnostics.py`

| horizon | status | rows | median_abs | p75_abs | p90_abs | breakeven_win_rate | below_2x_cost |
|---:|---|---:|---:|---:|---:|---:|---|
| 15 | `ok` | `6,281,164` | `0.189394` | `0.370370` | `0.621861` | `0.635491` | `true` |
| 30 | `no_labels` | `0` | - | - | - | - | - |
| 60 | `ok` | `5,527,234` | `0.341880` | `0.660502` | `1.136364` | `0.569931` | `false` |

사전 등록 기준은 h15 `median_abs_future_return_pct < 2 * trade_cost_pct`이면 필터 튜닝만으로 흑자 전환이 어렵다는 경고를 켜는 것이다. 현재 `2 * trade_cost_pct = 0.216`이고 h15 중위 절대 변동폭은 `0.189394`라 경고가 켜졌다.

Codex 의견: h15는 중위 거래가 비용을 이기기 어렵다. 따라서 “모델이 조금만 더 맞히면 된다”가 아니라, 거래 빈도를 크게 줄이거나, horizon을 늘리거나, 체결 비용/슬리피지를 줄이는 구조 검토가 먼저다. h60은 비용 구조가 더 낫지만, h60 주문 정책은 별도 gate와 체결 검증 전까지 만들지 않는다.

## 5. 반영 문서

- `docs/Buy-Avoid-Random-Control-Methodology.md`
  - §8 KIS-Cybos 비교표가 정본이고 cowork work/review 표는 스냅샷이라는 문장을 추가했다.
- `docs/Execution-Plan.md`
  - 상단 요약의 오래된 buy-avoid 후보 표현을 `재검증 필요, 무작위 대조군 대비 우위 미확인`으로 정정했다.
  - E1/E6 결과를 추가하고 E2/E3 보류 방향을 명시했다.
- `docs/Current-Implementation.md`
  - `summarize_signal_ic.py`, `summarize_cost_horizon_diagnostics.py` 실행 방법과 현재 판정을 추가했다.
- `docs/logbook.md`
  - 이번 review_ver_24 대응과 E1/E6 결과를 기록했다.

## 6. 다음 방향

### 계속 진행

1. h15 LightGBM `probability_down` 자체의 정보량이 약한 원인을 찾는다.
2. h15보다 h60에서 비용 구조가 나은지, 실제 신호/체결/포지션 정책으로도 의미가 있는지 별도 사전 등록 기준을 세운다.
3. KIS-only orderbook 피처(`bid_ask_imbalance`, `spread_bps`)와 시간대/모멘텀 후보를 신호 품질 개선 트랙에서 다시 본다.

### 보류

1. E2 EV 필터와 E3 regime 조건부 필터는 이번 E1 기준을 통과하지 못했으므로 즉시 실행하지 않는다.
2. buy-avoid를 주문 정책으로 반영하지 않는다.
3. active model, gate, threshold, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`를 바꾸지 않는다.

### 다음 cowork 리뷰 필요 시점

- h15 신호 품질 개선 트랙의 구체 실험 후보를 사전 등록할 때.
- h60 전환 후보를 실제 주문 정책 관점으로 설계하기 전.
- 2026-07-18 이후 KIS live random-control 추가 관측 구간이 닫힌 뒤.

## 7. self-review

- 누락한 작업: review_ver_24의 유일한 미완인 검증 결과 보고를 닫았다. 대안 계획의 Phase 1 E1/E6도 실행했다.
- 잘못 진행한 부분: 운영 DB는 read-only로만 열었고, 주문/게이트/실전 설정은 건드리지 않았다.
- 결과 판단: IC가 약하고 h15 비용 구조가 불리하다는 결론은 실제 JSON 수치와 일치한다. E2/E3는 보류가 맞다.
- 코드 오류점검: 신규 스크립트 2개와 테스트 2개를 추가했고 py_compile/pytest로 검증했다.
- 기타 리뷰: 방법론 문서 정본 기준을 명시해 work_ver 표와의 유지보수 충돌을 줄였다.
