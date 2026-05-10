# 현재 구현 상태

## 현재 요약

이 프로젝트는 국내 주식 실시간 데이터를 로컬에 저장하고, 분봉과 특징을 만들고, 15분/60분 예측과 모의운용 검증까지 이어지는 기본 운영 흐름을 갖췄다.
현재 목표는 실전 자동매매가 아니라 `수집 -> 특징 생성 -> 예측 -> 로컬 모의운용 + KIS 모의계좌 검증 -> 리포트` 흐름을 안정화하는 것이다.

궁극적인 동작 목표는 `데이터 수집 -> 전략 후보 생성 -> 비용/슬리피지/세금 반영 검증 -> walk-forward 검증 -> paper 운용 -> 소액 실전 검증 -> 리스크 제한 운용 -> 일일 분석 -> 승격/폐기`가 반복되는 로컬 투자 연구·운영 시스템이다. 수익 목표는 과도한 일간 고정 수익률이 아니라 손실일을 제한하고 유리한 장세에서 수익 기회를 키우는 구조로 둔다. 월 누적 `+50%`는 장기 stretch target 으로 기록하지만, 보장 수익률이나 즉시 실전 운용 기준은 아니다.

장중 데이터 수집은 실험과 분리된 백그라운드 축으로 유지한다. 일반 거래일에는 `runtime watchdog`이 live runtime 을 켜서 KIS WebSocket 체결/호가 데이터를 계속 쌓고, 오프라인 ML/룰 실험은 이 수집기를 끄지 않고 DB와 리포트를 읽는다. 코스피200 Cybos 갱신은 Windows COM API 제약 때문에 장후 배치 수집과 WSL 병합 흐름으로 분리한다.

장중에는 `수집 트랙`과 `연구 트랙`을 분리한다. 수집 트랙은 `runtime-data/dev.db`를 계속 쓰고, 연구 트랙은 `scripts/create_research_db_snapshot.sh`가 만든 SQLite backup 스냅샷을 `DATABASE_URL`로 지정해 실행한다. 기본 스냅샷과 연구 산출물 위치는 `/mnt/d/CodexData/Real-time-stock-price-prediction-program/` 아래이며, D드라이브가 없을 때만 `runtime-data/` 아래 fallback을 사용한다.

장마감 후 자동 관리는 runtime watchdog 이 하루 한 번 시작한다. 기본 30분 지연 뒤 `run_post_close_ml_maintenance.sh --quick`를 백그라운드 실행하고, quick 경로는 live DB를 무겁게 재학습하지 않고 runtime report, KIS live 데이터 품질, KIS-Cybos feature drift, KIS live feature-label 진단, dashboard snapshot 만 갱신한다. 이 진단들은 대시보드 갱신용 warning-only 작업이라 실패해도 heavy research 를 자동 시작하지 않는다. live DB는 장중 수집 원장으로 남긴다. snapshot DB와 `--rebuild-actual-ml`을 쓰는 heavy research 는 명시 명령이나 별도 저부하 시간대에서만 실행하며, 자동 학습은 active model 교체나 실전 주문 승격을 하지 않는다.

현재 기본 운영 자세는 아래와 같다.

- 기본 거래 모드: `paper`
- 실전 주문: 기본 비활성화
- 15분 활성 모델: `baseline-h15-v1`
- 60분 활성 모델: `baseline-h60-v1`
- LightGBM: 장후 재학습과 challenger 비교에 사용하되, 검증 통과 전 자동 승격하지 않음
- 대시보드 주소: 실행 시 `http://127.0.0.1:8765`
- runtime 데이터 루트: `runtime-data/`

## 구현 완료 범위

현재 구현된 큰 축은 아래와 같다.

- KIS REST 현재가/호가 조회
- KIS WebSocket 파서, 수신기, 재연결 처리
- KIS WebSocket 연결 준비와 장중 데이터 수신 검증 리포트
- SQLite와 JSONL 기반 runtime 저장
- 원시 체결/호가 저장
- 1분봉 생성
- feature / label 생성
- baseline, centroid, linear-score, LightGBM 학습과 비교
- 검증 꼬리구간 백테스트
- gap/max-train 제어가 가능한 walk-forward backtest
- challenger 평가, 순위, walk-forward gate, 승격 판단
- 활성 모델 등록부와 내장 예비 모델
- 재생과 실시간 흐름의 모의운용 상태 기록
- 실행 리포트, 백테스트 리포트, 워크포워드 리포트, 도전자 모델 리포트
- 로컬 대시보드 스냅샷 생성과 HTTP 제공
- 실시간 수집기 백그라운드 시작/상태/중지
- 실행 감시기 백그라운드 시작/상태/중지
- PC 로그인 후 자동 복구용 실행 자동시작과 시작프로그램 실행기
- KIS 브로커 모의계좌 잔고 조회
- 로컬 가상 계좌와 브로커 모의계좌 정합성 점검
- 로컬 가상 주문을 KIS 모의계좌로 함께 제출하는 브로커 모의계좌 미러링
- 브로커 기준 표시자 기반 모의계좌 기준선 정렬
- KIS 호출 제한 재시도와 안전 실패 처리
- pykrx 일봉 기반 장기 과거 데이터 backfill 과 기존 SQLite 구조 적재
- Cybos 실제 15분봉 기반 bar-only LightGBM 연구 실험 경로

## 데이터 흐름

기본 흐름은 아래와 같다.

```text
KIS 체결/호가
-> raw tick / raw orderbook 저장
-> 1분봉 생성
-> feature / label 생성
-> 모델 학습과 평가
-> 장중 예측
-> 15분 신호 판단
-> 로컬 모의주문
-> 선택적으로 KIS 모의계좌 주문 제출
-> 체결/포지션/계좌 정합성 점검
-> runtime report와 dashboard
```

## 대시보드

대시보드 스냅샷 생성:

```bash
python -m app --build-dashboard
```

대시보드 서버 실행:

```bash
./scripts/run_dashboard.sh
```

백그라운드 시작/상태/중지:

```bash
./scripts/start_dashboard_background.sh
./scripts/get_dashboard_status.sh
./scripts/stop_dashboard.sh
```

대시보드는 아래 기준으로 동작한다.

- 기본 자동 새로고침 주기: 10분
- 수동 갱신 버튼: `상태 업데이트`
- 기본 화면과 `/api/dashboard.json` 은 최신 캐시 스냅샷을 먼저 내려 빠르게 응답한다.
- 수동 갱신과 10분 자동 새로고침은 `/api/refresh` 로 스냅샷을 다시 만든 뒤 화면을 갱신한다.
- 대시보드 서버 시작 시 기존 캐시 스냅샷이 있으면 무거운 스냅샷 재생성을 먼저 하지 않고 서버부터 열어 기동 지연을 줄인다.
- 원시 체결/호가 행은 화면에 직접 표시하지 않고 분 단위 집계 카운트만 사용해 대시보드 재생성 부하를 낮춘다.
- 원시 체결/호가의 actual source 분 단위 집계는 `source, symbol, event_time` 인덱스를 사용해 Cybos 5년치 데이터가 섞인 DB에서도 대시보드 재생성 시간을 낮춘다.
- 기본 날짜 조회처럼 기간 필터가 있는 대시보드 생성은 대형 테이블 전체를 읽지 않고 SQL 시간 범위로 먼저 좁힌 뒤 실제 runtime 필터를 적용한다.
- 머신러닝 현황 탭의 `장후 자동 학습 상태` 카드는 post-close maintenance 상태, snapshot DB, snapshot runtime, stdout/stderr 로그 경로를 보여준다.
- 머신러닝 현황 탭의 `게이트 기준 워크포워드` 카드는 정본 저장소의 승격 게이트가 실제로 참조하는 `runtime-data/reports/backtests/latest-walk-forward-h15.json`의 시점, 학습창, fold 수, 수익률, 설정 점검 상태를 post-close snapshot 산출물과 분리해서 보여준다.
- 머신러닝 현황 탭의 `KIS live 데이터 품질` 카드는 `runtime-data/reports/data-quality/latest-kis-live-data-quality.json`을 읽어 최신 KIS 데이터의 feature/label 닫힘 상태를 보여준다.
- 머신러닝 현황 탭의 `KIS-Cybos feature drift` 카드는 `runtime-data/reports/data-quality/latest-feature-source-drift.json`을 읽어 Cybos historical 후보를 KIS live 대리값으로 볼 때의 source drift 판단을 보여준다.
- 머신러닝 현황 탭의 `KIS live feature-label 진단` 카드는 `runtime-data/reports/data-quality/latest-kis-live-feature-diagnostics.json`을 읽어 KIS live 단일 피처와 h15 label/future return 의 약한 관계를 보여준다. 이 카드는 feature triage 용이며 모델 승격 근거가 아니다.
- 정본 gate reference 워크포워드는 `python -m app --run-gate-walk-forward --horizon-min 15` 또는 `./scripts/run_gate_walk_forward_backtest.sh`로 생성하며, `source=cybos-historical`, `parameter_profile=gate_reference_v1` provenance 를 리포트에 남긴다.
- 스냅샷 파일 저장은 임시 파일 교체와 짧은 재시도를 사용해, 상태 점검이 같은 JSON 파일을 읽는 순간의 동시 읽기 충돌을 줄인다.
- SQLite 잠금이 잠깐 발생하면 연결을 끊지 않고 `일시 점검` 응답을 내려준다.
- 저장된 pid 만 믿지 않고 실제 명령줄과 포트 응답을 함께 확인한다.
- WSL2의 실제 Python 실행 파일을 우선 사용한다.
- 탭 선택 상태는 브라우저 localStorage에 저장해 새로고침 뒤에도 유지한다.

현재 대시보드 탭은 아래 10개다.

- `모의투자(가상)`
- `모의계좌(실제)`
- `실 운용계좌`
- `머신러닝 현황`
- `상태 및 설정`
- `예측현황`
- `신호 & 주문현황`
- `체결과 분봉`
- `오늘의 리포트`
- `기타`

각 상위 탭은 왼쪽 세로 보조탭 구조를 사용한다.
긴 표와 목록은 내부 스크롤 패널 안에서 확인한다.

대시보드 데이터 필터 기준은 아래와 같다.

- `sample`, `synthetic`, `demo` 실행 행은 기본 제외한다.
- 재생 전용 행은 실제 운용 범위에서 제외한다.
- 실제 출처와 테스트 출처가 섞인 오염 분봉은 제외한다.
- 정규장 밖 KIS REST 스냅샷 분봉과 원시 행은 실제 운용 집계에서 제외한다.
- 기본 `오늘` 조회에서 현재 날짜에 장중 기록이 없으면 마지막 실제 장중 날짜를 `최근 장중`으로 선택한다.

## 예측과 신호

- 장중에는 15분과 60분 예측을 함께 기록한다.
- 신호와 주문 판단은 15분 기준으로만 수행한다.
- 최근 예측은 기준가, 예상 변동, 실제 결과, 성공 여부를 함께 보여준다.
- 목표 시각의 정확한 분봉이 없어도 같은 거래일 안에서 목표 시각 이후 가장 가까운 분봉으로 실제 결과를 계산한다.
- 장마감 뒤 같은 거래일의 후속 분봉이 더 생길 수 없는 예측은 `대기 중`이 아니라 `결과 없음`으로 닫는다.
- 예측 상세 탭은 선택 기간의 전체 예측을 보여준다.
- 신호 & 주문현황 탭은 신호, 주문, 체결을 함께 보여주고 매도 신호 차단 이유를 설명한다.

## 머신러닝 운영

주요 명령:

```bash
python -m app --train-lightgbm --horizon-min 15
python -m app --run-backtest --horizon-min 15
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10
python -m app --run-gate-walk-forward --horizon-min 15
python -m app --run-challengers --horizon-min 15
python -m app --set-active-builtin --builtin-model baseline --horizon-min 15
./scripts/create_research_db_snapshot.sh
./scripts/run_research_on_snapshot.sh -- python -m app --run-cybos-rule-challengers --cybos-profitability-cost-pct 0.13
python -m app --run-cybos-bar-only-experiment --horizon-min 15
python -m app --run-cybos-profitability-review --cybos-profitability-cost-pct 0.13
python -m app --run-cybos-label-sensitivity-review --cybos-profitability-cost-pct 0.13
python -m app --run-cybos-label-reproducibility-review --cybos-profitability-cost-pct 0.13
python -m app --run-cybos-rule-challengers --cybos-profitability-cost-pct 0.13
python -m app --run-cybos-expected-value-review --horizon-min 15 --cybos-experiment-feature-set bar_context_momentum --cybos-profitability-cost-pct 0.108
python scripts/summarize_cybos_research_suite.py
python scripts/summarize_kis_live_data_quality.py --recent-days 10
python scripts/summarize_feature_source_drift.py
python scripts/summarize_kis_live_feature_diagnostics.py
```

현재 ML 기준은 아래와 같다.

- 운영 학습창: 최근 60거래일 + 오늘 데이터
- 장중: 추론 중심
- 장후: 특징 / 라벨 재생성, LightGBM 재학습, 백테스트, 워크포워드, 도전자 모델 비교
- 활성 모델 자동 교체 금지
- 도전자 모델이 워크포워드 관문을 통과하지 못하면 `review_required` 로 유지
- LightGBM 학습은 마지막 tail `10%`를 challenger 전용 holdout으로 예약하고, 학습/validation은 그 이전 development 구간에서 수행한다. challenger 평가는 `challenger_holdout_tail_10pct`를 기본으로 쓰며, candidate별 `evaluation_independence_status`를 리포트에 남긴다. LightGBM artifact에는 `training_run_id`와 holdout metadata를 저장하고, DB 최신 training row와 artifact run id가 다르면 복구/복사 불일치로 보고 승격 후보에서 제외한다. 재학습 뒤 live 데이터가 추가되어 holdout 경계가 바뀌면 fail-safe로 promotable이 막히므로, LightGBM 승격 검토는 재학습 직후 같은 데이터 경계에서 challenger를 이어서 실행한다.
- 오래된 데이터는 삭제하지 않고 변화 점검, 구간 비교, 재생, 회귀 검증에 보관
- Cybos 연구 실험은 `source=cybos-historical`만 사용하고, 호가가 없는 과거 데이터 특성상 `mid_price`, `spread_bps`, `bid_ask_imbalance`는 제외한다.
- Cybos rule challenger review는 고정 long-only 룰 후보를 비용 반영 walk-forward로 비교한다. 결과가 좋아도 자동 승격하지 않고 기간 분리 재현성 검증 후보로만 기록한다.
- Cybos 연구 실험의 지원 피처 세트는 `bar_only`, `bar_context`, `bar_context_momentum`이다.
- Cybos 손익 진단은 F-5 재현, 거래 원장 기반 손익 분해, 0.13% 왕복 비용 기준선, train-only confidence threshold, 60분 horizon 비교를 리포트로 남긴다.
- Cybos 라벨 민감도 진단은 threshold별 결과를 비교하되, 가장 좋은 threshold를 자동 채택하지 않는다.
- Cybos 라벨 재현성 진단은 민감도 진단에서 양수였던 threshold를 다른 fold 설계와 기간 샘플로 다시 검증한다.
- Cybos expected-value review는 각 walk-forward fold 안에서 train tail calibration 구간으로만 `probability_up` threshold를 선택하고 test 구간에 적용한다. 선택 기준은 비용 차감 평균 기대값 양수 여부이며, 수동 필터를 사후 튜닝하거나 자동 승격하지 않는다.
- Cybos expected-value review는 거래별 퍼센트 손익 합산과 별도로 `fixed_fraction_per_signal_horizon_proxy` 포트폴리오 프록시를 기록한다. 기본 해석은 `5% 고정 비중`, `총 익스포저 100% 제한`, `horizon 기반 청산`이며 실제 paper 계좌 수익률이 아니라 승격 전 진단값이다.
- Cybos 연구 suite 요약은 기존 `latest-cybos-*` 리포트를 재학습 없이 묶어 `latest-cybos-research-suite-summary.{json,md}`로 남긴다. 이 요약은 후보 승격이 아니라 다음 실험 우선순위를 정하는 진단표다.
- KIS live data quality 요약은 `raw_market_ticks`, `raw_orderbook_ticks`, 실제 KIS 분봉, feature, h15/h60 label coverage 를 최근 거래일별로 묶어 `runtime-data/reports/data-quality/latest-kis-live-data-quality.{json,md}`로 남긴다. 이 요약은 월요일 장전/장중 수집률 점검과 장후 label 닫힘 여부 확인에 쓴다.
- KIS live vs Cybos historical feature source drift 요약은 `runtime-data/reports/data-quality/latest-feature-source-drift.{json,md}`로 남긴다. KIS 표본은 가능하면 Cybos 마지막 일자 이후 live 날짜만 사용하며, `spread_bps`, `bid_ask_imbalance`처럼 Cybos historical 에 구조적으로 없는 호가 feature 분포 차이를 승격 판단 전에 확인한다. Cybos-only 후보는 실제 KIS live 성능의 직접 대리값이 아니라 구조 탐색과 후보 축소용으로 본다.
- KIS live feature diagnostics 요약은 `runtime-data/reports/data-quality/latest-kis-live-feature-diagnostics.{json,md}`로 남긴다. Cybos 마지막 일자 이후 live 날짜 중 h15 label 이 닫힌 feature row만 사용해, 단일 피처별 future return 상관과 구간별 label 분포를 확인한다. 이 리포트는 피처 후보 탐색용이며 모델 승격 근거로 쓰지 않는다.

## 과거 데이터 Backfill

5년치 분봉 학습 데이터는 현재 B안으로 운영한다.
KIS `주식일별분봉조회`는 과거 분봉 조회가 가능하지만 공식 샘플 기준 보관 기간이 최대 1년이라 2021년부터 현재까지의 5년치 기본 수집에는 쓰지 않는다.
대신 pykrx 일봉 OHLCV를 거래일당 26개 15분 proxy bar 로 변환해 기존 `curated_minute_bars`에 적재하고, feature 생성을 위해 같은 시각의 proxy orderbook 을 `raw_orderbook_ticks`에 `pykrx-daily-proxy` source 로 적재한다.

실행:

```bash
./scripts/collect_historical_data.sh --start-date 2021-01-01
```

최신 품질 리포트:

- `runtime-data/reports/historical/latest-historical-collection.json`
- `runtime-data/reports/historical/latest-historical-collection.md`

실데이터만 다시 구축:

```bash
./scripts/rebuild_actual_ml_state.sh
```

장후 머신러닝 관리:

```bash
./scripts/run_post_close_ml_maintenance.sh
```

장후 관리는 장외에 실시간 수집기를 다시 켜지 않는다.
이미 켜져 있으면 중지해 WebSocket 재연결 루프가 CPU를 계속 쓰지 않게 한다.
기본 실행은 quick 경로이며 `runtime-data/dev.db`를 무겁게 재학습하지 않고 runtime report, KIS live 데이터 품질, KIS-Cybos feature drift, KIS live feature-label 진단, dashboard snapshot 만 갱신한다.
quick 경로의 데이터 품질 진단은 warning-only 로 실행되어, 개별 진단 실패가 장후 상태 파일 전체 실패나 heavy research 자동 실행으로 이어지지 않는다.
watchdog 은 장마감 후 기본 30분이 지나면 이 경로를 하루 한 번 백그라운드로 시작한다.
같은 날짜의 post-close maintenance 상태 파일에 `starting`, `running`, `ok`, `failed` 등 status 값이 이미 있으면 watchdog 은 같은 작업을 반복 시작하지 않는다.
snapshot DB와 격리된 research run runtime 을 쓰는 heavy research 는 아래처럼 명시적으로 실행한다.

```bash
./scripts/run_post_close_ml_maintenance.sh --heavy-research --use-snapshot
```

## 로컬 가상 계좌와 KIS 모의계좌

로컬 가상 계좌는 프로그램 내부 모의주문 엔진의 장부다.
KIS 모의계좌는 한국투자 모의투자 서버에서 직접 조회한 계좌 상태다.
두 값은 주문 거절, 부분 체결, 체결 시차, KIS 예수금 표시 방식 때문에 일시적으로 다를 수 있다.

브로커 모의계좌 잔고 갱신:

```bash
./scripts/refresh_kis_account.sh
python -m app --kis-account-balance
```

로컬 가상 계좌와 브로커 모의계좌 비교:

```bash
./scripts/reconcile_paper_accounts.sh
python -m app --reconcile-paper-accounts
```

브로커 기준으로 로컬 가상 계좌 현재 상태 정렬:

```bash
./scripts/align_local_paper_to_broker.sh
python -m app --align-local-paper-to-broker
```

장 시작 전 시작 예수금 동기화와 정렬:

```bash
./scripts/verify_paper_dual_account_match.sh -SyncInitialCash -AlignToBroker -AsJson
```

장중 또는 장후 상태 확인:

```bash
./scripts/verify_paper_dual_account_match.sh -AsJson
```

브로커 모의계좌 주문 미러링 실행:

```bash
$env:ENABLE_BROKER_PAPER_MIRRORING="true"
./scripts/start_runtime_autoboot.sh
```

현재 기본 전략 설정은 `ENABLE_BROKER_PAPER_MIRRORING=true` 이다.
로컬 가상 주문은 KIS 모의계좌에도 제출될 수 있고, 브로커 상태/체결 동기화로 로컬 장부를 맞춘다.

계좌 비교에서 KIS 원시 현금값은 체결 뒤에도 총 예수금처럼 보일 수 있다.
따라서 대시보드와 reconciliation 은 `total_asset_amount - stock_evaluation_amount` 로 계산한 브로커 유효현금을 기준으로 비교하고, 원시 현금 차이는 `raw_cash_gap` 으로 따로 남긴다.

수동 브로커 주문/체결 조회가 KIS `EGW00201` rate-limit 에 걸리면 짧게 재시도한다.
계속 막히면 실행기를 죽이지 않고 `rate_limited` 리포트를 남기며 기존 제출 주문 종목을 대기 상태로 유지한다.
실시간 수집 중 브로커 체결 동기화는 분 단위로 제한하고, rate-limit 이 발생하면 즉시 재시도하지 않은 뒤 5분 동안 추가 조회를 쉬어 KIS 호출 제한, 지연, 로그 증가를 줄인다.

## KIS 계좌 설정 메모

모의투자 계좌 화면에 상품코드가 따로 없으면 root `.env` 의 `KIS_PRODUCT_CODE_PAPER` 는 빈 값으로 둔다.
앱은 KIS REST 계좌/주문 호출에 상품코드가 필요할 때 paper 기본값을 내부에서 적용한다.

계좌가 `12345678-01` 형태로 들어오면 설정 로더는 아래처럼 나눈다.

- `KIS_ACCOUNT_NO_PAPER=12345678`
- `KIS_PRODUCT_CODE_PAPER=01`

`.env` 에 템플릿 placeholder 값이 남아 있으면 빈 값으로 간주하고 paper 기본값을 적용한다.

KIS app key/secret 복구:

```bash
./scripts/restore_kis_env_interactive.sh
```

계좌 항목까지 함께 복구:

```bash
./scripts/restore_kis_env_interactive.sh -IncludeAccountFields
```

모의계좌번호만 연결 또는 복구:

```bash
./scripts/connect_kis_paper_account_interactive.sh
```

## 실시간 수집기

실시간 수집기 백그라운드 시작/상태/중지:

```bash
./scripts/start_live_runtime_background.sh
./scripts/get_live_runtime_status.sh
./scripts/stop_live_runtime.sh
```

실시간 수집기가 실행 중이면 아래를 수행한다.

- 관심 종목 목록의 종목을 계속 수집한다.
- 새 분이 닫힐 때마다 15분과 60분 예측을 기록한다.
- 신호와 주문 판단은 15분 기준으로 수행한다.
- 대시보드 상단 프로그램 상태와 로컬 모의운용 계좌가 `운용 중`으로 바뀐다.

실시간 실행 ID는 실행별 고유 이름공간을 포함한다.
재시작 뒤에도 `paper-order-online-*` ID를 재사용해 기존 SQLite row를 덮어쓰지 않는다.

## 실행 감시기

실행 감시기 시작/상태/중지:

```bash
./scripts/start_runtime_watchdog_background.sh
./scripts/get_runtime_watchdog_status.sh
./scripts/stop_runtime_watchdog.sh
```

감시기 동작 기준은 아래와 같다.

- 정규장에는 대시보드와 실시간 수집기가 둘 다 살아 있는지 확인하고, 꺼져 있으면 다시 올린다.
- 정규장 시작 60분 전부터는 장전 준비 단계로 실시간 수집기를 미리 켠다.
- 대부분의 장외 시간과 `config/market_calendar.toml`의 `holidays`에 적힌 휴장일에는 실시간 수집기를 새로 켜지 않고, 켜져 있으면 중지해 WebSocket 재연결 루프를 막는다.
- `holidays`는 KRX 전일 휴장일을 명시하는 로컬 운영 캘린더이며, 연도 변경이나 임시 휴장 공지가 있으면 장 시작 전 갱신한다.
- 대시보드 스냅샷 전체 재생성은 기본 10분 간격으로 제한해 CPU 사용을 줄인다.
- 실시간 지연 판단은 우선 실시간 수집기 상태값과 최신 KIS 검증 파일을 사용한다.
- 감시기 상태 조회는 프로세스 존재와 함께 `last_checked_at` 심박 나이를 확인한다. 프로세스가 살아 있어도 기본 10분 이상 상태 파일이 갱신되지 않으면 `stale` 로 본다.
- 감시기 시작 스크립트는 stale 심박을 가진 기존 감시기 프로세스를 재사용하지 않고 중지 후 새로 시작한다.
- 정규장에 실시간 수집기가 이미 최신 분봉을 쓰고 있으면 별도 KIS 검증 WebSocket 을 중복 실행하지 않는다.
- root `.env` 또는 KIS 자격정보가 없으면 차단 상태를 기록하고 같은 실패를 반복하지 않는다.
- `.env` 가 복구되고 활성 거래 모드 기준 app key/secret 이 준비되면 오래된 차단 상태를 해제한다.
- 실시간 수집기 상태 출력은 현재 장 상태와 마지막 KIS 검증 당시 장 상태를 분리해서 보여준다.
- 로컬 setup 점검은 현재 장 상태와 장전 준비 시간을 계산해, 장외나 장전 준비 전 실시간 수집기 중지를 정상 상태로 해석한다.

감시기 상태 파일:

- `runtime-data/reports/runtime-watchdog/state/watchdog-state.json`

## PC 로그인 후 자동 복구

PC 재부팅 후 자동 시작 루틴:

```bash
./scripts/start_runtime_autoboot.sh
./scripts/install_runtime_startup_launcher.sh
./scripts/get_runtime_startup_launcher_status.sh
./scripts/remove_runtime_startup_launcher.sh
```

`start_runtime_autoboot.sh` 는 아래를 수행한다.

- demo/sample SQLite row 정리
- 대시보드 백그라운드 시작
- 장중 또는 장전 준비 시간에는 실시간 수집기 백그라운드 시작
- 장외와 `config/market_calendar.toml`의 `holidays`에 적힌 휴장일에는 실시간 수집기 중지 상태 유지
- 실행 감시기 시작
- KIS 브로커 모의계좌 잔고 갱신
- 브로커 모의계좌 주문 동기화
- 모의계좌 정합성 점검
- 실행 리포트 갱신
- 대시보드 스냅샷 재생성

하위 `python -m app ...` 명령이 실패하면 성공처럼 넘기지 않고 즉시 오류로 처리한다.

WSL2/Windows 환경의 `install_runtime_startup_launcher.sh`는 Windows 시작프로그램의 `RealTimeStockRuntime.cmd`를 현재 WSL 정본 저장소 경로로 설치한다.
Windows 시작프로그램을 사용할 수 없는 순수 Linux 환경에서만 systemd user service 를 fallback 으로 사용한다.

## 월요일 시작 루틴

```bash
./scripts/start_monday_runtime.sh
```

이 스크립트는 아래를 수행한다.

- 대시보드 서버 시작
- 장중 또는 장전 준비 시간에는 실시간 수집기 수신기 시작
- 장외와 `config/market_calendar.toml`의 `holidays`에 적힌 휴장일에는 실시간 수집기 중지 상태 유지
- 실행 감시기 시작
- demo/sample SQLite 행 정리
- 실행 리포트와 대시보드 스냅샷 갱신
- 그림자 머신러닝 갱신
- 브로커 모의계좌 캐시 갱신
- 모의계좌 정합성 점검
- KIS 검증
- 주요 상태 JSON 요약 출력

## KIS WebSocket 검증

```bash
./scripts/verify_kis_ws.sh
python -m app --verify-kis-ws --symbols 005930 --max-frames 5 --max-reconnects 0
```

검증은 아래를 분리해서 기록한다.

- `.env` 존재 여부
- 자격정보 준비 여부
- `websockets` 패키지 사용 가능 여부
- approval key 발급 여부
- 연결 준비 완료 여부
- 실제 장중 데이터 수신 여부
- 장 상태에 따른 해석

장외에는 시장 데이터가 들어오지 않는 것이 정상일 수 있으므로 연결 준비 상태와 시장 데이터 흐름을 분리해 본다.

## 매시간 저장소 점검

1회 실행:

```bash
./scripts/run_hourly_repo_audit_iteration.sh
```

백그라운드 시작/상태/중지:

```bash
./scripts/start_hourly_repo_audit_background.sh
./scripts/get_hourly_repo_audit_status.sh
./scripts/stop_hourly_repo_audit.sh
```

권장 스케줄러는 Codex 자동화다.
bash 백그라운드 실행기는 Codex 자동화가 없을 때만 쓰는 예비 경로로 본다.

자동화는 아래를 수행한다.

- 기준 문서 재읽기
- 저장소 구조, runtime-data, git 상태 점검
- 정규장 시간에만 KIS 검증 후보 실행
- Codex CLI 기반 검토, 웹 메모, 초안, 문맥, 진행 상태, 우선순위 목록 산출
- `runtime-data/reports/codex/automation/` 아래 상태 보존
- 같은 미해결 항목 식별자 유지
- 저장된 pid 와 실제 bash 명령줄 대조

## 실데이터 정리와 재구축

테스트 운용 흔적 정리:

```bash
./scripts/cleanup_runtime_test_data.sh
```

실제 운용 데이터만 남기고 ML/검증 산출물 재생성:

```bash
./scripts/rebuild_actual_ml_state.sh
```

실데이터 전용 정리는 아래를 정리한다.

- demo / replay / synthetic 원시 체결과 호가
- 파생 분봉
- 서빙 테이블
- 모의운용 테이블
- 테스트용 포트폴리오 스냅샷

단, 실제 브로커 체결 시각에 생성된 portfolio snapshot 은 실제 운용 데이터로 보존한다.

## 추천 개발 흐름

합성 데이터 전체 흐름:

```bash
./scripts/run_full_synthetic_cycle.sh
```

명시적 백테스트:

```bash
./scripts/run_backtest.sh
```

명시적 워크포워드:

```bash
./scripts/run_walk_forward_backtest.sh
```

정본 gate reference 워크포워드:

```bash
./scripts/run_gate_walk_forward_backtest.sh
```

현재 데이터셋 권장 워크포워드 변형:

```bash
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 40
```

KIS REST 개발 흐름:

```bash
./scripts/run_full_kis_cycle.sh
```

안전한 활성 모델 초기화:

```bash
python -m app --set-active-builtin --builtin-model baseline --horizon-min 15
```

그림자 머신러닝 갱신:

```bash
./scripts/run_ml_shadow_cycle.sh
```

도전자 모델 비교:

```bash
./scripts/run_challenger_review.sh
```

## 유용한 CLI 명령

```bash
python -m app --kis-current-price --symbol 005930
python -m app --kis-orderbook --symbol 005930
python -m app --kis-watchlist-poll --iterations 5 --interval-seconds 5
python -m app --build-minute-bars
python -m app --build-feature-dataset
python -m app --train-baseline --horizon-min 15
python -m app --train-lightgbm --horizon-min 15
python -m app --set-active-builtin --builtin-model baseline --horizon-min 15
python -m app --run-backtest --horizon-min 15
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10
python -m app --run-challengers --horizon-min 15
python -m app --build-runtime-report
python -m app --reconcile-paper-accounts
python -m app --sync-broker-paper-orders
python -m app --replay-sample-ws --symbol 005930
python -m app --kis-ws-listen --max-frames 50 --max-reconnects 2
python -m app --verify-kis-ws --symbols 005930 --max-frames 5 --max-reconnects 0
```

## 주요 산출물 경로

- 실행 리포트: `runtime-data/reports/runtime/latest-runtime-report.md`
- 실행 리포트 JSON: `runtime-data/reports/runtime/latest-runtime-report.json`
- 백테스트 리포트: `runtime-data/reports/backtests/latest-backtest-h15.md`
- 백테스트 리포트 JSON: `runtime-data/reports/backtests/latest-backtest-h15.json`
- 워크포워드 리포트: `runtime-data/reports/backtests/latest-walk-forward-h15.md`
- 워크포워드 리포트 JSON: `runtime-data/reports/backtests/latest-walk-forward-h15.json`
- 도전자 모델 리포트: `runtime-data/reports/challengers/latest-challengers-h15.md`
- 도전자 모델 리포트 JSON: `runtime-data/reports/challengers/latest-challengers-h15.json`
- 도전자 모델 순위표 JSON: `runtime-data/reports/challengers/leaderboard-h15.json`
- KIS 검증 리포트: `runtime-data/reports/kis-ws/latest-verification.md`
- KIS 검증 리포트 JSON: `runtime-data/reports/kis-ws/latest-verification.json`
- 모의계좌 정합성 리포트: `runtime-data/reports/reconciliation/latest-paper-account-sync.md`
- 모의계좌 정합성 리포트 JSON: `runtime-data/reports/reconciliation/latest-paper-account-sync.json`
- 모의계좌 시작금 일치 리포트: `runtime-data/reports/reconciliation/latest-paper-dual-account-match.md`
- 모의계좌 시작금 일치 리포트 JSON: `runtime-data/reports/reconciliation/latest-paper-dual-account-match.json`
- 대시보드 스냅샷 HTML: `runtime-data/reports/dashboard/latest-dashboard.html`
- 대시보드 스냅샷 JSON: `runtime-data/reports/dashboard/latest-dashboard.json`
- 복구 setup 점검 JSON: `runtime-data/reports/recovery/latest-local-setup-check.json`
- 복구 setup 점검 Markdown: `runtime-data/reports/recovery/latest-local-setup-check.md`
- 모델 등록부: `runtime-data/ml/registry.json`
- centroid 산출물: `runtime-data/ml/models/`

## 현재 운영 권장

현재는 `baseline-h15-v1` 을 활성 실시간 모델로 유지하고, `lightgbm-h15-v1` 은 도전자 모델 산출물로 학습/비교한다.
최신 워크포워드 기준이 약하면 검증 구간에서 더 좋아 보여도 자동 승격하지 않는다.

다음 우선순위는 아래와 같다.

1. 실제 장중 수집 안정성 유지
2. 로컬 가상 계좌와 KIS 모의계좌 정합성 점검
3. 장후 재학습 산출물 검토
4. LightGBM 승격 기준 고도화
5. 뉴스/공시/반응 데이터 특징 추가
