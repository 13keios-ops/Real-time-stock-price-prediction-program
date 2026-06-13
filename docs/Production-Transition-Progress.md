# Production Transition Progress

이 문서는 실전 전환 작업의 현재 상태를 빠르게 보기 위한 진행판이다.
사이드패널에서 안정적으로 열리도록 긴 표 대신 짧은 섹션과 bullet 위주로 유지한다.

## 1. 갱신 규칙

- 실전 전환 관련 작업이 끝날 때마다 갱신한다.
- 현재 상태, 남은 blocker, 다음 권장 작업을 우선 기록한다.
- 긴 리뷰 전문은 `docs/cowork-reports/`에 둔다.
- 비밀값은 적지 않는다.
- 이 문서 갱신 목적으로 `app/risk/`, `config/`, `VERSION`, gate 기준값,
  `ALLOW_LIVE_ORDERS`는 수정하지 않는다.

관련 문서/코드 경로:
`docs/Production-Architecture.md`,
`docs/Production-Implementation-Blueprint.md`,
`docs/Execution-Plan.md`,
`docs/logbook.md`

## 2. 현재 스냅샷

- 마지막 갱신: 2026-06-13 16:45 KST
- 현재 런타임: `weekend`
- live runtime: 정지 상태가 정상
- runtime watchdog: running. `live_runtime_should_run=false`, `errors=[]`, heartbeat fresh.
- dashboard: running. `http://127.0.0.1:8765` 서버와 API가 응답 중.
- trading mode: `paper`
- 최신 cowork 기준:
  `docs/cowork-reports/2026-06-13-repo-goal-and-direction-deep-review-review_ver_18.md`
- 최신 통합 리포트:
  `docs/cowork-reports/2026-06-13-repo-goal-and-direction-deep-review-work_ver_18.md`
- 최신 Phase readiness:
  `runtime-data/reports/live-readiness/latest-readiness.json`
  기준 `phase1a_paper_readonly`, `status=ok`, `source=fixture-dry-run`,
  `generated_at=2026-06-13T13:34:06+09:00`.
  token/account/system_clock/ws_synthetic/dashboard/database evidence는 최신 freshness 기준을 통과했다.
  `market_status`와 `kill_switch`는 Phase 1a read-only에서 비차단 관측 실패로 남는다.
- 최신 dashboard snapshot:
  `runtime-data/reports/dashboard/latest-dashboard.html`
  기준 `generated_at=2026-06-13T13:33:09+09:00`.
- 최신 장전 readiness:
  `runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json`
  기준 `generated_at=2026-06-13 13:33:34 +0900`, `status=ok`.
- 최신 장후 ML maintenance:
  `runtime-data/reports/ml-maintenance/state/latest-post-close-ml.json`
  기준 `completed_at=2026-06-11 16:10:08 +0900`, `status=ok`, `mode=quick-live-train`.
- 최신 장후 label refresh:
  `runtime-data/reports/ml-maintenance/state/latest-post-close-label-refresh.json`
  기준 `completed_at=2026-06-11 16:45:07 +0900`, `status=ok`.
- 최신 KIS live data quality:
  `runtime-data/reports/data-quality/latest-kis-live-data-quality.json`
  기준 latest trade date `2026-06-12`, `assessment.status=ok`.
- 최신 검증:
  `python -m unittest tests.test_runtime_scope` 4개 통과,
  `python -m unittest discover -s tests -p "test_*.py"` 385개 통과,
  `git diff --check` 통과.
- 최신 challenger:
  `runtime-data/reports/challengers/latest-challengers-h15.json`
  기준 `challenger-h15-20260612045334514142`, active `baseline-h15-v1`,
  `recommended_action=keep_active`.
  LightGBM은 `independent_challenger_holdout`으로 심사 자격은 회복됐지만
  매수 신호 0건이고 walk-forward gate가 `needs_review`라 승격 대상이 아니다.
- 최신 gate reference walk-forward:
  `runtime-data/reports/backtests/latest-walk-forward-h15.json`
  기준 `walk-forward-h15-20260612042842731771`,
  `parameter_profile=gate_reference_v1`, `folds=118`,
  `three_class_accuracy=0.416342`, `walk_forward_gate_status=needs_review`.
- 최신 LightGBM buy-signal diagnostics:
  `runtime-data/reports/challengers/latest-lightgbm-buy-signal-diagnostics-h15.json`
  기준 `generated_at=2026-06-12T03:35:05+09:00`,
  `status=no_positive_expected_value_threshold`.
  threshold `0.40`에서도 `trades_taken=1845`,
  `cumulative_net_return_pct=-199.849736`라 자동 승격/threshold 채택 근거가 없다.
- 최신 LightGBM label band 재현성:
  `runtime-data/reports/challengers/latest-lightgbm-label-band-reproducibility-h15.json`
  기준 `0.40` 후보는 full walk-forward 가상 방향 순수익률이 양수였지만
  기간별 양수 재현이 `0/3`이라 정책 변경 후보가 아니다.
- 최신 LightGBM 방어 신호 후보:
  `runtime-data/reports/challengers/latest-lightgbm-defensive-signal-candidates-h15.json`
  기준 하락/회피 후보 `111`개가 추려졌고, 상위 후보는 하락 예측 구간에서
  비용 차감 양수 단서를 보인다. 단, 이 결과는 live short 또는 매수 승격 근거가 아니라
  buy-avoid / early-exit paper shadow 검증 후보로만 본다.
- 최신 LightGBM 방어 shadow:
  `runtime-data/reports/challengers/latest-lightgbm-defensive-shadow-h15.json`
  기준 `2026-06-11T09:15:00+09:00`~`2026-06-12T15:00:00+09:00`의
  baseline 매수 허용 신호 `3,130`건을 같은 시각 LightGBM 하락확률로 걸러 봤다.
  down threshold `0.40`은 매수 회피 `1,147`건, 비용 차감 누적 순수익률 delta
  `+114.8758%p`로 손실 축소 후보였지만, closed paper lot `1,029`건 기준 조기청산 shadow 는
  best threshold `0.58`에서도 delta `-48.7958%p`, cash delta `-178,007원`으로 악화됐다.
  따라서 현재 권장안은 `buy-avoid 후보 유지`, `early-exit 적용 보류`다.
- 최신 paper/KIS mismatch trace:
  `runtime-data/reports/reconciliation/latest-paper-kis-mismatch-trace.json`
  기준 mismatch source 는 `paper_account_sync`이고 mismatch 는 `4`종목
  `005380`, `035420`, `247540`, `373220`이다.
  2026-06-12 15:07~15:08 청산 주문이 local/broker 모두 submitted 상태이고
  broker order-fill 회수가 `EGW00201` 또는 장외 재시도 응답 지연으로 막힌 상태라
  자동 alignment로 덮지 않는다.
- 최신 gate walk-forward 극단 fold 요약:
  `runtime-data/reports/backtests/latest-walk-forward-extreme-folds-h15.json`
  기준 fold `118`개 중 정확도 `0.20` 미만 fold가 `3`개 있으며
  최저 fold 정확도는 `0.11842`다.
- 최신 gate walk-forward 극단 fold 장세 분석:
  `runtime-data/reports/backtests/latest-walk-forward-extreme-fold-regimes-h15.json`
  기준 최저 fold 5개 중 fold `5`, `12`, `11`은 flat 라벨 비중이 각각 약 `0.77`, `0.74`, `0.72`인데
  flat hit rate 가 `0.0061`, `0.0119`, `0.0074`로 붕괴했다. 이 기간들은 분봉 변동성도
  `0.44~0.50%` 수준으로 높아 `보합 라벨 우세 + 고변동 + flat 판별 실패`가 우선 원인 후보로 남았다.
  이 리포트는 원인 가설이며 label/gate 기준값 자동 변경 근거가 아니다.
- watchlist 확대 검토:
  `runtime-data/reports/data-quality/latest-kis-live-data-quality.json` 기준 최신 거래일 `2026-06-12`의
  watchlist 10종목 coverage assessment 는 `ok`다. 최근 h15 label 분포는 `down=9,665`,
  `flat=16,935`, `up=9,433`으로 flat 비중이 큰 편이다. 따라서 현 시점의 watchlist 확대는
  수집 누락 보완이 아니라 데이터 다양성/장세 다양성 확보 목적의 후보 검토이며,
  Phase 2 실전 canary 종목 수나 주문 한도 확대와 연결하지 않는다.
- KIS live data quality watch 세부 원인:
  `runtime-data/reports/data-quality/latest-kis-live-data-quality.json`과 `runtime-data/dev.db` read-only 조회 기준,
  2026-06-05, 2026-06-08, 2026-06-09 모두 feature/bar 비율은 `1.0`이라
  분봉 이후 feature 생성 장애 증거는 없다. 2026-06-05는 종가 동시호가와 산발 공백,
  2026-06-09는 `15:20~15:29` 종가 동시호가 공백을 제외하면 정상에 가깝다.
  2026-06-08은 raw market symbol-minute `3501`, bars/features `3491/3491`로 약했고,
  weak 구간이 `09:04~09:33`, `14:37~15:06`에 집중됐다. orderbook symbol-minute 는 `3854`로
  비교적 유지됐으므로 전 종목 수집 중단으로 단정하지 않고, 다음 거래일 같은 패턴 재발 시
  watchdog heartbeat 와 KIS WS frame 상태를 함께 비교한다.
- runtime scope 민감도 점검:
  `tests/test_runtime_scope.py::RuntimeScopeTests.test_runtime_scope_reveals_minute_bar_builder_lag`를 추가해,
  raw KIS 이벤트는 들어오지만 `curated_minute_bars`가 멈춘 상황을 격리 DB에서 재현했다.
  dashboard용 curated scope는 최신 raw minute를 자동 포함하지 않으므로, 분봉 생성기 지연은
  `최근 분봉 시각` stale과 data-quality raw coverage를 분리해서 해석해야 한다.
- 최신 paper/KIS 정합성:
  최신 `runtime-data/reports/reconciliation/latest-paper-account-sync.json`
  기준 `status=needs_review`.
  브로커는 보유 0이고 로컬은 `005380` 1주, `035420` 2주, `247540` 4주,
  `373220` 1주가 남아 있다.
- 최신 broker paper sync:
  `runtime-data/reports/broker-paper/latest-sync.json`
  기준 `status=rate_limited`, KIS `EGW00201`, open order 5건.
  2026-06-13 장외 1회 재시도는 2분 안에 완료되지 않아 Codex가 시작한 프로세스만 정리했다.
- 최신 forced NAS backup:
  `/mnt/backup/repos/real-time-stock-price-prediction-program/recovery-exports/real-time-stock-price-prediction-program-recovery-20260528-224455.tar.gz`
  (`5558128973` bytes).
- NAS 백업 실행 기준:
  앞으로 Codex는 주간/강제 NAS 백업을 자율 실행하지 않고,
  사용자가 해당 작업에서 명시적으로 지시했을 때만 실행한다.
- 다음 cowork 리뷰 권장 시점:
  6월 누적 변경 통합본과 이번 deep review 반영 결과를 묶어 전달한다.

관련 문서/코드 경로:
`scripts/get_live_runtime_status.sh`,
`scripts/get_runtime_watchdog_status.sh`

## 3. Phase 상태

### 설계 기준 정리

- 상태: 완료
- 완료:
  - `docs/Production-Architecture.md`
  - `docs/Production-Implementation-Blueprint.md`
  - cowork reports 누적
- 남은 blocker: 없음

### Phase 0: paper + KIS 모의계좌 mirroring

- 상태: 진행 중
- 현재 기준:
  - 2026-06-12 deep review ver_3 반영 뒤에도 Phase 0은 계속 진행 중이다.
  - KIS live data quality 최신 리포트는 `assessment.status=ok`로 회복됐지만,
    2026-06-05, 2026-06-08, 2026-06-09에 반복된 `watch` 원인은 별도 추적한다.
  - broker paper sync 최신 리포트는 KIS `EGW00201` rate limit 으로
    `status=rate_limited`, open order 5건이다.
  - 최신 paper-account sync 기준 브로커는 보유 0이고 로컬은
    `005380`, `035420`, `247540`, `373220` 4종목이 local-only position 으로 남아 있다.
  - `trace_paper_kis_mismatch.py`는 최신 `paper-account-sync` mismatch 목록을
    우선 기준으로 쓰도록 보강됐고, 현재 trace 기준 mismatch source 는 `paper_account_sync`다.
  - 2026-06-11 작업에서 broker paper sync 는 최근 rate-limit 리포트가
    30분 cooldown 안에 있으면 같은 KIS order-fill endpoint 를 재호출하지 않고
    `cooldown_active=true`, `skipped_broker_call=true`를 남기도록 보강했다.
  - 2026-06-11 최신 challenger 기준 active 는 `baseline-h15-v1`,
    권장은 `keep_active`다. LightGBM은 shadow/관찰 대상이며 승격되지 않았다.
  - 2026-05-28 장후 `initial_cash_mismatch`는 `-SyncInitialCash -AlignToBroker`로 조치했다.
  - 2026-05-29 장후 stale local snapshot 문제는 `rowid DESC` tie-break로 보강했다.
  - 2026-06-01 장후 정합성은 `status=matched_waiting_first_submission`이다.
  - 포지션 mismatch는 0건이고, 현금/총자산 gap은 `0원`이다.
  - 같은 timestamp 스냅샷 중 오래된 행을 최신으로 고르는 문제는
    `app/storage/sqlite_store.py`에서 `rowid DESC` tie-break로 보강했다.
  - 2026-06-01 broker paper sync는 `status=ok`였으나,
    로컬 평가 snapshot이 2026-05-29 가격에 머물러 있어
    `-AlignToBroker` marker-only 정렬로 KIS 모의계좌 현재 상태를 기준선으로 갱신했다.
  - 2026-06-02 broker paper sync는 KIS `EGW00201` rate limit으로
    `status=rate_limited`다.
  - 2026-06-02 정합성은 수량 mismatch 0이지만
    broker open order 3건(`105560`, `247540`, `373220`)이 남아 있어
    marker-only alignment를 보류했다.
  - 2026-06-04 장전 readiness, 장후 ML maintenance, 장후 label refresh,
    KIS live data quality는 모두 실행됐고 `ok` 상태다.
  - 2026-06-04 broker paper sync는 cooldown 뒤 1회 재시도해도
    KIS `EGW00201` rate limit이 유지됐다.
  - 2026-06-04 정합성은 포지션 mismatch 0이지만
    open broker order 3건이 남아 있어 marker-only alignment를 보류했다.
  - 2026-06-04 추가 원인 분석 결과 open broker order 3건은 모두
    `order_date=20260602`인 prior-day stale open snapshot 이었다.
    보유 수량 mismatch 0을 확인한 뒤 `-SyncInitialCash` 없이 marker-only
    alignment 를 적용했고, 이후 broker sync 는 `status=no_submissions`,
    `open_order_count=0`, dual-account match 는
    `status=matched_waiting_first_submission`이다.
  - `app/services/broker_paper_sync.py`는 broker status snapshot 이 이미 있는
    과거 주문일 미체결 잔량을 `expired` / `expired_partial` final 상태로
    해석하도록 보강했다.
  - 2026-06-05 PC 재부팅 후 watchdog/dashboard 는 stale 상태였고,
    장후 조치로 watchdog 과 dashboard 를 재기동했다.
  - 2026-06-05 장전 readiness, 장후 ML maintenance, 장후 label refresh,
    local setup 은 정상 실행됐다.
  - 2026-06-05 broker paper sync 는 KIS `EGW00201` rate limit 이 유지됐고
    당일 open/submitted 주문 5건 때문에 정합성이 `needs_review`였다.
    장후 broker account snapshot 이 정상/최신이고 다음 거래일 기준선 보호가
    우선이라 `-SyncInitialCash` 없이 marker-only alignment 를 적용했다.
    이후 broker sync 는 `status=no_submissions`, `open_order_count=0`,
    dual-account match 는 `status=matched_waiting_first_submission`이다.
  - bounded post-close label refresh 수정과 재실행 완료.
  - 2026-06-04 장후 KIS live data quality는 `assessment.status=ok`.
  - 2026-06-05 장후 KIS live data quality 는 latest trade date 는 맞지만
    최신일 coverage 미달로 `assessment.status=watch`다.
  - 2026-06-08 장전 readiness, 장후 ML maintenance, 장후 label refresh,
    local setup 은 정상 실행됐다.
  - 2026-06-08 broker paper sync 는 KIS `EGW00201` rate limit 이 유지됐고
    당일 sell close open 주문 2건(`005380`, `247540`) 때문에
    `status=rate_limited`였다. broker account snapshot 은 정상/최신이고
    보유 수량 mismatch 는 0이라 `-SyncInitialCash` 없이 marker-only
    alignment 를 적용했다. 이후 broker sync 는 `status=no_submissions`,
    `open_order_count=0`, dual-account match 는
    `status=matched_waiting_first_submission`이다.
  - 2026-06-08 장후 KIS live data quality 도 latest trade date 는 맞지만
    최신일 coverage 미달로 `assessment.status=watch`다.
  - 2026-06-09 장전 readiness 와 장후 ML maintenance 는 정상 실행됐다.
  - 2026-06-09 사용자가 첨부한 KIS 모의계좌 화면 기준 누적 수익률은
    `-6.98%`, 평가시점자산/총평가금액은 `9,301,757원`, 보유종목은 없음이다.
  - 2026-06-09 broker paper sync 는 KIS `EGW00201` rate limit 이 유지됐고,
    장후 broker 계좌는 보유 0인데 local 은 5종목 보유로 남아
    `needs_review`였다.
  - broker account snapshot 과 첨부 화면이 정상/최신이고 다음 거래일
    기준선 보호가 우선이라 `-SyncInitialCash` 없이 marker-only alignment 를
    적용했다. 이후 broker sync 는 `status=no_submissions`,
    `open_order_count=0`, dual-account match 는
    `status=matched_waiting_first_submission`이다.
  - `scripts/wsl_ops.py`의 dual-account 검증은 marker-only 정렬 후 flat 계좌를
    `initial_cash_mismatch`로 오탐하지 않도록 보강됐다. 이 경로는
    reconciliation 이 이미 일치하고 `aligned_to_broker_marker`가 확인될 때만
    초기 예수금 검사를 건너뛴다.
  - 2026-06-09 장후 KIS live data quality 는 latest trade date 는 맞고
    intraday coverage 는 97%대지만, 당일 h15 label coverage 주의로
    `assessment.status=watch`다.
- 남은 blocker:
  - 누적 paper-vs-broker 자동 집계와 dashboard 노출 확인.
  - 다음 장후에도 stale open 주문이 active open 으로 재발하지 않는지 확인한다.
  - 2026-06-05, 2026-06-08, 2026-06-09에 반복된 data quality `watch` 원인을 별도 확인한다.
  - 2026-06-09 장후 label refresh 최신 상태 파일이 2026-06-08 기준으로 남아
    다음 장후 자동화에서 갱신 여부를 다시 확인한다.

### Phase 1a: KIS 모의투자 read-only 리허설

- 상태: 1차 리허설 통과
- 목적:
  - 실전 계좌를 건드리지 않고 Phase 1 절차를 먼저 리허설한다.
  - token, account snapshot, system clock, dashboard, readiness flow를 검증한다.
- 현재 가능 여부:
  - 가능하며 2026-05-28 05:12 KST 기준 1차 dry-run을 통과했다.
  - 모의투자계좌 기반 `token_refresh`, `account_snapshot`, `system_clock` 증거를 생성했다.
  - `ws_recovery`는 실제 WebSocket 네트워크를 열지 않는 synthetic fault injection 증거다.
- 남은 blocker:
  - 현재 Phase 1a 자체 blocker는 없음.
  - 단, evidence freshness 기준을 넘기면 다음 리허설에서 다시 생성해야 한다.
- 비차단 관측:
  - `market_status=false`: Phase 1a 조회 리허설에서는 주문 제출 전 필터라 비차단.
  - `kill_switch=false`: Phase 1a 조회 리허설에서는 live submit OFF 파일을 요구하지 않음.
- 권장안:
  - Phase 1a는 필요 시 장전마다 반복 실행한다.
  - 다음 구조 작업은 Phase 1b 실전 계좌 read-only shape 확인 준비로 넘어간다.
  - kill switch OFF 파일은 Phase 2 live-submit 준비 전까지 만들지 않는다.

### Phase 1b: 실전 계좌 read-only 확인

- 상태: 대기
- 목적:
  - 실제 자금 운용 전에 실전 계좌의 조회 권한, 응답 shape, 예수금/주문가능금액,
    T+2 관련 필드가 실제로 어떻게 오는지 확인한다.
- 중요한 경계:
  - 주문 금지.
  - 실전 주문 메서드가 없는 read-only client로만 확인한다.
  - `ALLOW_LIVE_ORDERS=false` 유지.
- 왜 필요한가:
  - 모의투자와 실전 계좌의 응답 필드, 권한, 예수금/주문가능금액 계산이 다를 수 있다.
  - 실제 운용 전 이 차이를 모르면 Phase 2에서 주문 가능 금액, 포지션,
    정합성 판단이 틀어질 수 있다.
- 남은 blocker:
  - 실전 KIS 조회용 credentials를 비밀 저장소에 준비.
  - live account read-only shape 확인.
  - sanitized NAS 복구 drill 표본.
- 권장안:
  - Phase 1a를 먼저 완료한다.
  - 그다음 실전 계좌 read-only를 1회 연결한다.

### Phase 2: 실전 1종목 소액 canary

- 상태: 미시작
- 조건:
  - Phase 1a/1b 관측 통과.
  - submit guard, audit, alert, kill switch, model gate 통과.
- 남은 blocker:
  - Phase 1 미통과.
  - active model 승격 기준 미충족.

### Phase 3: 다종목 일일 한도 운용

- 상태: 미시작
- 조건:
  - Phase 2 20~60거래일 관측.
  - 손실/슬리피지/체결/감사 안정.

## 4. 현재 P0 보드

### alpha/model predictive power

- 상태: 진행 중
- 현재 판단:
  - 안전·운영 인프라는 Phase 1/2 준비 수준으로 많이 올라왔지만,
    비용 차감 후 양수 예측력은 아직 입증되지 않았다.
  - 2026-06-12 보강으로 LightGBM `holdout_window_mismatch` 구조 문제는 닫혔다.
    최신 challenger 는 `dataset_scope=challenger_holdout_training_anchor`이고
    LightGBM `evaluation_independence_status=independent_challenger_holdout`이다.
  - gate reference walk-forward 는 새 3분류/가상 방향 지표로 재생성됐지만
    `three_class_accuracy=0.416342`, gate `needs_review`다.
  - LightGBM buy-signal diagnostics 는 threshold `0.40~0.80` 전 구간에서
    비용 차감 순수익률이 양수가 아니었다.
- 다음 작업:
  - threshold 조정만으로는 부족하므로 피처/라벨/모델 레시피 개선 실험으로 넘어간다.
  - LightGBM buy-signal diagnostics 를 다음 장후 학습 결과에도 반복해,
    threshold별 거래 수와 기대값이 개선되는지 비교한다.
- 권장안:
  - Phase 2 논의보다 먼저 alpha 연구 스프린트를 진행한다.
  - 우선순위는 피처 확장, 라벨 분포/보합 폭 재검토, LightGBM calibration 이다.

### broker paper sync rate-limit / local-only mismatch

- 상태: 진행 중
- 현재 판단:
  - 최신 broker paper sync 는 KIS `EGW00201`로 `rate_limited`다.
  - 최신 paper-account sync 는 `005380`, `035420`, `247540`, `373220`
    4종목 local-only mismatch 때문에 `needs_review`다.
  - 2026-06-11 보강은 같은 KIS order-fill endpoint 반복 호출을 줄이는 1차 방어이며,
    local-only mismatch 자체를 자동으로 덮지 않는다.
  - 2026-06-13 장외 1회 broker paper sync 재시도는 2분 안에 끝나지 않아
    Codex가 시작한 프로세스만 정리했다.
- 다음 작업:
  - rate-limit 이 풀린 뒤 order-fill 상태를 1회 확인한다.
  - 브로커 계좌와 local paper 의 4종목 원장 차이를 주문/체결/강제청산 흐름으로 추적한다.
- 권장안:
  - mismatch 는 marker-only alignment 로 덮기 전에 원장 원인을 먼저 확인한다.

### dashboard/watchdog daemon 유지

- 상태: 진행 중
- 현재 판단:
  - `python -m app --build-dashboard`는 정상 통과하고 최신 snapshot도 생성된다.
  - 2026-06-13 장외 복구 후 dashboard 와 runtime watchdog 은 모두 `running`이고,
    dashboard/API 응답과 watchdog heartbeat fresh 를 확인했다.
  - 단, 정규장 중 장시간 유지 증거는 아직 다음 실제 거래일 장중 실측이 필요하다.
- 다음 작업:
  - 다음 실제 거래일 정규장 중 dashboard/API 응답과 watchdog heartbeat가 10분 이내로 유지되는지 read-only로 확인한다.
  - 재부팅 자동 시작 경로와 Codex 수동 호출 경로의 차이는 계속 분리해서 본다.
- 권장안:
  - 장외 수동 복구는 완료로 보고, 장중 장시간 유지 확인만 별도 운영 blocker로 남긴다.

### read-only 구조적 차단

- 상태: 진행 중
- 완료:
  - `KisReadOnlyClient` 골격과 isolation 테스트 구현.
- 다음 작업:
  - Phase 1a/1b flow에 read-only client를 고정.
- 권장안:
  - Phase 1 기본 client는 주문 메서드가 없는 read-only client로 고정한다.

### live enable guard

- 상태: 진행 중
- 완료:
  - live order guard와 guarded adapter 구현.
  - submit guard 테스트 구현.
- 다음 작업:
  - streaming/live submit caller 연결 전 clock/phase gate 자동 주입.
- 권장안:
  - 주문 manager와 KIS adapter 양쪽에서 이중 확인한다.

### system clock 검증

- 상태: 진행 중
- 완료:
  - KIS REST HTTP `Date` parser.
  - readiness `--system-clock-check-path` 병합.
  - KIS paper read-only probe 1회 성공.
- 다음 작업:
  - Phase 1b에서 live account header shape와 paper/live 비교 증거 확보.
- 권장안:
  - raw header 저장 금지.
  - parsed reference time/skew/delta만 기록.

### market status readiness 증거

- 상태: 진행 중
- 완료:
  - repo-local 수동 snapshot probe 구현.
  - `docs/Manual-Market-Status-Runbook.md` 추가.
  - 수동 source enum 고정.
- 현재 blocker:
  - 실제 거래일 snapshot 없음.
- 권장안:
  - 자동 원천 전에는 수동 snapshot만 허용한다.
  - 증거 없으면 자동 통과시키지 않는다.

### kill switch 상태 파일

- 상태: 진행 중
- 현재 판단:
  - missing 상태는 fail-closed로 신규 live submit을 차단한다.
  - Phase 0 paper와 Phase 1 read-only에는 지금 OFF 파일을 만들 필요가 없다.
  - Phase 2 이후 live-submit readiness에서만 OFF 파일을 요구한다.
- 다음 작업:
  - read-only readiness와 live-submit readiness를 분리한다.
- 권장안:
  - pre-open/regular-session 중에는 명시 승인 없이 OFF 파일을 만들지 않는다.
  - missing/broken/stale은 계속 안전 차단으로 둔다.

### readiness local fixture snapshot

- 상태: Phase 1a 기준 통과
- 2026-05-28 Phase 1a 결과:
  - `token_refresh=true`
  - `ws_recovery=true`
  - `account_snapshot=true`
  - `system_clock=true`
  - `database=true`
  - `disk_space=true`
  - `dashboard=true`
  - `storage_migration_state=true`
  - `market_status=false`
  - `kill_switch=false`
- dry-run phase: `phase1a_paper_readonly`
- dry-run status: `ok`
- passed: `true`
- blocking reasons: 없음
- non-blocking reasons:
  - `market_status_fault_dry_run_failed`
  - `kill_switch_fault_dry_run_failed`
- 권장안:
  - Phase 1a read-only에서는 kill switch OFF를 요구하지 않는다.
  - Phase 1b와 Phase 2의 live-submit readiness는 별도 기준으로 유지한다.
  - Phase 2/3은 synthetic WS evidence를 통과시키지 않는다.

### Windows 장전 자동화

- 상태: 진행 중
- 완료:
  - Windows startup launcher를 현재 WSL 정본 경로로 갱신.
  - 로그인 직후 20초 대기와 repo-local 로그 기록 추가.
  - startup fast path는 `--skip-runtime-cleanup --skip-dashboard-build`로 실행.
- 다음 확인:
  - 2026-05-28 08:20 자동 실행 결과 확인.

## 5. 실전 계좌 read-only 연결 방법

### 사용자가 준비할 것

- KIS 실전 계좌 API 접근 권한.
- 실전용 app key와 app secret.
- 실전 계좌번호와 상품 코드.
- 위 값들은 저장소 문서, cowork 리포트, git 추적 파일에 적지 않는다.

### Codex가 처리할 것

- 비밀값은 `.env` 또는 `../secrets` 계열 로컬 비밀 저장소에서만 읽도록 한다.
- `ALLOW_LIVE_ORDERS=false`를 유지한다.
- 주문 메서드가 없는 read-only client만 사용한다.
- token refresh, account snapshot, current price/system clock만 조회한다.
- raw response와 계좌번호는 저장하지 않는다.
- sanitized shape와 count, 필드 존재 여부만 readiness 증거로 남긴다.

### 권장 절차

1. Phase 1a 모의투자 read-only 리허설을 먼저 완료한다.
2. 실전 credentials를 로컬 비밀 저장소에 준비한다.
3. read-only client로 token/account/current-price probe를 1회 실행한다.
4. 주문 함수 호출 0건을 확인한다.
5. paper/live 응답 shape 차이를 문서화한다.
6. 문제가 없으면 Phase 1b 관측 기간을 시작한다.

### 주의

- 실전 계좌 read-only는 실제 자금 주문을 보내는 단계가 아니다.
- 실전 주문 활성 플래그는 켜지 않는다.
- 실전 계좌 조회만으로도 민감 정보가 포함될 수 있으므로, 본문과 git에는 sanitized 결과만 남긴다.

## 6. 열린 결정 항목

- NAS 복구 drill 실행 시점:
  - 권장안은 Phase 1 전 sanitized drill 표본만 별도 폴더에서 확인.
- Phase 1b live account read-only 허용:
  - 권장안은 조회만 허용, 주문 메서드 없는 client로 수행.
- live account `system_clock` probe:
  - 권장안은 Phase 1b 승인 뒤 주문 메서드 없는 client로 1회 실행.
- read-only readiness와 live-submit readiness 분리:
  - 권장안은 Phase 1 read-only는 kill switch OFF 없이 통과 가능하게 한다.
  - live-submit/Phase 2에서만 OFF 파일을 요구한다.
- 외부 알림 채널:
  - 권장안은 Telegram 기본, 중요 사고는 email 병행.

## 7. 작업 종료 체크리스트

매 작업 마지막에는 아래를 확인한다.

- 이 문서의 현재 스냅샷 갱신.
- Phase/P0 상태 갱신.
- 새 blocker와 다음 권장 작업 기록.
- `docs/logbook.md` 최신 entry 확인.
- 최종 보고에 이 파일 링크 출력.

관련 문서/코드 경로:
`docs/logbook.md`,
`docs/cowork-reports/README.md`
