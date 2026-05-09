# 작업 기록

## [2026-05-10] Codex → KIS live feature-label 진단

- 목적:
  - 실제 KIS live 표본 안에서 현재 피처가 h15 label/future return 과 어떤 관계를 보이는지 확인했다.
- 구현:
  - `scripts/summarize_kis_live_feature_diagnostics.py` 추가.
  - `tests/test_kis_live_feature_diagnostics.py` 추가.
  - 출력 리포트: `runtime-data/reports/data-quality/latest-kis-live-feature-diagnostics.{json,md}`.
- 결과:
  - 표본 rows `6,420`, symbols `10`, labeled trade_dates `2`.
  - h15 label distribution: down `1,041`, flat `3,997`, up `1,382`.
  - strongest by absolute Pearson: `return_1m_pct`, Pearson `-0.039879`, top-bottom future_return delta `-0.068962`.
  - `hl_range_pct`는 Pearson `0.015360`으로 약하지만 top-bottom up-ratio delta `0.217290`이 관찰됐다.
  - `bid_ask_imbalance`, `spread_bps`의 단일 피처 상관은 아직 매우 약하다.
- 판단:
  - posture: `sample_too_small`.
  - 현재 KIS live 데이터는 피처 후보를 관찰하는 정도로만 쓰고, 모델 승격 근거로 쓰지 않는다. 월요일 이후 더 쌓인 live 데이터로 같은 리포트를 재확인한다.

## [2026-05-10] Codex → KIS live vs Cybos historical feature source drift 진단

- 목적:
  - Cybos 5년치 15분봉 후보를 실제 KIS live 데이터의 직접 대리값으로 볼 수 있는지 feature 분포 기준으로 확인했다.
- 구현:
  - `scripts/summarize_feature_source_drift.py` 추가.
  - `tests/test_feature_source_drift_summary.py` 추가.
  - 출력 리포트: `runtime-data/reports/data-quality/latest-feature-source-drift.{json,md}`.
  - KIS 표본은 Cybos 마지막 일자 이후 live 날짜를 우선 사용해 같은 feature row가 양쪽 표본에 섞이지 않게 했다.
- 결과:
  - KIS 표본: `6,590` rows, `10` symbols, `3` trade dates, `2026-05-06..2026-05-08`.
  - Cybos 표본: `100,000` rows, `199` symbols, `20` trade dates, `2026-04-06..2026-05-04`.
  - `spread_bps`: KIS mean `12.546763`, zero_ratio `0.006070`; Cybos mean `0.0`, zero_ratio `1.0`.
  - `bid_ask_imbalance`: KIS mean `0.038760`, zero_ratio `0.007436`; Cybos mean `0.0`, zero_ratio `1.0`.
  - `avg_trade_size`도 KIS mean `400.831744` vs Cybos mean `1054.741933`으로 차이가 컸다.
- 판단:
  - posture: `source_drift_detected`.
  - Cybos historical 은 live 호가 feature 분포를 담지 못하므로, Cybos-only 연구 후보는 구조 탐색용으로만 보고 실제 KIS live 성능의 직접 대리값으로 승격 판단하지 않는다.
- 대시보드:
  - `머신러닝 현황 > 현재 운용`에 `KIS-Cybos feature drift` 카드를 추가해 위 진단 결과를 바로 확인할 수 있게 했다.

## [2026-05-10] Codex → KIS live 데이터 품질 요약과 label 닫힘 보정

- 목적:
  - 다음 모델 개선 전에 KIS 실시간 체결/호가 데이터가 feature/label 까지 닫히는지 정본 DB 기준으로 확인했다.
- 구현:
  - `scripts/summarize_kis_live_data_quality.py` 추가.
  - `tests/test_kis_live_data_quality_summary.py` 추가.
  - 출력 리포트: `runtime-data/reports/data-quality/latest-kis-live-data-quality.{json,md}`.
  - 첫 구현은 SQLite 임시 actual-minute 조인이 10분을 넘겨 중단했고, 반복 조인을 제거해 정본 DB 기준 약 10초 안에 완료되도록 바꿨다.
- 실행:
  - 첫 리포트에서 2026-05-08 feature `3,790` symbol-minute 대비 h15/h60 label 이 `0`으로 확인됐다.
  - `python -m app --build-feature-dataset` 실행 완료: `features_written=6,390,299`, `labels_written=11,551,557`, horizons `[15, 60]`.
  - 재실행한 품질 리포트 assessment 는 `ok`.
- 최신 2026-05-08 품질:
  - market symbol-minutes `3,821`
  - orderbook symbol-minutes `4,060`
  - minute bars `3,790`
  - features `3,790`
  - h15 labels `3,640`
  - h60 labels `3,200`
  - h15 label distribution: down `614`, flat `2,208`, up `818`
- 판단:
  - 최신 KIS live 데이터는 feature/label 기준으로 학습 가능한 상태까지 닫혔다.
  - 2026-05-07은 live runtime 늦은 재기동으로 인한 부분 수집일로 유지한다.
  - 월요일에는 장전/09:30 수집률 확인을 먼저 하고, 모델 튜닝은 그 이후 KIS 누적 품질을 보고 진행한다.

## [2026-05-10] Codex → dashboard KIS live 데이터 품질 카드 추가

- 목적:
  - 월요일 장전/장중 점검 때 대시보드만 보고도 KIS live 데이터가 feature/label까지 닫혔는지 확인할 수 있게 했다.
- 구현:
  - `app/services/dashboard.py`가 `latest-kis-live-data-quality.json`을 dashboard payload에 포함한다.
  - 머신러닝 현황의 현재 운용 탭에 `KIS live 데이터 품질` 카드를 추가했다.
- 확인:
  - `python -m app --build-runtime-report` 실행 완료.
  - `python -m app --build-dashboard` 실행 완료: `generated_at=2026-05-10T06:05:14.388332+09:00`.
  - HTML에서 `KIS 품질: ok`, `KIS 최신일: 2026-05-08`, h15 labels `3,640`, h60 labels `3,200` 표시 확인.

## [2026-05-10] Codex → Cybos 연구 suite 통합 요약

- 목적:
  - 주말 연구 두 번째 라운드로 기존 Cybos 리포트를 한곳에 모아 다음 의사결정 기준을 명확히 했다.
  - 새 대형 학습 없이 기존 결과를 재해석하는 안전한 작업으로 진행했다.
- 구현:
  - `scripts/summarize_cybos_research_suite.py` 추가.
  - `tests/test_cybos_research_suite_summary.py` 추가.
  - 출력 리포트: `runtime-data/reports/backtests/latest-cybos-research-suite-summary.{json,md}`.
- 결과:
  - posture: `hold_all_current_cybos_candidates`.
  - `bar_only`는 hit_rate `0.383333`이지만 net `-3.785540%`로 비용을 넘지 못했다.
  - `bar_context`, `bar_context_momentum`, `F-1 cybos bar-only`도 모두 비용 반영 net 음수다.
  - expected-value는 낮은 비용 `0.10%`, `0.108%`에서만 headline 양수이고 bootstrap CI 하단은 음수다.
  - rule challenger 최선인 `quiet_breakout`도 hit_rate `0.070254`, net `-106.838776%`로 승격 후보가 아니다.
  - label sensitivity/reproducibility는 각각 과최적화 의심, 재현성 부족으로 정리됐다.
- 판단:
  - 현재 Cybos 15분 과거봉 기반 후보는 자동 승격할 후보가 없다.
  - 다음 모델 방향은 신규 grid 튜닝보다 KIS 실시간 호가/체결 데이터 품질 누적, 비용 `0.13%` 이상에서 CI 하단 양수인 후보 탐색, regime/시장상태 피처 설계가 우선이다.

## [2026-05-10] Codex → dashboard profile 재측정

- 명령:
  - `./scripts/profile_dashboard_build.sh`
- 결과:
  - profile: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/profiles/dashboard/dashboard-build-20260510-030930/`
  - elapsed `0:25.65`, max RSS `459,068KB`.
- 판단:
  - 10분 자동 갱신 기준으로는 안정권이다.
  - 주 병목은 raw KIS source minute 집계로 재확인됐다.
  - 추가 expression index 는 dashboard 조회를 줄일 수 있으나 raw tick 쓰기 비용을 키울 수 있어, 월요일 장중 수집 안정성을 먼저 본 뒤 적용 여부를 판단한다.

## [2026-05-10] Codex → 주말 연구 배치: EV 비용 sweep 과 dashboard raw-source 인덱스

- 목적:
  - 월요일 장전 전까지 주말/저부하 시간에 할 수 있는 모델 품질·운영 품질 작업을 진행했다.
  - app/risk gate 는 건드리지 않고, 기존 리포트 재분석과 대시보드 병목 완화를 우선했다.
- expected-value 안정성:
  - `scripts/summarize_expected_value_stability.py`에 `--cost-sweep-pct` 옵션을 추가했다.
  - 기존 expected-value fold 선택을 재학습 없이 비용별로 재가격해 fold 분포와 bootstrap CI를 함께 기록한다.
  - 결과 리포트: `runtime-data/reports/backtests/latest-cybos-expected-value-stability-bar-context-momentum-h15.{json,md}`.
  - 비용 `0.10%`, `0.108%`에서는 trade-sum headline 이 양수지만 CI가 0을 가로질러 안정성이 부족하다.
  - 비용 `0.13%`, `0.16%`, `0.20%`에서는 비용 반영 trade-sum 이 음수다.
  - 판단: 현재 `bar_context_momentum` expected-value 후보는 비용 초과 알파가 안정적이지 않으므로 승격 보류를 유지한다.
- dashboard 성능:
  - 사전 profile: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/profiles/dashboard/dashboard-build-20260510-014912/`, elapsed `0:26.51`, max RSS `459,980KB`.
  - `raw_market_ticks(source, symbol, event_time)`, `raw_orderbook_ticks(source, symbol, event_time)` 인덱스를 스키마와 정본 DB에 반영했다.
  - source count 조회는 `lower(source)` 계산을 피하고 `source IN (...)`로 인덱스를 사용하도록 바꿨다.
  - 사후 profile: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/profiles/dashboard/dashboard-build-20260510-015234/`, elapsed `0:18.17`, max RSS `458,832KB`.
  - 판단: dashboard build 는 10분 갱신 기준 안정권이며, 직전 profile 대비 약 `31%` 단축됐다.
- 검증:
  - `python -m py_compile app/storage/sqlite_store.py scripts/summarize_expected_value_stability.py` 통과.
  - `python -m unittest tests.test_expected_value_stability tests.test_runtime_scope tests.test_dashboard`: 16개 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 93개 통과.

## [2026-05-09] Codex → challenger 독립 holdout 보강

- 목적:
  - LightGBM 학습 validation tail과 challenger 평가 tail이 사실상 같은 기간이던 문제를 줄였다.
  - 이제 challenger는 마지막 tail `10%`를 reserved holdout으로 떼어내고, 학습/validation은 그 이전 development 구간에서만 수행한다.
- 구현:
  - `app/services/research.py`에 challenger holdout split을 추가했다.
  - 학습 summary에 `challenger_holdout_split`을 기록한다.
  - challenger report와 candidate별 결과에 `dataset_scope`, `evaluation_split`, `evaluation_independence_status`를 기록한다.
  - 최신 LightGBM 학습 summary가 reserved holdout과 맞지 않으면 해당 LightGBM은 promotable 후보로 보지 않도록 했다.
  - cowork 리뷰 반영으로 holdout 경계/validation overlap 비교는 ISO 문자열 비교가 아니라 `datetime.fromisoformat` 비교로 보강했다.
  - legacy/mismatch/overlap/fallback 가드 분기와 split key 비중복을 단위 테스트로 고정했다.
- 실제 재실행:
  - `python -m app --train-lightgbm --horizon-min 15`
    - `training_run_id=train-lightgbm-h15-20260509030957756047`
    - `train_rows=4,295,040`, `validation_rows=1,183,354`, `validation_accuracy=0.571482`
  - `python -m app --run-challengers --horizon-min 15`
    - `dataset_scope=challenger_holdout_tail_10pct`
    - holdout rows `662,401`, start `2025-10-24T09:00:00+09:00`
    - best `latest_lightgbm`: accuracy `0.504269`, trade_hit_rate `0.202465`, net `-30.697069%`, trades `568`
    - `recommended_action=review_required`, active model은 `baseline-h15-v1` 유지
  - `python -m app --build-dashboard`: `generated_at=2026-05-09T03:26:29.971728+09:00`
- 판단:
  - challenger 평가 독립성은 개선됐지만, 독립 holdout 기준 비용 반영 성과가 음수라 모델 승격은 보류한다.
  - `0.92` validation 과열 자체는 이번 변경으로 직접 설명된 것이 아니며, 이번 변경은 해당 validation 구간을 challenger 승격 근거로 재사용하지 않게 한 조치다.
  - LightGBM 승격 검토는 재학습 직후 같은 데이터 경계에서 challenger를 이어 실행해야 한다. live 데이터가 추가되어 holdout 경계가 바뀌면 fail-safe로 promotable이 막힌다.
  - cowork 리뷰의 남은 위험인 artifact/DB 불일치 복구 시나리오도 보강했다. 새 LightGBM artifact는 `training_run_id`, `trained_at`, `dataset_scope`, `challenger_holdout_first_event_time`를 payload에 저장하고, challenger는 DB 최신 training row와 artifact의 `training_run_id`가 다르면 승격 후보에서 제외한다.
  - 정본 전체 `python -m app --train-lightgbm --horizon-min 15`와 `python -m app --run-challengers --horizon-min 15`는 각각 15분/10분 제한에서 완료되지 않고 메모리 95% 안팎까지 사용해 중단했다. 기존 artifact 시각은 `2026-05-09 03:09`로 partial overwrite는 확인되지 않았다.
  - 판단: 전체 LightGBM/challenger는 quick 작업이 아니라 D드라이브 snapshot 기반 heavy research 또는 bounded 평가 경로로 분리해야 한다.
  - 대시보드 표기도 점검했다. 기존 화면은 LightGBM `검증 정확도`를 학습 validation `57.15%`가 아니라 challenger holdout `50.43%`로 보여 혼동 여지가 있었고, 예전 challenger report의 `promotable=true`도 새 artifact lineage guard 기준과 맞지 않았다.
  - dashboard는 학습 validation split만 찾아 `학습 validation 정확도`로 표시하고, 현재 artifact lineage guard를 적용해 legacy metadata 없는 LightGBM 후보를 `승격 가능=아니오`로 표시하도록 바꿨다.
  - `python -m app --build-dashboard`로 `generated_at=2026-05-09T14:44:36.689019+09:00` snapshot을 만들고 dashboard server를 PID `439371`로 재시작했다.
- 검증:
  - `python -m py_compile app/models/lightgbm_model.py app/services/research.py` 통과.
  - `python -m unittest tests.test_research_pipeline`: 8개 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 91개 통과.

## [2026-05-08] Codex → cowork 의견 반영: post-close quick 분리, dashboard 병목 제거, EV 안정성 진단

- 판단:
  - cowork 의견 중 모델 승격 보류, portfolio proxy 해석 주의, fold 분포/CI 필요, quick/heavy 트랙 분리는 타당하다고 봤다.
  - 비용 sweep 전체 재학습은 장시간 작업이므로 먼저 기존 `0.13%` expected-value 결과를 재학습 없이 안정성 리포트로 요약했다.
- post-close 운영:
  - watchdog 기본 post-close 모드를 `quick-live-report`로 변경했다.
  - quick 경로는 `build-runtime-report`, `build-dashboard`만 수행하고, snapshot DB와 `--rebuild-actual-ml`을 쓰는 heavy research 는 `--heavy-research --use-snapshot` 명시 실행으로 분리했다.
  - `run_post_close_ml_maintenance.sh --quick` 직접 실행 결과 `status=ok`, `completed_at=2026-05-08 22:10:23 +0900`.
  - watchdog을 재기동해 `post_close_ml_mode=quick-live-report`를 새 기본값으로 반영했다.
- dashboard 병목:
  - profile 산출물: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/profiles/dashboard/dashboard-build-20260508-215838/`.
  - cProfile에서 `runtime_scope.build_runtime_scope`가 Cybos 5년치 raw row까지 actual runtime 판정에 넣는 것이 병목으로 확인됐다.
  - `fetch_raw_symbol_minute_source_counts(..., sources=...)`를 추가하고 actual scope 에서는 `kis-rest`, `kis-ws`만 SQL에서 먼저 읽도록 바꿨다.
  - 장 시간 판정은 minute 단위 캐시를 사용한다.
  - 재측정: `python -m app --build-dashboard`가 `0:35.04`, max RSS `453,960KB`로 완료됐다.
- expected-value 안정성:
  - 리포트: `runtime-data/reports/backtests/latest-cybos-expected-value-stability-bar-context-momentum-h15.{json,md}`.
  - fold 분포: 양수 `5`, 음수 `2`, no-trade `5`.
  - bootstrap 95% fold-sum net CI: `-203.859408..42.553578`.
  - 결론: 비용 반영 거래합산 수익률이 음수이고 fold 안정성도 낮으므로 모델 승격 보류를 유지한다.
- 검증:
  - `python -m py_compile app/services/runtime_scope.py app/storage/sqlite_store.py scripts/wsl_ops.py scripts/summarize_expected_value_stability.py` 통과.
  - `bash -n scripts/script_dispatch.sh scripts/profile_dashboard_build.sh scripts/run_post_close_ml_maintenance.sh` 통과.
  - `python scripts/wsl_ops.py run-watchdog-loop --single-pass` 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 88개 통과.

## [2026-05-08] Codex → 0.13% expected-value 재검증, 포트폴리오 프록시, dashboard 최적화

- expected-value 0.13% 비용 재검증:
  - 입력 DB: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-snapshots/post-close-h15-20260508-160019.db`.
  - 출력 runtime: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-runs/expected-value-20260508-h15-cost013/runtime-data`.
  - source=`cybos-historical`, feature set=`bar_context_momentum`, horizon=`15`, trade cost=`0.13%`.
  - 결과: `folds=12`, `rows_evaluated=600,000`, `trades_taken=2,599`, `overall_accuracy=0.534130`, `trade_hit_rate=0.300500`, `win_rate=0.497114`.
  - 거래합산: `trade_sum_net_return_pct=-51.251310`, `average_net_return_pct=-0.019720`.
  - 포트폴리오 프록시: `portfolio_return_pct=-1.802245`, `allocation=5%`, `max_gross_exposure=100%`, `executed=2,006`, `skipped_exposure=593`.
  - 판단: 0.108% 비용에서는 양수였지만 0.13% 보수 비용에서는 다시 음수다. hit rate는 문턱만 넘었고 비용 초과 기대값은 아직 부족하므로 모델 승격은 보류한다.
- 구현:
  - expected-value walk-forward에 `fixed_fraction_per_signal_horizon_proxy` 포트폴리오 프록시 수익률을 추가했다.
  - 이 값은 실제 paper 계좌 수익률이 아니라, 거래별 수익률 합산을 덜 과장해서 보기 위한 진단값이다.
- 대시보드:
  - `python -m app --build-dashboard` 기존 측정: `8분 03초`, max RSS 약 `7.9GB`.
  - 기본 `오늘` 화면에서 대형 테이블 전체를 읽지 않도록 기간 SQL 조회를 우선 사용하게 바꿨다.
  - 재측정: `3분 27초`, max RSS 약 `5.4GB`.
  - dashboard server와 watchdog은 둘 다 running 상태다.

## [2026-05-08] Codex → 장후 maintenance 중단, expected-value review 완료

- 장후 운영 상태:
  - 확인 시각: `2026-05-08 18:07 KST`.
  - live runtime은 `2026-05-08 15:30:33 +0900`에 정상 정지했고, watchdog은 post-close 상태에서 running 이다.
  - 09:00 이후 정본 DB 누적: `raw_market_ticks=1,170,143`, `raw_orderbook_ticks=647,201`, `curated_minute_bars=3,770`, `feature_model_inputs=3,770`, `serving_predictions=7,540`, `serving_trade_signals=3,770`.
- post-close maintenance:
  - 자동 post-close maintenance는 D드라이브 snapshot `post-close-h15-20260508-160019.db`를 만든 뒤 `--rebuild-actual-ml` 단계에서 2시간 가까이 진행됐다.
  - main DB가 아니라 snapshot/runtime 격리 경로에서 실행 중이었으나, 더 진행하면 같은 heavy job이 반복될 가능성이 커서 중단했다.
  - `latest-post-close-ml.json`은 `failed`로 표시했다.
  - watchdog이 `failed` 상태를 보고 같은 날짜 maintenance를 계속 재시작하는 문제가 있어, 오늘 날짜에 status 값이 있으면 `already_<status>`로 보고 재시작하지 않도록 `scripts/wsl_ops.py`를 수정했다.
  - 중단 중 생긴 불완전한 D드라이브 snapshot `post-close-h15-20260508-181250*`, `post-close-h15-20260508-181459*`는 삭제했다.
- expected-value review:
  - 실행 경로: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-runs/expected-value-20260508-h15/runtime-data`.
  - 입력 DB: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-snapshots/post-close-h15-20260508-160019.db`.
  - 명령은 도구 1시간 제한에서 timeout 됐지만 리포트 생성은 완료됐다.
  - 결과: `folds=12`, `rows_evaluated=600,000`, `trades_taken=3,008`, `overall_accuracy=0.534130`, `trade_hit_rate=0.304854`, `win_rate=0.523271`, `average_net_return_pct=0.006320`, `trade_sum_net_return_pct=+19.012036`, `estimated_cost_drag_pct=324.864`.
  - fold 안정성: 양수 fold 7개, 음수 fold 2개, no-trade fold 3개.
  - 판단: 비용 `0.108%` 기준에서는 train-only expected-value 선별이 처음으로 양수 거래합산 순수익과 0.3 이상 hit rate를 만들었다. 다만 0.13% 보수 비용 재검증과 portfolio-level 수익률 환산 전까지 자동 승격하지 않는다.
- 대시보드:
  - expected-value 리포트는 정본 `runtime-data/reports/backtests/`에도 복사했다.
  - `python -m app --build-dashboard`는 5분 제한에서 끝나지 않아 중단했다.
  - dashboard server는 `http://127.0.0.1:8765`에서 running, API responding 상태이며 최신 snapshot은 `2026-05-08 18:48` 파일이다.

## [2026-05-08] Codex → 장중 broker paper 체결 조회 rate-limit 완화

- 관찰:
  - 확인 시각: `2026-05-08 14:56 KST`.
  - live runtime은 `running`, `current_session_status=regular-session`, `trading_mode=paper` 상태다.
  - 09:00 이후 정본 DB 누적: `curated_minute_bars=3,550`, `feature_model_inputs=3,550`, `serving_predictions=7,100`, `serving_trade_signals=3,550`.
  - `live-runtime.stderr.log`에서 `KIS broker paper order-fill query rate-limited` 경고가 누적 231회 확인됐다.
- 조치:
  - 수동 `sync_broker_paper_orders`는 기존처럼 짧은 재시도를 유지한다.
  - 장중 `OnlinePipelineProcessor`의 브로커 체결 동기화는 rate-limit 발생 시 같은 호출 안에서 즉시 재시도하지 않고, 기존 5분 cooldown 으로 빠지도록 바꿨다.
  - 목적은 KIS 호출 제한 충돌, live loop 지연, 로그 폭증을 줄이는 것이다.
  - watchdog이 `2026-05-08 15:00:34 +0900`에 live runtime을 다시 올려 현재 실행 중인 프로세스에는 이번 변경이 적용된 상태다.
  - 15:00 재기동 직후 tail 기준으로는 broker paper 체결 조회 즉시 재시도 로그가 추가로 보이지 않았다.
- 검증:
  - `python -m py_compile app/services/broker_paper.py app/services/broker_paper_sync.py app/services/streaming.py` 통과.
  - `python -m unittest tests.test_broker_paper_sync tests.test_streaming_pipeline`: 11개 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 88개 통과.
  - `git diff --check` 통과.

## [2026-05-08] Codex → 장중 수집 확인과 train-only expected-value 실험 경로 추가

- 장중 수집 상태:
  - 확인 시각: `2026-05-08 12:14 KST`.
  - live runtime은 `2026-05-08 08:00:59 +0900`부터 `running`, `current_session_status=regular-session`, `trading_mode=paper` 상태다.
  - runtime watchdog은 `running`, `live_runtime_should_run=true`, 오류 없음이다.
  - 09:00 이후 정본 DB 누적: `curated_minute_bars=1,940`, `feature_model_inputs=1,946`, `serving_predictions=3,900`, `serving_trade_signals=1,950`.
  - 판단: 2026-05-08 장중 수집/추론 축은 살아 있다.
- 장중 heavy snapshot 중단:
  - `run_research_on_snapshot.sh --prefix intraday-metrics-gate -- python -m app --run-gate-walk-forward --horizon-min 15`는 live DB backup 단계가 1시간 이상 끝나지 않아 중단했다.
  - 미완성 D드라이브 snapshot 파일은 삭제했다.
  - 판단: 장중에는 live DB 전체 snapshot/gate 재생성을 직접 밀지 않고, 장후 maintenance에서 snapshot 기반으로 실행한다.
- 모델 개선 경로:
  - `python -m app --run-cybos-expected-value-review`를 추가했다.
  - 이 경로는 각 fold의 train tail calibration 구간에서만 `probability_up` threshold를 고르고 test 구간에 적용한다.
  - 선택 기준은 비용 차감 평균 기대값 양수 여부이며, test 결과를 보고 threshold를 다시 맞추지 않는다.
  - 장후 후속 heartbeat는 16:20 KST에 gate/challenger 재생성과 expected-value review를 이어서 확인하도록 갱신했다.
- 검증:
  - `python -m py_compile app/__main__.py app/services/research.py app/services/dashboard.py` 통과.
  - `python -m unittest tests.test_research_pipeline tests.test_dashboard`: 18개 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 88개 통과.
  - `git diff --check` 통과.

## [2026-05-08] Codex → 수익률 지표 의미 분리와 장전 자동 기동 확인

- 장전 자동 기동 확인:
  - `2026-05-08 08:37 KST` 기준 runtime watchdog은 `running`, `live_runtime_should_run=true`, 오류 없음.
  - live runtime은 `2026-05-08 08:00:59 +0900`에 시작됐고 `running`, `trading_mode=paper`, `credentials_ready_for_quotes=true` 상태다.
  - 판단: 2026-05-08 장전 자동 기동은 정상 작동했다. 실제 09:00 이후 분봉/feature 누적은 09:35 heartbeat에서 확인한다.
- 수익률 지표 정리:
  - 기존 `cumulative_net_return_pct`가 실제 계좌 수익률처럼 오해될 수 있어, research metric에 집계 방식 필드를 추가했다.
  - 추가 필드: `return_aggregation=sum_of_trade_pct_not_portfolio`, `trade_sum_gross_return_pct`, `trade_sum_net_return_pct`, `estimated_cost_drag_pct`, `portfolio_return_pct=null`, `portfolio_return_unavailable_reason`.
  - 기존 `cumulative_*` 필드는 하위 호환을 위해 유지한다.
  - 대시보드 문구는 `누적 순수익률` 대신 `거래합산 순수익률`, `비용 차감 합계`, `수익률 집계 방식`을 보여주도록 바꿨다.
- 판단:
  - `net=-170736%` 같은 값은 데이터 병합 오류의 직접 증거가 아니라, 거래별 퍼센트 손익을 다수 거래에 단순 합산한 진단값이다.
  - 다음 실험에서는 거래합산 수익률보다 비용 초과 평균 기대값과 거래 선별 능력을 우선한다.
- 검증:
  - `python -m py_compile app/services/research.py app/services/dashboard.py` 통과.
  - `python -m unittest tests.test_research_pipeline tests.test_dashboard`: 17개 통과.

## [2026-05-08] Codex → 장전 운영 복구, gate reference 재생성, Cybos momentum 실험

- 운영 상태:
  - 확인 시각은 `2026-05-08 02:29 KST`였고 시장 상태는 `pre-open`이었다.
  - live runtime은 꺼져 있었지만 정규장 시작 60분 전이 아니므로 정상 범위로 판단했다.
  - runtime watchdog이 stale 상태여서 `./scripts/start_runtime_watchdog_background.sh`로 재기동했다.
  - 대시보드 서버도 stale 상태였으나 watchdog 재시작 뒤 `running`, `dashboard_responding=true`, `dashboard_api_responding=true`로 복구됐다.
  - 09:35 장중 수집 확인 heartbeat를 등록했다.
- 대시보드:
  - `python -m app --build-dashboard`를 실행해 최신 dashboard snapshot을 `2026-05-08T03:27:23.027323+09:00`로 갱신했다.
- 정본 gate walk-forward:
  - `python -m app --run-gate-walk-forward --horizon-min 15` 실행.
  - `parameter_profile=gate_reference_v1`, `command_source=cli_run_gate_walk_forward`, `feature_market_source=cybos-historical`.
  - 결과: `folds=118`, `rows_evaluated=5900000`, `trades_taken=1572715`, `overall_accuracy=0.416342`, `trade_hit_rate=0.125765`, `cumulative_net_return_pct=-170736.127782`.
  - 설정 provenance와 Cybos source 분리는 정상화됐지만, gate 성능 조건은 통과하지 못했다.
- challenger 재평가:
  - `python -m app --run-challengers --horizon-min 15` 실행.
  - `recommended_action=keep_active`, `walk_forward_gate_status=needs_review`.
  - 최신 LightGBM 후보는 `overall_accuracy=0.343409`, `trade_hit_rate=0.170136`, `cumulative_net_return_pct=-46489.671791`.
  - 이전의 LightGBM 0.92 수준 validation 과열은 사라졌고, 현재 challenger와 gate reference는 모두 부정적 방향으로 일관된다.
- 모델 개선 실험:
  - `bar_context_momentum` 피처셋으로 Cybos LightGBM 실험을 실행했다.
  - walk-forward 결과: `folds=12`, `rows_evaluated=600000`, `trades_taken=6666`, `overall_accuracy=0.535122`, `trade_hit_rate=0.282628`, `cumulative_gross_return_pct=529.484167`, `cumulative_net_return_pct=-190.443833`.
  - 판단: gross 기준 방향성은 일부 있으나 거래비용 `0.108%`를 넘지 못한다. 현재 병목은 비용을 초과하는 거래 선별 능력 부족이다.
- 다음:
  - 모델 승격은 보류한다.
  - 장중 수집이 실제로 09:00 이후 누적되는지 09:35 heartbeat에서 확인한다.
  - 다음 모델 실험은 비용 초과 기대값을 직접 기준으로 삼는 평가/학습 구조 또는 거래 빈도 억제 방향을 우선한다.

## [2026-05-08] Codex → WSL/D드라이브 경로 정리

- 환경 확인:
  - `C:` 여유 공간이 약 0.8GB, `D:` 여유 공간이 약 970GB로 확인됐다.
  - Ubuntu WSL2 배포판 BasePath가 `C:\Users\Keios\AppData\Local\wsl\{5043514c-aa32-4220-928c-802d47b0f90b}`로 확인됐다.
  - Windows Machine PATH에 오래된 `J:\Program Files\Git\Git\cmd`가 남아 있고, User PATH에는 없음을 확인했다.
- 조치:
  - `wsl --manage Ubuntu --move D:\WSL\Ubuntu`로 Ubuntu WSL2 배포판을 D드라이브로 이동했다.
  - 이동 후 BasePath가 `D:\WSL\Ubuntu`로 바뀐 것을 확인했고, WSL 기동 smoke test가 성공했다.
  - Machine PATH의 `J:\Program Files\Git\Git\cmd`는 사용자 관리자 PowerShell 조치 후 제거된 것으로 확인했다.
  - 현재 Codex 앱 프로세스는 제거 전 PATH를 물고 있어 이 세션 일부 `wsl` 실행에는 경고가 남을 수 있다. 새 PowerShell 또는 Codex 재시작 후에는 사라지는 상태로 판단한다.
  - 앞으로 Cybos 수집 임시 DB도 C드라이브가 아니라 `D:\CodexData\Real-time-stock-price-prediction-program\cybos\cybos_collect.db`를 기본값으로 사용하도록 바꿨다.
  - `AGENTS.md`에 D드라이브 우선 정책을 명시했다. 새 데이터 수집, 다운로드, 스냅샷, 장기 보관, 대용량 임시 파일은 어쩔 수 없는 OS/도구 캐시를 제외하고 D드라이브만 사용한다.
- 변경:
  - `AGENTS.md`: WSL 배포판 위치 `D:\WSL\Ubuntu`, 대용량 작업 D드라이브 우선, `C:\Temp` 기본 사용 금지 규칙 추가.
  - `scripts/collect_cybos_historical.py`: 기본 `--db-path`를 D드라이브 데이터 경로로 변경.
  - `scripts/merge_cybos_to_main.sh`, `README.md`: 병합 예시를 `/mnt/d/CodexData/.../cybos_collect.db` 기준으로 갱신.
- 검증:
  - 이동 후 `C:` 여유 공간이 약 17GB로 회복됐다.
  - `python -m py_compile scripts/collect_cybos_historical.py` 통과.
  - `bash -n scripts/merge_cybos_to_main.sh scripts/run_gate_walk_forward_backtest.sh` 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 87개 통과.
  - `python -m app --build-dashboard`: `runtime-data/reports/dashboard/latest-dashboard.html`, `latest-dashboard.json` 생성 성공.

## [2026-05-07] Codex → WSL 자동 시작, Cybos feature 재빌드, gate reference 분리

- WSL 정본 자동 시작:
  - Windows 시작프로그램의 `RealTimeStockRuntime.cmd`, `GitAutoPushWatcher.cmd`가 예전 `D:\GitHub\Real-time-stock-price-prediction-program` 경로를 가리키던 것을 확인했다.
  - 두 런처를 현재 WSL 정본 저장소 `/home/keios/projects/Real-time-stock-price-prediction-program` 기준 `wsl.exe -d Ubuntu --cd ...` 명령으로 갱신했다.
  - WSL systemd user service는 이 환경에서 WSL 세션 불안정을 일으킬 수 있어 비활성화/삭제했다.
  - `install_runtime_startup_launcher.sh`, `install_git_autopush_startup_launcher.sh`는 Windows 시작프로그램을 사용할 수 있으면 systemd user service를 만들지 않고 Windows 런처만 갱신하도록 바꿨다.
  - 검증: `get_runtime_startup_launcher_status.sh` 결과 `installed=true`, `ok=true`, `windows_startup_launcher.ok=true`, systemd service `not-found`.
- Cybos feature/label:
  - 원인: 기존 feature builder가 호가 snapshot이 있는 분봉만 feature를 생성해, 호가가 없는 `cybos-historical` 15분봉 대부분이 학습 feature에 들어오지 못했다.
  - 조치: `source=cybos-historical` 분봉은 내부 synthetic orderbook으로 feature row를 만들고, 학습에서는 `mid_price`, `spread_bps`, `bid_ask_imbalance`를 제외한다.
  - `python -m app --build-feature-dataset` 실행 완료: `features_written=6386509`, `labels_written=11544717`.
  - 재확인: `feature_model_inputs=6386509`, `feature_labels=11544717`, labeled feature source 샘플은 `cybos-historical`.
- Gate reference:
  - walk-forward 리포트에 `parameter_profile`, `command_source`, `feature_market_source` provenance 를 남기도록 변경했다.
  - 정본 gate reference 전용 명령 `python -m app --run-gate-walk-forward --horizon-min 15`와 `scripts/run_gate_walk_forward_backtest.sh`를 추가했다.
  - gate 전용 경로는 `feature_market_source=cybos-historical`, `parameter_profile=gate_reference_v1`로 기록한다.
- 복구 메모:
  - 대용량 feature 재빌드 직후 WSL이 일시적으로 `Wsl/Service/E_UNEXPECTED` 상태가 되었고, Windows 재부팅 후 복구됐다.
  - 이후 systemd user service 대신 Windows 시작프로그램 런처를 주 자동 기동 경로로 둔다.

## [2026-05-07] Codex → walk-forward 생성 경로, challenger split, live 공백 원인 진단

- 정본 walk-forward 생성 경로:
  - `runtime-data/reports/backtests/latest-walk-forward-h15.json`은 `2026-05-06T20:08:51.772212+09:00`에 평가되고 `20:08:58 +0900`에 파일이 갱신됐다.
  - 현재 설정은 `min_train_rows=30`, `test_window_rows=10`, `step_rows=10`, `gap_rows=15`, `max_train_rows=200`이다.
  - `scripts/run_walk_forward_backtest.sh` 기본 경로는 `max_train_rows`를 넘기지 않고, `--rebuild-actual-ml` 경로는 `max_train_rows=40`을 쓴다.
  - 따라서 현재 정본 gate reference는 자동 post-close 산출물이 아니라, 2026-05-06 실험 E의 수동 명령 `--walk-forward-gap-rows 15 --walk-forward-max-train-rows 200`이 안정 경로를 덮어쓴 결과로 판단한다.
  - 후속 후보: walk-forward JSON에 생성 명령/parameter profile을 남기고, gate reference 전용 생성 경로를 분리한다.
- challenger 누수 진단:
  - 현재 코드의 split은 거래일 기준 tail 20% validation + horizon purge 구조다.
  - 정본 DB 기준 현재 15분 labeled dataset은 `343807` rows이며, train `262178` rows(`2021-01-04..2025-04-08`), validation `81629` rows(`2025-04-09..2026-05-06`)로 나뉜다.
  - train/validation `(symbol,event_time)` overlap은 `0`, 날짜 overlap도 `0`이다.
  - 최신 LightGBM candidate의 학습 run `train-lightgbm-h15-20260506200645749446`도 last train `2025-04-08T15:00:00+09:00`, first validation `2025-04-09T09:00:00+09:00`로 기록되어 직접 row leakage 증거는 없다.
  - 다만 LightGBM 학습 시 validation으로 쓰인 tail 구간과 challenger evaluation 구간이 사실상 같은 기간이라, challenger metric은 독립 out-of-sample 평가가 아니라 validation 재사용 평가로 취급한다.
  - 추가로 canonical labeled dataset source resolve 결과 `pykrx-daily-proxy=328429`, `cybos-historical=152`라서, 5년치 Cybos 병합 이후 기대한 `cybos-historical only` feature/label 상태가 아니다. 기준선 재측정 전 feature 재생성과 source resolve 점검이 필요하다.
- 2026-05-07 live runtime 공백:
  - 정본 DB의 2026-05-07 분봉/특징은 15:17~15:18의 20건뿐이다.
  - WSL 정본 로그에서 2026-05-07 첫 live runtime 연결은 `15:17:48`, KIS WebSocket 연결 성공은 `15:17:50`이다.
  - 현재 watchdog state의 `started_at`은 `2026-05-07 16:53:13 +0900`이라 장전/장중 자동 기동을 담당했다는 증거가 없다.
  - `get_runtime_startup_launcher_status.sh` 결과는 `installed=false`, `systemctl --user is-enabled stock-runtime-autoboot.service`는 `not-found`다.
  - 반면 오래된 local setup check에는 Windows 시작프로그램 런처가 `D:\GitHub\Real-time-stock-price-prediction-program`을 가리키던 기록이 남아 있다.
  - 결론: 저장소 이전 뒤 WSL 정본 기준 자동 시작 런처가 재설치되지 않은 것이 5/7 장중 공백의 1차 원인이다. 다음 조치는 WSL 정본을 대상으로 한 시작 런처 재설치/검증이다.

## [2026-05-07] Codex → 정본 gate reference와 장중 수집 공백 점검

- Cowork 검토 내용을 WSL2 정본 저장소 기준으로 다시 확인했다.
- 정본 `runtime-data/reports/backtests/latest-walk-forward-h15.json`은 `2026-05-06T20:08:51.772212+09:00`에 생성된 결과이며, 설정은 `min_train_rows=30`, `test_window_rows=10`, `step_rows=10`, `gap_rows=15`, `max_train_rows=200`이다.
- 해당 walk-forward 결과는 `folds=33284`, `overall_accuracy=0.380246`, `trade_hit_rate=0.104502`, `cumulative_net_return_pct=-10411.176412`로 gate를 통과하지 못한다.
- 문제 해석:
  - 현재 gate 미통과는 맞다.
  - 다만 정본 gate reference가 5년치 데이터 승격 판단용으로는 지나치게 작은 학습창/검증창으로 만들어져 있어, 다음 조치는 gate 우회가 아니라 의미 있는 학습창의 정본 walk-forward를 다시 만드는 방향이어야 한다.
- 변경 전 challenger 정본 리포트의 `latest_lightgbm`은 accuracy `0.921672`, net `+2026.652123`로 보였지만, 같은 정본의 walk-forward와 격차가 커서 승격 근거로 쓰지 않는다. tail validation 평가 편향 또는 데이터 누수 의심 대상으로 기록한다.
- 코드 변경 뒤 `python -m app --run-challengers --horizon-min 15`를 재실행해 최신 challenger 리포트를 `2026-05-07T20:30:09.309909+09:00`로 갱신했다.
  - best candidate: `linear_score_builtin`
  - accuracy `0.510456`, trade_hit_rate `0.491738`, net `+359.201116`, trades `1755`
  - `latest_lightgbm`: accuracy `0.534479`, trade_hit_rate `0.244785`, net `-723.208906`, trades `18265`
  - recommended_action: `review_required`
  - decision_reason: `Walk-forward setup needs review (...)`
- 2026-05-07 장중 데이터:
  - 정본 DB 기준 분봉/특징은 15:17~15:18의 20건뿐이다.
  - label 0건은 해당 시각의 15분 horizon이 장마감 이후로 넘어가므로 정상이다.
  - 실제 문제는 live runtime이 09:00~15:16에 켜져 있지 않았던 공백이다.
- 변경:
  - walk-forward gate 판정에 설정 점검 사유를 추가했다. 작은 학습창/검증창 또는 과도한 fold 수는 기준 완화 없이 `needs_review`로 표시된다.
  - 대시보드에 `게이트 기준 워크포워드` 카드를 추가해 정본 gate reference와 post-close snapshot 산출물을 분리해서 볼 수 있게 했다.
- 검증:
  - `python -m py_compile app/services/research.py app/services/dashboard.py`
  - `python -m unittest tests.test_dashboard`: 13개 통과
  - `python -m unittest tests.test_research_pipeline`: 3개 통과
  - `python -m app --run-challengers --horizon-min 15`
  - `python -m app --build-dashboard`: `2026-05-07T20:33:54.440248+09:00`

## [2026-05-07] Codex → post-close snapshot ML 완료 확인과 wide walk-forward 재측정

- 확인 내용:
  - `runtime-data/reports/ml-maintenance/state/latest-post-close-ml.json` 상태가 `ok`로 바뀐 것을 확인했다.
  - 완료 시각은 `2026-05-07 19:14:42 +0900`이다.
  - snapshot DB는 `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-snapshots/post-close-h15-20260507-165315.db`이고, snapshot runtime 은 `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-runs/post-close-20260507-h15/runtime-data`이다.
- 대시보드:
  - `python -m app --build-dashboard`를 다시 실행해 `runtime-data/reports/dashboard/latest-dashboard.html`과 `.json`을 갱신했다.
  - 생성 시각은 `2026-05-07T19:21:42.344608+09:00`이다.
  - `장후 자동 학습 상태` 카드에 `status=ok`, 완료 시각, snapshot DB/runtime 경로가 표시되는 것을 확인했다.
- 데이터 진단:
  - snapshot DB에는 KIS WebSocket 기반 raw market ticks `2,194,180`, raw orderbook ticks `1,703,559`, curated minute bars/features `10,655`가 있다.
  - 15분 라벨은 `10,246`, 60분 라벨은 `9,016`이다.
  - `2026-05-07` 데이터는 15:17~15:18의 20개 분봉뿐이라 아직 15분 라벨로 닫히지 않았다.
- 모델 개선 실험:
  - 기본 post-close walk-forward 는 `min_train_rows=30`, `max_train_rows=40`이라 승격 판단용으로 너무 짧다.
  - 별도 runtime 에서 wide walk-forward sanity 를 실행했다.
  - 명령 설정: `min_train_rows=3000`, `test_rows=500`, `step_rows=500`, `gap_rows=15`, `max_train_rows=8000`
  - 결과: `folds=14`, `rows_evaluated=7000`, `trades_taken=1495`, `overall_accuracy=0.266857`, `trade_hit_rate=0.138462`, `cumulative_net_return_pct=-262.298425`
- 판단:
  - 오늘 post-close 실제 KIS 데이터 기반 모델은 승격하지 않는다.
  - 다음 개선은 단순 파라미터 조정보다 장중 데이터 누적, 라벨 닫힘률 개선, snapshot actual-ML 지표를 대시보드에 별도 표시하는 작업이 우선이다.

## [2026-05-07] Codex → 대시보드 장후 자동 학습 상태 표시

- 변경 파일:
  - `app/services/dashboard.py`
  - `tests/test_dashboard.py`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - 대시보드 `머신러닝 현황 > 현재 운용` 화면에 `장후 자동 학습 상태` 카드를 추가했다.
  - 이 카드는 `runtime-data/reports/ml-maintenance/state/latest-post-close-ml.json`의 상태, 기준일, 시작/완료 시각, 실행 모드, horizon, pid, snapshot DB, snapshot runtime, stdout/stderr 로그, 오류 메시지를 보여준다.
  - 장중 수집과 연구/학습 snapshot 트랙이 분리되어 있으므로, 사용자가 터미널 로그를 직접 열지 않아도 장후 자동 학습 진행 여부를 대시보드에서 확인할 수 있다.
- 모델 개선 병행:
  - watchdog 이 시작한 post-close snapshot 재학습을 유지한다.
  - 현재 실행 중인 무거운 재학습과 DB snapshot 작업을 방해하지 않기 위해 추가 중복 학습은 시작하지 않고, 완료 상태와 산출물 확인을 다음 연결점으로 둔다.
- 검증:
  - `python -m py_compile app/services/dashboard.py`
  - `python -m unittest tests.test_dashboard`: 13개 통과
  - `python -m unittest discover -s tests -p "test_*.py"`: 86개 통과
  - `git diff --check`
  - `python -m app --build-dashboard`: post-close snapshot 재학습 진행 중 180초 제한 내 미완료. 재학습 완료 후 실제 dashboard snapshot 재생성을 다시 확인한다.

## [2026-05-07] Codex → 장마감 후 자동 snapshot ML maintenance 연결

- 변경 파일:
  - `AGENTS.md`
  - `scripts/script_dispatch.sh`
  - `scripts/wsl_ops.py`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - 사용자 수동 작업은 Codex가 물리적으로 처리할 수 없는 필수 작업만 안내한다는 원칙을 `AGENTS.md`에 기록했다.
  - `run_post_close_ml_maintenance.sh` 기본 실행을 snapshot DB 기준으로 바꿨다.
  - snapshot DB에서 `--rebuild-actual-ml`, runtime report, dashboard build 를 실행하고, main state 파일에는 snapshot 경로와 별도 runtime output 경로를 남긴다.
  - runtime watchdog 이 post-close 상태에서 장마감 후 기본 30분이 지나면 하루 한 번 장후 ML maintenance 를 백그라운드로 시작하도록 했다.
  - 자동 학습은 active model 자동 교체와 실전 주문 승격을 하지 않는다.
- 검증:
  - `python -m py_compile scripts/wsl_ops.py`
  - `bash -n scripts/script_dispatch.sh`
  - `bash -n scripts/run_post_close_ml_maintenance.sh`
  - `python scripts/wsl_ops.py run-watchdog-loop --single-pass --disable-post-close-ml`
  - `python -m unittest discover -s tests -p "test_*.py"`: 86개 통과
- 운영 참고:
  - 검증 중 임시 runtime 으로 뜬 dashboard 프로세스는 중지했다.
  - 실제 watchdog 재시작은 검증과 커밋 뒤 현재 WSL2 저장소 기준으로 다시 수행한다.

## [2026-05-07] Codex → 투트랙 장중 수집 + 연구 스냅샷 운영

- 변경 파일:
  - `scripts/create_research_db_snapshot.sh`
  - `scripts/run_research_on_snapshot.sh`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - 장중 `수집 트랙`과 오프라인 `연구 트랙`을 명시적으로 분리했다.
  - live runtime/watchdog 은 계속 `runtime-data/dev.db`에 장중 KIS 체결/호가를 적재한다.
  - 연구/학습은 SQLite backup API로 만든 snapshot DB를 `DATABASE_URL`로 지정해 실행한다.
  - 기본 snapshot / research run 보관 위치는 `/mnt/d/CodexData/Real-time-stock-price-prediction-program/` 아래로 두고, D드라이브가 없을 때만 `runtime-data/` 아래 fallback을 사용한다.
  - `scripts/run_research_on_snapshot.sh -- python -m app ...` 형태로 기존 연구 명령을 live DB lock 없이 실행할 수 있게 했다.
- 검증:
  - `bash -n scripts/create_research_db_snapshot.sh`
  - `bash -n scripts/run_research_on_snapshot.sh`
  - `.tmp-tests/two-track/live.db` 기준 snapshot smoke test
  - snapshot runner의 `DATABASE_URL` / `RUNTIME_DATA_DIR` 환경 주입 smoke test
- 판단:
  - 앞으로 장중에는 수집 안정성을 우선하고, 무거운 ML/룰 실험은 snapshot DB와 격리된 runtime output에서 실행한다.
  - 수집 트랙을 끄고 실험하는 방식은 기본 운영 방식에서 제외한다.

## [2026-05-07] Codex → 궁극 운영 목표 문서화와 G-1 룰 기반 challenger

- 변경 파일:
  - `app/__main__.py`
  - `app/services/research.py`
  - `scripts/wsl_ops.py`
  - `tests/test_research_pipeline.py`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - README와 Current Implementation에 궁극 운영 목표를 명시했다.
  - 목표는 `데이터 수집 -> 전략 후보 생성 -> 비용/슬리피지/세금 반영 검증 -> walk-forward 검증 -> paper 운용 -> 소액 실전 검증 -> 리스크 제한 운용 -> 일일 분석 -> 승격/폐기`가 반복되는 로컬 투자 연구·운영 시스템으로 정리했다.
  - 월 누적 `+50%`는 장기 stretch target 으로 기록하되, 보장 수익률이나 즉시 실전 운용 기준은 아니라고 명시했다.
  - 장중 데이터 수집은 ML/룰 실험과 분리된 background live runtime/watchdog 축으로 유지하고, 코스피200 Cybos 갱신은 장후 Windows 배치 + WSL 병합 흐름으로 분리한다고 문서화했다.
  - `--run-cybos-rule-challengers` CLI를 추가해 고정 long-only 룰 후보 5개를 비용 반영 walk-forward로 비교하도록 했다.
  - watchdog 상태 조회가 실제 `wsl_ops.py run-watchdog-loop` 프로세스를 `stale`로 오판하지 않도록 보강했다.
- 장중 수집 점검:
  - `2026-05-07 15:17` 현재 WSL2 저장소 기준으로 live runtime과 runtime watchdog을 재기동했다.
  - KIS WebSocket 연결 로그를 확인했다.
  - `15:30` 장마감 이후 상태는 `post-close`이며 watchdog의 `off_session_hold_post-close`가 정상 동작이다.
- G-1 실행 결과:
  - 실행 명령: `python -m app --run-cybos-rule-challengers --cybos-profitability-cost-pct 0.13`
  - `quiet_breakout`: `trades=669`, `trade_hit_rate=0.070254`, `net=-106.838776`
  - `opening_momentum`: `trades=1884`, `trade_hit_rate=0.242569`, `net=-201.657683`
  - `pullback_bounce`: `trades=6144`, `trade_hit_rate=0.148438`, `net=-855.823355`
  - `momentum_follow`: `trades=8607`, `trade_hit_rate=0.149065`, `net=-1174.643028`
  - `range_expansion`: `trades=11810`, `trade_hit_rate=0.168417`, `net=-1642.290757`
- 판단:
  - 고정 룰 challenger 5개 모두 비용 반영 기준에서 음수이므로 자동 승격하지 않는다.
  - 다음 연구 방향은 KIS 호가 데이터 누적 기반 피처 검증 또는 더 엄격한 기간 분리/시장상태 기준 실험으로 분리한다.
- 산출물:
  - `runtime-data/reports/backtests/latest-cybos-rule-challengers-review.json`
  - `runtime-data/reports/backtests/latest-cybos-rule-challengers-review.md`

## [2026-05-07] Codex → F-6b threshold 0.20 재현성 검증

- 변경 파일:
  - `app/__main__.py`
  - `app/services/research.py`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - Cybos 연구 경로에 `--run-cybos-label-reproducibility-review` CLI를 추가했다.
  - F-6에서 유일하게 양수였던 `threshold=0.20`을 자동 채택하지 않고, fold 설계와 기간 샘플을 바꿔 재현성을 확인하도록 했다.
  - 기본 F-6 fold, 더 촘촘한 step, 짧은 학습창, 2021~2023 샘플, 2024~2026 샘플을 같은 비용 0.13% 기준으로 비교했다.
- 실행 결과:
  - `f6_baseline`: `trades=44`, `trade_hit_rate=0.545455`, `net=+3.577014%`
  - `denser_step`: `trades=46`, `trade_hit_rate=0.565217`, `net=+3.706487%`
  - `shorter_train`: `trades=109`, `trade_hit_rate=0.339450`, `net=-11.557602%`
  - `early_2021_2023_sample`: `trades=78`, `trade_hit_rate=0.269231`, `net=-5.929057%`
  - `recent_2024_2026_sample`: `trades=70`, `trade_hit_rate=0.442857`, `net=-2.350204%`
- 거래 원장 참고:
  - baseline 맞춘 거래 평균 gross `0.754928%`
  - baseline 틀린 거래 평균 gross `-0.441063%`
  - 양수 결과는 fold 설계 일부에서만 나타나며 기간 샘플 분리에서는 재현되지 않았다.
- 판단:
  - `threshold=0.20`은 재현성 부족으로 채택하지 않는다.
  - Cybos 15분 bar-only ML의 threshold 튜닝은 우선순위를 낮추고, 다음은 룰 기반 challenger 또는 KIS 호가 데이터 누적 후 호가 피처 검증으로 분리한다.
- 산출물:
  - `runtime-data/reports/backtests/latest-cybos-label-reproducibility-review.json`
  - `runtime-data/reports/backtests/latest-cybos-label-reproducibility-review.md`

## [2026-05-07] Codex → F-6 라벨 민감도 진단

- 변경 파일:
  - `app/__main__.py`
  - `app/services/research.py`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - Cybos 연구 경로에 `--run-cybos-label-sensitivity-review` CLI를 추가했다.
  - F-6은 threshold 선택/승격 실험이 아니라 라벨 민감도 진단으로 구현했다.
  - threshold grid는 실행 전 고정값 `[0.13, 0.20, 0.35, 0.50]`로 두고, 현재 설정값 `0.35`를 포함했다.
  - threshold별 전체 up/down 라벨 수, walk-forward 거래 수, hit-rate, 비용 0.13% 반영 순수익률, `trades < 30` 신뢰 낮음 표시를 리포트에 남겼다.
- 사전 확인:
  - 실제 로딩된 `label_threshold_15=0.35%`
  - 왕복 비용 기준 `0.13%`
  - 현재 threshold는 비용보다 높아, 현 설정 자체가 비용 미만 움직임을 학습하는 구조라고 보기는 어렵다.
- 실행 결과:
  - threshold `0.13`: `trades=25`, `trade_hit_rate=0.480000`, `net=-1.724058%`, `신뢰 낮음`
  - threshold `0.20`: `trades=44`, `trade_hit_rate=0.545455`, `net=+3.577014%`
  - threshold `0.35`: `trades=57`, `trade_hit_rate=0.333333`, `net=-1.413583%`
  - threshold `0.50`: `trades=77`, `trade_hit_rate=0.181818`, `net=-18.729151%`
- 판단:
  - `0.20` 하나만 양수이고 여러 threshold에서 일관된 양수 패턴이 아니다.
  - threshold를 자동 채택하지 않고 `채택 보류, 과최적화 의심`으로 기록한다.
  - 다음 검증은 별도 기간/다른 fold 설계 또는 룰 기반 challenger와 비교하는 방식으로 분리한다.
- 산출물:
  - `runtime-data/reports/backtests/latest-cybos-label-sensitivity-review.json`
  - `runtime-data/reports/backtests/latest-cybos-label-sensitivity-review.md`

## [2026-05-07] Codex → F-5 손익 진단과 비용 반영 재평가

- 변경 파일:
  - `app/__main__.py`
  - `app/services/research.py`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - Cybos 연구 경로에 `--run-cybos-profitability-review` CLI를 추가했다.
  - F-5 walk-forward 거래 원장, 종목/시간대/confidence 구간별 손익 진단, 비용 재계산, train-only confidence threshold, H60 bar-only 비교를 한 번에 남기도록 했다.
  - threshold 실험은 사전 고정 grid `[0.58, 0.60, 0.62, 0.64, 0.66, 0.68, 0.70, 0.75, 0.80]`만 사용하고, 각 fold의 train calibration 구간에서만 선택한 뒤 test에 적용했다.
  - 수동 시간대/종목 제외 필터는 과최적화 위험 때문에 만들지 않았다.
- 실행 결과:
  - F-5 재현: `trades=57`, `overall_accuracy=0.580310`, `trade_hit_rate=0.333333`, `gross=+5.996417%`
  - F-5 기존 비용 0.108% net: `-0.159583%`
  - F-5 요청 비용 0.13% net: `-1.413583%`
  - F-5 구조 가설: 소수 거래와 비용 민감도가 핵심이며, confidence가 수익 거래를 안정적으로 분리하지 못함.
  - train-only threshold: `trades=55`, `trade_hit_rate=0.327273`, `net=-2.295251%`
  - H60 bar-only walk-forward: `trades=112`, `overall_accuracy=0.587108`, `trade_hit_rate=0.187500`, `net=-60.233578%`
- 판단:
  - F-5는 실전 비용 기준으로 손익분기라 보기 어렵다.
  - threshold 보정과 60분 horizon 전환 모두 개선이 아니었다.
  - 다음 실험은 단순 confidence 조정보다 새로운 정보가 있는 피처 또는 데이터 품질 개선 쪽이 필요하다.
- 산출물:
  - `runtime-data/reports/backtests/latest-cybos-profitability-review.json`
  - `runtime-data/reports/backtests/latest-cybos-profitability-review.md`

## [2026-05-07] Codex → F-5 이후 수익 양수화 실험

- 변경 파일:
  - `app/__main__.py`
  - `app/services/research.py`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - Cybos 실험 CLI에 `--cybos-experiment-feature-set`을 추가해 `bar_only`, `bar_context`, `bar_context_momentum` 피처 세트를 선택할 수 있게 했다.
  - `bar_context`는 `close_position_pct`, `minute_slot_pct`, `log_volume`을 추가한다.
  - `bar_context_momentum`은 여기에 `prev_return_pct`, `prev_hl_range_pct`, `log_volume_delta`를 추가한다.
  - 기존 F-1/F-5 계열 `bar_only` 피처는 유지했다.
- 실험 결과:
  - F-2 `bar_context`, `train_rows=20000`: walk-forward accuracy `0.559345`, trade_hit_rate `0.240113`, net `-84.717904`
  - F-3 `bar_context_momentum`, `train_rows=20000`: walk-forward accuracy `0.569643`, trade_hit_rate `0.255112`, net `-113.966154`
  - F-4 `bar_only`, `train_rows=50000`: walk-forward accuracy `0.575857`, trade_hit_rate `0.303030`, net `-16.066645`
  - F-5 `bar_only`, `train_rows=100000`: walk-forward accuracy `0.580310`, trade_hit_rate `0.333333`, net `-0.159583`
  - F-6 `bar_only`, `train_rows=200000`: walk-forward accuracy `0.575893`, trade_hit_rate `0.208333`, net `-4.788923`
  - F-7 `bar_only`, `train_rows=100000`, `LABEL_THRESHOLD_15=0.40`: walk-forward accuracy `0.615464`, trade_hit_rate `0.204082`, net `-8.857048`
  - F-8 `bar_only`, `train_rows=100000`, `LABEL_THRESHOLD_15=0.33`: walk-forward accuracy `0.564798`, trade_hit_rate `0.383333`, net `-3.785540`
- 판단:
  - 완료 조건인 `trade_hit_rate >= 0.3`과 `cumulative_net_return_pct > 0`을 동시에 만족한 실험은 아직 없다.
  - F-5가 현재 최고 후보이며 순수익률은 손익분기 근처지만 여전히 음수다.
  - F-6/F-7/F-8이 모두 F-5 수익률을 넘지 못해 `3회 연속 개선 없음` 조건에 도달했다.
  - 자율 진행을 멈추고 운영자 판단을 요청한다.
- 산출물:
  - `runtime-data/reports/backtests/latest-cybos-bar-only-h15.json`
  - `runtime-data/reports/backtests/latest-cybos-bar-context-h15.json`
  - `runtime-data/reports/backtests/latest-cybos-bar-context-momentum-h15.json`
  - `runtime-data/ml/models/lightgbm-cybos-bar-only-h15-v1.joblib`
  - `runtime-data/ml/models/lightgbm-cybos-bar-context-h15-v1.joblib`
  - `runtime-data/ml/models/lightgbm-cybos-bar-context-momentum-h15-v1.joblib`

## [2026-05-07] Codex → ML 실험 자율 범위 추가와 Cybos bar-only F-1 기준선

- 변경 파일:
  - `AGENTS.md`
  - `app/__main__.py`
  - `app/services/research.py`
  - `app/storage/sqlite_store.py`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - `AGENTS.md`의 `7. 운영 안전 규칙` 아래에 `7-1. ML 실험 자율 범위`를 추가했다.
  - ML 실험에 한해 피처 조합, split, 학습 파라미터, 하이퍼파라미터, 재실험 방향을 Codex가 자율 판단할 수 있도록 기준을 명시했다.
  - 운영자 판단이 필요한 조건은 `3회 연속 개선 없음`, 완료 조건 충족, 데이터 소스 추가/변경, 스프린트 목표 변경, `app/risk/` 변경, `scripts/` 구조 변경으로 구분했다.
  - `source=cybos-historical`만 조회하는 SQLite helper와 Cybos bar-only LightGBM 실험 CLI `--run-cybos-bar-only-experiment`를 추가했다.
  - Cybos 과거 데이터에는 호가가 없으므로 `mid_price`, `spread_bps`, `bid_ask_imbalance`는 제외하고 `avg_trade_size`, `hl_range_pct`, `return_1m_pct`만 사용했다.
  - `pykrx-daily-proxy`, `kis-ws`, `kis-rest-historical`, `synthetic` 데이터는 F-1 학습/평가에서 제외했다.
- 데이터셋:
  - source: `cybos-historical`
  - symbols: `199`
  - source_rows: `6283279`
  - labeled_rows: `6040981`
  - 기간: `2021-03-30T09:15:00+09:00..2026-05-04T15:15:00+09:00`
  - label distribution: `flat=4437376`, `down=805811`, `up=797794`
- 실험 결과:
  - F-1 `train_rows=2000`: validation `0.473329`, walk-forward accuracy `0.546787`, trade_hit_rate `0.217913`, net `-1041.554842`
  - F-1b `train_rows=10000`: validation `0.487424`, walk-forward accuracy `0.563363`, trade_hit_rate `0.282515`, net `-27.799564`
  - F-1c `train_rows=20000`: validation `0.506736`, walk-forward accuracy `0.576262`, trade_hit_rate `0.284987`, net `-25.134498`
  - F-1c feature importance: `avg_trade_size=2795`, `hl_range_pct=2401`, `return_1m_pct=2015`
- 판단:
  - validation accuracy가 `0.6` 이하로 내려와 proxy 누수성 과대평가는 해소된 상태로 본다.
  - walk-forward `trade_hit_rate`가 최고 `0.284987`로 완료 기준 `0.3`에는 아직 못 미친다.
  - F-1 -> F-1b -> F-1c 순서로 개선이 있어 `3회 연속 개선 없음` 보고 조건은 아니다.
  - 다음 자율 실험 방향은 데이터 소스나 risk/gate 변경 없이 `close_position_pct`, `minute_slot`, `log_volume` 같은 bar-context 피처를 추가하는 것이다.
- 산출물:
  - `runtime-data/reports/backtests/latest-cybos-bar-only-f1-h15.json`
  - `runtime-data/reports/backtests/latest-cybos-bar-only-f1-h15.md`
  - `runtime-data/ml/models/lightgbm-cybos-bar-only-h15-v1.joblib`

## [2026-05-07] Codex → 스프린트 04 재시작 전 Cybos 학습 가능성 점검

- 변경 파일:
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - Cybos 5년치 실제 15분봉 병합 후 `python -m app --build-feature-dataset`를 재실행했다.
  - feature 재생성 결과는 `features_written=356970`, `labels_written=647510`, horizons `15, 60` 이었다.
  - main DB의 `raw_market_ticks` 기준 `cybos-historical`은 199종목 `6283279`행, `kis-ws`는 10종목 `3054451`행이다.
  - `raw_orderbook_ticks` 기준 `cybos-historical`은 0행이고, `kis-ws`는 `2245513`행, `pykrx-daily-proxy`는 `332228`행이다.
  - H15 labeled feature row는 전체 `343807`행이고, market source 기준 `cybos-historical` row는 `243993`행이지만 호가 source는 대부분 proxy다.
  - 실험 F의 조건인 `spread_bps`, `bid_ask_imbalance`를 Cybos 실제 호가 피처로 포함하는 조건이 현재 DB로 충족되지 않아 학습/챌린저/walk-forward 실행은 보류했다.
- 실행 명령:
  ```bash
  python -m app --build-feature-dataset
  git diff --check -- docs/STATUS.md docs/logbook.md
  ```
- 확인 결과:
  - H15 label distribution: `flat=258339`, `up=42591`, `down=42877`
  - `git diff --check`: `ok`

## [2026-05-07] Codex → 외부 수집 데이터 D드라이브 보관 기준 정리

- 변경 파일:
  - `AGENTS.md`
  - `README.md`
  - `docs/logbook.md`
- 변경 내용:
  - 앞으로 이 저장소 작업 중 새로 내려받거나 수집하는 대용량 외부 데이터는 기존 `D:\GitHub\Real-time-stock-price-prediction-program` 폴더가 아니라 `D:\CodexData\Real-time-stock-price-prediction-program\` 아래에 보관하도록 기준을 추가했다.
  - WSL2 접근 경로는 `/mnt/d/CodexData/Real-time-stock-price-prediction-program/` 로 기록했다.
  - `C:\Temp\cybos_collect.db`는 병합 스크립트가 `--src` DB를 삭제하므로, 병합용 원본은 유지하고 보관본을 `D:\CodexData\Real-time-stock-price-prediction-program\cybos\cybos_collect_20260507.db`로 복사했다.
  - `C:\Temp\cybos_collect.db`와 D드라이브 보관본 크기가 모두 `1373368320` bytes 임을 확인했다.
  - `C:\Temp\cybos_collect.db` 내용 확인 결과 `source=cybos-historical`, 유효 종목 `199`개, `raw_market_ticks=6283279`, `curated_minute_bars=6283279`, 범위 `2021-03-30T09:15:00+09:00..2026-05-04T15:30:00+09:00` 로 수집되어 있었다.
  - 종목별 row 수는 최소 `7826`, 최대 `32451`, 평균 `31574.27`개였다. 일부 신규상장/편입 종목은 시작일이 늦어 row 수가 짧다.
  - main DB는 아직 기존 삼성전자 병합분만 반영된 상태로, `raw_market_ticks WHERE source='cybos-historical'` 기준 `1`종목 `32451`행이다.
  - Cybos 병합 명령은 현재 작업 위치와 무관하게 실행되도록 절대 스크립트 경로 형태를 기준으로 정리했다.
- 기준 병합 명령:
  ```bash
  bash ~/projects/Real-time-stock-price-prediction-program/scripts/merge_cybos_to_main.sh \
    --src /mnt/c/Temp/cybos_collect.db \
    --dst ~/projects/Real-time-stock-price-prediction-program/runtime-data/dev.db
  ```
- 검증:
  - `git diff --check`: `ok`

## [2026-05-07] Codex → Cybos 코스피200 코드 필터 보강

- 변경 파일:
  - `scripts/collect_cybos_historical.py`
  - `README.md`
  - `docs/logbook.md`
- 변경 내용:
  - `CpUtil.CpCodeMgr.GetGroupCodeList(180)` 결과에 `A0126Z0` 같은 비주식 코드가 섞일 때 수집기가 fatal 로 중단되는 문제를 수정했다.
  - Cybos 그룹 조회 결과는 `A` 접두어를 제거한 뒤 정규식 `^[0-9]{6}$`에 맞는 종목 코드만 사용한다.
  - 필터링 후 `코스피200 유효 종목: N개`를 출력하고, 제외한 잘못된 코드는 개수와 일부 샘플만 출력한 뒤 계속 진행한다.
- 실행 명령:
  ```bash
  python -m py_compile scripts/collect_cybos_historical.py
  python - <<'PY'
  from scripts.collect_cybos_historical import load_kospi200_symbols
  class CodeMgr:
      def GetGroupCodeList(self, group_code):
          return ["A005930", "A0126Z0", "000660", "101S12", "005930"]
  print(load_kospi200_symbols(CodeMgr(), group_code=180))
  PY
  git diff --check
  python -m unittest discover -s tests -p "test_*.py"
  ```
- 확인 결과:
  - 문법 검사: `ok`
  - 필터 smoke test: `A005930`, `000660`, 중복 `005930`은 유효 종목 2개로 정규화하고 `A0126Z0`, `101S12`는 제외
  - 공백 오류 검사: `ok`
  - 전체 단위 테스트: `Ran 85 tests in 18.052s`, `OK`

## [2026-05-07] Codex → Cybos 삼성전자 15분봉 실제 수집과 병합

- 변경 파일:
  - `scripts/collect_cybos_historical.py`
  - `README.md`
  - `docs/logbook.md`
- 변경 내용:
  - 실제 실행에서 기본 365일 chunk 요청이 Cybos `StockChart` 행 수 제한에 걸려 앞구간이 잘리는 것을 확인했다.
  - 수집기 기본 `--chunk-days`를 60일로 낮춰 긴 기간 요청 시 row cap에 걸릴 가능성을 줄였다.
  - 삼성전자 실제 수집/병합 결과와 Cybos가 반환하지 않은 초기 구간을 문서화했다.
- 실행 명령:
  ```powershell
  E:\Users\Keios\AppData\Local\Programs\Python\Python311-32\python.exe `
    scripts\collect_cybos_historical.py `
    --symbols 005930 --start 2021-01-04 --chunk-days 60 --force
  ```
  ```bash
  bash scripts/merge_cybos_to_main.sh \
    --src /mnt/c/Temp/cybos_collect.db \
    --dst ~/projects/Real-time-stock-price-prediction-program/runtime-data/dev.db
  ```
- 확인 결과:
  - 관리자 권한 PowerShell 실행: `status=ok`, `bars_written=32451`, `requests=33`
  - 수집 범위: `2021-03-30T09:15:00+09:00..2026-05-04T15:30:00+09:00`
  - 병합 결과: `raw_market_ticks_merged=32451`, `curated_minute_bars_merged=32451`
  - main DB 확인: `source=cybos-historical`, `symbol=005930`, `rows=32451`
  - `C:\Temp\cybos_collect.db`와 sidecar 파일 삭제 확인
  - `2021-01-04..2021-03-29` 구간은 15일 단위로 재시도했지만 Cybos가 모두 `raw_rows=0`을 반환했다.
  - 문법 검사, bash 파싱 검사, 공백 오류 검사: `ok`
  - 전체 단위 테스트: `Ran 85 tests in 12.883s`, `OK`

## [2026-05-07] Codex → Cybos 수집 DB 로컬화와 WSL 병합 스크립트

- 변경 파일:
  - `scripts/collect_cybos_historical.py`
  - `scripts/merge_cybos_to_main.sh`
  - `README.md`
  - `docs/logbook.md`
- 변경 내용:
  - Windows 에서 WSL2 UNC 경로 SQLite DB를 직접 열 때 `database is locked`가 날 수 있어, Cybos 수집 기본 DB를 `C:\Temp\cybos_collect.db`로 바꿨다.
  - 수집 DB의 parent 폴더가 없으면 자동 생성하도록 했다.
  - 수집 완료 후 WSL2에서 main runtime DB로 병합하는 `scripts/merge_cybos_to_main.sh`를 추가했다.
  - 병합 스크립트는 `raw_market_ticks`의 동일 `(symbol,event_time,source)` 행을 교체하고, `curated_minute_bars`는 기존 기본키로 upsert 한다.
  - 병합 성공 뒤 `/mnt/c/Temp/cybos_collect.db` 같은 source DB 파일을 삭제한다.
- 실행 명령:
  ```bash
  python -m py_compile scripts/collect_cybos_historical.py
  bash -n scripts/merge_cybos_to_main.sh
  bash scripts/merge_cybos_to_main.sh --src .tmp-tests/cybos-merge/src.db --dst .tmp-tests/cybos-merge/dst.db
  git diff --check
  python -m unittest discover -s tests -p "test_*.py"
  ```
- 확인 결과:
  - 문법 검사: `ok`
  - bash 파싱 검사: `ok`
  - 병합 smoke test: `merge_smoke_ok`, `raw_rows=1`, `bar_rows=1`, source DB와 sidecar 삭제 확인
  - 공백 오류 검사: `ok`
  - 전체 단위 테스트: `Ran 85 tests in 12.671s`, `OK`

## [2026-05-06] Codex → Cybos Plus 15분봉 수집 스크립트 추가

- 변경 파일:
  - `scripts/collect_cybos_historical.py`
  - `README.md`
  - `docs/logbook.md`
- 변경 내용:
  - Windows 32bit Python 전용 Cybos Plus `CpSysDib.StockChart` 15분봉 수집 스크립트를 추가했다.
  - 코스피200 전체 수집 시 `CpUtil.CpCodeMgr.GetGroupCodeList(180)`로 구성 종목을 동적으로 조회하도록 했다.
  - `raw_market_ticks`에는 `source=cybos-historical`로 저장하고, `curated_minute_bars`에는 기존 `(symbol, bar_time)` 기본키 구조 그대로 `INSERT OR REPLACE`로 적재한다.
  - Cybos 조회 제한을 초당 15회 이하로 맞추고, 종목별 실패는 다음 종목으로 넘어가도록 했다.
  - 재실행 시 `raw_market_ticks`의 기존 `cybos-historical` 범위가 요청 구간을 이미 덮으면 해당 종목을 skip한다.
- 실행 명령:
  ```bash
  python -m py_compile scripts/collect_cybos_historical.py
  git diff --check
  python -m unittest discover -s tests -p "test_*.py"
  ```
  ```powershell
  E:\Users\Keios\AppData\Local\Programs\Python\Python311-32\python.exe `
    scripts\collect_cybos_historical.py `
    --symbols 005930 --start 2021-01-04
  ```
- 확인 결과:
  - 문법 검사: `ok`
  - 공백 오류 검사: `ok`
  - 전체 단위 테스트: `Ran 85 tests in 18.452s`, `OK`
  - Windows 32bit Python 실행: 스크립트 진입은 확인했으나 `CpCybos.IsConnect == 0`으로 실패
  - 오류 메시지: `fatal: Cybos Plus is not connected. Log in to Cybos Plus, then rerun this script.`
  - Cybos Plus가 로그인/연결되지 않아 삼성전자 `bars_written`과 기간 범위는 아직 확인하지 못했다.

## [2026-05-06] Codex → WSL2 git-autopush watcher 전환

- 변경 파일:
  - `scripts/wsl_ops.py`
  - `README.md`
  - `docs/Versioning.md`
  - `docs/logbook.md`
- 변경 내용:
  - WSL2 watcher의 push 단계에서 WSL `git push`가 GitHub HTTPS 인증 실패로 멈추지 않도록 `GIT_TERMINAL_PROMPT=0`을 적용했다.
  - WSL push가 실패하면 Windows GitHub Desktop의 `git.exe`와 저장된 자격 증명으로 같은 WSL 작업 폴더를 push하는 fallback을 추가했다.
  - watcher 기준 `ScanRoot`를 현재 WSL2 저장소 root로 실행하는 기준을 문서화했다.
  - 이전 WSL 인증 실패로 남아 있던 `git push origin main` 잔여 프로세스를 종료했다.
- 실행 명령:
  ```bash
  # git_push fallback smoke test는 scripts/wsl_ops.py의 git_push()를 직접 호출
  python -m py_compile scripts/wsl_ops.py
  python -m unittest discover -s tests -p "test_*.py"
  ./scripts/test_git_autopush_watcher.sh
  ```
- 확인 결과:
  - Windows GitHub Desktop Git fallback smoke test: `git_push_ok`
  - 단위 테스트: `Ran 85 tests in 12.860s`, `OK`
  - autopush watcher 자체 테스트: `git autopush watcher test passed`
  - watcher 상태: `healthy=true`, `watcher_pids=[92294]`, `managed_repo_count=1`
  - 상태 파일 기준 `scan_root=/home/keios/projects/Real-time-stock-price-prediction-program`
  - 자동 커밋/푸쉬 watcher는 더 이상 `D:\GitHub`가 아니라 현재 WSL2 저장소 기준 상태 파일을 갱신한다.
  - 자동화 정책은 기존처럼 `VERSION` 변경을 트리거로 사용한다.

## [2026-05-06] Codex → 스프린트 04 실험 E 일봉 단위 split

- 변경 파일:
  - `app/services/research.py`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - train/validation split을 행 단위 tail 80/20에서 거래일 단위 tail 80/20로 변경했다.
  - 같은 날짜 row가 train과 validation에 동시에 들어가지 않도록 했고, horizon purge는 validation 시작 시각 기준으로 유지했다.
  - 작은 synthetic fixture에서 날짜 split 또는 purge 후 `down/flat/up` 라벨 구성이 깨질 때만 row-level fallback을 사용하도록 했다.
  - proxy 포함 학습셋 feature list는 실험 B/D 상태 그대로 `avg_trade_size`, `hl_range_pct`, `return_1m_pct`를 유지했다.
- 실행 명령:
  ```bash
  python -m py_compile app/services/research.py
  python -m unittest discover -s tests -p "test_*.py"
  python -m app --train-lightgbm --horizon-min 15
  python -m app --run-challengers --horizon-min 15
  python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 200
  python -m app --run-challengers --horizon-min 15
  ```
- 확인 결과:
  - 단위 테스트: `Ran 85 tests in 11.904s`, `OK`
  - split: `trade_date_tail_20pct`, train `2025-04-08`까지, validation `2025-04-09`부터, 날짜 overlap `0`
  - LightGBM: `train_rows=254350`, `validation_rows=78542`, `validation_accuracy=0.921672`, `trades_taken=5911`, `trade_hit_rate=0.870919`, `cumulative_net_return_pct=2026.652123`
  - walk-forward: `folds=33284`, `rows_evaluated=332840`, `overall_accuracy=0.380246`, `trades_taken=111223`, `trade_hit_rate=0.104502`, `cumulative_net_return_pct=-10411.176412`
  - challenger 최종 판단: `review_required`, `walk_forward_gate_status=needs_review`, 활성 모델은 `baseline-h15-v1` 유지
- 판단:
  - validation_accuracy가 `0.7` 이하로 떨어지지 않았으므로, 기존 `0.912`가 같은 날짜 train/validation 혼입 때문이었다는 가설은 확인되지 않았다.
  - walk-forward trade_hit_rate가 `0.3` 이상으로 오르지 않아 실전 방향성 개선도 확인되지 않았다.
  - 다음 단계는 proxy 15분 라벨 자체를 제외하거나 실제 KIS 분봉 기반 검증을 분리하는 쪽이 우선이다.

## [2026-05-06] Codex → 스프린트 04 긴급 누수 점검과 실험 B/D

- 변경 파일:
  - `app/services/research.py`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - `pykrx-daily-proxy` 라벨이 같은 일봉 OHLC에서 보간된 현재 proxy close와 미래 proxy close의 차이로 만들어지는지 확인했다.
  - 기존 train/validation split이 tail 80/20만 수행하고 horizon purge를 적용하지 않던 점을 확인하고, validation 시작 시각 기준 `train.event_time + horizon < validation_start_time` purge를 추가했다.
  - proxy 포함 학습셋에서 `spread_bps`, `bid_ask_imbalance`에 더해 `mid_price`도 학습 feature list에서 제외했다.
  - 작은 synthetic fixture에서는 purge 후 `down/flat/up` 라벨 구성이 깨질 때 기존 split을 유지해 테스트 안정성을 보존했다.
- 실행 명령:
  ```bash
  python -m py_compile app/services/research.py
  python -m unittest discover -s tests -p "test_*.py"
  python -m app --train-lightgbm --horizon-min 15
  python -m app --run-challengers --horizon-min 15
  python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 200
  python -m app --run-challengers --horizon-min 15
  ```
- 확인 결과:
  - 단위 테스트: `Ran 85 tests in 12.835s`, `OK`
  - 실험 B/D feature_names: `avg_trade_size`, `hl_range_pct`, `return_1m_pct`
  - LightGBM: `train_rows=266300`, `validation_rows=66582`, `validation_accuracy=0.911793`, `trades_taken=5113`, `trade_hit_rate=0.889693`, `cumulative_net_return_pct=1816.829656`
  - walk-forward: `folds=33284`, `rows_evaluated=332840`, `overall_accuracy=0.380246`, `trades_taken=111223`, `trade_hit_rate=0.104502`, `cumulative_net_return_pct=-10411.176412`
  - challenger 최종 판단: `review_required`, `walk_forward_gate_status=needs_review`, 활성 모델은 `baseline-h15-v1` 유지
- 판단:
  - `mid_price` 제거 후에도 validation이 `0.6` 이하로 떨어지지 않았으므로 `mid_price` 단독 누수 가설은 지지되지 않는다.
  - walk-forward trade_hit_rate도 `0.3` 이상으로 개선되지 않아, 다음 단계는 proxy 15분 라벨 자체를 제외하거나 일봉 단위 split/검증으로 바꾸는 방향이 우선이다.

## [2026-05-06] Codex → 스프린트 04 C-1 재실험과 KIS REST 수집 경로

- 변경 파일:
  - `app/services/research.py`
  - `app/storage/sqlite_store.py`
  - `app/brokers/kis_quote_rest.py`
  - `app/collectors/historical.py`
  - `app/__main__.py`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - `pykrx-daily-proxy` row가 포함된 학습셋에서는 `spread_bps`, `bid_ask_imbalance`를 학습 feature list에서 제외하도록 변경했다.
  - LightGBM C-1 설정으로 `class_weight="balanced"`를 적용했다.
  - source lookup 성능을 위해 raw tick/orderbook의 `(symbol,event_time)` index를 추가했다.
  - KIS REST `FHKST03010200` 분봉 수집 CLI `--collect-kis-historical`을 추가하고 `source=kis-rest-historical`로 기존 DB에 적재하도록 했다.
- 실행 명령:
  ```bash
  python -m unittest discover -s tests -p "test_*.py"
  python -m app --train-lightgbm --horizon-min 15
  python -m app --run-challengers --horizon-min 15
  python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 200
  python -m app --run-challengers --horizon-min 15
  python -m app --collect-kis-historical --start 2025-05-06 --end 2026-05-06
  ```
- 확인 결과:
  - 전체 단위 테스트: `Ran 85 tests in 13.796s`, `OK`
  - C-1 LightGBM: `train_rows=266313`, `validation_rows=66579`, `validation_accuracy=0.911699`, `trades_taken=5328`, `trade_hit_rate=0.863176`, `cumulative_net_return_pct=1807.293048`
  - C-1 전체 라벨: `down=22656`, `flat=286577`, `up=23659`
  - walk-forward: `folds=33284`, `rows_evaluated=332840`, `overall_accuracy=0.412748`, `trades_taken=104327`, `trade_hit_rate=0.101259`, `cumulative_net_return_pct=-10384.138893`
  - challenger 최종 판단: `review_required`, `walk_forward_gate_status=needs_review`, 활성 모델은 `baseline-h15-v1` 유지
  - KIS REST 수집: 요청 기간 `2025-05-06~2026-05-06`, 실제 적재 `4200` bars, 범위 `2026-05-04T15:02:00+09:00~2026-05-06T15:30:00+09:00`
- 제한 사항:
  - 공식 KIS 샘플 기준 `FHKST03010200`은 당일 분봉 성격이라, 이번 실행도 1년 전체가 아니라 최근 일부 구간만 반환됐다.
  - 1년 실제 분봉 백필은 다른 장기 분봉 TR 또는 별도 실제 분봉 소스 검토가 필요하다.

## [2026-05-06] Codex → 스프린트 04 전 데이터 품질 점검

- 변경 파일:
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - `pykrx-daily-proxy` 일봉 기반 15분 프록시 분봉 생성 방식을 점검했다.
  - 프록시 호가는 `bid=close-tick`, `ask=close+tick`, `bid_size=ask_size` 구조라 `mid_price`는 프록시 close와 같고, `spread_bps`는 tick size 기반 기계값이며, raw 기준 `bid_ask_imbalance`는 항상 `0.0`임을 확인했다.
  - `runtime-data/dev.db`에서 `kis-ws`와 `pykrx-daily-proxy`의 호가 기반 피처 분포를 비교해 `spread_bps`와 `bid_ask_imbalance`의 source 간 차이가 큰 위험을 `docs/STATUS.md` 상단에 기록했다.
- 확인 결과:
  - raw orderbook rows: `kis-ws=2245513`, `pykrx-daily-proxy=332228`
  - exact feature samples: `kis-ws=12521`, `pykrx-daily-proxy=332228`
  - `spread_bps` median/mean: `kis-ws=12.83/14.74`, `pykrx-daily-proxy=37.92/42.31`
  - `bid_ask_imbalance`: `kis-ws`는 p05 `-0.8056`, p95 `0.8500` 분산이 있으나, 순수 proxy 구간은 `0.0` 고정
- 검증:
  - `git diff --check`: `ok`

## [2026-05-06] Codex → 스프린트 03 과거 데이터 수집 파이프라인

- 변경 파일:
  - `app/collectors/historical.py`
  - `app/storage/sqlite_store.py`
  - `app/__main__.py`
  - `scripts/collect_historical_data.sh`
  - `requirements.txt`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/logbook.md`
- 변경 내용:
  - KIS 공식 샘플의 `주식일별분봉조회`는 과거 분봉 조회가 가능하지만 최대 1년 보관으로 안내되어 5년치에는 부적합하다고 판단하고 B안으로 진행.
  - pykrx 일봉 OHLCV를 거래일당 26개 15분 proxy bar 로 변환해 기존 `curated_minute_bars`에 적재.
  - feature 생성을 위해 같은 시각의 proxy orderbook 을 `raw_orderbook_ticks`에 `pykrx-daily-proxy` source 로 적재.
  - 기존 DB 스키마는 변경하지 않고 SQLite batch upsert/insert helper 만 추가.
  - `./scripts/collect_historical_data.sh --start-date 2021-01-01` 실행 경로와 품질 리포트를 추가.
- 실행 명령:
  ```bash
  pip install --break-system-packages -r requirements.txt
  ./scripts/collect_historical_data.sh --start-date 2021-01-01
  ```
- 확인 결과:
  - 수집 방식: `B: pykrx daily OHLCV to 15-minute proxy bars`
  - 수집 기간: `2021-01-01` ~ `2026-05-06`
  - 실제 적재 시작일: `2021-01-04`
  - 대상 종목: watchlist 10개
  - proxy bars written: `332228`
  - proxy orderbooks written: `332228`
  - feature rows written: `345877`
  - label rows written: `625990`
  - 학습 가능 15분 row: `332892`
  - 품질: `expected_complete_symbol_dates=12778`, `complete_symbol_dates=12778`, `missing_or_partial_symbol_dates=0`
  - 리포트: `runtime-data/reports/historical/latest-historical-collection.{json,md}`
- 검증:
  - Python 컴파일: `ok`
  - bash 파싱 검사: `ok`
  - `git diff --check`: `ok`
  - 전체 단위 테스트: `Ran 85 tests in 13.164s`, `OK`

## [2026-05-06] Codex → WSL2 스프린트 02 완료

- 변경 파일:
  - `requirements.txt`
  - `docs/logbook.md`
- 변경 내용:
  - WSL2 환경에 `pip` 이 없어 `python3-pip` 을 설치한 뒤, Ubuntu externally-managed 환경 제한에 따라 `pip install --break-system-packages -r requirements.txt` 로 Python 의존성을 설치했다.
  - 저장소에 없던 `requirements.txt` 를 추가해 WSL2 테스트와 Synthetic 실행에 필요한 `joblib`, `lightgbm`, `numpy`, `scikit-learn`, `scipy`, `websockets` 를 명시했다.
  - runtime-data 복사 후 Synthetic 30분 사이클을 재실행해 통과를 확인했다.
- 실행 명령:
  ```bash
  pip install -r requirements.txt
  pip install --break-system-packages -r requirements.txt
  python -m unittest discover -s tests -p "test_*.py"
  python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 30 --horizon-min 15
  ```
- 확인 결과:
  - 단위 테스트: `Ran 85 tests in 32.458s`, `OK`
  - Synthetic 30분: `exit 0`
  - Synthetic 학습: `train_rows=11336`, `validation_rows=2834`, `validation_accuracy=0.655963`
  - Synthetic walk-forward: `folds=1412`, `rows_evaluated=14120`, `overall_accuracy=0.272309`
  - Challenger 판단: `recommended_action=review_required`, `best_model_version=lightgbm-h15-v1`, `active_model_version_after_run=baseline-h15-v1`
- 예상 결과:
  - WSL2 이전 후 작업 4, 5 기준 검증은 통과 상태다.
  - LightGBM은 후보 1위지만 walk-forward gate 가 `needs_review` 이므로 자동 승격하지 않는다.

## [2026-05-06] Codex → Cowork

- 변경 파일:
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 변경 내용:
  - Windows 로컬 환경에서 Phase 1 명령을 직접 실행하고 결과를 `docs/STATUS.md` 상단에 기록.
  - 전체 단위 테스트 85개 통과 후 walk-forward, LightGBM 학습, challenger 비교를 순서대로 실행.
  - LightGBM 피처 중요도 상위 5개와 baseline 대비 핵심 판단을 함께 기록.
  - MDD와 샤프지수는 현재 리포트에 원 필드가 없어 거래별/폴드별 순수익률 단순누적 기준 참고값으로 계산해 명시.
- 실행 요청 명령:
  ```bash
  python -m unittest discover -s tests -p "test_*.py"
  python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 40
  python -m app --train-lightgbm --horizon-min 15
  python -m app --run-challengers --horizon-min 15
  ```
- 확인할 수치:
  - 단위 테스트: `Ran 85 tests in 25.449s`, `OK`
  - walk-forward: `folds=1147`, `rows_evaluated=11470`, `trades_taken=3126`, `overall_accuracy=0.438710`, `cumulative_net_return_pct=-14.115270`
  - LightGBM 학습: `train_rows=9212`, `validation_rows=2303`, `validation_accuracy=0.816761`
  - challenger: `recommended_action=keep_active`, `walk_forward_gate_status=needs_review`, `active_model_version_after_run=baseline-h15-v1`
  - LightGBM latest: `trades_taken=3`, `cumulative_net_return_pct=-0.113131`, `overall_accuracy=0.816761`
  - baseline active: `trades_taken=1013`, `cumulative_net_return_pct=-51.599478`, `overall_accuracy=0.108120`
  - 피처 중요도 top5: `mid_price=1450`, `spread_bps=1110`, `bid_ask_imbalance=1077`, `avg_trade_size=986`, `hl_range_pct=853`
- 예상 결과 (성공 기준):
  - 운영자는 `docs/STATUS.md` 상단의 Phase 1 Windows 직접 실행 결과를 보고 Phase 2 원인 분석 착수 여부를 판단한다.
  - 현재 자동 승격은 하지 않는다. LightGBM은 정확도는 높지만 거래 수가 3건뿐이라 `keep_active`가 정상 판단이다.

## [2026-05-06] Codex → Cowork

- 변경 파일:
  - `app/storage/sqlite_store.py`
  - `tests/test_sqlite_store.py`
  - `docs/logbook.md`
- 변경 내용:
  - SQLite 시작 초기화를 `WAL → DELETE → MEMORY` 3단계 fallback으로 변경.
  - `PRAGMA journal_mode` 호출만이 아니라 `journal mode 설정 + synchronous 설정 + schema 생성 + commit` 전체를 한 단계로 보고, 어느 지점에서든 `sqlite3.OperationalError`가 나면 다음 journal mode로 재시도하도록 수정.
  - `DELETE`에서 `CREATE TABLE` 중 `disk I/O error`가 나는 Cowork FUSE/virtiofs 환경은 다음 단계인 `MEMORY`로 넘어가도록 처리.
  - 성공 시 시작 로그에 `SQLite startup using journal_mode=<MODE> for database=<path>` 형식으로 실제 동작 모드를 남김.
  - fallback 실패 로그는 `SQLite startup journal_mode=<MODE> failed ... falling back to <NEXT>` 형식으로 남김.
  - fallback 순서와 `MEMORY`까지의 재시도, 시작 로그 출력 단위 테스트를 기존 SQLite 테스트 안에서 갱신.
- 실행 요청 명령:
  ```bash
  git pull origin main
  python -m unittest discover -s tests -p "test_*.py"
  python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 30 --horizon-min 15
  ```
- 확인할 수치:
  - 로컬 전체 단위 테스트: `Ran 85 tests in 25.305s`, `OK`
  - 로컬 Synthetic 30분: `exit 0`
  - Synthetic 학습: `train_rows=9212`, `validation_rows=2303`, `validation_accuracy=0.818498`
  - Synthetic walk-forward: `folds=1147`, `rows_evaluated=11470`, `overall_accuracy=0.282127`
  - 로컬 시작 로그: `SQLite startup using journal_mode=WAL ...`
- 예상 결과 (성공 기준):
  - Cowork FUSE/virtiofs 환경에서 `WAL` 실패 후 `DELETE`를 시도하고, `DELETE`가 schema 생성 중 `disk I/O error`를 내면 `MEMORY`로 자동 전환되어 단위 테스트와 Synthetic Step 1이 통과해야 한다.
  - Cowork 로그에는 최종적으로 `SQLite startup using journal_mode=MEMORY ...`가 보여야 한다.

## [2026-05-06] Cowork 후속 검증 — Codex 패치 적용 후에도 SQLite "disk I/O error" 잔존

- 트리거: Codex `eb3949f fix(storage): fallback sqlite journal on mounted paths` pull 후 가이드 명령 재실행
- 환경: Cowork Linux 샌드박스(Ubuntu 22.04, Python 3.10.12). 저장소는 `fuse`/virtiofs로 마운트(`fstype=fuse, source=/mnt/.virtiofs-root/shared/d/...`).
- 사전 조치:
  - 작업트리 `app/storage/sqlite_store.py`가 1074줄 → 964줄(BOM+CRLF, `query = """`에서 잘림)으로 도착해 SyntaxError. FUSE 동기화 중 절단으로 추정. `git show HEAD:app/storage/sqlite_store.py` 로 정본 추출 후 `cp` 로 작업트리 덮어써서 1074줄 정본 복원.
  - `select_sqlite_journal_mode(Path('runtime-data/dev.db').resolve())` → `DELETE` (Codex 의도대로 동작)
- 단위 테스트: `python -m unittest discover -s tests -p "test_*.py"`
  - `Ran 85 tests in 2.031s` — 테스트 개수는 Codex 인수인계 기대치(85)와 일치
  - `FAILED (errors=40)` — 40건 모두 `sqlite3.OperationalError: disk I/O error` (`connection.execute(statement)` for CREATE TABLE)
- 핵심 진단(샌드박스에서 직접 SQLite pragma 조합 실험 결과):
  | 조합 | 결과 |
  |---|---|
  | `journal_mode=DELETE` | FAIL: disk I/O error |
  | `journal_mode=DELETE` + `synchronous=NORMAL` | FAIL: disk I/O error |
  | `journal_mode=DELETE` + `synchronous=OFF` | FAIL: disk I/O error |
  | `journal_mode=DELETE` + `locking_mode=EXCLUSIVE` | OK |
  | `journal_mode=MEMORY` | OK |
  | `journal_mode=OFF` | OK |
  fcntl flock·F_SETLK은 정상 동작. SQLite 자체의 journal 파일 생성/동기화 syscall이 이 virtiofs FUSE에서 실패함.
- 결론: Codex 패치는 의도대로 `DELETE`를 선택했으나, virtiofs 환경에서는 `DELETE` 단독으로는 부족함. `DELETE` 선택 시 `PRAGMA locking_mode=EXCLUSIVE` 를 함께 설정하거나, mount 감지가 `DELETE` 트리거되는 경로에 대해 `journal_mode=MEMORY` 로 한 단계 더 fallback 필요.
- Cowork 조치: 가이드의 "Synthetic 통과 전 Step 2 보류" 규칙대로 Step 2~5 미실행. 운영자 호출 양식 갱신.
- 추가 환경 메모(다음 세션 가속용):
  - 프로젝트 `requires-python = ">=3.12"` 이지만 Cowork 샌드박스 Python은 3.10.12. `tomllib` 백포트 shim(`~/.local/lib/python3.10/site-packages/tomllib.py`) 적용 후 `app.config.settings` 로딩 가능.
  - `pip install --break-system-packages lightgbm scikit-learn websockets joblib tomli scipy threadpoolctl` 완료.
  - `PYTHONPYCACHEPREFIX=/tmp/pyc` 사용해 마운트된 `__pycache__` 의 stale `.pyc` 우회 필요.

## [2026-05-06] Codex → Cowork

- 변경 파일:
  - `app/storage/sqlite_store.py`
  - `tests/test_sqlite_store.py`
  - `docs/logbook.md`
- 변경 내용:
  - SQLite 스키마 초기화 전에 DB 경로 환경을 감지해 journal mode를 선택하도록 수정.
  - 정상 로컬 디스크는 기존처럼 `WAL`을 사용하고, UNC 경로·Windows 원격 드라이브·Windows reparse/mount 폴더·Linux/WSL 계열 마운트/네트워크 파일시스템(`drvfs`, `9p`, `cifs`, `nfs`, `virtiofs`, `fuse.*` 등)은 `DELETE` 모드로 자동 전환.
  - 감지 누락으로 `WAL` 설정이 실패해도 `DELETE`로 한 번 fallback 하도록 보강.
  - `DELETE` 모드 DB에서는 `wal_checkpoint`를 no-op 처리해 백업 경로가 WAL 전용 pragma에 묶이지 않도록 수정.
  - 네트워크/마운트 환경 선택과 WAL 실패 fallback 단위 테스트 추가.
- 실행 요청 명령:
  ```bash
  python -m unittest discover -s tests -p "test_*.py"
  python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 30 --horizon-min 15
  ```
- 확인할 수치:
  - 전체 단위 테스트: `85 tests OK`
  - Synthetic 30분 재실행: `exit 0`
  - Synthetic 학습: `train_rows=9212`, `validation_rows=2303`, `validation_accuracy=0.818498`
  - Synthetic walk-forward: `folds=1147`, `rows_evaluated=11470`, `overall_accuracy=0.282127`
  - Challenger 판단: `recommended_action=keep_active`, `active_model_version_after_run=baseline-h15-v1`, `walk_forward_gate_status=needs_review`
  - 참고: 처음 Synthetic 실행은 120초 도구 제한으로 timeout 되었고, 600초 제한 재실행에서 정상 통과.
- 예상 결과 (성공 기준):
  - Cowork Linux 샌드박스에서 Windows 폴더를 마운트한 경로는 WAL을 시도하기 전에 `DELETE` journal mode로 열려 Synthetic Step 1이 통과해야 한다.
  - Windows 로컬 디스크 실행은 기존 WAL 모드를 유지해야 한다.

## [2026-05-06] Cowork 스프린트 01 Phase 1 시도 — Synthetic 실행 환경 오류

- 트리거: COWORK_GUIDE.md 세션 시작 순서에 따른 스프린트 01 Phase 1 진단 시도
- 환경: Cowork Linux 샌드박스(Ubuntu 22.04, Python 3.10.12), 저장소는 Windows `~/projects/Real-time-stock-price-prediction-program` 폴더 마운트
- 사전 준비:
  - Python 3.12 사용 불가 → `tomllib` 누락 → `tomli` 백포트를 `tomllib`로 별칭 처리(`~/.local/lib/python3.10/site-packages/tomllib.py`)
  - 패키지 설치: `lightgbm 4.6.0`, `scikit-learn 1.7.2`, `websockets 16.0`, `joblib 1.5.3`, `tomli 2.4.1`, `scipy 1.15.3`, `threadpoolctl 3.6.0`
  - `app.config.settings.load_settings()` 호출 성공
- 실행: `python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 30 --horizon-min 15`
- 결과: `exit 1`. 핵심 traceback:
  ```
  File "app/storage/sqlite_store.py", line 312, in _initialize_schema
      connection.execute("PRAGMA journal_mode=WAL")
  sqlite3.OperationalError: unable to open database file
  ```
- 추가 검증: 표준 sqlite3로도 동일 오류 — `python -c "sqlite3.connect('runtime-data/dev.db').execute('PRAGMA journal_mode=WAL')"` → `unable to open database file`
- 해석: WAL 모드는 공유 메모리 매핑(`-shm`, `-wal`)을 요구하는데, Cowork에서 Windows 폴더를 Linux 샌드박스에 마운트한 가상 파일시스템이 이 매핑을 지원하지 않는 것으로 보임. 코드베이스가 깨진 것은 아님.
- 조치: 가이드의 "Synthetic 실패 시 Step 2 보류" 규칙에 따라 Step 2~5 실행 중단. `docs/STATUS.md` 상단에 운영자 판단 필요 양식 기록.
- 운영자 질문: ① Phase 1 진단을 운영자가 Windows에서 직접 실행할지, ② Codex에 환경 fallback 코드 수정을 지시할지, ③ Phase 1 자체를 보류할지

## 현재 스냅샷

- 날짜: `2026-05-05`
- 현재 버전: `0.2.0`
- 최근 릴리스 커밋: `8f601ba`
- 감시기 방식: `VERSION` 변경 감지
- 저장소 자동 점검 참여: 켜짐
- 기준 문서 동기화: 예
- 실행 자동시작 실행기 설치: 예

## 현재 상태

- Python 기반 로컬 연구, 수집, 예측, 모의운용 흐름이 구현되어 있다.
- KIS REST 현재가/호가 조회, KIS WebSocket 파서와 수신기, 재연결 처리가 준비되어 있다.
- SQLite와 JSONL 기반 실행 저장소에 원시 체결, 호가, 분봉, 특징, 라벨, 예측, 신호, 주문, 체결, 평가를 기록한다.
- 15분과 60분 예측을 기록하되, 신호와 주문 판단은 15분 기준으로 수행한다.
- 현재 15분 활성 모델은 `baseline-h15-v1` 이고, LightGBM은 장후 재학습과 도전자 모델 비교에 사용한다.
- LightGBM은 정상 학습되지만 워크포워드 기준이 약하면 자동 승격하지 않는다.
- 운영 학습창은 `최근 60거래일 + 오늘 데이터` 기준이며, 오래된 데이터는 삭제하지 않고 비교와 회귀 검증에 보관한다.
- 로컬 대시보드는 `http://127.0.0.1:8765` 에서 실행되며, 기본 자동 새로고침 주기는 10분이다.
- 대시보드는 기본 화면과 `/api/dashboard.json` 에서 최신 캐시 스냅샷을 우선 사용하고, 수동 갱신과 자동 새로고침 때 `/api/refresh` 로 다시 생성한다.
- 대시보드는 실제 운용 데이터만 기본 표시하고 `sample`, `synthetic`, `demo`, 재생 전용 행, 정규장 밖 스냅샷 분봉을 제외한다.
- 대시보드는 원시 체결/호가 행 전체를 메모리에 올리지 않고 분 단위 집계 카운트로 요약해 생성 시간을 줄인다.
- 예측 상세 탭은 선택 기간의 전체 예측을 보여준다.
- 장마감 뒤 같은 거래일의 후속 분봉이 더 생길 수 없는 예측은 `대기 중`이 아니라 `결과 없음`으로 닫는다.
- 로컬 가상 계좌와 KIS 모의계좌는 시작 예수금 동기화와 브로커 기준 정렬을 통해 비교한다.
- KIS 모의계좌 상품코드는 화면에 없으면 `.env` 에 빈 값으로 두고, 앱 내부에서 모의투자 기본값을 적용한다.
- 브로커 모의계좌 주문 미러링은 `ENABLE_BROKER_PAPER_MIRRORING=true` 일 때 켜진다.
- 브로커 주문/체결 조회가 KIS 호출 제한에 걸리면 재시도하고, 계속 막히면 안전하게 `rate_limited` 리포트를 남긴다.
- 실시간 수집 중 브로커 체결 동기화는 분 단위로 제한하고, KIS rate-limit 발생 뒤 5분 냉각 시간을 둔다.
- 실행 감시기와 자동 시작 스크립트는 정규장에는 대시보드와 실시간 수집기를 복구하고, 장외와 설정된 휴장일에는 실시간 수집기를 다시 켜지 않아 CPU 재연결 루프를 줄인다.
- 정규장 시작 60분 전부터는 장전 준비 단계로 실시간 수집기를 미리 켠다.
- PC 로그인 후 자동 복구용 실행 자동시작과 시작프로그램 실행기가 준비되어 있다.
- 매시간 저장소 점검 자동화는 git 추적 파일을 직접 수정하지 않고 `runtime-data/reports/codex/automation/` 아래에만 산출물을 남긴다.

## 활성 체크리스트

- [x] KIS REST 수집 구현
- [x] SQLite 적재와 실행 기록기 구현
- [x] 분봉 / 특징 / 라벨 생성 구현
- [x] 기준 모델 학습 구현
- [x] 검증 꼬리구간 백테스트 구현
- [x] 워크포워드 백테스트 구현
- [x] 실행 리포트 구현
- [x] VERSION 기반 감시기 참여 설정 정리
- [x] 다중 모델 도전자 비교 구조
- [x] LightGBM 학습 파이프라인 추가
- [x] 로컬 모니터링 대시보드 추가
- [x] 대시보드 10탭 구조와 한글 UI
- [x] 대시보드 기본 새로고침 10분과 수동 갱신 경로
- [x] 대시보드 예측 상세 전체 표시
- [x] 실제 KIS WebSocket 장중 수신 검증
- [x] KIS 브로커 모의계좌 잔고 조회와 대시보드 반영
- [x] 브로커 모의계좌 주문 제출 미러링
- [x] 로컬 가상투자와 KIS 모의투자의 시작 예수금 동기화
- [x] 실행 감시기 백그라운드 제어 스크립트
- [x] 장중 유휴 WebSocket 수집 상태 감지와 복구
- [x] 장외 실시간 수집기 재기동 제한으로 CPU 사용 절감
- [x] 설정 휴장일 실시간 수집기와 자동 시작 차단
- [x] git 추적 Markdown 문서의 사람이 읽는 본문 한글 정리
- [x] 저장소 맞춤형 `AGENTS.md` 재구성

## 버전과 감시기

- 감시기가 보는 기준 파일은 root `VERSION` 이다.
- 저장소 참여 설정 파일은 root `autopush.json` 이다.
- 현재 설정은 `enabled=true`, `trigger=version-change`, `branch=main` 이다.
- 버전을 바꾸는 명령은 `scripts/bump_version.sh` 를 사용한다.
- 감시기 확인 위치:
- `runtime-data/autopush/git-autopush.log`
- `runtime-data/autopush/git-autopush-state.json`

## 최신 검증 결과

- `2026-05-05 01시대` 저장소 점검과 개선:
- 현재 시각 `2026-05-05 01:47 +09:00` 기준 dashboard 는 `127.0.0.1:8765` 로 정상 응답했고, runtime watchdog 은 `running`, `heartbeat_stale=false` 였다.
- 실시간 수집기는 `pre-open` 장전 준비 시작 전이라 `stopped` 가 정상 상태였고, `check_local_setup.sh -AsJson` 은 `ok=true`, KIS paper 자격정보와 LightGBM 사용 가능 상태를 확인했다.
- 문제점: `config/market_calendar.toml`이 2026-05-05 어린이날 휴장을 몰라 현재 장 상태를 `pre-open`으로 계산했다. 이 상태면 08:00 이후 감시기가 불필요하게 실시간 수집기를 시작할 수 있다.
- 조치: 2026년 KRX 전일 휴장일을 `holidays`에 확장해 2026-05-05와 연말 휴장 등을 반영했다.
- 문제점: 전일 live runtime 로그에서 KIS 브로커 모의계좌 체결 조회가 주문 제출 직후 반복 실행되어 `EGW00201` rate-limit 재시도가 다수 발생했다.
- 조치: 실시간 브로커 체결 동기화를 분당 1회로 제한하고, rate-limit 발생 시 5분 냉각 시간을 두도록 변경했다. 주문 제출 직후 강제 체결 조회는 제거하고 다음 분 단위 동기화에서 반영한다.
- 문제점: 대시보드 수동 생성이 원시 체결/호가 대량 행을 여러 번 메모리에 올려 120초 제한 안에 끝나지 않았고, 기존 대시보드 서버 `/api/refresh`도 watchdog timeout 경고를 낼 수 있었다.
- 조치: runtime scope 에 원시 체결/호가 분 단위 카운트를 보관하고 대시보드는 이 집계값을 사용하도록 바꿔 원시 행 전체 로딩을 제거했다.
- 부분 검증 `python -m unittest tests.test_dashboard tests.test_runtime_scope`: `14 tests OK`
- 브로커 동기화 관련 부분 검증 `python -m unittest tests.test_settings tests.test_kis_ws_verification tests.test_streaming_pipeline tests.test_broker_paper_sync`: `20 tests OK`
- 전체 단위 테스트 `python -m unittest discover -s tests -p "test_*.py"`: `81 tests OK`
- 공백 오류 검사 `git diff --check`: `ok`
- 대시보드 생성 시간 재측정 `python -m app --build-dashboard`: `ok`, `23.27초`
- 새 대시보드 서버 `/api/refresh`: `ok`, `19.41초`
- 대시보드 서버 재시작 뒤 상태: `running`, `http://127.0.0.1:8765`, 실시간 수집기 `stopped`, 장 상태 `holiday`
- 실행 감시기 상태: `running`, `heartbeat_stale=false`, `market_session_status=holiday`, `live_runtime_should_run=false`, `live_runtime_action=off_session_hold_holiday`

- `2026-05-04 17시대` 동작 구조 점검과 감시기 보강:
- 저장소 목적 대비 구조는 `brokers/collectors -> features/labels -> models/services -> paper_trading/portfolio/risk -> reporting` 흐름으로 맞게 분리되어 있고, 기본 운용도 `paper` 검증 중심으로 유지 중이다.
- 실제 상태 점검에서 dashboard 는 `127.0.0.1:8765` 로 정상 응답했고, 장마감 뒤 live runtime 은 중지 상태가 정상임을 확인했다.
- 문제점: runtime watchdog 프로세스는 살아 있었지만 `watchdog-state.json`의 `last_checked_at`이 오래 멈춘 상태를 `running`으로 표시했다. 이 경우 내일 장전 자동 복구가 살아 있는 것처럼 보일 수 있다.
- `get_runtime_watchdog_status.sh`가 심박 나이와 stale 기준을 표시하고, 프로세스가 살아 있어도 기본 10분 이상 심박이 멈추면 `stale` 로 판정하도록 수정했다.
- `start_runtime_watchdog_background.sh`가 stale 심박을 가진 기존 감시기 프로세스를 재사용하지 않고 중지 후 새로 시작하도록 수정했다.
- `run_runtime_watchdog_loop.sh`는 장마감 ML 정비 시작 직전 상태 파일에 `post_close_ml_rebuild_starting`을 먼저 기록하고, live runtime 이 최신 분봉을 쓰는 정규장에는 별도 KIS 검증 WebSocket 을 중복 실행하지 않도록 수정했다.
- 확인 결과: stale 감시기 프로세스를 새 기준으로 감지했고, 감시기 재시작 후 `status=running`, `heartbeat_stale=false`, `last_checked_at=2026-05-04 17:53:33 +09:00`, 장 상태 `post-close`, live runtime `stopped` 로 정리했다.
- bash 파싱 검사: 감시기 관련 3개 스크립트 모두 `parse ok`
- 전체 단위 테스트 `python -m unittest discover -s tests -p "test_*.py"`: `80 tests OK`
- 대시보드 스냅샷 생성 `python -m app --build-dashboard`: `ok`, `generated_at=2026-05-04T17:53:17.750250+09:00`
- 공백 오류 검사 `git diff --check`: `ok`

- `2026-05-04 15시대` 보안 점검:
- git 추적 파일과 git 기록에서 실제 root `.env` 추적은 발견되지 않았고, `.env.example`만 추적 중인 것을 확인했다.
- 로컬 `.env`는 존재하지만 `.gitignore`에 의해 ignore 처리되어 있다.
- 대시보드 프로세스는 `127.0.0.1:8765`에만 바인딩되어 외부 인터페이스로 열려 있지 않다.
- 치명 후보로 NAS 복구 스냅샷이 root `.env*`, `runtime-data/cache/kis/access_token.json`, runtime 로그를 포함할 수 있는 구조를 확인했다.
- `scripts/export_recovery_snapshot.sh`가 root `.env*`, KIS 토큰 캐시, runtime 로그, private key 계열 파일을 제외하도록 수정했다.
- RECOVERY.md, README.md, AGENTS.md, 주간/강제 NAS 백업 wrapper에 비밀값 제외 백업 원칙을 반영했다.
- 로컬 `.env`와 `runtime-data/cache/kis/paper/access_token.json`의 Windows ACL에서 일반 `Users`/`Authenticated Users` 상속 권한을 제거하고 현재 사용자, Administrators, SYSTEM만 접근하도록 좁혔다.
- bash 파싱 검사: NAS 백업 관련 4개 스크립트 모두 `parse ok`
- 임시 로컬 백업 패키지 생성 검증: `.env`, `.env.local`, `runtime-data/cache/kis`, `runtime-data/logs`, `access_token.json`, private key 패턴 파일 모두 스냅샷에 없음
- 공백 오류 검사 `git diff --check`: `ok`

- `2026-05-01 10시대` 휴장일 전체 점검:
- 오늘 `2026-05-01`은 휴장일로 운용해야 하므로 `config/market_calendar.toml`의 `holidays`에 추가했다.
- 기존 bash 장 상태 계산이 주말과 시간만 보고 오늘을 `regular-session`으로 오판해 watchdog 이 live runtime 을 재기동한 것을 확인했다.
- `get_live_runtime_status.sh`, `check_local_setup.sh`, `run_runtime_watchdog_loop.sh`, `run_post_close_ml_maintenance.sh`, `run_hourly_repo_audit_iteration.sh`가 `holidays`를 읽어 `holiday`로 해석하도록 보강했다.
- 추가 점검에서 `start_runtime_autoboot.sh`, `start_monday_runtime.sh`도 실시간 수집기를 직접 시작할 수 있어 같은 휴장일 차단 조건을 적용했다.
- 휴장일 자동 부팅 시뮬레이션 `start_runtime_autoboot.sh -SkipDashboard -SkipAccountRefresh -SkipRuntimeCleanup -SkipDashboardBuild -SkipWatchdog`: `market_session_status=holiday`, `live_runtime_should_run=false`, `live_runtime=stopped`
- Python 설정, KIS 검증, runtime scope, 대시보드도 같은 휴장일 설정을 사용하도록 맞췄다.
- 즉시 `stop_runtime_watchdog.sh`와 `stop_live_runtime.sh`를 실행해 휴장일 불필요한 WebSocket 재연결을 중지했다.
- 부분 검증 `python -m unittest tests.test_settings tests.test_runtime_scope tests.test_kis_ws_verification`: `10 tests OK`
- 전체 검증 `python -m unittest discover -s tests -p "test_*.py"`: `80 tests OK`
- 실행 리포트 생성 `python -m app --build-runtime-report`: `ok`
- 대시보드 스냅샷 생성 `python -m app --build-dashboard`: `ok`, `session_status=holiday`, `live_runtime=stopped`
- bash 파싱 검사: 휴장일 관련 5개 스크립트와 자동 시작 2개 스크립트 모두 `parse ok`
- `scripts/get_live_runtime_status.sh`: `current_session_status=holiday`, `status=stopped`

- `2026-05-01 00시대` 전체 점검과 복구:
- 전체 단위 테스트 `python -m unittest discover -s tests -p "test_*.py"`: `79 tests OK`
- 공백 오류 검사 `git diff --check`: `ok`
- 대시보드 스냅샷 생성 `python -m app --build-dashboard`: `ok`
- 실행 리포트 생성 `python -m app --build-runtime-report`: `ok`
- 실행 리포트 행 수: `raw_market_ticks=1523101`, `raw_orderbook_ticks=1244192`, `minute_bars=7614`, `feature_rows=7614`, `labels=13889`, `predictions=13041`, `signals=6521`, `orders=1165`, `fills=114`, `broker_order_submissions=46`
- 대시보드 서버 시작 지연 원인은 서버가 포트를 열기 전에 무거운 스냅샷 재생성을 먼저 수행하던 구조였다. 기존 캐시 스냅샷이 있으면 서버를 먼저 열도록 수정했다.
- 대시보드 스냅샷 저장 중 상태 점검이 같은 JSON 파일을 읽어 Windows 파일 잠금 충돌이 1회 발생한 로그를 확인했다. 스냅샷 저장을 임시 파일 교체와 짧은 재시도 방식으로 보강했다.
- 보강 뒤 `python -m unittest tests.test_dashboard`, `python -m unittest discover -s tests -p "test_*.py"`, `python -m app --build-dashboard`, `git diff --check` 를 다시 통과했다.
- 실시간 수집기 상태가 오래된 KIS 검증 파일의 `regular-session` 값을 현재 장 상태처럼 보여주던 문제를 수정했다. 이제 현재 장 상태와 마지막 KIS 검증 당시 장 상태를 분리해서 보여준다.
- 로컬 setup 점검은 현재 장 상태와 장전 준비 시간을 계산해, 장외나 장전 준비 전 실시간 수집기 중지를 정상으로 해석한다.
- SQLite 연결을 명시적으로 닫도록 수정해 테스트 중 반복되던 `unclosed database` 경고를 제거했다.
- bash 파싱 검사: `scripts/get_live_runtime_status.sh`, `scripts/check_local_setup.sh` 모두 `parse ok`
- 대시보드 단위 테스트 `python -m unittest tests.test_dashboard`: `13 tests OK`
- 로컬 setup 점검 `scripts/check_local_setup.sh -AsJson`: `ok=true`
- 대시보드 상태: `running`, `http://127.0.0.1:8765`, `/health`와 `/api/dashboard.json` 응답 `ok`
- 실행 감시기 상태: `running`, 장 상태 `pre-open`, `live_runtime_should_run=false`
- 실시간 수집기 상태: `stopped`, 현재 장 상태 `pre-open`, 장전 준비 시작 전이므로 정상 대기
- 로컬 가상투자와 KIS 모의투자 정합성 `scripts/verify_paper_dual_account_match.sh -AsJson`: `ok=true`, `status=matched_waiting_first_submission`, `cash_gap=0`, `total_asset_gap=0`
- `2026-04-30` 로컬 `AGENTS.md` 재구성:
- `D:/GitHub/ref_AGENTS.md`는 공통 설계 기준서로만 참고하고, 현재 저장소의 실제 구조와 기준 문서를 먼저 확인한 뒤 `AGENTS.md`를 다시 작성했다.
- 현재 존재하는 `app/`, `scripts/`, `tests/`, `runtime-data/`, `docs/` 기준으로 작업 순서, 운영 안전 규칙, 주요 명령, 검증 기준을 구체화했다.
- KIS 모의계좌, 로컬 가상투자 비교, 장외 CPU 절감, 대시보드 10분 새로고침, 감시기, NAS 백업 기준을 로컬 예외로 반영했다.
- `AGENTS.md`에 적은 주요 디렉터리, 파일, bash 스크립트 경로 존재 확인: 모두 `True`
- 공백 오류 검사 `git diff --check`: `ok`
- `2026-04-30` 문서 한글화 정리:
- git 추적 중인 Markdown 문서의 사람이 읽는 제목과 설명을 한글 기준으로 정리했다.
- 명령어, 파일 경로, 환경변수, API 이름, 모델명, 상태 키는 실행 정확성을 위해 원문 식별자를 유지했다.
- `docs/logbook.md` 는 오래된 누적 로그 대신 현재 상태와 최신 결과 중심으로 압축했다.
- git 추적 Markdown 본문 스캔: 영어-only 설명 문장 `0건`
- 공백 오류 검사 `git diff --check`: `ok`
- 전체 단위 테스트 `python -m unittest discover -s tests -p "test_*.py"`: `79 tests OK`
- 테스트가 만든 `.tmp-tests` 임시 산출물은 워크스페이스 내부 경로 확인 뒤 삭제했다.
- `2026-04-30` 장마감 실행 검토:
- 실제 실행 행: `raw_market_ticks=619669`, `raw_orderbook_ticks=612546`, `minute_bars=3725`, `feature_rows=3725`, `labels=6700`, `predictions=7450`, `signals=3725`, `orders=1036`, `fills=5`, `broker_order_submissions=10`
- 예측 요약: `total=7450`, `evaluated=6700`, `pending=0`, `no_result=750`, `success_rate=0.110149`
- 장후 머신러닝 관리: `status=ok`, `features_written=7613`, `labels_written=13889`, LightGBM `train_rows=5912`, `validation_rows=1478`, `validation_accuracy=0.751691`
- 최신 백테스트: `rows_evaluated=1478`, `trades_taken=777`, `overall_accuracy=0.104871`, `cumulative_net_return_pct=-150.552985`
- 최신 워크포워드: `folds=734`, `rows_evaluated=7340`, `overall_accuracy=0.440054`, `cumulative_net_return_pct=-96.657339`
- 최신 도전자 모델 비교: `recommended_action=review_required`, `best_candidate=latest_lightgbm`, `walk_forward_gate_status=needs_review`, 활성 모델은 `baseline-h15-v1` 유지
- 브로커 기준 정렬 뒤 모의계좌 정합성: `ok=true`, `status=aligned_waiting_first_submission`, `mismatch_count=0`, `cash_gap=0`, `total_asset_gap=0`
- 대시보드 계좌 동기화: `account_sync.status=일치`, `cash_gap=0`, `raw_cash_gap=88045`
- 전체 테스트: `python -m unittest discover -s tests -p "test_*.py"` 기준 `79 tests OK`
- 실행 리포트 생성: `python -m app --build-runtime-report` 기준 `ok`
- 대시보드 생성: `python -m app --build-dashboard` 기준 `ok`

## 다음 명령

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m app --run-synthetic-dev-cycle --symbol 005930 --minutes 90 --horizon-min 15
python -m app --set-active-builtin --builtin-model baseline --horizon-min 15
python -m app --train-lightgbm --horizon-min 15
./scripts/run_ml_shadow_cycle.sh
python -m app --run-challengers --horizon-min 15
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 40
python -m app --verify-kis-ws --symbols 005930 --max-frames 5 --max-reconnects 0
python -m app --build-runtime-report
python -m app --build-dashboard
./scripts/run_dashboard.sh
./scripts/start_dashboard_background.sh
./scripts/get_dashboard_status.sh
./scripts/stop_dashboard.sh
./scripts/start_live_runtime_background.sh
./scripts/get_live_runtime_status.sh
./scripts/stop_live_runtime.sh
./scripts/start_runtime_watchdog_background.sh
./scripts/get_runtime_watchdog_status.sh
./scripts/stop_runtime_watchdog.sh
./scripts/check_local_setup.sh
./scripts/connect_kis_paper_account_interactive.sh
./scripts/reconcile_paper_accounts.sh
./scripts/start_hourly_repo_audit_background.sh
./scripts/get_hourly_repo_audit_status.sh
./scripts/bump_version.sh -Version 0.2.1
```
