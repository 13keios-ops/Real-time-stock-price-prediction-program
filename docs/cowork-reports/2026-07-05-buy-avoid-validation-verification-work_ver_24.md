# 2026-07-05 buy-avoid validation verification work_ver_24

## 1. 작업 범위

- 입력 리뷰: `docs/cowork-reports/2026-07-04-buy-avoid-validation-verification-review_ver_23.md`
- 목적: review_ver_23에서 지적한 `손실 축소 후보` 표현 위험을 기준 문서/생성 리포트 문구에서 정정하고, KIS live와 Cybos proxy를 같은 random-control 기준으로 나란히 해석한다.
- 금지선: 공식/seed/부호 규약 변경 없음. `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음. 실전 주문/취소 없음.

## 2. cowork 리뷰에 대한 Codex 판단

review_ver_23의 핵심 지적은 타당하다.

- KIS live threshold `0.40`은 baseline 대비 delta만 보면 좋아 보이지만, 같은 coverage의 무작위 회피보다 나쁜 거래를 더 잘 고른 것이 아니다.
- 따라서 KIS live buy-avoid를 `손실 축소 후보`라고 부르면 운영자가 실제 주문 반영 후보로 오해할 수 있다.
- Cybos proxy는 full 재생성 후 모든 target에서 random-control을 통과했지만, 구조가 KIS live와 다르므로 KIS 정책으로 바로 전이할 수 없다.
- 기존 `status`, `decision.status`, `conclusion`, `delta_net_pct`, `net_improvement_pct`는 호환/맥락용으로 남겨도 되지만, 최종 해석은 `random_control_gate` 또는 `random_control_aggregate`가 우선해야 한다.

Codex 의견: 지금 필요한 것은 새 모델 실험이 아니라 “좋아 보이는 수치”를 운영 후보로 읽지 못하게 만드는 해석 잠금이다. 이번 작업은 그 잠금을 문서와 생성 Markdown 양쪽에 넣는 작업으로 처리했다.

## 3. 조치 내역

### 3.1 기준 문서 보강

- `docs/Buy-Avoid-Random-Control-Methodology.md`
  - 해석 우선순위를 명문화했다.
  - `random_control_gate` / `random_control_aggregate`가 기존 `status`, `decision.status`, `conclusion`, `delta_net_pct`, `net_improvement_pct`보다 우선한다.
  - KIS-Cybos 비교 요약 표를 추가했다.

### 3.2 현재 상태 문서 표현 정정

- `docs/Execution-Plan.md`
  - Cybos 결과는 `Cybos proxy 내부` 손실 축소 후보로만 제한했다.
  - KIS live 현재 표현은 `재검증 필요, 무작위 대조군 대비 우위 미확인`으로 고정했다.
  - 모델 overlay의 `either_model_down_veto_0.40`도 random-control 미적용 조합 후보로 약화했다.
- `docs/Current-Implementation.md`
  - LightGBM 방어 shadow 설명을 2026-07-05 random-control 기준으로 갱신했다.
- `docs/Production-Transition-Progress.md`
  - KIS live shadow, Cybos proxy full 재생성, random-control 결과를 최신 수치로 정리했다.
- `docs/logbook.md`
  - review_ver_23 대응 entry를 추가했다.
  - 오래된 `손실 축소 후보` 표현을 최신 기준으로 정정했다.

### 3.3 생성 리포트 문구 보강

- `scripts/summarize_lightgbm_defensive_shadow.py`
  - 생성 Markdown에 `legacy status/delta 수치는 호환용이며 random_control_gate가 우선` 문구를 추가했다.
- `scripts/summarize_cybos_buy_avoid_proxy.py`
  - 생성 Markdown에 `decision.status/conclusion은 호환용이며 random_control_aggregate가 우선` 문구를 추가했다.

## 4. KIS-Cybos 같은 기준 비교

| 항목 | KIS live shadow | Cybos proxy |
|---|---|---|
| 데이터 범위 | KIS live h15, 2026-06-11~2026-07-03, `joined_rows=25,198` | Cybos historical h15, 5년 proxy fold, `folds_usable=12` |
| 기준 방식 | 고정 threshold `down_threshold=0.40` | target skip coverage `0.3665`에 맞춰 fold 안에서 threshold 보정 |
| 거래 비용 | `trade_cost_pct=0.108` | `trade_cost_pct=0.13` |
| 실제 회피 손익 | `actual_skipped_cumulative_net_pct=-486.3753` | `actual_skipped_cumulative_net_pct=-367.7152` |
| 무작위 기대값 | `expected_random_skipped_sum_pct=-711.8525` | `expected_random_skipped_sum_pct=-182.1662` |
| excess | `+225.4772` | `-185.5490` |
| z-score | `+4.6278` | `-6.3607` |
| verdict | `filter_worse_than_random_p95` | `filter_better_than_random_p95` |
| 정책 해석 | 재검증 필요, 무작위 대조군 대비 우위 미확인 | Cybos proxy 내부 손실 축소 후보. KIS 전이 근거 아님 |

부호 해석: excess가 음수면 필터가 무작위보다 더 나쁜 거래를 골라냈다는 뜻이라 좋다. KIS는 excess가 양수라 나쁘고, Cybos는 음수라 좋다.

## 5. 앞으로 방향

### 계속 진행

- KIS live buy-avoid는 2026-07-04~2026-07-18 구간까지 같은 random-control 기준으로 reverse-selection 지속 여부를 본다.
- 장후 리포트에서는 `delta`보다 `random-control verdict`를 먼저 읽는다.
- Cybos proxy가 왜 통과하고 KIS live가 왜 실패하는지 원인을 좁히는 전이성 분석은 계속 유효하다.

### 보류

- KIS live 주문 정책 반영 보류.
- gate, active model, threshold 변경 보류.
- `buy-rescue`, `hold-rescue`를 주문 후보로 올리는 작업 보류. 현재는 보조 진단이다.

### 다음 cowork 리뷰가 필요한 시점

- 2026-07-18 장후 또는 그 이후 KIS live random-control 관측 구간이 추가로 닫혔을 때.
- dashboard/장후 자동화가 여전히 `손실 축소 후보`처럼 오해 가능한 문구를 노출하는 것이 확인될 때.
- Cybos-KIS 전이성 분석에서 KIS live에서도 같은 방향으로 반복되는 후보가 새로 발견될 때.

## 6. 검증 예정

- `python3 -m py_compile scripts/buy_avoid_random_control.py scripts/summarize_lightgbm_defensive_shadow.py scripts/summarize_cybos_buy_avoid_proxy.py`
- `python3 -m pytest tests/test_buy_avoid_random_control.py tests/test_lightgbm_defensive_shadow.py tests/test_cybos_buy_avoid_proxy.py -q`
- `git diff --check`

## 7. self-review

- 누락한 작업: review_ver_23의 P0 표현 정정, P1 KIS-Cybos 비교 요약, 생성 문구 우선순위 보강을 반영했다.
- 잘못 진행한 부분: 공식/seed/부호 규약, gate 기준값, live 주문 관련 설정은 건드리지 않았다.
- 결과 판단: KIS live는 우위 미확인, Cybos proxy는 내부 손실 축소 후보로 분리했다. 두 결과를 합쳐 정책 후보로 단정하지 않았다.
- 코드 오류점검: 생성 Markdown 문자열만 바꿨으므로 py_compile과 관련 pytest로 확인한다.
- 기타 리뷰: 과거 cowork report의 역사적 문구는 직접 수정하지 않고, 기준 문서와 logbook에서 최신 해석으로 덮어썼다.
