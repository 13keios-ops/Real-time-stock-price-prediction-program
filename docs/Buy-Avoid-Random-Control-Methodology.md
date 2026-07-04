# Buy-Avoid Random-Control Methodology (무작위 대조군 검증 표준)

- 제정: 2026-07-04, cowork(Claude) 직접 구현
- 지위: **이 문서가 buy-avoid류 필터 검증의 단일 기준(single source of truth)이다.**
- 구현: `scripts/buy_avoid_random_control.py`
- 테스트: `tests/test_buy_avoid_random_control.py` (DB 없이 실행 가능)
- 적용 리포트: `latest-lightgbm-defensive-shadow-h*.json`, `latest-cybos-buy-avoid-proxy-h*.json`

**Codex 규칙: buy-avoid/skip/filter 관련 코드를 만지기 전에 반드시 이 문서를 읽는다.
아래 공식·부호 규약·seed를 바꾸려면 (1) 이 문서를 먼저 수정하고 (2) 테스트를 갱신하고
(3) work_ver 리포트에 변경 사유를 명기해야 한다. 셋 중 하나라도 빠지면 그 변경은 무효로 간주한다.**

---

## 1. 왜 이 검증이 필수인가 (착시의 원리)

baseline 거래 모집단의 평균 수익률이 음수이면, **어떤 부분집합을 제거해도** 남은 집합의
누적 수익률은 개선된다. 무작위로 제거해도 개선된다. 따라서:

> `delta_net_pct > 0` (필터 적용 후 개선) 은 필터가 나쁜 거래를 골라냈다는 증거가 **아니다**.

실제 사례 (2026-07-04 review_ver_23에서 발견):
KIS live shadow threshold 0.40은 delta +486.38%p로 "개선"처럼 보였지만,
같은 개수(6,694건)를 무작위로 제거했을 때의 기대 개선은 +711.85%p였다.
즉 필터가 무작위보다 약 225%p **못했다**. delta만 보면 이 사실이 절대 보이지 않는다.

## 2. 공식 (구현과 1:1 대응)

기호: 모집단(baseline) 거래의 net 수익률 목록 `x_1..x_N`, 필터가 회피한 거래 수 `n`.

```
모집단 평균          μ  = (Σ x_i) / N
모집단 분산          σ² = (Σ (x_i - μ)²) / N          ← N으로 나눔 (모분산)
무작위 회피 기대값    E  = n · μ
무작위 회피 분산      V  = n · σ² · (N - n) / (N - 1)  ← 비복원추출 유한모집단 보정
무작위 회피 표준편차  S  = √V
초과분               excess = actual_skipped_sum - E
z-score              z  = excess / S
```

- `actual_skipped_sum` = 필터가 실제로 회피한 거래들의 net 수익률 합 (cost 차감 후, 리포트의 다른 수치와 동일 기준).
- 비복원추출 보정 `(N-n)/(N-1)`을 빼먹으면 분산이 과대평가된다. 반드시 유지.
- 검증용 엄밀 예제: 모집단 `[-1, 0, 1]`에서 2개 추출 → 가능한 합 {-1, 0, 1}, 기대 0, 분산 2/3.
  공식 대입: 2·(2/3)·(3-2)/(3-1) = 2/3 ✓ (테스트에 포함됨)

## 3. 부호 규약 (절대 뒤집지 말 것)

```
excess < 0  → 필터가 회피한 거래가 무작위보다 더 손실이 컸다 → 필터가 진짜 선별한다 (좋음)
excess > 0  → 필터가 회피한 거래가 무작위보다 나았다        → 역선별 (나쁨)
```

판정 (단측 95%, |z|≥1.6449):

| z | verdict |
|---|---|
| z ≤ -1.6449 | `filter_better_than_random_p95` (통과) |
| -1.6449 < z < +1.6449 | `not_distinguishable_from_random` (미통과) |
| z ≥ +1.6449 | `filter_worse_than_random_p95` (미통과, 역선별) |

**fail-closed: 통과는 오직 `filter_better_than_random_p95` 하나뿐이다.**

## 4. 시뮬레이션과 자기검증(self-check)

해석적 공식이 1차 기준이고, 시뮬레이션은 구현 오류 탐지용 교차검증이다.

- seed: `seed_base=20260704`, trial i는 `random.Random(seed_base + i)` 사용. 총 100회.
- 각 trial: `rng.sample(range(N), n)`으로 비복원 무작위 추출 → 합 기록.
- **self-check: |시뮬레이션 평균 - E| ≤ 5·(S/√trials)** 여야 한다.
  실패 시 verdict는 `self_check_failed_do_not_use`가 되고 그 블록 전체를 신뢰하면 안 된다.
  (모집단을 잘못 넘겼거나, n이 틀렸거나, 샘플링이 편향된 것)
- seed_base를 바꾸면 과거 리포트와 시뮬레이션 수치가 비교 불가능해진다. 바꾸지 말 것.

## 5. fold 구조(Cybos proxy)에서의 집계

Cybos proxy는 fold별로 threshold를 다시 잡으므로 무작위 대조군도 **fold 안에서** 만든다.
fold별 (actual, E_f, V_f)를 구한 뒤 독립성에 의해 합산한다:

```
E_total = Σ E_f,   V_total = Σ V_f,   z_total = (Σ actual_f - E_total) / √V_total
```

- 풀링된 평균으로 한 번에 계산하면 fold별 threshold 재보정 구조를 무시하게 되므로 금지.
- fold별 verdict 분포(`fold_verdict_counts`)도 함께 기록한다 — 한 개 fold가 전체를 지배하는지 확인용.
- 구현: `aggregate_random_control_reports()` (`random_control_aggregate` 필드).

## 6. 리포트 반영 규칙

1. KIS shadow (`summarize_lightgbm_defensive_shadow.py`): threshold 블록마다 `random_control`,
   `buy_avoid_shadow.random_control_gate` (best_by_net_delta 기준 통과 여부).
2. Cybos proxy (`summarize_cybos_buy_avoid_proxy.py`): fold별 target_result마다 `random_control`,
   target summary마다 `random_control_aggregate`.
3. `random_control_gate.passed=false`인 동안 문서/리포트/대화에서 buy-avoid를
   "손실 축소 후보"라고 표현하지 않는다. 표준 문구: **"재검증 필요, 무작위 대조군 대비 우위 미확인"**.
4. 해석 우선순위는 `random_control_gate` 또는 `random_control_aggregate`가 최상위다.
   기존 `status`, `decision.status`, `conclusion`, `delta_net_pct`, `net_improvement_pct` 문자열과 수치는
   하위 소비자(dashboard 등) 호환 및 맥락 설명용이며, random-control 판정과 충돌하면 random-control을 따른다.

## 7. 회귀 기준값 (구현이 맞는지 확인하는 anchor)

Codex가 리포트를 재생성했을 때 아래와 크게 다르면 **데이터가 아니라 구현을 먼저 의심하라.**

KIS shadow, threshold 0.40, 관측구간 2026-06-11~07-03 (25,198건, skip 6,694건):

| 항목 | 값 |
|---|---|
| actual_skipped_cumulative_net_pct | -486.3753 |
| expected_random_skipped_sum_pct | ≈ -711.85 (= 6,694 × -0.106342) |
| excess_vs_random_pct | ≈ +225.48 |
| verdict | `filter_better_than_random_p95`가 **절대 아님** (excess가 양수) |
| random_control_gate.passed | false |

Cybos proxy, target_skip 0.3665 (7,807건, skip 2,824건):

- actual 합 ≈ -367.72%p. 풀링 평균 근사의 무작위 기대는 ≈ -194.6%p지만,
  **정식 계산은 fold별 기대의 합**이므로 값이 이와 다소 다를 수 있다.
- 부호 기대: excess < 0 (Cybos에서는 필터가 무작위보다 나쁜 거래를 실제로 골라냈음).
  excess가 양수로 나오면 구현 오류를 의심하라.

## 8. 현재 KIS-Cybos 비교 요약 (2026-07-05)

| 항목 | KIS live shadow | Cybos proxy |
|---|---|---|
| 데이터 범위 | KIS live h15, 2026-06-11~2026-07-03, `joined_rows=25,198` | Cybos historical h15, 5년 proxy fold, `folds_usable=12` |
| 기준 방식 | 고정 threshold `down_threshold=0.40` | target skip coverage `0.3665`에 맞춰 fold 안에서 threshold 보정 |
| 거래 비용 | `trade_cost_pct=0.108` | `trade_cost_pct=0.13` |
| random-control 판정 | `filter_worse_than_random_p95`, `random_control_gate.passed=false` | `filter_better_than_random_p95` |
| 해석 | KIS live에서는 **재검증 필요, 무작위 대조군 대비 우위 미확인** | Cybos proxy 내부에서는 하락 위험 필터가 무작위보다 나쁜 거래를 더 잘 골라낸 근거 |
| 정책 영향 | 주문 정책, gate, active model 변경 금지 | KIS 전이 근거가 아니라 장외 보조 진단 |

같은 공식으로 봐도 KIS live와 Cybos proxy의 결론이 반대로 나온다. 따라서 Cybos 장기 데이터에서 좋은 결과가 나왔다는 이유만으로 KIS live 주문 판단에 옮기지 않는다. Cybos 결과는 `왜 장기 proxy 에서는 작동했는가`를 파악하는 연구 자료이고, KIS live 정책 후보는 KIS live random-control 통과 뒤에만 논의한다. 이 표는 현재 비교 해석의 정본이며, `docs/cowork-reports/`의 work/review 표는 당시 스냅샷으로만 본다.

## 9. Codex 작업 전 체크리스트

```
[ ] 이 문서를 끝까지 읽었다
[ ] python3 -m pytest tests/test_buy_avoid_random_control.py -q  → 전부 통과
[ ] python3 -m pytest tests/test_lightgbm_defensive_shadow.py tests/test_cybos_buy_avoid_proxy.py -q → 전부 통과
[ ] 리포트 재생성 후 §7 anchor와 대조했다
[ ] 공식/seed/부호 규약을 바꾸지 않았다 (바꿨다면 §0의 3단계 절차를 수행했다)
[ ] app/risk/, config/, VERSION, ALLOW_LIVE_ORDERS, gate 임계값을 건드리지 않았다
```

## 10. 이 방법론의 한계 (정직하게)

- 무작위 대조군은 "선별력이 있는가"만 판정한다. 통과해도 흑자 전환과는 별개 문제다
  (cost/horizon 구조 문제는 별도 트랙).
- z-score는 거래 간 독립을 가정한다. 같은 분봉·같은 종목 신호가 몰려 있으면 실효 표본수가
  줄어 z가 과대평가될 수 있다. z가 ±1.6449 근처라면 통과/미통과를 단정하지 말고 블록
  부트스트랩(향후 과제)으로 재확인하라. |z|가 5를 넘는 현재 상황에서는 결론이 뒤집히지 않는다.
- 100회 시뮬레이션은 p05/p95 추정용으로 충분하지만 극단 꼬리(p<0.01) 판정에는 부족하다.
  판정은 해석적 z를 기준으로 한다.
