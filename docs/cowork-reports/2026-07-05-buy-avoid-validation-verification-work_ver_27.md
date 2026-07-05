# 2026-07-05 buy-avoid validation verification work_ver_27

## 1. 이번 입력과 범위 제한

- 입력 리뷰: `docs/cowork-reports/2026-07-05-buy-avoid-validation-verification-review_ver_26.md`
- 사용자 범위 제한:
  - P0: review_ver_26 §6 E1 신호 분해만 진행.
  - P1: review_ver_26 §4-1 baseline join 날짜 필터 정합만 진행.
  - 2026-07-18 전까지 이 두 개만 진행.
- 결론:
  - review_ver_26의 판단은 타당하다. E6 비용 구조 문제는 KIS live 기준으로 해소됐고, 병목은 E1 신호 정보량이다.
  - E1을 시간대·종목·변동성 구간별 daily IC로 분해했다.
  - 시간대/변동성 구간에서는 사전 기준을 넘는 후보가 없다.
  - 종목 단위에서 3개 후보가 나왔지만, 모두 07-18 전까지 정책 반영이 아니라 관찰 후보로만 둔다.

## 2. P0 — E1 신호 분해 구현

변경 파일:

- `scripts/summarize_signal_ic.py`
- `tests/test_signal_ic.py`

산출물:

- `runtime-data/reports/research/latest-signal-ic-h15.json`
- `runtime-data/reports/research/latest-signal-ic-h15.md`

### 2.1 사전 등록 기준

이번 분해는 결과를 보고 기준을 고른 것이 아니라 review_ver_26 §6 지시에 맞춰 아래 기준을 JSON/Markdown에 먼저 박아두고 실행했다.

| 항목 | 기준 |
|---|---|
| 분석 대상 | baseline 매수 허용 row + 같은 시각 LightGBM h15 shadow prediction + 닫힌 h15 label |
| daily IC | trade date 별 Spearman rank correlation |
| 분해 축 | 시간대, 종목, 최근 변동성 구간 |
| 후속 후보 기준 | `abs(mean_daily_ic) >= 0.03` and `abs(t_stat) >= 2.5` and `days_usable >= 5` |
| 판정 제한 | 2026-07-18 전까지 진단용. E2/E3 threshold/EV tuning, order policy, gate, active model 변경 금지 |

시간대 bucket:

| bucket | 기준 |
|---|---|
| `open_early` | 09:00 <= event_time < 10:00 KST |
| `midday` | 10:00 <= event_time < 14:30 KST |
| `close` | 14:30 <= event_time <= 15:30 KST |

변동성 bucket:

- 현재 schema에 별도 volatility feature가 없으므로 `curated_minute_bars`의 close를 read-only로 조회했다.
- 각 event_time 기준 최근 5개 1분 close-to-close 절대수익률 평균을 recent volatility proxy로 잡았다.
- joined row 안에서 tercile로 `low / medium / high`를 나눴다.

Codex 의견: 이 방식은 신호 원인 분해용 proxy로는 충분하지만, 모델 feature로 바로 쓰는 설계는 아니다. 변동성 bucket에서 후보가 나오더라도 07-18 전까지는 정책에 반영하지 않는다.

## 3. P0 결과 — 전체 E1 유지

기존 전체 E1 판정은 유지됐다.

| signal | usable_days | mean_daily_ic | t_stat | 판정 |
|---|---:|---:|---:|---|
| `probability_down` | 17 | 0.004754 | 0.367342 | `signal_quality_insufficient` |
| `probability_up` | 17 | 0.021684 | 1.947040 | 사전 기준 미달 |

해석:

- down 확률은 여전히 미래 수익률을 낮게 고르는 신호가 아니다.
- up 확률은 약한 양의 흔적이 있지만 사전 기준에는 못 미친다.
- 따라서 E2/E3 threshold/EV 필터 튜닝은 계속 보류한다.

## 4. P0 결과 — 시간대 분해

| time_bucket | rows | down mean IC | down t | up mean IC | up t | 후보 |
|---|---:|---:|---:|---:|---:|---|
| `open_early` | 3,335 | -0.021168 | -0.603916 | 0.032356 | 0.904864 | 없음 |
| `midday` | 19,646 | 0.007306 | 0.544207 | 0.028079 | 2.635612 | 없음 (`mean_ic < 0.03`) |
| `close` | 2,217 | 0.027358 | 0.885211 | 0.046075 | 1.339112 | 없음 |

해석:

- 시간대별로는 사전 기준을 넘는 후보가 없다.
- `midday probability_up`은 t-stat은 높지만 mean IC가 0.03 미만이라 후보가 아니다.

## 5. P0 결과 — 변동성 구간 분해

| volatility_bucket | rows | down mean IC | down t | up mean IC | up t | 후보 |
|---|---:|---:|---:|---:|---:|---|
| `low` | 8,400 | -0.008184 | -0.534421 | 0.026606 | 1.642578 | 없음 |
| `medium` | 8,399 | -0.005887 | -0.495603 | 0.007102 | 0.577906 | 없음 |
| `high` | 8,399 | 0.015153 | 0.813248 | 0.018981 | 1.138140 | 없음 |

해석:

- 최근 변동성 구간 자체가 LightGBM 신호 품질을 살리는 증거는 없다.
- 따라서 변동성 bucket 기반 필터를 07-18 전 새로 만들지 않는다.

## 6. P0 결과 — 종목 분해

사전 기준을 넘은 종목 후보만 요약한다.

| symbol | signal | rows | days | mean_daily_ic | t_stat | 후보 유형 |
|---|---|---:|---:|---:|---:|---|
| `005380` | `probability_up` | 2,421 | 17 | 0.056581 | 2.929750 | expected direction |
| `035420` | `probability_down` | 2,598 | 17 | -0.080897 | -2.722788 | expected direction |
| `105560` | `probability_down` | 2,551 | 17 | 0.090894 | 2.557247 | reverse direction |

해석:

- `005380`: up 확률이 높은 row가 실제 미래 수익률도 상대적으로 높은 후보다.
- `035420`: down 확률이 높은 row가 실제 미래 수익률이 낮은 후보다. buy-avoid 관점에서는 가장 자연스러운 후보다.
- `105560`: down 확률이 높은데 실제 미래 수익률은 오히려 높게 나온 reverse 후보다. 이건 방어 필터가 아니라 반대 해석 가능성을 뜻한다.
- 세 후보 모두 17거래일 표본의 부분집합 결과다. 다중 비교 후 살아남은 후보이긴 하지만, 07-18 전까지 정책에 반영하지 않는다.

Codex 의견: 이 결과는 “모델 전체가 쓸모없다”가 아니라 “전체로 섞으면 신호가 사라지고, 일부 종목에서만 후보가 보인다”에 가깝다. 다만 후보가 종목 단위에서 나온 만큼 과적합 위험이 크다. 다음은 새 필터 생성이 아니라 07-18까지 같은 기준으로 재측정하는 것이 맞다.

## 7. P1 — baseline join 날짜 필터 정합

변경 파일:

- `scripts/summarize_cost_horizon_diagnostics.py`
- `tests/test_cost_horizon_diagnostics.py`

변경 내용:

- `kis_live_baseline_buy_join`에 `s.event_time >= 2026-06-11` 필터를 추가했다.
- method 문구에도 같은 날짜 필터를 명시했다.
- 회귀 테스트에서 2026-06-10 baseline buy row가 제외되는지 확인했다.

결과:

| 항목 | 변경 전 | 변경 후 |
|---|---:|---:|
| `kis_live_baseline_buy_join` h15 rows | 64,173 | 25,198 |
| h15 median_abs | 0.311365 | 0.349650 |
| below_2x_cost | false | false |

해석:

- review_ver_26 §4-1 지적은 맞았다. 기존 baseline join은 날짜 창이 달라 `kis_live` 근사보다 row 수가 많았다.
- 날짜 필터 적용 후 baseline join rows가 E1 joined rows와 같은 `25,198`로 정합해졌다.
- E6 결론에는 영향 없다. baseline buy join h15도 여전히 비용 기준을 넘는다.

## 8. 반영 문서

- `docs/Current-Implementation.md`
  - E1 신호 분해 축, 사전 등록 기준, 결과 후보를 반영했다.
  - E6 baseline join 날짜 필터 정합 결과를 반영했다.
- `docs/Execution-Plan.md`
  - 07-18 전까지 작업 범위를 E1 분해와 baseline join 정합으로 제한한다고 명시했다.
- `docs/logbook.md`
  - review_ver_26 대응 기록을 추가했다.

## 9. 검증

| 검증 | 결과 |
|---|---|
| `python3 -m py_compile scripts/summarize_signal_ic.py scripts/summarize_cost_horizon_diagnostics.py tests/test_signal_ic.py tests/test_cost_horizon_diagnostics.py` | 통과 |
| `python3 -m pytest tests/test_signal_ic.py tests/test_cost_horizon_diagnostics.py -q` | `6 passed` |
| `python3 scripts/summarize_signal_ic.py --horizon-min 15` | 통과, E1 decomposition report 재생성 |
| `python3 scripts/summarize_cost_horizon_diagnostics.py --horizons 15 30 60` | 통과, E6 report 재생성 |
| 전체 pytest | 최종 검증에서 별도 보고 |

## 10. 다음 방향

### 2026-07-18 전까지 계속할 것

1. 같은 기준으로 KIS live shadow를 계속 쌓는다.
2. E1 전체 down/up IC와 후보 3개 종목을 같은 사전 기준으로 관찰한다.
3. 장후 자동화/대시보드/정합성은 기존 운영 체크만 유지한다.

### 2026-07-18 전까지 하지 않을 것

1. E2/E3 threshold/EV 필터 튜닝을 시작하지 않는다.
2. 종목별 후보를 주문 정책으로 반영하지 않는다.
3. h60 주문 정책을 설계하지 않는다.
4. active model, gate, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`를 바꾸지 않는다.

### 다음 cowork 리뷰 필요 시점

- 이번 work_ver_27에서 E1 분해 수치와 baseline join 정합이 맞는지 확인받는 시점.
- 그 다음 큰 리뷰는 2026-07-18 이후 재측정 결과가 나온 뒤가 적절하다.

## 11. self-review

- 누락한 작업: review_ver_26의 P0/P1만 처리했고, 07-18 전 보류 항목은 건드리지 않았다.
- 잘못 진행한 부분: 새 모델 학습, threshold tuning, gate/policy 변경 없음.
- 결과 판단: 시간대/변동성 후보 없음, 종목 후보 3개라는 해석은 JSON 결과와 일치한다.
- 코드 오류점검: 신규 분해 로직과 날짜 필터 회귀 테스트를 추가했다.
- 기타 리뷰: 변동성 bucket은 기존 feature가 아니라 `curated_minute_bars` 기반 recent volatility proxy 라는 한계를 명시했다.
