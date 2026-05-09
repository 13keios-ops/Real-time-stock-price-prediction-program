# docs/STATUS.md

## [2026-05-10 07:20] KIS live vs Cybos historical feature source drift 진단

- 목적:
  - Cybos 5년치 15분봉 연구 후보가 모두 승격 보류인 상태에서, Cybos 기반 결과를 실제 KIS live 데이터의 직접 대리값으로 볼 수 있는지 feature 분포 기준으로 점검했다.
- 구현:
  - `scripts/summarize_feature_source_drift.py` 추가.
  - `tests/test_feature_source_drift_summary.py` 추가.
  - 출력:
    - `runtime-data/reports/data-quality/latest-feature-source-drift.json`
    - `runtime-data/reports/data-quality/latest-feature-source-drift.md`
  - KIS 표본은 가능하면 Cybos 마지막 일자 이후의 live 날짜만 선택한다. 이번 정본 DB에서는 `post_cybos_overlap` 방식으로 `2026-05-06`, `2026-05-07`, `2026-05-08`을 사용했다.
- 표본:
  - KIS live: rows `6,590`, symbols `10`, trade_dates `3`, range `2026-05-06T08:30:00+09:00..2026-05-08T15:19:00+09:00`.
  - KIS h15 labels: down `1,041`, flat `3,997`, up `1,382`.
  - Cybos historical sample: rows `100,000`, symbols `199`, trade_dates `20`, range `2026-04-06T13:15:00+09:00..2026-05-04T15:30:00+09:00`.
  - Cybos h15 labels: down `14,059`, flat `67,467`, up `14,497`.
- 주요 drift:
  - `spread_bps`: KIS mean `12.546763`, zero_ratio `0.006070`; Cybos mean `0.0`, zero_ratio `1.0`.
  - `bid_ask_imbalance`: KIS mean `0.038760`, zero_ratio `0.007436`; Cybos mean `0.0`, zero_ratio `1.0`.
  - `avg_trade_size`: KIS mean `400.831744`, Cybos mean `1054.741933`, Cybos 표준편차 기준 delta `-2.377566`.
- 판단:
  - posture: `source_drift_detected`.
  - Cybos historical row는 live 호가 feature 분포를 담지 못한다. 따라서 Cybos-only 후보의 성과는 실제 KIS live 성과의 직접 대리값으로 쓰지 않고, 구조 탐색/후보 축소용으로만 본다.
  - 다음 모델 개선은 KIS live 데이터가 충분히 누적될 때까지 Cybos threshold/grid 추가 튜닝보다 KIS live feature 품질, source drift, 비용 초과 기대값 검증을 우선한다.
- 대시보드:
  - `머신러닝 현황 > 현재 운용`에 `KIS-Cybos feature drift` 카드를 추가했다.
  - 표시 항목: posture, 생성 시각, KIS 표본 날짜, KIS/Cybos rows·symbols·기간·h15 라벨 분포, mismatch 피처, 주요 drift, 결론.

## [2026-05-10 04:56] KIS live 데이터 품질 요약과 label 닫힘 보정

- 목적:
  - Cybos 15분 과거봉 후보가 모두 승격 보류인 상태에서, 다음 모델 개선의 전제인 KIS 실시간 체결/호가 데이터 누적 품질을 정본 DB 기준으로 점검했다.
- 구현:
  - `scripts/summarize_kis_live_data_quality.py` 추가.
  - `tests/test_kis_live_data_quality_summary.py` 추가.
  - 출력:
    - `runtime-data/reports/data-quality/latest-kis-live-data-quality.json`
    - `runtime-data/reports/data-quality/latest-kis-live-data-quality.md`
  - 초기 구현은 SQLite 임시 actual-minute 테이블 조인이 10분을 넘겨 중단했다. 최종 구현은 raw KIS 분 단위 인덱스를 한 번 만들고, 파생 테이블은 `symbol + 시간범위`로 좁혀 읽도록 바꿔 정본 DB 기준 약 10초 안에 완료된다.
- label 닫힘:
  - 첫 품질 리포트에서 2026-05-08 KIS feature 는 `3,790` symbol-minute 인데 h15/h60 label 이 `0`으로 확인됐다.
  - `python -m app --build-feature-dataset` 실행으로 feature / label 을 재생성했다.
  - 결과: `features_written=6,390,299`, `labels_written=11,551,557`, horizons `[15, 60]`, 실행 시간 약 15분.
- 최신 품질 결과:
  - observed KIS dates: `7`, range `2026-04-28..2026-05-08`.
  - raw source:
    - `raw_market_ticks/kis-ws`: `4,227,658` rows, `10` symbols.
    - `raw_orderbook_ticks/kis-ws`: `2,920,106` rows, `10` symbols.
  - latest date `2026-05-08`:
    - market symbol-minutes `3,821`
    - orderbook symbol-minutes `4,060`
    - minute bars `3,790`
    - features `3,790`
    - h15 labels `3,640`
    - h60 labels `3,200`
    - feature/bar ratio `1.0`
    - h15 label/feature ratio `0.960422`
    - h15 label distribution: down `614`, flat `2,208`, up `818`
  - assessment: `ok`.
- 해석:
  - 2026-05-08 기준 KIS live 데이터는 feature 와 label 이 학습 가능한 상태로 닫혔다.
  - 2026-05-07은 market symbol-minutes `30`, orderbook symbol-minutes `130`으로 매우 작아, 이전에 확인한 live runtime 늦은 재기동일로 계속 취급한다.
  - 월요일에는 새 모델 튜닝보다 09:30 기준 live runtime/watchdog 자동 기동과 symbol-minute 증가 여부를 먼저 확인한다.

## [2026-05-10 06:05] Dashboard KIS live 데이터 품질 카드 추가

- 목적:
  - 월요일 장전/장중 점검 때 별도 JSON 파일을 열지 않고도 대시보드 `머신러닝 현황`에서 KIS live 데이터 품질을 확인할 수 있게 했다.
- 구현:
  - `app/services/dashboard.py`가 `runtime-data/reports/data-quality/latest-kis-live-data-quality.json`을 dashboard payload에 포함한다.
  - `머신러닝 현황 > 현재 운용`에 `KIS live 데이터 품질` 카드를 추가했다.
  - 표시 항목: 상태, 생성 시각, 관측 기간, 최근 거래일, 시장 체결/호가 symbol-minute, 분봉/특징/h15/h60 label symbol-minute, feature/bar ratio, h15 label/feature ratio, h15 label 분포.
- 확인:
  - `python -m app --build-runtime-report`로 runtime report 갱신.
  - `python -m app --build-dashboard` 재실행: `generated_at=2026-05-10T06:05:14.388332+09:00`.
  - dashboard JSON/HTML에서 `KIS 품질=ok`, `KIS 최신일=2026-05-08`, h15 labels `3,640`, h60 labels `3,200` 표시 확인.

## [2026-05-10 02:00] 주말 연구 배치: EV 비용 sweep 과 dashboard 인덱스 최적화

- 목적:
  - 주말/저부하 시간에 live runtime 보호 제약을 낮추고, 현재 모델 후보가 거래비용을 넘는지와 대시보드 병목이 재발하는지를 먼저 점검했다.
- expected-value 안정성 확장:
  - `scripts/summarize_expected_value_stability.py`에 기존 fold 선택을 재학습 없이 비용별로 재가격하는 `cost_sweep` 요약을 추가했다.
  - 입력: `runtime-data/reports/backtests/latest-cybos-expected-value-bar-context-momentum-h15.json`.
  - 출력: `runtime-data/reports/backtests/latest-cybos-expected-value-stability-bar-context-momentum-h15.{json,md}`.
  - 비용 sweep: `0.10`, `0.108`, `0.13`, `0.16`, `0.20%`.
  - 같은 fold 선택 기준 재가격 결과:
    - `0.10%`: trade_sum_net `+26.718690%`, bootstrap 95% fold-sum CI `-135.441480..153.617988`, 결론 `positive headline is not stable`.
    - `0.108%`: trade_sum_net `+5.926690%`, bootstrap 95% fold-sum CI `-151.338788..124.047470`, 결론 `positive headline is not stable`.
    - `0.13%`: trade_sum_net `-51.251310%`, bootstrap 95% fold-sum CI `-200.593919..42.773342`, 결론 `negative`.
    - `0.16%`: trade_sum_net `-129.221310%`, bootstrap 95% fold-sum CI `-298.346521..-3.665398`, 결론 `negative`.
    - `0.20%`: trade_sum_net `-233.181310%`, bootstrap 95% fold-sum CI `-465.384772..-48.753643`, 결론 `negative`.
  - 해석: headline 이 양수인 낮은 비용 구간도 CI가 0을 가로지른다. 현재 `bar_context_momentum` expected-value 후보는 비용 초과 알파가 안정적이라고 보기 어렵고 승격 보류가 맞다.
- dashboard 성능:
  - 사전 profile: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/profiles/dashboard/dashboard-build-20260510-014912/`, elapsed `0:26.51`, max RSS `459,980KB`.
  - 병목: `runtime_scope.build_runtime_scope` 안의 raw source minute count SQL.
  - 조치: `raw_market_ticks(source, symbol, event_time)`, `raw_orderbook_ticks(source, symbol, event_time)` 인덱스를 스키마에 추가하고 정본 DB에도 즉시 생성했다. source 조회는 `lower(source)` 계산 대신 `source IN (...)`로 인덱스를 타도록 바꿨다.
  - 사후 profile: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/profiles/dashboard/dashboard-build-20260510-015234/`, elapsed `0:18.17`, max RSS `458,832KB`.
  - 해석: 대시보드 전체 build 는 10분 자동 갱신 기준으로 충분히 안정권이며, 같은 장비 기준 직전 대비 약 `31%` 단축됐다.
- 검증:
  - `python -m py_compile app/storage/sqlite_store.py scripts/summarize_expected_value_stability.py` 통과.
  - `python -m unittest tests.test_expected_value_stability tests.test_runtime_scope tests.test_dashboard`: 16개 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 93개 통과.
  - dashboard server `http://127.0.0.1:8765`는 PID `439371`, API responding 상태다.

## [2026-05-10 03:05] Cybos 연구 suite 통합 요약

- 목적:
  - 주말 자율 연구 두 번째 라운드로, 새 대형 학습을 돌리기 전에 기존 Cybos ML/EV/룰/라벨 리포트를 한 장짜리 판단표로 묶었다.
- 구현:
  - `scripts/summarize_cybos_research_suite.py` 추가.
  - 입력: `runtime-data/reports/backtests/latest-cybos-*.json`.
  - 출력:
    - `runtime-data/reports/backtests/latest-cybos-research-suite-summary.json`
    - `runtime-data/reports/backtests/latest-cybos-research-suite-summary.md`
- 요약 결과:
  - posture: `hold_all_current_cybos_candidates`.
  - bar experiments:
    - `bar_only`: hit_rate `0.383333`, net `-3.785540%`, 상태 `hit_rate_ok_but_cost_negative`.
    - `F-1 cybos bar-only`: hit_rate `0.284987`, net `-25.134498%`, 상태 `hold`.
    - `bar_context`: hit_rate `0.240113`, net `-84.717904%`, 상태 `hold`.
    - `bar_context_momentum`: hit_rate `0.282628`, net `-190.443833%`, 상태 `hold`.
  - expected-value 비용 sweep:
    - `0.10%`, `0.108%` 비용에서는 headline 양수지만 bootstrap CI 하단이 음수라 안정성이 부족하다.
    - `0.13%` 이상에서는 비용 반영 순수익이 음수다.
  - rule challengers:
    - best by net return 은 `quiet_breakout`이지만 trade_hit_rate `0.070254`, net `-106.838776%`로 승격 후보가 아니다.
  - label reviews:
    - sensitivity: `채택 보류, 과최적화 의심`.
    - reproducibility: `재현성 부족`.
- 판단:
  - 현재 Cybos 15분 과거봉 기반 ML/룰 후보는 자동 승격 후보가 없다.
  - 다음 모델 작업은 신규 threshold/grid 튜닝보다 KIS 실시간 호가/체결 데이터 누적 품질, 0.13% 이상 비용 기준 CI 하단 양수 여부, regime/시장상태 피처 설계 쪽을 우선한다.

## [2026-05-10 03:10] Dashboard profile 재측정

- 명령:
  - `./scripts/profile_dashboard_build.sh`
- 결과:
  - profile: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/profiles/dashboard/dashboard-build-20260510-030930/`
  - elapsed `0:25.65`, max RSS `459,068KB`.
- 해석:
  - 직전 best profile `0:18.17`보다 느리지만 10분 자동 갱신 기준으로는 여전히 안정권이다.
  - cProfile 기준 주 병목은 계속 `runtime_scope.build_runtime_scope` 안의 raw KIS source minute 집계다.
  - 추가 expression index 는 dashboard 조회를 더 줄일 수 있지만 raw tick 쓰기 비용을 늘릴 수 있어, 장중 수집 안정성 확인 전에는 적용하지 않는다.

## [2026-05-09 14:45] 대시보드 표기 점검과 ML 카드 정정

- 점검:
  - dashboard server는 `http://127.0.0.1:8765`에서 응답 중이었지만, 기존 프로세스가 오래 떠 있어 새 코드 기준과 표시가 일부 어긋났다.
  - 기존 dashboard snapshot은 LightGBM `검증 정확도`를 학습 validation `57.15%`가 아니라 challenger holdout `50.43%`로 표시했다. 학습 행/검증 행과 함께 보이면 잘못 해석될 수 있는 표기였다.
  - 최신 challenger report는 `6b5b056`의 artifact lineage guard 이전 산출물이라 `latest_lightgbm.promotable=true`를 담고 있었다. 현재 코드 기준에서는 기존 artifact에 `training_run_id` metadata가 없어 `artifact_missing_training_run_id`로 승격 불가가 맞다.
- 수정:
  - dashboard는 LightGBM 상태에서 학습 validation split만 찾아 `학습 validation 정확도`로 표시한다.
  - dashboard 생성 시점의 artifact lineage guard를 challenger report 위에 덧씌워, legacy artifact metadata가 없는 LightGBM 후보는 `승격 가능=아니오`로 표시한다.
  - 챌린저 비교 표에 `승격 가능`, `독립성/아티팩트` 컬럼을 추가했다.
  - LightGBM 실제 현황 표에 artifact 정합성, artifact 학습 run, DB 최신 학습 run을 표시한다.
- 실제 반영:
  - `python -m app --build-dashboard`: `generated_at=2026-05-09T14:44:36.689019+09:00`.
  - dashboard server를 재시작해 PID `439371`, `raw_status=running`, API 응답 정상으로 맞췄다.
  - 최신 dashboard JSON 확인 결과 `validation_accuracy=0.5714815684909165`, `validation_split_name=validation`, `artifact_lineage_status=artifact_missing_training_run_id`, `latest_lightgbm.promotable=false`로 표시된다.

## [2026-05-09 12:55] LightGBM artifact/DB 정합성 가드 보강

- 목적:
  - NAS 복구나 수동 파일 복사로 `runtime-data/ml/models/lightgbm-h15-v1.joblib` artifact와 `ml_training_runs`의 최신 학습 row가 서로 어긋나는 경우, DB 메타데이터만 보고 LightGBM을 승격 후보로 착각하지 않게 막는다.
- 구현:
  - LightGBM artifact payload에 `training_run_id`, `trained_at`, `dataset_scope`, `challenger_holdout_first_event_time`를 저장한다.
  - challenger 평가는 최신 DB training row의 `training_run_id`와 artifact 내부 `training_run_id`가 일치할 때만 `artifact_training_run_match`로 본다.
  - holdout 독립성이 통과하더라도 artifact가 metadata를 갖고 있지 않거나 DB 최신 row와 다르면 `artifact_missing_training_run_id` 또는 `artifact_training_run_mismatch`로 fail-safe 차단한다.
- 테스트:
  - artifact/run id 일치, 불일치, 누락, training summary 없음 분기를 단위 테스트로 고정했다.
  - pipeline 테스트에서 새로 학습된 LightGBM artifact가 training run id와 challenger holdout metadata를 저장하는지 확인한다.
- 실제 정본 재실행 시도:
  - `python -m app --train-lightgbm --horizon-min 15`는 15분 제한에서 완료되지 않았고 CPU 약 `800%`, 메모리 약 `95%`까지 사용해 중단했다.
  - `python -m app --run-challengers --horizon-min 15`도 10분 제한에서 완료되지 않았고 CPU 약 `740%`, 메모리 약 `96%`까지 사용해 중단했다.
  - 기존 artifact 파일 시각은 `2026-05-09 03:09`로 남아 partial artifact overwrite는 확인되지 않았다.
- 판단:
  - 이번 코드는 fail-safe 보강이다. 새 metadata가 없는 기존 LightGBM artifact는 다음 challenger 평가에서 승격 불가 상태가 되는 것이 정상이다.
  - 정본 전체 LightGBM 재학습/challenger는 장중 또는 일반 quick 작업으로 돌리지 않고, D드라이브 snapshot 기반 heavy research 또는 별도 bounded 평가 경로로 분리해야 한다.
- 검증:
  - `python -m py_compile app/models/lightgbm_model.py app/services/research.py`: 통과.
  - `python -m unittest tests.test_research_pipeline`: 8개 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 91개 통과.

## [2026-05-09 04:05] cowork 리뷰 반영: holdout 가드 테스트와 문서 보강

- 반영:
  - cowork 리뷰 중 `challenger_holdout_tail_10pct` 구조 자체는 타당하다는 판단을 유지한다.
  - ISO datetime 문자열 비교는 timezone 표기가 섞일 때 위험할 수 있어 `datetime.fromisoformat` 기반 비교로 바꿨다.
  - `legacy_training_without_reserved_holdout`, `training_reserved_holdout_missing`, `holdout_metadata_missing`, `holdout_window_mismatch`, `validation_overlaps_challenger_holdout`, 성공 분기 `independent_challenger_holdout`을 단위 테스트로 고정했다.
  - split 테스트에서 train/validation key와 challenger holdout key가 겹치지 않는 것도 확인한다.
- 문서 보강:
  - `0.92` validation 과열 자체의 원인 분석은 이번 변경 범위가 아니며, 이번 변경은 해당 validation 구간을 challenger 승격 근거로 재사용하지 않게 한 것이라고 정리했다.
  - `best candidate` 표현은 `best by sort key`, 즉 모두 음수인 후보 중 가장 덜 나쁜 후보라는 뜻으로 정정했다.
  - 재학습 뒤 live 데이터가 추가되어 holdout 경계가 바뀌면 fail-safe로 promotable이 막히므로, 승격 검토는 재학습 직후 같은 데이터 경계에서 challenger를 이어서 실행해야 한다는 운영 invariant를 기록했다.

## [2026-05-09 03:30] challenger 독립성 보강과 실제 holdout 재평가

- 목적:
  - 기존 challenger 평가는 LightGBM 학습 때 validation으로 본 tail 구간을 다시 평가에 쓰는 구조라, row overlap은 없어도 모델 선택용 validation과 challenger 평가가 독립적이지 않았다.
  - 이번 변경은 마지막 tail `10%`를 `challenger_holdout_tail_10pct`로 예약하고, LightGBM 학습/validation은 그 이전 development 구간에서만 수행하도록 분리했다.
- 구현:
  - `train_lightgbm_from_sqlite`와 centroid 학습 summary에 `challenger_holdout_split` 메타데이터를 기록한다.
  - `run_model_challenger_review_from_sqlite`는 `validation_tail_20pct`가 아니라 reserved holdout을 평가 구간으로 사용한다.
  - 각 candidate에 `evaluation_independence_status`를 기록한다.
  - 최신 LightGBM artifact가 reserved holdout 메타데이터 없이 학습된 legacy 모델이면 promotable 후보에서 제외된다.
  - 재학습 뒤 live 데이터가 추가되어 holdout 경계가 바뀌면 `holdout_window_mismatch`로 fail-safe 차단된다. 따라서 LightGBM 승격 검토는 재학습 직후 같은 데이터 경계에서 challenger를 이어서 실행해야 한다.
- 실제 정본 DB 재실행:
  - `python -m app --train-lightgbm --horizon-min 15`
    - `training_run_id=train-lightgbm-h15-20260509030957756047`
    - `train_rows=4,295,040`, `validation_rows=1,183,354`
    - `validation_accuracy=0.571482`
    - `activation_applied=false`
  - `python -m app --run-challengers --horizon-min 15`
    - `dataset_scope=challenger_holdout_tail_10pct`
    - holdout rows `662,401`
    - holdout start `2025-10-24T09:00:00+09:00`
    - best by sort key `latest_lightgbm` (모든 주요 후보가 음수이며, 가장 덜 나쁜 후보)
    - `latest_lightgbm`: accuracy `0.504269`, trade_hit_rate `0.202465`, trades `568`, net `-30.697069%`
    - `evaluation_independence_status=independent_challenger_holdout`
    - `recommended_action=review_required`
    - `decision_reason=Walk-forward overall accuracy is too low (0.4163).`
- 판단:
  - 예전 `0.92`대 validation 과열을 challenger 승격 근거로 재사용하지 않도록 평가 독립성은 보강됐다. 다만 `0.92` validation 자체의 원인 분석은 별도 과제로 남긴다.
  - 독립 holdout 기준 LightGBM은 여전히 비용 반영 순수익과 trade hit rate가 부족하므로 active model은 `baseline-h15-v1` 유지가 맞다.
- 대시보드:
  - `python -m app --build-dashboard`: `generated_at=2026-05-09T03:26:29.971728+09:00`.
- 검증:
  - `python -m py_compile app/services/research.py`: 통과.
  - `python -m unittest tests.test_research_pipeline`: 5개 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 88개 통과.

## [2026-05-08 22:15] cowork 의견 반영: quick/heavy 분리, dashboard 병목 고정, EV 안정성 진단

- 비판적 검토:
  - 모델 승격 보류 판단은 유지한다. `0.13%` 비용에서 expected-value 결과가 음수이고, `portfolio_return_pct=-1.802245`는 실제 계좌 수익률이 아니라 fixed-fraction 진단 프록시다.
  - cowork 의견처럼 단일 평균보다 fold 분포와 신뢰구간을 보는 쪽이 맞다.
  - 비용 sweep 전체 재학습은 장시간 작업이므로 먼저 기존 `0.13%` 리포트에서 안정성 요약을 생성했다.
- post-close 운영 분리:
  - watchdog 기본 post-close 모드를 `quick-live-report`로 변경했다.
  - quick 작업은 `build-runtime-report`, `build-dashboard`만 수행하고 목표 시간은 10분이다.
  - snapshot DB와 `--rebuild-actual-ml`을 쓰는 heavy research 는 `run_post_close_ml_maintenance.sh --heavy-research --use-snapshot` 명시 실행으로 분리했다.
  - 2026-05-08 quick maintenance 직접 실행 결과: `status=ok`, `mode=quick-live-report`, `completed_at=2026-05-08 22:10:23 +0900`.
  - dashboard snapshot 재생성: `generated_at=2026-05-08T22:12:07.623207+09:00`, 장후 자동 학습 상태 카드가 quick `ok` 상태를 읽는다.
- dashboard profiling:
  - profile 산출물: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/profiles/dashboard/dashboard-build-20260508-215838/`.
  - cProfile 기준 병목: `runtime_scope.build_runtime_scope`가 Cybos 5년치 raw row까지 장 상태 판정에 넣으며 660만 회 이상 `get_market_session_status` 계열 호출을 만들었다.
  - 보강: actual runtime scope 는 `kis-rest`, `kis-ws` source만 SQL에서 먼저 읽고, 장 시간 판정은 minute 단위 캐시로 줄였다.
  - 재측정: `python -m app --build-dashboard`가 `0:35.04`, max RSS `453,960KB`로 완료됐다. 직전 측정 `3:27`, `5.4GB` 대비 크게 완화됐다.
- expected-value 안정성:
  - 리포트: `runtime-data/reports/backtests/latest-cybos-expected-value-stability-bar-context-momentum-h15.{json,md}`.
  - fold 분포: 양수 fold `5`, 음수 fold `2`, no-trade fold `5`.
  - bootstrap 95% fold-sum net CI: `-203.859408..42.553578`.
  - reliability flags: `low_fold_count`, `contains_no_trade_folds`, `bootstrap_ci_crosses_zero`, `hit_rate_near_random_or_lower`.
  - 결론: `hold: cost-adjusted trade-sum return is negative.`
- 검증:
  - `python -m py_compile app/services/runtime_scope.py app/storage/sqlite_store.py scripts/wsl_ops.py scripts/summarize_expected_value_stability.py`: 통과.
  - `bash -n scripts/script_dispatch.sh scripts/profile_dashboard_build.sh scripts/run_post_close_ml_maintenance.sh`: 통과.
  - `python scripts/wsl_ops.py run-watchdog-loop --single-pass`: 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 88개 통과.

## [2026-05-08 21:35] 보수 비용 expected-value 재검증과 dashboard 병목 완화

- expected-value 0.13% 비용 재검증:
  - 입력 DB: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-snapshots/post-close-h15-20260508-160019.db`.
  - 출력 runtime: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-runs/expected-value-20260508-h15-cost013/runtime-data`.
  - source: `cybos-historical`, feature set: `bar_context_momentum`, horizon: `15`.
  - 비용: 왕복 `0.13%`.
  - 결과: `folds=12`, `rows_evaluated=600,000`, `trades_taken=2,599`, `overall_accuracy=0.534130`, `trade_hit_rate=0.300500`, `win_rate=0.497114`.
  - 거래합산: `trade_sum_gross_return_pct=+286.618690`, `trade_sum_net_return_pct=-51.251310`, `average_net_return_pct=-0.019720`.
  - 포트폴리오 프록시: `portfolio_return_pct=-1.802245`, model=`fixed_fraction_per_signal_horizon_proxy`, allocation=`5%`, max gross exposure=`100%`, executed=`2,006`, skipped by exposure=`593`.
- 판단:
  - `0.108%` 비용에서는 양수였던 expected-value 선별이 `0.13%` 보수 비용에서는 음수로 돌아섰다.
  - hit rate는 `0.3005`로 문턱만 넘었지만, 비용 초과 기대값은 아직 부족하다.
  - 모델 승격은 계속 보류한다.
- 코드 보강:
  - expected-value walk-forward 리포트에 포트폴리오 프록시 수익률을 추가했다.
  - 이 값은 실제 paper 계좌 수익률이 아니라, `5% 고정 비중 / horizon 기반 청산 / 총 익스포저 100% 제한`으로 계산한 보수적 진단값이다.
- dashboard 병목:
  - 기존 `python -m app --build-dashboard`는 `8분 03초`, max RSS 약 `7.9GB`.
  - 대형 테이블을 기본 `오늘` 화면에서도 전부 읽던 경로를 줄이고, 기간 필터가 있으면 SQL 범위 조회를 우선 사용하도록 바꿨다.
  - 재측정 결과 `3분 27초`, max RSS 약 `5.4GB`.
  - 아직 가볍지는 않지만 10분 자동 갱신 주기 안에는 들어왔다. 다음 병목은 raw tick minute source 집계다.

## [2026-05-08 19:30] 장후 maintenance 중단과 expected-value review 결과

- 장후 운영 상태:
  - 확인 시각: `2026-05-08 18:07 KST`.
  - live runtime은 `2026-05-08 15:30:33 +0900`에 정상 정지했다.
  - runtime watchdog은 post-close 상태에서 running 이며, latest 상태는 `ml_maintenance_action=already_failed`다.
  - 09:00 이후 정본 DB 누적: `raw_market_ticks=1,170,143`, `raw_orderbook_ticks=647,201`, `curated_minute_bars=3,770`, `feature_model_inputs=3,770`, `serving_predictions=7,540`, `serving_trade_signals=3,770`.
- post-close maintenance:
  - 자동 maintenance는 D드라이브 snapshot `post-close-h15-20260508-160019.db`를 만든 뒤 `--rebuild-actual-ml` 단계에서 2시간 가까이 진행됐다.
  - main DB가 아니라 snapshot/runtime 격리 경로였지만, 과도하게 오래 걸려 중단했고 상태 파일은 `failed`로 기록했다.
  - watchdog이 `failed` 상태를 보고 같은 날짜 maintenance를 계속 재시작하는 문제가 있어 `scripts/wsl_ops.py`를 수정했다. 이제 오늘 날짜에 status 값이 있으면 `already_<status>`로 보고 재시작하지 않는다.
  - 중단 중 생긴 불완전한 D드라이브 snapshot `post-close-h15-20260508-181250*`, `post-close-h15-20260508-181459*`는 삭제했다.
- expected-value review:
  - 입력 DB: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-snapshots/post-close-h15-20260508-160019.db`.
  - 출력 runtime: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-runs/expected-value-20260508-h15/runtime-data`.
  - 리포트: `latest-cybos-expected-value-bar-context-momentum-h15.json`, `.md`.
  - dataset: `symbols=199`, `trade_dates=1,249`, `source_rows=6,283,279`, `labeled_rows=6,040,981`, 기간 `2021-03-30T09:15:00+09:00..2026-05-04T15:15:00+09:00`.
  - walk-forward: `folds=12`, `rows_evaluated=600,000`, `trades_taken=3,008`, `overall_accuracy=0.534130`, `trade_hit_rate=0.304854`, `win_rate=0.523271`.
  - 비용 `0.108%` 반영: `average_net_return_pct=0.006320`, `trade_sum_net_return_pct=+19.012036`, `estimated_cost_drag_pct=324.864`.
  - fold 안정성: 양수 fold 7개, 음수 fold 2개, no-trade fold 3개.
- 판단:
  - 🟢 완료 조건 일부 충족: 비용 `0.108%` 기준으로 `trade_hit_rate >= 0.3`와 비용 반영 거래합산 순수익 양수를 동시에 달성했다.
  - 다만 이 값은 계좌 수익률이 아니라 `sum_of_trade_pct_not_portfolio`이며, 보수 비용 `0.13%` 재검증과 portfolio-level 환산 전까지 모델 승격은 보류한다.
- 대시보드:
  - expected-value 리포트는 정본 `runtime-data/reports/backtests/`에도 복사했다.
  - `python -m app --build-dashboard`는 5분 제한에서 끝나지 않아 중단했다.
  - dashboard server는 `http://127.0.0.1:8765`에서 running/API responding 상태다.

## [2026-05-08 15:00] broker paper 체결 조회 rate-limit 완화

- 관찰:
  - live runtime: `running`, `current_session_status=regular-session`, `trading_mode=paper`.
  - 09:00 이후 누적: `curated_minute_bars=3,550`, `feature_model_inputs=3,550`, `serving_predictions=7,100`, `serving_trade_signals=3,550`.
  - `live-runtime.stderr.log`의 `KIS broker paper order-fill query rate-limited` 경고가 누적 231회였다.
- 조치:
  - 수동 브로커 체결 동기화는 기존 짧은 재시도를 유지한다.
  - 장중 온라인 처리 루프에서는 rate-limit 발생 시 즉시 재시도하지 않고, 기존 5분 cooldown 으로 빠지도록 변경했다.
  - 기대 효과: KIS 호출 제한 충돌 감소, live loop 지연 감소, stderr 로그 증가 감소.
  - watchdog이 `2026-05-08 15:00:34 +0900`에 live runtime을 다시 올려 현재 실행 중인 프로세스에는 이번 변경이 적용된 상태다.
  - 15:00 재기동 직후 tail 기준으로는 broker paper 체결 조회 즉시 재시도 로그가 추가로 보이지 않았다.
- 검증:
  - `python -m py_compile app/services/broker_paper.py app/services/broker_paper_sync.py app/services/streaming.py` 통과.
  - `python -m unittest tests.test_broker_paper_sync tests.test_streaming_pipeline`: 11개 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 88개 통과.
  - `git diff --check` 통과.

## [2026-05-08 12:20] 장중 수집 확인과 train-only expected-value 실험 경로

- 장중 수집 상태:
  - live runtime: `running`, `started_at=2026-05-08 08:00:59 +0900`, `current_session_status=regular-session`, `trading_mode=paper`.
  - runtime watchdog: `running`, `live_runtime_should_run=true`, 오류 없음.
  - 09:00 이후 누적: `curated_minute_bars=1,940`, `feature_model_inputs=1,946`, `serving_predictions=3,900`, `serving_trade_signals=1,950`.
  - 판단: 2026-05-08 장중 수집/추론은 정상 축으로 유지 중이다.
- 장중 heavy snapshot 판단:
  - `run_research_on_snapshot.sh --prefix intraday-metrics-gate -- python -m app --run-gate-walk-forward --horizon-min 15`는 live DB backup 단계가 1시간 이상 끝나지 않아 중단했다.
  - 미완성 D드라이브 snapshot 파일은 삭제했다.
  - 판단: 장중에는 live DB 전체 snapshot/gate 재생성을 피하고, 정규장 종료 뒤 snapshot maintenance로 처리한다.
- 모델 개선:
  - `python -m app --run-cybos-expected-value-review`를 추가했다.
  - 목적: `bar_context_momentum` Cybos LightGBM에서 비용을 초과하는 거래만 남길 수 있는지 train-only calibration으로 진단한다.
  - threshold 선택 기준: 각 fold train tail calibration 구간의 비용 차감 평균 기대값 양수 여부.
  - 안전장치: test 결과를 보고 threshold를 재조정하지 않고, active model 자동 승격도 하지 않는다.
- 다음 실행:
  - 16:20 KST heartbeat에서 장후 snapshot 기반 gate/challenger 재생성과 expected-value review를 이어간다.
- 검증:
  - `python -m py_compile app/__main__.py app/services/research.py app/services/dashboard.py` 통과.
  - `python -m unittest tests.test_research_pipeline tests.test_dashboard`: 18개 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 88개 통과.
  - `git diff --check` 통과.

## [2026-05-08 08:45] 수익률 지표 의미 분리와 장전 자동 기동 확인

- 장전 자동 기동:
  - 확인 시각: `2026-05-08 08:37 KST`.
  - `runtime watchdog`: `running`, `live_runtime_should_run=true`, 오류 없음.
  - `live runtime`: `running`, `started_at=2026-05-08 08:00:59 +0900`, `trading_mode=paper`, `credentials_ready_for_quotes=true`.
  - 판단: 2026-05-08 장전 자동 기동은 정상 작동 중이다. 실제 장중 분봉/feature 누적은 09:35 heartbeat에서 확인한다.
- 지표 정리:
  - 기존 `cumulative_net_return_pct`는 실제 계좌 수익률이 아니라 거래별 수익률을 단순 합산한 진단 지표다.
  - 이 오해를 줄이기 위해 research metric에 `return_aggregation=sum_of_trade_pct_not_portfolio`를 추가했다.
  - `trade_sum_gross_return_pct`, `trade_sum_net_return_pct`, `estimated_cost_drag_pct`, `portfolio_return_pct=null`, `portfolio_return_unavailable_reason`를 추가했다.
  - 기존 필드는 하위 호환을 위해 유지하되, 대시보드 표시는 `누적 순수익률` 대신 `거래합산 순수익률`과 `비용 차감 합계`로 바꿨다.
- 판단:
  - `net=-170736%` 같은 숫자는 병합 오류의 직접 증거가 아니라, 과도한 거래 수와 거래별 비용/손익 합산이 만든 진단 신호다.
  - 다음 모델 실험에서는 계좌 수익률처럼 보이는 합산 지표보다, 비용 초과 평균 기대값과 거래 선별 능력을 우선 본다.
- 검증:
  - `python -m py_compile app/services/research.py app/services/dashboard.py` 통과.
  - `python -m unittest tests.test_research_pipeline tests.test_dashboard`: 17개 통과.

## [2026-05-08 03:30] 장전 운영 상태, gate reference 재생성, Cybos momentum 실험

- 장전 운영 상태:
  - 확인 시각: `2026-05-08 02:29 KST`.
  - 현재 장 상태는 `pre-open`이고, 정규장 시작 60분 전이 아니므로 live runtime이 꺼져 있는 것은 정상 범위다.
  - `runtime watchdog`이 stale 상태였기 때문에 `./scripts/start_runtime_watchdog_background.sh`로 재기동했다.
  - 재기동 후 watchdog 상태는 `running`, `live_runtime_should_run=false`, `live_runtime_action=off_session_hold_pre-open`.
  - 대시보드 서버도 stale 상태였으나 watchdog 재시작 뒤 `running`, `dashboard_responding=true`, `dashboard_api_responding=true`로 복구됐다.
  - 09:35 장중 수집 확인 heartbeat를 등록했다. 확인 대상은 watchdog/live runtime 상태와 09:00~09:35 사이 `curated_minute_bars`, `feature_model_inputs` 누적 상태다.
- 대시보드:
  - `python -m app --build-dashboard`를 실행해 `runtime-data/reports/dashboard/latest-dashboard.html`, `.json`을 갱신했다.
  - 최신 생성 시각: `2026-05-08T03:27:23.027323+09:00`.
- 정본 gate walk-forward:
  - 실행 명령: `python -m app --run-gate-walk-forward --horizon-min 15`.
  - `parameter_profile=gate_reference_v1`, `command_source=cli_run_gate_walk_forward`, `feature_market_source=cybos-historical`.
  - 결과: `folds=118`, `rows_evaluated=5,900,000`, `trades_taken=1,572,715`.
  - `overall_accuracy=0.416342`, `trade_hit_rate=0.125765`, `cumulative_gross_return_pct=-882.907782`, `cumulative_net_return_pct=-170736.127782`.
  - 판단: 설정 provenance와 Cybos source 분리는 정상화됐지만, gate 통과 조건에는 크게 미달한다.
- challenger 재평가:
  - 실행 명령: `python -m app --run-challengers --horizon-min 15`.
  - `challenger_run_id=challenger-h15-20260508024418178175`.
  - `recommended_action=keep_active`, `decision_reason=The top challenger matches the current active model.`
  - `walk_forward_gate_status=needs_review`, 사유: `Walk-forward overall accuracy is too low (0.4163).`
  - 최신 LightGBM 후보는 `overall_accuracy=0.343409`, `trade_hit_rate=0.170136`, `cumulative_net_return_pct=-46489.671791`로 승격 불가.
  - 이전의 LightGBM 0.92 수준 비정상 validation 격차는 사라졌고, 현재는 gate/challenger 모두 부정적 방향으로 일관된다.
- 모델 개선 실험:
  - 실행 명령: `python -m app --run-cybos-bar-only-experiment --horizon-min 15 --cybos-experiment-feature-set bar_context_momentum --cybos-experiment-train-max-rows 100000 --cybos-experiment-walk-test-rows 50000 --cybos-experiment-walk-step-rows 100000 --cybos-experiment-walk-gap-rows 15 --cybos-experiment-walk-max-folds 20`.
  - 피처셋: `avg_trade_size`, `hl_range_pct`, `return_1m_pct`, `close_position_pct`, `minute_slot_pct`, `log_volume`, `prev_return_pct`, `prev_hl_range_pct`, `log_volume_delta`.
  - feature importance 상위 5개: `minute_slot_pct`, `hl_range_pct`, `prev_hl_range_pct`, `prev_return_pct`, `return_1m_pct`.
  - validation: `overall_accuracy=0.517758`, `trade_hit_rate=0.282409`, `cumulative_gross_return_pct=1449.501001`, `cumulative_net_return_pct=-1552.142999`.
  - walk-forward: `folds=12`, `rows_evaluated=600,000`, `trades_taken=6,666`, `overall_accuracy=0.535122`, `trade_hit_rate=0.282628`, `cumulative_gross_return_pct=529.484167`, `cumulative_net_return_pct=-190.443833`.
  - 판단: 방향성 신호가 일부 있어 gross 기준은 양수지만, 왕복 비용 `0.108%`를 넘지 못한다. 현재 병목은 예측 정확도 자체보다 비용을 넘는 거래 선별 능력 부족이다.
- 다음 판단:
  - 현 상태에서는 모델 승격하지 않는다.
  - 다음 실험은 수동 threshold 튜닝보다 비용 초과 기대값을 직접 학습/평가하는 구조, 거래 빈도 억제, 또는 장중 KIS 실데이터 누적 확인을 우선한다.

## [2026-05-08 00:25] WSL/D드라이브 경로 정리

- 원인:
  - `C:` 여유 공간이 약 0.8GB까지 줄었고, Ubuntu WSL2 배포판 BasePath가 `C:\Users\Keios\AppData\Local\wsl\{5043514c-aa32-4220-928c-802d47b0f90b}`로 확인됐다.
  - 대용량 `runtime-data/dev.db`, feature/label 재빌드 산출물이 WSL VHD 안에 쌓이면서 C드라이브 압박과 WSL 불안정이 같이 발생한 것으로 판단했다.
- 조치:
  - `wsl --manage Ubuntu --move D:\WSL\Ubuntu`로 Ubuntu WSL2 배포판을 D드라이브로 이동했다.
  - 이동 후 `DistributionName=Ubuntu`, `BasePath=D:\WSL\Ubuntu`, `Version=2`로 확인했고, `wsl -d Ubuntu --exec /bin/bash -lc "echo ok"`가 성공했다.
  - Cybos 수집기 기본 DB 경로를 `D:\CodexData\Real-time-stock-price-prediction-program\cybos\cybos_collect.db`로 변경했다.
  - 병합 안내 경로도 `/mnt/d/CodexData/Real-time-stock-price-prediction-program/cybos/cybos_collect.db` 기준으로 갱신했다.
  - `AGENTS.md` 산출물 규칙에 D드라이브 우선 정책을 명시했다. 새 데이터 수집, 다운로드, 스냅샷, 장기 보관, 대용량 임시 파일은 어쩔 수 없는 OS/도구 캐시를 제외하고 D드라이브만 사용한다.
- 검증:
  - 이동 후 `C:` 여유 공간은 약 17GB로 회복됐다.
  - `python -m py_compile scripts/collect_cybos_historical.py` 통과.
  - `bash -n scripts/merge_cybos_to_main.sh scripts/run_gate_walk_forward_backtest.sh` 통과.
  - `python -m unittest discover -s tests -p "test_*.py"`: 87개 통과.
  - `python -m app --build-dashboard`: `runtime-data/reports/dashboard/latest-dashboard.html`, `latest-dashboard.json` 생성 성공.
- 남은 수동 조치:
  - Windows 시스템 PATH에 오래된 `J:\Program Files\Git\Git\cmd`는 제거된 것으로 확인됐다.
  - 현재 Codex 앱 프로세스는 제거 전 PATH를 물고 있어 이 세션의 일부 `wsl` 실행에서는 경고가 남을 수 있다. 새 PowerShell 또는 Codex 재시작 후에는 사라지는 상태로 판단한다.

## [2026-05-07 23:55] WSL 자동 시작 경로, Cybos feature 재빌드, gate reference 분리

- WSL 정본 자동 시작:
  - Windows 시작프로그램의 `RealTimeStockRuntime.cmd`와 `GitAutoPushWatcher.cmd`가 예전 `D:\GitHub\Real-time-stock-price-prediction-program`을 가리키던 것을 확인했다.
  - 두 런처를 현재 WSL 정본 저장소 `/home/keios/projects/Real-time-stock-price-prediction-program` 기준 `wsl.exe -d Ubuntu --cd ...` 명령으로 갱신했다.
  - WSL systemd user service는 이 환경에서 WSL 세션 불안정을 일으킬 수 있어 비활성화/삭제했고, 설치 스크립트도 Windows 시작프로그램을 사용할 수 있으면 systemd를 만들지 않도록 바꿨다.
  - 현재 `get_runtime_startup_launcher_status.sh`: `installed=true`, `ok=true`, `windows_startup_launcher.ok=true`, systemd service `not-found`.
- Cybos feature/label 재빌드:
  - 원인: 기존 feature builder는 호가 snapshot이 있는 분봉만 feature를 만들었다. Cybos 15분봉은 호가 데이터가 없어 199종목 대부분이 `feature_model_inputs`에 들어오지 못했다.
  - 조치: `source=cybos-historical` 분봉은 내부 synthetic orderbook으로 feature row를 만들되, 학습 단계에서는 `mid_price`, `spread_bps`, `bid_ask_imbalance`를 제외한다.
  - `python -m app --build-feature-dataset` 실행 완료.
  - 결과: `features_written=6,386,509`, `labels_written=11,544,717`.
  - 재확인: `feature_model_inputs=6,386,509`, `feature_labels=11,544,717`, labeled feature source 샘플은 `cybos-historical`.
- Gate reference 분리:
  - walk-forward 리포트에 `parameter_profile`, `command_source`, `feature_market_source` provenance 를 기록하도록 변경했다.
  - 일반 `--run-walk-forward`는 `parameter_profile=ad_hoc_cli`로 남긴다.
  - 정본 gate reference 전용 명령을 추가했다.
    - `python -m app --run-gate-walk-forward --horizon-min 15`
    - `./scripts/run_gate_walk_forward_backtest.sh`
  - gate 전용 경로는 SQL 단계에서 `feature_market_source=cybos-historical`만 읽고, `parameter_profile=gate_reference_v1`로 기록한다.
- 주의:
  - 대용량 feature 재빌드 직후 WSL 서비스가 일시적으로 `Wsl/Service/E_UNEXPECTED` 상태가 되었고, Windows 재부팅 후 복구됐다.
  - 이후 systemd user service는 사용하지 않고 Windows 시작프로그램 런처를 주 자동 기동 경로로 둔다.

## [2026-05-07 21:15] walk-forward 생성 경로, challenger split, live 공백 원인 진단

### 1. 정본 walk-forward 생성 경로

- 정본 파일:
  - `runtime-data/reports/backtests/latest-walk-forward-h15.json`
  - `evaluated_at=2026-05-06T20:08:51.772212+09:00`
  - 파일 mtime: `2026-05-06 20:08:58 +0900`
- 현재 파일의 설정:
  - `min_train_rows=30`
  - `test_window_rows=10`
  - `step_rows=10`
  - `gap_rows=15`
  - `max_train_rows=200`
- 생성 경로 확인:
  - CLI `python -m app --run-walk-forward`는 `app/__main__.py`에서 `run_walk_forward_backtest_from_sqlite()`로 직접 연결된다.
  - CLI 기본값은 `min_train_rows=30`, `test_rows=10`, `step_rows=10`, `gap_rows=None`, `max_train_rows=None`이다.
  - `scripts/run_walk_forward_backtest.sh`는 `scripts/script_dispatch.sh`에서 `--walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10`만 넘긴다. 따라서 현재 파일의 `gap_rows=15`, `max_train_rows=200`과 완전히 일치하지 않는다.
  - `--rebuild-actual-ml` 경로는 `app/services/research.py`의 `rebuild_actual_runtime_ml_state()`에서 `min_train_rows=30`, `test_rows=10`, `step_rows=10`, `gap_rows=15`, `max_train_rows=40`을 쓴다. 따라서 현재 파일의 `max_train_rows=200`과 다르다.
  - `docs/logbook.md`의 2026-05-06 실험 E 기록에 아래 수동 명령이 남아 있고, 현재 파일의 설정과 일치한다.
    - `python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 200`
- 판단:
  - 현재 gate reference는 자동 post-close 산출물이 아니라, 2026-05-06 수동 실험 E 명령이 안정 경로 `latest-walk-forward-h15.json`을 덮어쓴 결과로 보는 것이 가장 타당하다.
  - 현 구조는 생성 명령/파라미터 provenance가 JSON에 명확히 남지 않고, 모든 실행이 같은 `latest-*` 경로를 덮어쓴다. 다음 수정 후보는 walk-forward 리포트에 `command_source`/`parameter_profile`을 남기고, gate reference 생성 명령을 별도로 고정하는 것이다.

### 2. challenger 누수 진단

- 현재 `run_model_challenger_review_from_sqlite()`는 `app/services/research.py`에서 `_load_labeled_feature_dataset()` 후 `_split_dataset()`을 사용한다.
- split 방식:
  - `_date_level_tail_split()`으로 거래일 기준 tail 20%를 validation으로 분리한다.
  - `_apply_horizon_purge()`가 validation 시작 시각 기준으로 train row를 purge한다.
  - train에 `down/flat/up` 라벨이 모두 없을 때만 row-level fallback을 사용한다.
- 현재 정본 DB 기준 15분 labeled dataset 진단:
  - 전체 rows `343807`, 날짜 `1309`, 범위 `2021-01-04T09:00:00+09:00..2026-05-06T15:15:00+09:00`
  - train rows `262178`, 날짜 `1047`, 범위 `2021-01-04..2025-04-08`
  - validation rows `81629`, 날짜 `262`, 범위 `2025-04-09..2026-05-06`
  - train/validation `(symbol,event_time)` overlap: `0`
  - train/validation date overlap: `0`
- 최신 LightGBM candidate:
  - challenger training_run_id: `train-lightgbm-h15-20260506200645749446`
  - 학습 당시 train rows `254350`, validation rows `78542`
  - 학습 summary split: last train `2025-04-08T15:00:00+09:00`, first validation `2025-04-09T09:00:00+09:00`
- 판단:
  - LightGBM 학습 rows와 challenger evaluation rows가 같은 날짜/시각으로 직접 겹친 증거는 없다.
  - 다만 LightGBM 학습 시 validation으로 쓴 tail 구간과 challenger가 다시 평가하는 tail validation 구간이 사실상 같은 기간이다. 따라서 현재 challenger 수치는 독립 out-of-sample 평가가 아니라 validation 재사용 평가로 본다.
  - 즉시 확인된 문제는 직접 row leakage가 아니라 평가 독립성 부족이다. 승격 판단은 계속 walk-forward gate를 우선해야 한다.
- 추가 관찰:
  - 현재 canonical labeled dataset은 `pykrx-daily-proxy`가 `328429` rows로 대부분이고, `cybos-historical`로 resolve된 rows는 `152`뿐이다. 5년치 Cybos 병합과 별개로 정본 feature/label dataset이 기대한 `cybos-historical only` 상태가 아니므로, 다음 기준선 재측정 전 feature 재생성/소스 resolve를 다시 점검해야 한다.

### 3. 2026-05-07 live runtime 공백 원인

- 정본 DB 확인:
  - `curated_minute_bars`: `20` rows, 범위 `2026-05-07T15:17:00+09:00..2026-05-07T15:18:00+09:00`
  - `feature_model_inputs`: `20` rows, 같은 범위
  - `feature_labels`: `0` rows
- 로그 확인:
  - `runtime-data/logs/app/app.log`와 `live-runtime.stderr.log`의 2026-05-07 첫 WSL 정본 live runtime 연결 로그는 `15:17:48`이다.
  - `15:17:50`에 KIS WebSocket 연결은 성공했다.
  - 09:00~15:16 사이 WSL 정본 live runtime 연결 로그는 확인되지 않았다.
- watchdog 상태:
  - 현재 `runtime-data/reports/runtime-watchdog/state/watchdog-state.json`의 watchdog `started_at=2026-05-07 16:53:13 +0900`이다.
  - 즉 당일 장전/장중 자동 기동을 담당하던 watchdog이 WSL 정본 기준으로 살아 있었다는 증거가 없다.
- startup launcher:
  - 현재 `./scripts/get_runtime_startup_launcher_status.sh` 결과는 `installed=false`다.
  - `systemctl --user is-enabled stock-runtime-autoboot.service` 결과도 `not-found`다.
  - 반면 오래된 `runtime-data/reports/recovery/latest-local-setup-check.json`에는 Windows 시작프로그램 런처가 `D:\GitHub\Real-time-stock-price-prediction-program`을 가리키던 기록이 남아 있다.
- 판단:
  - 5/7 장중 공백의 1차 원인은 WSL 정본 저장소 기준 watchdog/autoboot가 장전부터 자동 시작되지 않은 것이다.
  - 저장소 이전 뒤 자동 시작 경로가 WSL 정본으로 재설치되지 않았고, 예전 D드라이브 런처 기록이 남아 있어 장전 자동 기동이 정본 DB에 도달하지 못한 것으로 본다.
  - 다음 실질 조치는 WSL 정본을 대상으로 한 Windows 로그인 시작 런처 또는 WSL systemd user service를 설치/검증하는 것이다. OS 시작프로그램 변경이므로 별도 실행 전에 사용자 승인 또는 명시 지시가 필요하다.

## [2026-05-07 20:30] 정본 게이트 기준 walk-forward와 장중 수집 공백 점검

- Cowork 검토 내용을 WSL2 정본 저장소 기준으로 재확인했다.
- 정본 gate reference:
  - 파일: `runtime-data/reports/backtests/latest-walk-forward-h15.json`
  - 평가 시각: `2026-05-06T20:08:51.772212+09:00`
  - 설정: `min_train_rows=30`, `test_window_rows=10`, `step_rows=10`, `gap_rows=15`, `max_train_rows=200`
  - 결과: `folds=33284`, `rows_evaluated=332840`, `trades_taken=111223`, `overall_accuracy=0.380246`, `trade_hit_rate=0.104502`, `cumulative_net_return_pct=-10411.176412`
  - 판단: 이 파일은 5년치 데이터 승격 판단용으로 학습창과 fold 구성이 너무 작다. 게이트 미통과 자체는 맞지만, 실패 사유를 단순 정확도 부족으로만 보면 다음 조치가 흐려진다.
- challenger 정본 리포트:
  - 변경 전 `2026-05-06T20:09:21.396280+09:00` 리포트에서는 `latest_lightgbm` accuracy `0.921672`, net `+2026.652123`처럼 walk-forward와 격차가 큰 수치가 있어 승격 근거로 쓰지 않고 평가 편향/누수 의심 대상으로 기록했다.
  - 변경 후 `python -m app --run-challengers --horizon-min 15` 재실행으로 `2026-05-07T20:30:09.309909+09:00` 리포트를 갱신했다.
  - 최신 best candidate 는 `linear_score_builtin`이고 accuracy `0.510456`, trade_hit_rate `0.491738`, net `+359.201116`, trades `1755`다.
  - 최신 `latest_lightgbm`은 accuracy `0.534479`, trade_hit_rate `0.244785`, net `-723.208906`, trades `18265`다.
  - 권장 조치는 `review_required`이며, 사유는 `Walk-forward setup needs review (...)`로 바뀌었다.
- 장중 수집 공백:
  - 정본 DB의 `2026-05-07` 분봉/특징은 `15:17:00`~`15:18:00` 20건뿐이다.
  - 해당 구간 label `0`건은 15분 horizon이 장마감 이후로 넘어가므로 정상적으로 닫히지 않는 구조다.
  - 문제는 label 계산이 아니라 09:00~15:16 live runtime 공백이다.
- 코드 반영:
  - challenger gate 판정에 walk-forward 설정 점검을 추가했다. `min_train_rows < 1000`, `test_window_rows < 100`, `max_train_rows < 1000`, `folds > 5000`이면 gate 통과 전에 `needs_review` 사유로 표시한다. 기존 gate 기준을 완화하지 않는다.
  - 대시보드 `머신러닝 현황 > 현재 운용`에 `게이트 기준 워크포워드` 카드를 추가해 정본 gate reference와 D드라이브 post-close snapshot 산출물을 분리 표시한다.
- 검증:
  - `python -m py_compile app/services/research.py app/services/dashboard.py`: 통과
  - `python -m unittest tests.test_dashboard`: 13개 통과
  - `python -m unittest tests.test_research_pipeline`: 3개 통과
  - `python -m app --run-challengers --horizon-min 15`: 통과
  - `python -m app --build-dashboard`: 통과, 생성 시각 `2026-05-07T20:33:54.440248+09:00`

## [2026-05-07 19:28] post-close snapshot ML 완료와 wide walk-forward 재측정

- post-close ML maintenance:
  - 상태: `ok`
  - 완료 시각: `2026-05-07 19:14:42 +0900`
  - snapshot DB: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-snapshots/post-close-h15-20260507-165315.db`
  - snapshot runtime: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-runs/post-close-20260507-h15/runtime-data`
- 대시보드:
  - `python -m app --build-dashboard`: 통과
  - 생성 시각: `2026-05-07T19:21:42.344608+09:00`
  - `머신러닝 현황 > 현재 운용 > 장후 자동 학습 상태` 카드에서 `status=ok`와 snapshot 경로 표시 확인.
- snapshot 데이터 진단:
  - raw market ticks: `2,194,180`, 범위 `2026-04-28T09:01:41+09:00` ~ `2026-05-07T15:19:28+09:00`
  - raw orderbook ticks: `1,703,559`, 범위 `2026-04-28T09:01:41+09:00` ~ `2026-05-07T15:29:38+09:00`
  - curated minute bars/features: `10,655`, 범위 `2026-04-28T09:01:00+09:00` ~ `2026-05-07T15:18:00+09:00`
  - 15분 labels: `10,246`, 범위 `2026-04-28T09:01:00+09:00` ~ `2026-05-04T14:46:00+09:00`
  - 60분 labels: `9,016`, 범위 `2026-04-28T09:01:00+09:00` ~ `2026-05-04T14:01:00+09:00`
  - `2026-05-07`은 15:17~15:18의 20개 분봉만 있어 아직 15분 라벨로 닫히지 않았다.
- post-close 기본 결과:
  - LightGBM validation accuracy: `0.350991`
  - LightGBM validation trades: `37`
  - LightGBM validation trade_hit_rate: `0.081081`
  - LightGBM validation cumulative_net_return_pct: `-6.839696`
  - fresh_centroid validation cumulative_net_return_pct: `+8.118964`
  - 기본 walk-forward는 `min_train_rows=30`, `max_train_rows=40`라 실제 승격 판단용으로는 학습창이 너무 작다.
- 추가 실험: wide walk-forward sanity
  - 실행 DB: 위 snapshot DB
  - 출력 runtime: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-runs/post-close-20260507-h15-wide-wf/runtime-data`
  - 설정: `min_train_rows=3000`, `test_rows=500`, `step_rows=500`, `gap_rows=15`, `max_train_rows=8000`
  - 결과: `folds=14`, `rows_evaluated=7000`, `trades_taken=1495`, `overall_accuracy=0.266857`, `trade_hit_rate=0.138462`, `cumulative_net_return_pct=-262.298425`

판단: 오늘 post-close 실제 KIS 데이터 기반 모델은 승격하지 않는다. 더 현실적인 학습창에서는 손실이 확대되어, 현재 단계의 다음 개선 축은 파라미터 조정보다 장중 KIS 데이터 누적, 라벨 닫힘률 개선, 대시보드에 snapshot 실제 ML 지표를 별도 표시하는 쪽이다.

## [2026-05-07 17:20] 대시보드 장후 자동 학습 상태 표시

- 목적: 장중 수집과 분리된 장후 snapshot ML maintenance 가 실제로 돌고 있는지 대시보드에서 바로 확인할 수 있게 한다.
- 변경 파일:
  - `app/services/dashboard.py`
  - `tests/test_dashboard.py`
  - `README.md`
  - `docs/Current-Implementation.md`
  - `docs/STATUS.md`
  - `docs/logbook.md`
- 표시 위치:
  - 대시보드 `머신러닝 현황` 탭
  - `현재 운용` 하위 탭
  - `장후 자동 학습 상태` 카드
- 표시 항목:
  - 상태, 기준일, 시작/완료 시각, 실행 모드, 예측 수평선, 프로세스 ID
  - snapshot DB 경로, snapshot runtime 경로
  - stdout/stderr 로그 경로, 오류 메시지
- 모델 개선 병행:
  - 현재 watchdog 이 시작한 post-close snapshot 재학습이 백그라운드에서 진행 중이다.
  - 무거운 학습을 중복 실행하지 않고, 완료 상태와 산출물 경로를 대시보드와 상태 파일에서 추적한다.
- 검증:
  - `python -m py_compile app/services/dashboard.py`: 통과
  - `python -m unittest tests.test_dashboard`: 13개 통과
  - `python -m unittest discover -s tests -p "test_*.py"`: 86개 통과
  - `git diff --check`: 통과
  - `python -m app --build-dashboard`: post-close snapshot 재학습이 진행 중이라 180초 제한 내 완료되지 않음. 재학습 완료 뒤 재시도 대상.

## [2026-05-07 16:50] 장마감 후 자동 snapshot ML maintenance 연결

- 목적: 사용자가 수동으로 학습을 실행하지 않아도, 장중 수집이 끝난 뒤 snapshot DB 기준으로 장후 학습/검증이 자동 실행되도록 한다.
- 변경 스크립트:
  - `scripts/script_dispatch.sh`
  - `scripts/wsl_ops.py`
- 동작 방식:
  - runtime watchdog 이 `post-close` 상태를 감지한다.
  - 장마감 후 기본 30분이 지나면 하루 한 번 `run_post_close_ml_maintenance.sh`를 백그라운드로 시작한다.
  - `run_post_close_ml_maintenance.sh`는 기본적으로 `runtime-data/dev.db`를 직접 학습하지 않고 snapshot DB를 만든 뒤, 그 snapshot DB를 `DATABASE_URL`로 지정해 `--rebuild-actual-ml`, runtime report, dashboard build 를 실행한다.
  - main 상태 파일은 `runtime-data/reports/ml-maintenance/state/latest-post-close-ml.json`에 남긴다.
  - 자동 active model 교체와 실전 주문 승격은 하지 않는다.
- 검증:
  - `python -m py_compile scripts/wsl_ops.py`: 통과
  - `bash -n scripts/script_dispatch.sh`: 통과
  - `bash -n scripts/run_post_close_ml_maintenance.sh`: 통과
  - `run-watchdog-loop --single-pass --disable-post-close-ml`: 통과
  - `python -m unittest discover -s tests -p "test_*.py"`: 86개 통과

판단: 사용자가 직접 실행해야 하는 작업은 Cybos Plus 로그인/Windows COM 수집처럼 Codex가 대신할 수 없는 작업으로 제한하고, 일반 장후 학습은 watchdog 자동화에 맡긴다.

## [2026-05-07 16:20] 투트랙 장중 수집 + 연구 운영 구조

- 목적: 장중 KIS live runtime 이 쓰는 `runtime-data/dev.db`와 오프라인 ML/룰 실험의 DB 접근을 분리해, 수집 누락과 SQLite lock 위험을 줄인다.
- 추가 스크립트:
  - `scripts/create_research_db_snapshot.sh`
  - `scripts/run_research_on_snapshot.sh`
- 운영 방식:
  - 수집 트랙: live runtime/watchdog 이 기존 `runtime-data/dev.db`를 계속 쓴다.
  - 연구 트랙: SQLite backup API로 만든 snapshot DB를 `DATABASE_URL`로 지정하고 실험을 실행한다.
  - 기본 D드라이브 경로: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-snapshots/`
  - 연구 산출물 기본 경로: `/mnt/d/CodexData/Real-time-stock-price-prediction-program/research-runs/`
- 사용 예:
  ```bash
  ./scripts/run_research_on_snapshot.sh -- \
    python -m app --run-cybos-rule-challengers --cybos-profitability-cost-pct 0.13
  ```
- 검증:
  - `bash -n scripts/create_research_db_snapshot.sh`: 통과
  - `bash -n scripts/run_research_on_snapshot.sh`: 통과
  - `.tmp-tests/two-track/live.db` smoke snapshot: 통과
  - `run_research_on_snapshot.sh` 환경 주입 smoke test: 통과

판단: 장중 수집을 계속 켠 상태에서 연구/학습은 스냅샷 기준으로 실행하는 투트랙 구조를 기본 운영 방향으로 둔다. 실전 주문 승격은 여전히 별도 승인 대상이다.

## [2026-05-07 15:30] G-1 Cybos 룰 기반 challenger 진단

- 목적: Cybos 15분 bar-only ML의 threshold 튜닝 우선순위를 낮추고, 해석 가능한 고정 long-only 룰 후보가 비용을 넘는지 확인했다.
- 실행 명령: `python -m app --run-cybos-rule-challengers --cybos-profitability-cost-pct 0.13`
- 실행 리포트: `runtime-data/reports/backtests/latest-cybos-rule-challengers-review.{json,md}`
- 공통 설정: `source=cybos-historical`, horizon `15`, feature set `bar_context_momentum`, 비용 `0.13%`, fold `42`, test rows `84,000`.
- 정책: 최고 룰을 자동 채택하거나 active 전략으로 승격하지 않는다.

| rank | strategy | trades | trade_hit_rate | win_rate | 비용 반영 net pct | profit_factor | max_drawdown_pct |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | `quiet_breakout` | 669 | 0.070254 | 0.215247 | -106.838776 | 0.198372 | -107.104815 |
| 2 | `opening_momentum` | 1,884 | 0.242569 | 0.376327 | -201.657683 | 0.677301 | -201.657683 |
| 3 | `pullback_bounce` | 6,144 | 0.148438 | 0.304688 | -855.823355 | 0.438917 | -861.622012 |
| 4 | `momentum_follow` | 8,607 | 0.149065 | 0.306379 | -1174.643028 | 0.455382 | -1175.108130 |
| 5 | `range_expansion` | 11,810 | 0.168417 | 0.317866 | -1642.290757 | 0.490418 | -1645.177930 |

판단: 고정 룰 challenger 5개 모두 비용 반영 수익이 음수다. 현재 룰 후보는 승격하지 않고, 다음 후보는 KIS 호가 데이터 누적 기반 피처 검증 또는 더 엄격한 기간 분리/시장상태 기준을 별도 실험으로 설계한다.

장중 수집 상태: `2026-05-07 15:17`에 현재 WSL2 저장소 기준으로 live runtime/watchdog을 재기동했고 KIS WebSocket 연결 로그를 확인했다. 이후 `15:30` 장마감으로 `post-close`가 되어 watchdog은 live runtime을 다시 켜지 않는 상태가 정상이다.

## [2026-05-07 14:54] F-6b threshold 0.20 재현성 검증

- 목적: F-6에서 유일하게 양수였던 `threshold=0.20`을 채택하지 않고, 다른 fold 설계와 기간 샘플에서도 재현되는지 확인했다.
- 실행 리포트: `runtime-data/reports/backtests/latest-cybos-label-reproducibility-review.{json,md}`
- 공통 설정: `source=cybos-historical`, `feature_set=bar_only`, `threshold=0.20`, `min_signal_confidence=0.58`, 비용 `0.13%`.
- 정책: 양수가 나와도 threshold를 자동 채택하지 않는다.

### fold 설계 변경

| 설계 | folds | trades | trade_hit_rate | 비용 반영 net pct | 판단 |
|---|---:|---:|---:|---:|---|
| `f6_baseline` | 42 | 44 | 0.545455 | 3.577014 | 양수 |
| `denser_step` | 50 | 46 | 0.565217 | 3.706487 | 양수 |
| `shorter_train` | 43 | 109 | 0.339450 | -11.557602 | 음수 |

### 기간 샘플 분리

| 기간 샘플 | selected rows | folds | trades | trade_hit_rate | 비용 반영 net pct | 판단 |
|---|---:|---:|---:|---:|---:|---|
| `early_2021_2023_sample` | 250,000 | 10 | 78 | 0.269231 | -5.929057 | 음수 |
| `recent_2024_2026_sample` | 250,000 | 10 | 70 | 0.442857 | -2.350204 | 음수 |

거래 원장 참고:

| 항목 | 값 |
|---|---:|
| baseline trades | 44 |
| baseline net pct | 3.577014 |
| 맞춘 거래 평균 gross | 0.754928 |
| 틀린 거래 평균 gross | -0.441063 |

판단: 일부 fold 설계에서만 양수이고, 학습창 축소와 기간 샘플 분리에서는 음수다. `threshold=0.20`은 재현성이 부족하므로 채택하지 않는다.

다음 연결점: Cybos 15분 bar-only ML의 threshold 튜닝은 우선순위를 낮춘다. 다음 실험은 룰 기반 challenger 또는 KIS 호가 데이터 누적 후 호가 피처 검증으로 분리한다.

## [2026-05-07 14:08] F-6 라벨 민감도 진단

- 목적: threshold를 고르는 실험이 아니라, 15분 bar-only ML이 비용을 넘는 움직임을 구조적으로 학습하는지 확인했다.
- 실행 리포트: `runtime-data/reports/backtests/latest-cybos-label-sensitivity-review.{json,md}`
- 사전 확인: 실제 로딩된 `label_threshold_15`는 `0.35%`이고, 요청 비용 기준 왕복 `0.13%`보다 높다. 따라서 현재 설정만 놓고는 "맞혀도 비용을 못 넘는 라벨" 구조라고 보기는 어렵다.
- 공통 설정: `source=cybos-historical`, `feature_set=bar_only`, `train_rows=100000`, `test_rows=2000`, `step_rows=30000`, `gap_rows=15`, `max_folds=50`, `min_signal_confidence=0.58`, 비용 `0.13%`.
- 정책: 결과가 좋은 threshold를 자동 채택하지 않는다. 이 결과는 민감도 진단용이다.

| threshold | 현재값 | up labels | down labels | trades | trade_hit_rate | 비용 반영 net pct | 신뢰 |
|---:|:---:|---:|---:|---:|---:|---:|---|
| 0.13 |  | 1,857,896 | 1,969,099 | 25 | 0.480000 | -1.724058 | 신뢰 낮음 |
| 0.20 |  | 1,389,326 | 1,457,173 | 44 | 0.545455 | 3.577014 | 기록 가능 |
| 0.35 | yes | 797,794 | 805,811 | 57 | 0.333333 | -1.413583 | 기록 가능 |
| 0.50 |  | 439,288 | 419,414 | 77 | 0.181818 | -18.729151 | 기록 가능 |

판단: `0.20`만 비용 반영 양수이고 나머지는 음수다. 여러 threshold에서 일관되게 양수가 나온 것이 아니므로 threshold를 채택하지 않는다. 결론은 `채택 보류, 과최적화 의심`이다.

다음 연결점: `0.20`은 후속 검증 후보가 아니라 과최적화 의심 관찰값으로만 둔다. 바로 승격하지 말고, 별도 기간/다른 fold 설계 또는 룰 기반 challenger와 비교하는 검증으로 분리한다.

## [2026-05-07 12:41] F-5 손익 진단 + 비용 기준선 + train-only threshold + 60분 horizon

- 상황: F-5가 기본 비용 기준으로 손익분기 근처였는지, 비용 반영 후에도 의미가 있는지 확인하기 위해 원장 기반 진단을 재실행했다.
- 실행 리포트: `runtime-data/reports/backtests/latest-cybos-profitability-review.{json,md}`
- 공통 설정: `source=cybos-historical`, `feature_set=bar_only`, `train_rows=100000`, `test_rows=2000`, `step_rows=30000`, `gap_rows=15`, `max_folds=50`, `min_signal_confidence=0.58`
- 비용 기준: 수수료 편도 0.015% + 슬리피지 편도 0.05%, 왕복 0.13%. 세금은 이번 비용 기준에서 제외하고 후속 보수 시나리오로 둔다.

### 1단계. F-5 손익 진단

| 지표 | 값 |
|---|---:|
| folds | 42 |
| rows_evaluated | 84,000 |
| trades_taken | 57 |
| overall_accuracy | 0.580310 |
| trade_hit_rate | 0.333333 |
| win_rate | 0.438596 |
| cumulative_gross_return_pct | 5.996417 |
| cumulative_net_return_pct @ 기존 비용 0.108% | -0.159583 |
| cumulative_net_return_pct @ 비용 0.13% | -1.413583 |

손익 분해:

| 항목 | 관찰 |
|---|---|
| 맞춘 거래 평균 gross | 0.801686% |
| 틀린 거래 평균 gross | -0.243043% |
| 시간대 | 09시 `+2.025118%`, 13시 `+1.026586%`는 양수지만 10시 `-2.717397%`, 11시 `-0.764369%`, 15시 `-0.758251%`가 손실을 키움 |
| confidence 구간 | `0.58-0.60`만 `+2.395907%`, `0.60-0.65`는 `-2.441334%`, `0.70-0.75`도 `-1.016512%` |
| up 예측 전체 | 16,511건, 평균 future return `+0.037929%` |
| down 예측 전체 | 17,845건, 평균 future return `+0.005615%`로 방향성 분리 실패 |

구조적 문제 가설: F-5 손실은 소수 거래와 비용 민감도가 핵심이며, confidence가 수익 거래를 안정적으로 분리하지 못한다.

주의: 위 시간대/종목/구간 결과는 손실 원인 진단용이며, 해당 구간을 수동으로 제외하는 필터는 만들지 않았다.

### 2단계. 거래비용 포함 기준선

| 비용 기준 | cumulative_net_return_pct |
|---|---:|
| 기존 코드 비용 0.108% | -0.159583 |
| 요청 비용 0.13% | -1.413583 |

판단: F-5는 비용 없는 gross 기준으로는 양수지만, 보수 비용 기준에서는 명확히 음수다. 실전 기준선은 `-1.413583%`로 본다.

### 3단계. train-only confidence threshold

threshold 후보는 사전 고정 grid `[0.58, 0.60, 0.62, 0.64, 0.66, 0.68, 0.70, 0.75, 0.80]`를 사용했다. 각 fold의 train calibration 구간에서 비용 반영 net return 기준으로 threshold를 선택하고 test에만 적용했다.

| 지표 | 값 |
|---|---:|
| folds | 42 |
| trades_taken | 55 |
| overall_accuracy | 0.580310 |
| trade_hit_rate | 0.327273 |
| cumulative_net_return_pct @ 비용 0.13% | -2.295251 |

threshold 선택 분포:

| threshold | fold 수 |
|---:|---:|
| 0.58 | 40 |
| 0.60 | 1 |
| 0.62 | 1 |

판단: train-only threshold는 과최적화 방지 구조로 실행했지만, F-5 비용 기준선보다 악화됐다. confidence threshold만으로는 손익 전환이 어렵다.

### 4단계. 60분 horizon 전환

F-5와 동일하게 Cybos bar-only, class_weight=balanced, 일봉 split 계열 설정을 유지하고 horizon만 60분으로 바꿨다.

| 구분 | validation | walk-forward |
|---|---:|---:|
| accuracy | 0.558385 | 0.587108 |
| trades_taken | 824 | 112 |
| trade_hit_rate | 0.234223 | 0.187500 |
| cumulative_net_return_pct @ 비용 0.13% | -27.818170 | -60.233578 |

H60 feature importance:

| rank | feature | importance |
|---:|---|---:|
| 1 | `avg_trade_size` | 4,105 |
| 2 | `hl_range_pct` | 3,759 |
| 3 | `return_1m_pct` | 3,401 |

최종 판단:

- F-5 기본 비용 결과는 재현됐지만 비용 0.13% 적용 시 실전 기준선은 음수다.
- train-only confidence threshold는 개선이 아니며, 수동 시간대/종목 필터는 과최적화 위험 때문에 적용하지 않았다.
- 60분 horizon은 hit-rate와 수익률 모두 악화되어 현재 bar-only 피처만으로는 대안이 아니다.
- 다음 실험은 단순 threshold 확대보다 새로운 정보가 있는 피처 또는 데이터 소스 품질 개선이 필요하다.

생성일: 2026-05-06
스프린트: 04 Cybos 실제 분봉 기준선

## 🔴 [2026-05-07 11:35] F-5 이후 수익 양수화 실험 — 3회 연속 비개선

- 상황: F-5에서 `trade_hit_rate=0.333333`으로 목표 hit-rate를 넘겼지만 walk-forward 순수익률이 `-0.159583%`로 소폭 음수였다. 수익 양수화를 목표로 추가 실험을 진행했다.
- 가져갈 파일: `docs/STATUS.md`, `docs/logbook.md`, `README.md`, `docs/Current-Implementation.md`
- 판단: F-6, F-7, F-8이 모두 F-5의 walk-forward 순수익률을 넘지 못했다. 완료 조건인 `trade_hit_rate >= 0.3`과 `cumulative_net_return_pct > 0`를 동시에 만족한 실험은 아직 없다.
- 최종 조치: `3회 연속 개선 없음` 조건에 따라 자율 진행을 중단하고 운영자 판단을 요청한다. 현재까지 최고 후보는 여전히 F-5다.

### 추가 실험 결과

| 실험 | 설정 | label_threshold_15 | train_rows | walk-forward accuracy | trades | trade_hit_rate | cumulative_net_return_pct | 판단 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| F-5 | `bar_only` | 0.35 | 100,000 | 0.580310 | 57 | 0.333333 | -0.159583 | 최고 후보, 손익분기 근접 |
| F-6 | `bar_only`, 학습창 확대 | 0.35 | 200,000 | 0.575893 | 24 | 0.208333 | -4.788923 | 악화 |
| F-7 | `bar_only`, 라벨 임계값 상향 | 0.40 | 100,000 | 0.615464 | 49 | 0.204082 | -8.857048 | 악화 |
| F-8 | `bar_only`, 라벨 임계값 하향 | 0.33 | 100,000 | 0.564798 | 60 | 0.383333 | -3.785540 | hit-rate 개선, 수익률 악화 |

### bar-context 피처 실험 참고

| 실험 | feature_set | train_rows | walk-forward accuracy | trades | trade_hit_rate | cumulative_net_return_pct | 판단 |
|---|---|---:|---:|---:|---:|---:|---|
| F-2 | `bar_context` | 20,000 | 0.559345 | 2,124 | 0.240113 | -84.717904 | F-1c 대비 악화 |
| F-3 | `bar_context_momentum` | 20,000 | 0.569643 | 2,054 | 0.255112 | -113.966154 | F-1c 대비 악화 |
| F-4 | `bar_only` | 50,000 | 0.575857 | 132 | 0.303030 | -16.066645 | hit-rate 목표 도달, 수익률 음수 |

### 해석

- bar-context 계열(`close_position_pct`, `minute_slot_pct`, `log_volume`, 직전 봉 피처)은 거래 수를 늘렸지만 hit-rate와 순수익률을 모두 악화시켰다.
- `bar_only`에서 학습창을 20,000 -> 50,000 -> 100,000으로 키우는 방향은 개선됐지만, 200,000까지 키우면 거래가 너무 줄고 hit-rate도 무너졌다.
- 라벨 임계값 상향 `0.40`은 전체 accuracy는 높였지만 거래 hit-rate와 수익률을 악화시켰다.
- 라벨 임계값 하향 `0.33`은 hit-rate를 높였지만 평균 수익이 비용을 넘지 못했다.

### 운영자 판단 필요

다음 중 하나를 선택해야 한다.

1. F-5를 현재 최고 연구 기준선으로 유지하고 다음 스프린트에서 거래 후처리/신뢰도 calibration을 별도 실험으로 분리한다.
2. 수익 양수화를 계속 목표로 하되, 현재 gate 기준 변경 없이 모델 확률 calibration 또는 fold별 regime 필터를 새 실험 범위로 승인한다.
3. 완료 조건을 hit-rate 중심으로 재정의할지 검토한다. 단, 현재 `cumulative_net_return_pct`는 아직 음수다.

## [2026-05-07 04:20] 실험 F-1 — Cybos 실제 분봉 bar-only 기준선

- 상황: `AGENTS.md`에 ML 실험 자율 범위를 추가한 뒤, Cybos 실제 15분봉 5년치 기준으로 LightGBM 기준선을 다시 측정했다.
- 가져갈 파일: `docs/STATUS.md`, `AGENTS.md`, `README.md`, `docs/Current-Implementation.md`, `docs/logbook.md`
- 판단: `source=cybos-historical`만 사용하고 `pykrx-daily-proxy`, `kis-ws`는 제외했다. Cybos 병합 데이터에는 과거 호가가 없으므로 `spread_bps`, `bid_ask_imbalance`, `mid_price`는 제외하고 bar-only 피처만 사용했다.
- 최종 조치: 자동 승격 금지 유지. 최고 결과인 F-1c도 walk-forward `trade_hit_rate=0.284987`, `cumulative_net_return_pct=-25.134498`로 완료 조건에는 못 미친다. 다만 F-1 -> F-1b -> F-1c 순서로 개선이 있어 `3회 연속 개선 없음` 보고 조건은 아니다.

### 데이터셋

| 항목 | 값 |
|---|---:|
| source | `cybos-historical` |
| symbols | 199 |
| trade_dates | 1,249 |
| source_rows | 6,283,279 |
| labeled_rows | 6,040,981 |
| 기간 | `2021-03-30T09:15:00+09:00..2026-05-04T15:15:00+09:00` |
| validation_start_date | `2025-04-23` |

라벨 분포:

| label | count | ratio |
|---|---:|---:|
| flat | 4,437,376 | 73.46% |
| down | 805,811 | 13.34% |
| up | 797,794 | 13.21% |

### 공통 설정

- 모델: LightGBM, `class_weight=balanced`
- split: 거래일 기준 tail 20% validation
- source filter: `cybos-historical` only
- 제외 source: `pykrx-daily-proxy`, `kis-ws`, `kis-rest-historical`, `synthetic`
- feature_names: `avg_trade_size`, `hl_range_pct`, `return_1m_pct`
- 제외 feature: `mid_price`, `spread_bps`, `bid_ask_imbalance`
- gate/risk 기준: 변경 없음

### 실행 결과

| 실험 | train_rows | validation_accuracy | validation trades | validation trade_hit_rate | validation net pct | walk-forward overall_accuracy | walk-forward trades | walk-forward trade_hit_rate | walk-forward net pct |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| F-1 | 2,000 | 0.473329 | 51,992 | 0.180105 | -4,737.492793 | 0.546787 | 10,417 | 0.217913 | -1,041.554842 |
| F-1b | 10,000 | 0.487424 | 15,344 | 0.229797 | -1,333.702180 | 0.563363 | 1,161 | 0.282515 | -27.799564 |
| F-1c | 20,000 | 0.506736 | 18,541 | 0.233698 | -1,122.516600 | 0.576262 | 393 | 0.284987 | -25.134498 |

F-1c feature importance:

| rank | feature | importance |
|---:|---|---:|
| 1 | `avg_trade_size` | 2,795 |
| 2 | `hl_range_pct` | 2,401 |
| 3 | `return_1m_pct` | 2,015 |

판단 기준 대비:

- validation accuracy는 `0.6 이하`로 내려와 proxy 누수성 과대평가가 해소된 상태로 본다.
- walk-forward `trade_hit_rate`는 최고 `0.284987`로 `0.3` 기준에 아직 못 미친다.
- walk-forward 누적 순수익률은 최고 `-25.134498%`로 아직 음수다.
- 다음 자율 실험 방향은 데이터 소스나 risk/gate 변경 없이 bar-context 피처를 추가하는 것이다. 후보는 `close_position_pct`, `minute_slot`, `log_volume` 중심이다.

실행 명령:

```bash
python -m app --run-cybos-bar-only-experiment --horizon-min 15 \
  --cybos-experiment-train-max-rows 2000 \
  --cybos-experiment-walk-test-rows 2000 \
  --cybos-experiment-walk-step-rows 10000 \
  --cybos-experiment-walk-gap-rows 15 \
  --cybos-experiment-walk-max-folds 120

python -m app --run-cybos-bar-only-experiment --horizon-min 15 \
  --cybos-experiment-train-max-rows 10000 \
  --cybos-experiment-walk-test-rows 2000 \
  --cybos-experiment-walk-step-rows 20000 \
  --cybos-experiment-walk-gap-rows 15 \
  --cybos-experiment-walk-max-folds 80

python -m app --run-cybos-bar-only-experiment --horizon-min 15 \
  --cybos-experiment-train-max-rows 20000 \
  --cybos-experiment-walk-test-rows 2000 \
  --cybos-experiment-walk-step-rows 30000 \
  --cybos-experiment-walk-gap-rows 15 \
  --cybos-experiment-walk-max-folds 50
```

산출물:

- `runtime-data/reports/backtests/latest-cybos-bar-only-f1-h15.json`
- `runtime-data/reports/backtests/latest-cybos-bar-only-f1-h15.md`
- `runtime-data/ml/models/lightgbm-cybos-bar-only-h15-v1.joblib`

## 🔴 [2026-05-07 02:55] 스프린트 04 재시작 — Cybos 병합 데이터 사전 확인

- 상황: Cybos 5년치 실제 15분봉 병합 완료 후 실험 F를 새 데이터 기준으로 재시작하려 했다.
- 가져갈 파일: `docs/STATUS.md`
- 판단: Cybos 분봉 자체는 main DB에 199종목 6,283,279행으로 병합됐지만, `raw_orderbook_ticks`에는 `source=cybos-historical` 행이 0개다. 따라서 `spread_bps`, `bid_ask_imbalance`를 Cybos 실제 호가 피처로 포함하는 실험 F 조건은 현재 DB로 충족되지 않는다.
- 최종 조치: `python -m app --build-feature-dataset`까지 실행하고, 학습/챌린저/walk-forward는 실행하지 않았다. 이 상태에서 학습하면 새 Cybos 실제 호가 기준선이 아니라 pykrx proxy 호가가 섞인 기준선이 된다.

### 사전 확인 1. source별 raw row 수

| source | symbol 수 | raw_market_ticks row | 기간 |
|---|---:|---:|---|
| `cybos-historical` | 199 | 6,283,279 | `2021-03-30T09:15:00+09:00..2026-05-04T15:30:00+09:00` |
| `kis-ws` | 10 | 3,054,451 | `2026-04-28T09:00:13+09:00..2026-05-06T13:41:25+09:00` |
| `kis-rest-historical` | 10 | 4,200 | `2026-05-04T15:02:00+09:00..2026-05-06T15:30:00+09:00` |

호가 원천 확인:

| source | raw_orderbook_ticks row | 판단 |
|---|---:|---|
| `cybos-historical` | 0 | Cybos 실제 호가 피처 없음 |
| `kis-ws` | 2,245,513 | 실제 WebSocket 호가 |
| `pykrx-daily-proxy` | 332,228 | proxy 호가 |

### 사전 확인 2. 피처/라벨 재생성

실행 명령:

```bash
python -m app --build-feature-dataset
```

결과:

| 항목 | 값 |
|---|---:|
| features_written | 356,970 |
| labels_written | 647,510 |
| horizons | 15, 60 |
| feature symbols | 10 |
| feature range | `2021-01-04T09:00:00+09:00..2026-05-06T15:30:00+09:00` |

15분 라벨 기준 학습 가능 row:

| 기준 | row |
|---|---:|
| 전체 H15 labeled feature row | 343,807 |
| `cybos-historical` market source가 붙은 row | 243,993 |
| `kis-ws` market source가 붙은 row | 9,519 |
| `kis-ws` orderbook source가 붙은 row | 12,399 |
| `pykrx-daily-proxy` orderbook source가 붙은 row | 329,227 |

주의: `cybos-historical` market source row는 실제 Cybos 분봉 가격을 쓰지만, 같은 시각의 호가 source는 대부분 `pykrx-daily-proxy`다. 따라서 이 row에서 `spread_bps`, `bid_ask_imbalance`를 포함하면 Cybos 실제 호가가 아니라 proxy 호가를 학습하게 된다.

### 라벨 분포

전체 H15 labeled feature row 기준:

| label | count | ratio |
|---|---:|---:|
| flat | 258,339 | 75.14% |
| up | 42,591 | 12.39% |
| down | 42,877 | 12.47% |

`cybos-historical` market source row 기준:

| label | count | ratio |
|---|---:|---:|
| flat | 193,636 | 79.36% |
| up | 25,221 | 10.34% |
| down | 25,136 | 10.30% |

### 실험 F 상태

실험 F는 실행하지 않았다.

이유:

- 요구 조건은 `spread_bps`, `bid_ask_imbalance`를 Cybos 실제 호가 피처로 포함하는 것이다.
- 현재 Cybos 병합 데이터에는 실제 호가 테이블인 `raw_orderbook_ticks`의 `cybos-historical` 행이 없다.
- 현재 학습 로더를 그대로 쓰면 proxy row가 포함된 학습셋으로 판단되어 `mid_price`, `spread_bps`, `bid_ask_imbalance`가 제외된다.
- 반대로 제외 로직을 억지로 풀면 Cybos 실제 호가가 아니라 pykrx proxy 호가를 실제 호가처럼 학습하게 된다.

다음 선택지는 둘 중 하나다.

1. Cybos에서 과거 호가를 별도로 수집할 수 있는 TR을 찾아 `raw_orderbook_ticks source=cybos-historical`를 실제로 채운 뒤 실험 F를 재실행한다.
2. 실험 F를 “Cybos 실제 분봉 bar-only 기준선”으로 재정의하고, 피처를 `avg_trade_size`, `hl_range_pct`, `return_1m_pct` 중심으로 학습한다. 이 경우 `spread_bps`, `bid_ask_imbalance`는 포함하지 않는다.

## 🔴 [2026-05-06 20:10] 실험 E — 일봉 단위 train/validation split

- 상황: 실험 B/D에서 `mid_price`를 제거하고 horizon purge를 적용해도 validation_accuracy가 `0.911793`으로 유지됐다. 이번 실험은 같은 거래일의 proxy 15분 봉이 train과 validation에 동시에 들어가는 문제를 차단하기 위해 날짜 단위 80/20 split을 적용했다.
- 가져갈 파일: `docs/STATUS.md`
- 판단: validation_accuracy가 `0.921672`로 유지되어, 기존 `0.912`가 단순히 같은 날짜 train/validation 혼입 때문이었다는 가설은 확인되지 않았다. 다만 walk-forward는 여전히 실패권이므로 proxy 15분 라벨/보간 규칙 자체의 암기 가능성은 계속 높다.
- 최종 조치: 자동 승격 금지 유지. active model은 `baseline-h15-v1` 그대로 유지.

### 변경 내용

- `app/services/research.py`의 train/validation split을 행 단위 tail 80/20에서 거래일 단위 tail 80/20로 변경했다.
- 같은 날짜의 모든 row는 train 또는 validation 중 한쪽에만 들어간다.
- horizon purge는 유지한다. validation 시작 시각 기준으로 `train.event_time + horizon < validation_start_time`을 만족하지 않는 train row를 제거한다.
- 작은 synthetic fixture에서 날짜 split 또는 purge 후 `down/flat/up` 라벨 구성이 깨질 때만 기존 row-level split을 fallback으로 사용한다.
- 피처는 실험 B/D 상태 그대로 유지했다. `mid_price`, `spread_bps`, `bid_ask_imbalance`는 proxy 포함 학습셋 feature list에서 제외된다.

### split 확인

| 항목 | 값 |
|---|---:|
| split method | `trade_date_tail_20pct` |
| feature_names | `avg_trade_size`, `hl_range_pct`, `return_1m_pct` |
| total labeled rows | 332,892 |
| train_rows | 254,350 |
| validation_rows | 78,542 |
| train_date_count | 1,047 |
| validation_date_count | 262 |
| last_train_date | `2025-04-08` |
| first_validation_date | `2025-04-09` |
| last_train_event_time | `2025-04-08T15:00:00+09:00` |
| first_validation_event_time | `2025-04-09T09:00:00+09:00` |
| train/validation date overlap | 0 |

### 실험 E 실행 결과

실행 명령:

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m app --train-lightgbm --horizon-min 15
python -m app --run-challengers --horizon-min 15
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 200
python -m app --run-challengers --horizon-min 15
```

학습 설정:

| 항목 | 값 |
|---|---:|
| training_run_id | `train-lightgbm-h15-20260506200645749446` |
| train_rows | 254,350 |
| validation_rows | 78,542 |
| validation_accuracy | 0.921672 |
| proxy_rows | 318,683 |
| source_counts | `pykrx-daily-proxy=318683`, `kis-ws=12388`, `unknown=1192`, `kis-rest-historical=554`, `synthetic=75` |

라벨 분포:

| 기준 | down | flat | up |
|---|---:|---:|---:|
| validation actual label | 7,311 | 63,643 | 7,588 |
| LightGBM validation predicted label | 6,231 | 65,923 | 6,388 |
| walk-forward actual label | 22,640 | 286,541 | 23,659 |
| walk-forward predicted label | 107,264 | 110,316 | 115,260 |

주요 결과:

| 지표 | LightGBM validation/challenger | Walk-forward |
|---|---:|---:|
| trades_taken | 5,911 | 111,223 |
| validation_accuracy / overall_accuracy | 0.921672 | 0.380246 |
| cumulative_net_return_pct | 2,026.652123 | -10,411.176412 |
| trade_hit_rate | 0.870919 | 0.104502 |
| win_rate | 0.889359 | 0.341638 |

실험 누적표:

| 실험 | split | feature_names | validation_accuracy | walk-forward overall_accuracy | walk-forward trade_hit_rate | walk-forward cumulative_net_return_pct | walk-forward trades_taken | 판단 |
|---|---|---|---:|---:|---:|---:|---:|---|
| C-1 | row tail 80/20 | `avg_trade_size`, `hl_range_pct`, `mid_price`, `return_1m_pct` | 0.911699 | 0.412748 | 0.101259 | -10,384.138893 | 104,327 | validation 과대, gate 실패 |
| B/D | row tail 80/20 + purge | `avg_trade_size`, `hl_range_pct`, `return_1m_pct` | 0.911793 | 0.380246 | 0.104502 | -10,411.176412 | 111,223 | `mid_price` 단독 누수 아님 |
| E | date tail 80/20 + purge | `avg_trade_size`, `hl_range_pct`, `return_1m_pct` | 0.921672 | 0.380246 | 0.104502 | -10,411.176412 | 111,223 | 같은 날짜 혼입 누수만으로 설명 안 됨 |

판단 기준 대비:

- `validation_accuracy`가 `0.7 이하`로 떨어지지 않았다. 따라서 기존 `0.912`가 같은 날짜 proxy 봉 혼입 때문이었다는 판단은 확인되지 않았다.
- `walk-forward trade_hit_rate`는 `0.104502`로 `0.3` 기준에 못 미친다. 실전 방향성 개선은 확인되지 않았다.
- 다음 단계는 proxy 15분 라벨을 학습/validation에서 제외하거나, proxy는 일봉 라벨용으로만 쓰고 실제 KIS 분봉만 15분 라벨 검증에 쓰는 방향이 더 타당하다.

Challenger 최종 판단:

- best_candidate: `latest_lightgbm`
- recommended_action: `review_required`
- recommended_model_version: `lightgbm-h15-v1`
- walk_forward_gate_status: `needs_review`
- reason: `Walk-forward overall accuracy is too low (0.3802).`
- active_model_version_after_run: `baseline-h15-v1`

검증:

- `python -m py_compile app/services/research.py`: 통과
- `python -m unittest discover -s tests -p "test_*.py"`: `Ran 85 tests in 11.904s`, `OK`

## 🔴 [2026-05-06 18:23] 긴급 누수 점검 — 실험 B/D(mid_price 제거)

- 상황: C-1에서 LightGBM validation `0.911699`와 walk-forward `0.412748`의 격차가 너무 커서, pykrx proxy 라벨 구조와 train/validation split 누수를 먼저 점검했다.
- 가져갈 파일: `docs/STATUS.md`
- 판단: `mid_price` 단독 누수가 주원인이라는 가설은 지지되지 않는다. `mid_price`를 제거하고 horizon purge를 적용해도 validation_accuracy는 `0.911793`으로 유지됐고, walk-forward는 `0.380246`으로 더 낮아졌다. 현재 1차 의심은 `pykrx-daily-proxy`의 같은 일봉 OHLC 보간 경로 자체와 그 경로에서 만든 15분 라벨이다.
- 최종 조치: 자동 승격 금지 유지. active model은 `baseline-h15-v1` 그대로 유지.

### 확인 1. pykrx proxy 라벨 생성 구조

구현 위치:

- `app/collectors/historical.py`
- `app/services/research.py`

확인 결과:

- `pykrx-daily-proxy`는 일봉 OHLCV 1개를 거래일당 26개 15분 봉으로 변환한다.
- 가격 anchor는 아래처럼 하루 전체 OHLC를 이미 알고 있는 상태에서 정한다.
  - 상승/보합일: index `0=open`, `6=low`, `18=high`, `25=close`
  - 하락일: index `0=open`, `6=high`, `18=low`, `25=close`
- 각 proxy bar의 close는 위 anchor 사이 선형 보간값이다.
- 라벨 생성은 현재 봉 `bar.close`와 `bar_time + horizon` 이후 같은 날짜 첫 future bar의 `future_bar.close` 차이로 `future_return_pct`를 만든다.
- 따라서 proxy 데이터의 15분 라벨은 대부분 같은 일봉 OHLC에서 보간된 현재 proxy close와 미래 proxy close의 차이다.

판단:

- 코드가 시간순 배열 밖의 임의 미래 row를 잘못 join하는 형태의 직접 누수는 아니다.
- 하지만 proxy의 하루 경로가 당일 OHLC를 모두 사용해 사후적으로 만들어지므로, 같은 일봉 안에서 만든 15분 라벨은 일봉 OHLC 패턴을 모델이 외우기 쉬운 구조다.
- 특히 `hl_range_pct`, `return_1m_pct`, `avg_trade_size`만 남긴 뒤에도 validation이 유지됐기 때문에, 누수성 신호가 특정 `mid_price` 하나에만 묶여 있지 않다.

### 확인 2. train/validation split horizon purge

확인 결과:

- 기존 `_split_dataset`은 시간순 80/20 tail split만 수행했고, train 마지막 row의 label horizon이 validation 시작 구간에 닿는지 제거하지 않았다.
- 이번 작업에서 `app/services/research.py`의 split을 아래 방식으로 보강했다.
  - validation 시작 시각과 같은 timestamp row는 모두 validation 쪽으로 보낸다.
  - `horizon_min > 0`이면 `train.event_time + horizon < validation_start_time`을 만족하지 않는 train row를 제거한다.
  - 아주 작은 synthetic test fixture에서 purge 후 `down/flat/up` 라벨 구성이 깨질 때만 기존 train split을 유지한다.
- 실제 5년치 학습 데이터에서는 purge가 적용됐고, split은 아래처럼 확인됐다.

| 항목 | 값 |
|---|---:|
| feature_names | `avg_trade_size`, `hl_range_pct`, `return_1m_pct` |
| total labeled rows | 332,892 |
| train_rows | 266,300 |
| validation_rows | 66,582 |
| train_end | `2025-06-20T13:45:00+09:00` |
| validation_start | `2025-06-20T14:15:00+09:00` |
| purge gap | 30분 |

### 확인 3. 실험 B/D — mid_price 제거 후 재학습

처리 방식:

- proxy 포함 학습셋에서는 기존 제외 피처 `spread_bps`, `bid_ask_imbalance`에 더해 `mid_price`도 학습 피처 목록에서 제외했다.
- 실험 B/D feature_names: `avg_trade_size`, `hl_range_pct`, `return_1m_pct`
- `source=kis-ws` row의 저장 피처는 수정하지 않았다. 학습 로더에서 proxy 포함 학습셋 feature list만 조정했다.

실행 명령:

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m app --train-lightgbm --horizon-min 15
python -m app --run-challengers --horizon-min 15
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 200
python -m app --run-challengers --horizon-min 15
```

학습 설정:

| 항목 | 값 |
|---|---:|
| training_run_id | `train-lightgbm-h15-20260506181808816399` |
| class_weight | `balanced` |
| train_rows | 266,300 |
| validation_rows | 66,582 |
| validation_accuracy | 0.911793 |
| proxy_rows | 318,683 |
| source_counts | `pykrx-daily-proxy=318683`, `kis-ws=12388`, `unknown=1192`, `kis-rest-historical=554`, `synthetic=75` |

라벨 분포:

| 기준 | down | flat | up |
|---|---:|---:|---:|
| validation actual label | 6,533 | 53,113 | 6,936 |
| LightGBM validation predicted label | 5,421 | 55,419 | 5,742 |
| walk-forward actual label | 22,640 | 286,541 | 23,659 |
| walk-forward predicted label | 107,264 | 110,316 | 115,260 |

주요 결과:

| 지표 | LightGBM validation/challenger | Walk-forward |
|---|---:|---:|
| trades_taken | 5,113 | 111,223 |
| validation_accuracy / overall_accuracy | 0.911793 | 0.380246 |
| cumulative_net_return_pct | 1,816.829656 | -10,411.176412 |
| trade_hit_rate | 0.889693 | 0.104502 |
| win_rate | 0.895951 | 0.341638 |

판단 기준 대비:

- `validation_accuracy`가 `0.912 → 0.6 이하`로 떨어지지 않았다. 따라서 `mid_price`가 누수의 주원인이라는 판단은 보류한다.
- `walk-forward trade_hit_rate`가 `0.3 이상`으로 오르지 않았다. 실제 결과는 `0.104502`로 C-1의 `0.101259`와 거의 같은 실패권이다.
- validation과 walk-forward 격차가 계속 크므로, 다음 실험은 proxy 15분 label 자체를 제거하거나 일봉 단위 split/검증으로 바꾸는 방향이 우선이다.

Challenger 최종 판단:

- best_candidate: `latest_lightgbm`
- recommended_action: `review_required`
- recommended_model_version: `lightgbm-h15-v1`
- walk_forward_gate_status: `needs_review`
- reason: `Walk-forward overall accuracy is too low (0.3802).`
- active_model_version_after_run: `baseline-h15-v1`

검증:

- `python -m py_compile app/services/research.py`: 통과
- `python -m unittest discover -s tests -p "test_*.py"`: `Ran 85 tests in 12.835s`, `OK`

## 🟠 [2026-05-06 17:24] 스프린트 04 — proxy 호가 피처 제외 + C-1 5년치 재실행

- 상황: 스프린트 03 품질 점검에서 `pykrx-daily-proxy`의 `spread_bps`, `bid_ask_imbalance`가 실제 KIS 호가와 의미가 다르다고 확인되어, proxy 포함 학습에서는 두 피처를 학습 피처 목록에서 제외했다.
- 가져갈 파일: `docs/STATUS.md`
- 판단: LightGBM C-1은 validation 기준으로 크게 개선됐지만, walk-forward gate는 아직 `needs_review`이므로 승격 금지 유지.

### 사전 작업. 호가 피처 제외 처리

- 구현 위치:
  - `app/services/research.py`
  - `app/storage/sqlite_store.py`
- 처리 방식:
  - `feature_model_inputs`의 저장된 `values_json`은 수정하지 않는다.
  - 학습 데이터 로더가 `raw_orderbook_ticks`/`raw_market_ticks`의 source를 함께 읽어 row source를 판정한다.
  - `pykrx-daily-proxy` row가 포함된 학습셋에서는 `spread_bps`, `bid_ask_imbalance`를 학습 feature_names에서 제외한다.
  - `mid_price`는 유지한다.
  - C-1 학습 feature_names: `avg_trade_size`, `hl_range_pct`, `mid_price`, `return_1m_pct`
- 성능 보강:
  - source lookup이 느려지지 않도록 `raw_market_ticks(symbol,event_time)`, `raw_orderbook_ticks(symbol,event_time)` index를 추가했다.
  - 33만 labeled row 로딩 확인: 약 `13.11s`
- 단위 테스트:
  - `python -m unittest discover -s tests -p "test_*.py"`
  - 결과: `Ran 85 tests in 13.796s`, `OK`

### 실험 C-1. class_weight=balanced 5년치 재실행

실행 명령:

```bash
python -m app --train-lightgbm --horizon-min 15
python -m app --run-challengers --horizon-min 15
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 200
python -m app --run-challengers --horizon-min 15
```

학습 설정:

| 항목 | 값 |
|---|---:|
| training_run_id | `train-lightgbm-h15-20260506171325113244` |
| class_weight | `balanced` |
| train_rows | 266,313 |
| validation_rows | 66,579 |
| validation_accuracy | 0.911699 |
| proxy_rows | 318,683 |
| source_counts | `pykrx-daily-proxy=318683`, `kis-ws=12401`, `synthetic=75`, `unknown=1733` |

라벨 분포:

| 기준 | down | flat | up |
|---|---:|---:|---:|
| 전체 actual label | 22,656 | 286,577 | 23,659 |
| validation actual label | 6,533 | 53,110 | 6,936 |
| LightGBM validation predicted label | 5,563 | 55,420 | 5,596 |
| walk-forward predicted label | 100,902 | 127,608 | 104,330 |

주요 결과:

| 지표 | LightGBM validation/challenger | Walk-forward |
|---|---:|---:|
| trades_taken | 5,328 | 104,327 |
| validation_accuracy / overall_accuracy | 0.911699 | 0.412748 |
| cumulative_net_return_pct | 1,807.293048 | -10,384.138893 |
| trade_hit_rate | 0.863176 | 0.101259 |
| win_rate | 0.877252 | 0.336260 |

Challenger 최종 판단:

- best_candidate: `latest_lightgbm`
- recommended_action: `review_required`
- recommended_model_version: `lightgbm-h15-v1`
- walk_forward_gate_status: `needs_review`
- reason: `Walk-forward overall accuracy is too low (0.4127).`
- active_model_version_after_run: `baseline-h15-v1`

### 병행 작업. KIS REST 1년치 실제 분봉 수집 코드

- 구현 위치:
  - `app/brokers/kis_quote_rest.py`
  - `app/collectors/historical.py`
  - `app/__main__.py`
- CLI:

```bash
python -m app --collect-kis-historical --start 2025-05-06 --end 2026-05-06
```

- TR: `FHKST03010200`
- source: `kis-rest-historical`
- 저장:
  - 기존 `curated_minute_bars`에 OHLCV upsert
  - 기존 `raw_market_ticks`에 close/volume tick을 `source=kis-rest-historical`로 적재
  - 기존 DB 테이블 구조는 변경하지 않음
- rate-limit 처리:
  - `EGW00201` 발생 시 backoff 재시도
  - 종목별 실패는 summary error로 기록하고 다음 종목 진행

실행 결과:

| 항목 | 값 |
|---|---:|
| requested_days | 366 |
| bars_written | 4,200 |
| raw_ticks_written | 4,200 |
| per-symbol records_written | 420 |
| earliest_bar_time | `2026-05-04T15:02:00+09:00` |
| latest_bar_time | `2026-05-06T15:30:00+09:00` |
| report | `runtime-data/reports/historical/latest-kis-rest-historical-collection.{json,md}` |

제한 사항:

- 공식 KIS 샘플 기준 `FHKST03010200`은 주식당일분봉조회 성격이며, 1회 최대 30건과 전일자 분봉 제한이 있다.
- 실제 실행에서는 요청 기간 366일 중 최근 일부 구간만 반환됐다. 따라서 1년 전체 실제 분봉 백필은 이 TR만으로는 완료되지 않았다.
- 다음 단계에서는 `FHKST03010200` 반복 조회 한계와 별개로, KIS가 제공하는 다른 장기 분봉 TR 또는 외부 실제 분봉 소스를 검토해야 한다.

## 🟠 [2026-05-06 16:18] 스프린트 04 전 점검 — pykrx 프록시 분봉 품질 확인

- 상황: 스프린트 03에서 적재한 `pykrx-daily-proxy` 15분 프록시 분봉이 실제 KIS WebSocket 기반 분봉과 같은 DB 구조로 들어가지만, 호가 기반 피처의 의미가 실제 호가와 크게 다르다.
- 가져갈 파일: `docs/STATUS.md`
- 판단: 스프린트 04 학습/검증에 프록시 데이터를 그대로 쓸 수는 있으나, `spread_bps`, `bid_ask_imbalance` 같은 호가 기반 피처는 source 별 분포 차이가 커서 별도 처리 필요.

### 확인 1. pykrx 프록시 분봉 구조

구현 위치: `app/collectors/historical.py`

- 거래일당 26개 봉을 만든다. `_market_times()`는 09:00부터 15분 간격으로 시각을 만들기 때문에 마지막 프록시 봉은 15:15다.
- 가격 경로는 일봉 OHLC를 선형 보간한다.
  - 상승일 또는 보합/상승일: index `0=open`, `6=low`, `18=high`, `25=close`
  - 하락일: index `0=open`, `6=high`, `18=low`, `25=close`
  - 각 봉의 open은 직전 프록시 close, close는 보간값이다.
  - high/low는 기본적으로 open/close 사이 값이며, 보간 close가 일봉 high/low anchor와 같을 때만 해당 일봉 high/low를 반영한다.
- 거래량은 전체 일봉 거래량을 U자형 가중치로 26개 봉에 나눈다. 장 초반과 장 후반에 더 큰 weight가 붙고, 마지막 봉에서 반올림 잔여량을 보정한다.
- 프록시 호가는 각 프록시 close 기준으로 `bid=close-tick`, `ask=close+tick`을 만들고, `bid_size=ask_size=max(1, volume//2)`로 채운다.
- 따라서 raw proxy orderbook 기준:
  - `mid_price`는 사실상 프록시 close와 같다.
  - `spread_bps`는 실제 호가 스프레드가 아니라 가격대별 tick size로 만든 기계적 값이다.
  - `bid_ask_imbalance`는 bid/ask size를 같게 넣기 때문에 항상 `0.0`이다.
- 구조 호환성: `MinuteBar`, `OrderbookSnapshot`, `curated_minute_bars`, `raw_orderbook_ticks`, `feature_model_inputs`, `feature_labels`를 그대로 쓰므로 KIS WebSocket 분봉과 스키마는 호환된다. 다만 실제 호가 압력, 체결 강도, 장중 변동 경로를 재현한 데이터는 아니다.

### 확인 2. KIS 실제 호가 vs pykrx 프록시 피처 분포

비교 기준 DB: `runtime-data/dev.db`

| 항목 | `kis-ws` | `pykrx-daily-proxy` |
|---|---:|---:|
| raw orderbook rows | 2,245,513 | 332,228 |
| raw 기간 | 2026-04-28 09:00 ~ 2026-05-06 13:41 | 2021-01-04 09:00 ~ 2026-05-06 15:15 |
| exact feature samples | 12,521 | 332,228 |
| proxy/KIS exact overlap minutes | - | 798 |

주요 feature 분포:

| feature | `kis-ws` median / mean | `pykrx-daily-proxy` median / mean | 판단 |
|---|---:|---:|---|
| `mid_price` | 221,250 / 478,689 | 172,500 / 295,257 | 기간과 종목 가격대 차이 영향이 커 직접 비교 지표로는 제한적 |
| `spread_bps` | 12.83 / 14.74 | 37.92 / 42.31 | 프록시가 실제보다 약 3배 높게 형성되어 분포 차이 큼 |
| `bid_ask_imbalance` | 0.0418 / 0.0337, p05=-0.8056, p95=0.8500 | 0.0 / 0.0, zero_ratio=100% | 프록시는 호가 불균형 정보가 완전히 사라짐 |

### 결론과 스프린트 04 권장 조치

- `pykrx-daily-proxy`는 5년치 가격/라벨 볼륨을 확보하는 목적에는 유효하다.
- 단, 실제 KIS WebSocket 기반 학습/추론과 같은 의미로 호가 피처를 쓰면 분포 이동이 크다.
- 스프린트 04에서는 아래 중 하나를 먼저 정해야 한다.
  1. proxy source 학습에서는 `spread_bps`, `bid_ask_imbalance`를 제외하거나 neutral 처리한다.
  2. feature에 `data_source` 또는 `is_proxy` 계열 구분값을 추가해 모델이 source 차이를 학습하게 한다.
  3. 실제 KIS 데이터만으로 짧은 기간 검증을 할 때와 proxy 장기 데이터 검증을 분리해 평가 리포트를 따로 낸다.
- 현재 상태에서 LightGBM 중요도 상위에 `mid_price`, `spread_bps`, `bid_ask_imbalance`가 들어간 것은 proxy/actual 분포 차이 또는 가격수준 의존 가능성을 함께 의심해야 한다.

## 🔴 [2026-05-06 05:22] 운영자 판단 필요 — Phase 1 Windows 직접 실행 완료

- 상황: Windows 로컬 환경에서 작업 1 단위 테스트 통과 후 Phase 1 명령 3개를 순서대로 직접 실행 완료. LightGBM은 validation 정확도와 누적 손실 폭에서는 baseline보다 좋아 보이나, 실제 매수 신호가 3건뿐이라 challenger 판단은 `keep_active`이며 walk-forward gate도 `needs_review`.
- 가져갈 파일: `docs/STATUS.md`
- 질문: 아래 Phase 1 수치를 기준으로 Codex가 Phase 2 원인 분석(거래 수 부족, walk-forward 정확도 미달, LightGBM 신호 희소성)을 진행해도 되는지 확인 필요.

### 실행 명령과 결과

| 단계 | 명령 | 결과 |
|---|---|---|
| 작업 1 검증 | `python -m unittest discover -s tests -p "test_*.py"` | `Ran 85 tests in 25.449s`, `OK` |
| baseline/참조 walk-forward | `python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 40` | `exit 0` |
| LightGBM 학습 | `python -m app --train-lightgbm --horizon-min 15` | `exit 0` |
| Challenger 비교 | `python -m app --run-challengers --horizon-min 15` | `exit 0` |

### Phase 1 핵심 수치

> MDD와 샤프지수는 현재 리포트 원 필드가 아니라, 거래별 또는 fold별 `net_return_pct` 단순누적 시퀀스로 계산한 참고값이다.

| 지표 | baseline / active | LightGBM latest | baseline 대비 |
|---|---:|---:|---|
| validation rows | 2303 | 2303 | 동일 |
| trades_taken | 1013 | 3 | LightGBM 신호가 과소 |
| 누적 순수익률 | -51.599478% | -0.113131% | LightGBM 손실 폭 우위 |
| MDD | -58.734863% | -0.177832% | LightGBM 손실 폭 우위 |
| 샤프지수 | -0.163627 | -0.203249 | baseline 우위 |
| 정확도 | 0.108120 | 0.816761 | LightGBM 우위 |
| win_rate | 0.358342 | 0.333333 | baseline 우위 |
| baseline 대비 판정 | 기준 | 정확도/순수익률은 우위이나 거래 수 3건으로 승격 불가 | `recommended_action=keep_active` |

### Walk-forward 참조 수치

| 항목 | 값 |
|---|---:|
| model_version | `walk-forward-centroid-h15-v1` |
| folds | 1147 |
| rows_evaluated | 11470 |
| trades_taken | 3126 |
| overall_accuracy | 0.438710 |
| trade_hit_rate | 0.197377 |
| win_rate | 0.442738 |
| 누적 순수익률 | -14.115270% |
| MDD(폴드 순수익 단순누적 기준) | -160.630188% |
| 샤프지수(폴드 순수익 기준) | -0.010281 |
| gate | `needs_review` — `Walk-forward overall accuracy is too low (0.4387).` |

### LightGBM 학습 수치

| 항목 | 값 |
|---|---:|
| training_run_id | `train-lightgbm-h15-20260506052213057306` |
| train_rows | 9212 |
| validation_rows | 2303 |
| validation_accuracy | 0.816761 |
| activation_applied | `false` |

### 피처 중요도 상위 5개

| 순위 | 피처 | importance |
|---:|---|---:|
| 1 | `mid_price` | 1450 |
| 2 | `spread_bps` | 1110 |
| 3 | `bid_ask_imbalance` | 1077 |
| 4 | `avg_trade_size` | 986 |
| 5 | `hl_range_pct` | 853 |

### 다음 요청

- Codex Phase 2 원인 분석 후보:
  - LightGBM validation 정확도는 높지만 `up` 신호가 3건뿐이라 거래 커버리지가 부족한 이유 확인.
  - walk-forward 정확도 0.438710으로 gate 0.55 기준 미달 원인 확인.
  - `mid_price`, `spread_bps`, `bid_ask_imbalance` 중심 중요도 편중이 데이터 누수/가격수준 의존인지 점검.
- 운영자 판단 필요: 예 — Phase 2 원인 분석 착수 승인 필요.

## 🔴 [2026-05-06 두 번째 호출] 운영자 판단 필요 — Codex 패치 후에도 Synthetic 미통과

- 상황: Codex 커밋 `eb3949f`(WAL→DELETE journal fallback) 적용 후 재실행했으나, virtiofs FUSE 환경에서는 `journal_mode=DELETE` 단독으로도 SQLite 가 `disk I/O error` 로 실패. 단위 테스트 85 발견(개수 일치) 중 40건이 동일 오류로 실패. Synthetic 도 같은 원인으로 진입 직후 실패.
- 가져갈 파일: `docs/logbook.md` (상단 "Cowork 후속 검증" 섹션에 pragma 조합별 실험표 포함)
- 질문: Codex 에 다음 중 어떤 추가 조치를 지시할지 결정 필요
  1. **`DELETE` 선택 시 `PRAGMA locking_mode=EXCLUSIVE` 함께 설정** — 실험에서 동작 확인. 단일 프로세스 운영(Cowork synthetic, 단위 테스트)에는 영향 없으나 동시 접속이 필요한 대시보드/감시기 동시 운영 시 영향 검토 필요.
  2. **DELETE 실패 시 `journal_mode=MEMORY` 로 한 단계 더 fallback** — 가장 단순. 정전·크래시 시 DB 무결성 약간 저하 가능. Cowork 샌드박스 한정 적용 권장.
  3. **Phase 1 진단을 운영자가 Windows 로컬에서 직접 실행** — Cowork 환경 자체를 우회. 가장 빠르지만 자동화 흐름 깨짐.

### 사전 정리(이번 세션 적용 사항 — 다음 세션에 영향 없음)
- 작업트리 `app/storage/sqlite_store.py` 가 FUSE 동기화 중 1074→964줄로 절단된 채 도착해 `SyntaxError`. `git show HEAD:` 로 정본 1074줄 복원함(코드 변경 아님, 정본 복원).
- Cowork 샌드박스 Python 3.10.12 ↔ 프로젝트 요구 ≥3.12 갭은 `tomli` 백포트를 `tomllib` shim 으로 메움.
- 누락 패키지(`lightgbm`, `scikit-learn`, `websockets`, `joblib`, `tomli`, `scipy`, `threadpoolctl`) 설치 완료.

### 핵심 실험표 (logbook.md 상세)

| pragma 조합 | 결과 |
|---|---|
| `journal_mode=DELETE` | FAIL: disk I/O error |
| `journal_mode=DELETE` + `synchronous=NORMAL` (현재 코드) | FAIL: disk I/O error |
| `journal_mode=DELETE` + `synchronous=OFF` | FAIL: disk I/O error |
| `journal_mode=DELETE` + `locking_mode=EXCLUSIVE` | OK |
| `journal_mode=MEMORY` | OK |
| `journal_mode=OFF` | OK |

### Phase 1 결과
- Step 1 Synthetic 흐름 검증: **여전히 실패** (Codex 1차 패치로는 미해결)
- Step 2~5: 미실행 (가이드의 "Synthetic 통과 전 Step 2 보류" 규칙)

### 다음 단계
운영자 결정 후 Codex 재작업 또는 Windows 직접 실행 결정. 결정 전까지 추가 실행 없이 대기.
