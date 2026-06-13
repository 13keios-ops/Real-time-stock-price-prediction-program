# repo-goal-and-direction deep review work_ver_20-1

작성 시각: 2026-06-14 KST
작성자: Codex
직전 기준: `docs/cowork-reports/2026-06-13-repo-goal-and-direction-deep-review-work_ver_20.md`

---

## 1. 전달 목적

사용자가 전달한 cowork 추가 의견, 즉 `baseline 매수 허용 신호와 LightGBM shadow 예측 연결 표본이 충분할 것`에 숫자 기준이 없다는 지적을 반영했다.

---

## 2. 반영한 기준

buy-avoid shadow 10거래일 누적 뒤 `충분/부족`을 아래 기준으로 판정한다.

- `matched_buy_shadow_rows`: baseline 매수 허용 신호와 LightGBM h15 shadow 예측, 닫힌 h15 label 이 같은 `symbol/event_time`으로 연결된 행이 최소 `1,000`건 이상.
- `matched_trade_days`: 연결 표본이 있는 거래일이 최소 `10거래일`이고, 그중 최소 `8거래일`은 일별 연결 표본이 `50`건 이상.
- `matched_symbols`: 연결 표본이 있는 종목이 최소 `5`종목이고, 각 종목별 연결 표본이 `50`건 이상.
- `avoid_candidate_rows`: 기준 down threshold `0.40`에서 매수 회피 후보가 최소 `200`건 이상이고, 최소 `5거래일`에 걸쳐 분포.

위 조건 중 하나라도 부족하면 모델 성능 실패로 단정하지 않고 `표본 부족`으로 분류해 관측을 연장한다.

---

## 3. 문서 반영

- `docs/Execution-Plan.md`
  - walk-forward 재검증 선행 조건에 buy-avoid 연결 표본 충분성 기준을 추가했다.
- `docs/Production-Transition-Progress.md`
  - alpha/model predictive power 다음 작업에 같은 숫자 기준을 요약 반영했다.
- `docs/logbook.md`
  - 이번 기준 보강 이력을 추가한다.

---

## 4. 안전 범위

- 문서 변경만 수행한다.
- 코드, active model, gate 기준값, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS` 변경 없음.
- 실전 주문/취소 없음.
- NAS 백업 없음.
