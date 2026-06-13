# repo-goal-and-direction deep review work_ver_20

작성 시각: 2026-06-13 KST
작성자: Codex
직전 리뷰: `docs/cowork-reports/2026-06-13-repo-goal-and-direction-deep-review-review_ver_20.md`

---

## 1. 전달 목적

`review_ver_20` 확인 뒤, 사용자가 추가로 전달한 cowork 모델개선 순서 보정 의견을 반영한 결과를 정리한다.

핵심 결론:

- 모델개선시험은 2026-06-12에 이미 수행했다.
- 다만 채택 가능한 새 모델 개선 결과가 나온 것은 아니다.
- 다음 단계는 새 학습 실험을 더 늘리는 것이 아니라, `buy-avoid` shadow 관측과 walk-forward 재검증 기준을 먼저 고정하는 것이다.

---

## 2. 확인한 모델개선시험

실행 완료된 1차 모델개선시험:

- `runtime-data/reports/challengers/latest-lightgbm-performance-diagnostics-h15.md`
- `runtime-data/reports/challengers/latest-lightgbm-feature-source-experiment-h15.md`
- `runtime-data/reports/challengers/latest-lightgbm-feature-profile-experiment-h15.md`
- `runtime-data/reports/challengers/latest-lightgbm-label-band-experiment-h15.md`
- `runtime-data/reports/challengers/latest-lightgbm-calibration-experiment-h15.md`
- `runtime-data/reports/challengers/latest-lightgbm-label-band-reproducibility-h15.md`
- `runtime-data/reports/challengers/latest-lightgbm-defensive-signal-candidates-h15.md`
- `runtime-data/reports/challengers/latest-lightgbm-defensive-shadow-h15.md`

판정:

- `feature_source`, `feature_profile`, `label_band`, `calibration` 실험은 실행됐다.
- 결과는 연구 후보 또는 관찰 후보이며, active model 승격이나 gate/threshold 변경 근거는 아니다.
- `buy-avoid` 쪽은 손실 축소 후보지만 현재 shadow 관측이 2026-06-11~2026-06-12 2거래일 수준이라 결론으로 쓰지 않는다.

---

## 3. cowork 의견 반영

cowork 지적 중 타당하다고 본 부분:

- KIS live 데이터가 약 1개월 수준이라 새 모델 실험을 계속 늘리면 과최적화 위험이 크다.
- label band 재현성 결과가 이미 단일 구간 양수 성과를 신뢰하기 어렵다는 신호를 줬다.
- buy-avoid shadow 는 새 학습 없이 기존 LightGBM shadow serving 예측과 baseline 매수 허용 신호로 바로 누적 관측할 수 있다.

반영한 기준:

- 지금은 새 모델 학습 실험을 즉시 늘리지 않는다.
- buy-avoid shadow 를 최소 2주 또는 10거래일 이상 관측한다.
- walk-forward 재검증은 아래 조건을 모두 충족한 뒤 다시 본다.
  - KIS live h15 labeled row 최소 `60,000`행 이상
  - KIS live 고유 거래일 최소 `30거래일` 이상
  - buy-avoid shadow 최소 `10거래일` 이상
  - baseline 매수 허용 신호와 LightGBM shadow 예측이 같은 종목/시각으로 충분히 연결됨
- 보합 regime 분리와 변동성 구간별 모델 분리는 위 재검증 뒤에 결정한다.

---

## 4. 문서 반영

반영 파일:

- `docs/Execution-Plan.md`
  - 모델 성능개선 스프린트 순서를 `새 학습 실험 확대`에서 `buy-avoid shadow 관측 + 재검증 기준 충족` 우선으로 보정했다.
- `docs/Production-Transition-Progress.md`
  - 최신 cowork 기준을 `review_ver_20`, 통합 리포트를 `work_ver_20`으로 갱신했다.
  - alpha/model predictive power 다음 작업을 buy-avoid shadow 2주/10거래일 관측으로 바꿨다.
- `docs/logbook.md`
  - 이번 모델개선 순서 보정 이력을 추가한다.

---

## 5. 다음 작업

월요일 P0와 모델 트랙은 분리해서 진행한다.

월요일 P0:

- 장중 watchdog heartbeat 10분 이내 유지 실측
- 장후 `EGW00201` 재발 여부와 4종목 mismatch 체결 상태 확인
- 2026-06-08 raw market 공백 패턴 재발 여부 관찰

모델 트랙:

- 기존 LightGBM shadow serving 예측과 baseline 매수 허용 신호를 계속 누적한다.
- 새 학습 실험은 buy-avoid shadow 2주/10거래일 관측과 walk-forward 재검증 기준 충족 뒤 재개한다.

---

## 6. 안전 범위

- 코드 변경 없음.
- active model 변경 없음.
- `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, gate 기준값 변경 없음.
- 실전 주문/취소 없음.
- NAS 백업 실행 없음.
