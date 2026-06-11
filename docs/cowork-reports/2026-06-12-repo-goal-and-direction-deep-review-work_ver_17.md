# repo-goal-and-direction deep review work_ver_17

작성 시각: 2026-06-12 KST

## 1. Codex 비판적 판정

Claude cowork `review_ver_3`의 핵심 판정은 타당합니다. 이번 라운드의 중심은 인프라 추가가 아니라 모델 심사 체인을 유효하게 만드는 것이었습니다.

- P0-1 `holdout_window_mismatch`: 코드와 실제 리포트에서 닫힘.
- P0-2 gate reference 구식 포맷: 새 3분류/가상 방향 지표가 들어간 리포트로 갱신.
- P0-3 매수 신호 0건: threshold sweep 진단 리포트 생성.
- P0-4 dashboard/watchdog daemon 유지: 아직 열림.

## 2. 구현 조치

- `app/services/research.py`
  - 최신 LightGBM 학습 run의 challenger holdout 시작 시각을 anchor 로 사용해 `challenger_holdout_training_anchor` 평가 구간을 만들도록 보강했습니다.
  - label refresh 등으로 데이터가 뒤에 추가되어도 LightGBM 학습 때 예약한 holdout 경계가 유지됩니다.
  - `run_lightgbm_buy_signal_diagnostics_from_sqlite()`를 추가했습니다.
- `app/__main__.py`
  - `python -m app --run-lightgbm-buy-signal-diagnostics --horizon-min 15` CLI를 추가했습니다.
  - threshold 자동 채택은 하지 않습니다.
- `tests/test_research_pipeline.py`
  - anchor split 단위 테스트와 diagnostics report 생성 검증을 추가했습니다.

## 3. 실제 실행 결과

### P0-1 결과

최신 challenger:

- `challenger_run_id`: `challenger-h15-20260612045334514142`
- `dataset_scope`: `challenger_holdout_training_anchor`
- LightGBM `evaluation_independence_status`: `independent_challenger_holdout`
- LightGBM `artifact_training_status`: `artifact_training_run_match`
- `recommended_action`: `keep_active`

해석: 심사 자격 무효 문제는 닫혔습니다. 다만 승격 가능한 성능은 아닙니다.

### P0-2 결과

snapshot DB:

- path: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-snapshots/gate-ref-h15-20260612-033742.db`
- size: `13302407168` bytes
- `quick_check`: `ok`

새 gate reference:

- `evaluation_id`: `walk-forward-h15-20260612042842731771`
- `parameter_profile`: `gate_reference_v1`
- `feature_market_source`: `cybos-historical`
- `folds`: `118`
- `rows_evaluated`: `5900000`
- `three_class_accuracy`: `0.416342`
- `virtual_direction_trades_taken`: `2675212`
- gate: `needs_review`
- reason: `Walk-forward overall accuracy is too low (0.4163).`

해석: 구식 포맷 문제는 닫혔지만, gate 성능은 여전히 통과가 아닙니다.

### P0-3 결과

LightGBM buy-signal diagnostics:

- report: `runtime-data/reports/challengers/latest-lightgbm-buy-signal-diagnostics-h15.json`
- `status`: `no_positive_expected_value_threshold`
- `rows_evaluated`: `25091`
- `probability_up max`: `0.572185`

threshold sweep 핵심:

| threshold | trades_taken | buy_hit | cumulative_net_return_pct |
|---:|---:|---:|---:|
| 0.40 | 1845 | 0.304065 | -199.849736 |
| 0.45 | 576 | 0.326389 | -64.289680 |
| 0.50 | 47 | 0.276596 | -4.188580 |
| 0.55 | 2 | 0.000000 | -1.016107 |
| 0.57 | 1 | 0.000000 | -0.471108 |
| 0.58+ | 0 | 0.000000 | 0.000000 |

해석: 기존 0.58 threshold 가 높아 매수 신호 0건이 된 것은 맞지만, 낮은 threshold에서도 비용 차감 기대값이 음수입니다. 다음 조치는 threshold 단순 완화가 아니라 피처/라벨/모델 calibration 연구입니다.

## 4. 검증

- `python -m py_compile app/services/research.py app/__main__.py tests/test_research_pipeline.py`: 통과
- `python -m unittest tests.test_research_pipeline`: 10개 통과
- `python -m app --run-challengers --horizon-min 15`: 통과
- `python -m app --run-lightgbm-buy-signal-diagnostics --horizon-min 15`: 통과
- `python -m app --build-dashboard`: 통과, `generated_at=2026-06-12T04:54:41.287826+09:00`

## 5. 남은 질문 / 다음 리뷰 권장 시점

다음 cowork 리뷰는 아래 중 하나가 끝난 뒤가 적절합니다.

- 다음 장후 자동화에서 anchor 기반 challenger가 자동으로 유지되는지 확인
- 다음 거래일 장후 `EGW00201` cooldown 실효성 확인
- 첫 모델 연구 스프린트 결과 1건 생성

남은 P0:

- dashboard/watchdog daemon 장시간 유지 검증
- alpha 연구 스프린트: 피처 확장, 라벨 분포/보합 폭 재검토, LightGBM calibration

P1:

- `373220` local-only mismatch 원장 추적
- 과거 data quality `watch` 반복 원인 기록
