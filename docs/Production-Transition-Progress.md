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

### 2026-07-11 02:45 KST 장외 스냅샷

- 주말 상태에서 live runtime은 정상 정지, watchdog/dashboard/startup launcher는 정상 실행 중이다.
- 금요일 장후 ML은 `status=ok`, `completed_at=2026-07-10 16:17:58 +0900`, `mode=quick-live-train`이고 label refresh도 `status=ok`, `completed_at=2026-07-10 16:50:42 +0900`다. 중복 학습은 실행하지 않았다.
- review_ver_27의 2026-07-20 장후 E1/E5 라운드를 `scripts/run_preregistered_e1_e5_round.py/.sh`로 단일 실행화했다. 날짜·장 상태·2026-07-20 label refresh gate, D드라이브 연구 snapshot, 고정 구간 `2026-07-04~2026-07-18`, E1 후보 3건 재현성, `105560` p_flat 및 p_down/p_up 관계, E5 threshold `0.40` random-control 비교를 코드와 합성 테스트로 잠갔다.
- 현재 dry-run은 `before_preregistered_not_before`로 정상 차단됐고 네트워크·주문 호출은 각각 0건이다. 실제 E1/E5 결과는 아직 생성하지 않았으며 첫 허용 시각은 `2026-07-20 15:30 KST`다.
- Phase 1b 실전계좌 read-only 제한 관측을 2026-07-11 주말 장외에 완료했다. live token, paper/live account shape, live system clock 및 전용 readiness가 모두 통과했고 네트워크 호출은 4회, 주문 메서드 호출은 0회였다. 이는 실제 주문 단계 진입이 아니라 조회 경로 검증 완료다.
- 다음 외부 시점 작업은 다음 거래일 장후 mismatch 4종목 1회 재확인, 정규장 dashboard/watchdog 장시간 관측, 2026-07-20 장후 E1/E5 실측이다.
- 주문 정책, gate, active model, KIS live shadow 범위, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`는 변경하지 않았다.

### 2026-07-10 22:10 KST 장후 스냅샷

- live runtime은 `stopped/post-close`, watchdog과 dashboard는 `running`이고 오류 없이 정상 응답 중이다.
- 장후 ML은 `status=ok`, `completed_at=2026-07-10 16:17:58 +0900`, `mode=quick-live-train`이다. label refresh도 `status=ok`, `completed_at=2026-07-10 16:50:42 +0900`로 완료됐다.
- active model은 `baseline-h15-v1`을 유지한다. challenger 권고는 `keep_active`, `promotion_applied=false`, gate는 `needs_review`다. top challenger `fresh_centroid`는 3분류 정확도 `0.314705`, 매수 신호 적중률 `0.75`, 누적 순수익률 합 `+5.444049%p`, 거래 `4건`이라 표본 부족을 먼저 본다.
- KIS live data quality는 `assessment.status=ok`, 최신 거래일 `2026-07-10`, 거래일 `50일`, feature/bar 비율 `1.0`, h15 label/feature 비율 `0.973009`다. 다만 Cybos와 KIS 사이 `bid_ask_imbalance`, `spread_bps` source drift와 단일 피처 신호 부족은 계속 관찰한다.
- `./scripts/recheck_paper_kis_mismatch.sh`를 장후 1회 실행했다. broker sync는 `status=ok`, open order `0`, pending symbol 없음이지만 reconciliation은 4종목(`035420`, `086520`, `105560`, `247540`) 불일치로 `needs_review`다. 네 종목 모두 local paper 수량은 KIS order/fill 원장 순수량과 맞고, KIS 계좌 snapshot 수량만 달라 `kis_account_snapshot_vs_order_fill_ledger_divergence`로 분류한다. 자동 align과 `SyncInitialCash`는 계속 보류한다.
- order/fill 조회 중 `EGW00201` 제한 경고가 3회 발생했으나 10/30/60초 대기 후 wrapper는 정상 완료됐다. 같은 endpoint는 오늘 다시 호출하지 않는다.
- 이 관측으로 미완료였던 P0 호출량 축소를 적용했다. 기본 helper, 장후 batch, 장중 종료 force sync는 이제 HTTP 1회만 시도하고, 최초 제한부터 2시간 cooldown과 남은 초를 기록한다.
- recheck wrapper도 보강해 실제 실행 결과와 dry-run/차단 시도 파일을 분리했다. 자기검토 중 덮인 최신 wrapper 요약은 보존된 sync·reconciliation·trace 증거에서 복원했고, dry-run 전후 SHA-256이 동일함을 확인했다.
- buy-avoid threshold `0.40`은 2026-06-11~2026-07-10 `joined_rows=33,007`, skip `9,002`, raw net delta `+846.0341%p`다. 그러나 random control 대비 excess가 `+238.2658%p`, z-score `4.1266`, verdict `filter_worse_than_random_p95`이므로 주문 정책 후보로 승격하지 않고 관측만 유지한다.
- buy-rescue는 Cybos 결과 `buy_avoid_candidate_only`를 유지한다. KIS live no-trade ledger가 없어 live 실패로 단정하지 않는다.
- hold-rescue replay는 eligible lot `161`, 적용 lot `37`, `delta_cash_sum=-26,387원`, 개선 비율 `35.135%`, 비음수 거래일 비율 `21.429%`로 `diagnostic_only_no_hold_rescue_candidate`다.
- 주문 정책, gate, active model, KIS live shadow 범위, `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`는 변경하지 않았다. 2026-07-18 이후 첫 거래일 장후 E1/E5 예약과 실험 동결도 유지한다.

### 2026-07-07 01:15 KST 스냅샷

- review_ver_29 §5 운영자 승인에 따라 Phase 1 readiness 규격 준비를 시작했다.
- `scripts/prepare_market_status_snapshot_template.sh`를 추가하고, `runtime-data/reports/live-readiness/market-status-snapshot.json`에 watchlist 10종목 fail-closed 템플릿을 생성했다. 현재 check는 `allowed_count=0`, 모든 종목 `tradable_unknown`으로 차단된다.
- `scripts/set_live_kill_switch.sh --enable --reason phase1_readiness_preparation_fail_closed --actor account_owner --apply`로 kill switch 상태 파일을 만들었다. 상태 파일은 존재하지만 `enabled=true`라 submit 차단이 유지된다.
- read-only/offline 증거를 현재 시점에서 재생성했다. `ws_recovery`, `token_refresh`, `account_snapshot`, `system_clock`은 ok 이며, readiness blocker 는 의도대로 `market_status_fault_dry_run_failed`, `kill_switch_fault_dry_run_failed` 두 개다.
- 다음 장전 체크에서는 `.agents/skills/daily-ops-check/SKILL.md` 기준으로 `ws_recovery` 증거를 다시 만들고, `token_refresh`, `account_snapshot`, `system_clock`을 장전 시간대에 재확인한다. 현재 야간 증거는 장전 증거를 대체하지 않는다.
- 실험 동결: 2026-07-18 이후 첫 거래일 장후 E1/E5 라운드 전까지 신규 threshold/EV tuning, 종목별 주문 정책, h60 주문 정책, active model/gate 변경은 하지 않는다.
### 2026-07-07 최신 스냅샷

- 마지막 갱신: 2026-07-07 00:20 KST, review_ver_28 P0/P1 반영.
- KIS read-only probe 3종: `token_refresh`, `account_snapshot`, `system_clock` 모두 현재 증거상 ok 다. readiness blocker 는 이 3종이 아니라 `ws_recovery` stale, `market_status`, `kill_switch`다.
- account_snapshot과 mismatch 관계: account snapshot probe는 API 호출과 shape 검증은 통과했다. paper/KIS mismatch는 account snapshot API 실패가 아니라 KIS 계좌 snapshot 수량과 KIS order/fill 원장 순수량 사이의 divergence 로 본다.
- PreRegistration: OB-1 다중 비교 수 `k=12`, OB-2 다중 비교 수 `k=24`를 사전 고정했다. h60은 random-control `abs(z_score) >= 2.5`, empirical 5% 밖, `days_usable >= 10`, `symbols >= 5`, `virtual_trades >= 100`을 최소 기준으로 둔다.
- 실험 동결: 2026-07-18 이후 첫 거래일 장후 E1/E5 라운드 전까지 신규 threshold/EV tuning, 종목별 주문 정책, h60 주문 정책, active model/gate 변경은 하지 않는다.
### 2026-07-06 최신 스냅샷

- 마지막 갱신: 2026-07-06 20:50 KST, 장후 운영 체크와 다음 거래일 paper/KIS mismatch 재확인.
- live runtime: stopped/post-close 로 정상이다. `stopped_at=2026-07-06 15:31:01 +0900`, `process_running=false`.
- runtime watchdog: running 이고 `post_close_ml_enabled=true`, `ml_maintenance_action=already_ok`, `errors=[]`, heartbeat fresh 상태다.
- dashboard: running 이고 API 응답 중이다. 장후 스냅샷은 `runtime-data/reports/dashboard/latest-dashboard.json` 기준 `generated_at=2026-07-06T20:45:30.914283+09:00`로 갱신됐다.
- 장후 ML: `runtime-data/reports/ml-maintenance/state/latest-post-close-ml.json` 기준 `status=ok`, `maintenance_date=2026-07-06`, `completed_at=2026-07-06 16:15:41 +0900`, `mode=quick-live-train`.
- 장후 label refresh: `runtime-data/reports/ml-maintenance/state/latest-post-close-label-refresh.json` 기준 `status=ok`, `maintenance_date=2026-07-06`, `completed_at=2026-07-06 16:49:06 +0900`.
- challenger: `runtime-data/reports/challengers/latest-challengers-h15.json` 기준 active `baseline-h15-v1`, `recommended_action=keep_active`, `recommended_model_version=baseline-h15-v1`, `promotion_applied=false`. top challenger 는 `centroid-challenger-h15-v1`, `three_class_accuracy=0.298914`, `trade_hit_rate=0.5`, `cumulative_net_return_pct=1.843915`, `trades_taken=2`라 표본이 작아 수익률 숫자를 확대 해석하지 않는다.
- paper/KIS mismatch recheck: `./scripts/recheck_paper_kis_mismatch.sh` 실행 완료. wrapper status 는 `ok`였지만 trace assessment 는 계속 `needs_review`다. mismatch 5종목(`005380`, `035420`, `086520`, `105560`, `247540`) 모두 root cause scope 가 `kis_account_snapshot_vs_order_fill_ledger_divergence`로 유지됐다. broker sync 는 `open_order_count=1`, `pending_symbols=["068270"]`이다. 자동 align 은 계속 보류한다.
- buy-avoid: `runtime-data/reports/challengers/latest-lightgbm-defensive-shadow-h15.json` 기준 2026-06-11~2026-07-03, `joined_rows=25,198`, threshold `0.40` 후보의 net delta 는 `+486.3753%p`이나 random-control verdict 는 `filter_worse_than_random_p95`다. 따라서 주문 정책 후보가 아니라 30/60거래일 checkpoint 관측 후보로 유지한다.
- buy-rescue: `runtime-data/reports/backtests/latest-cybos-rescue-proxy-h15.json` 기준 `decision.status=buy_avoid_candidate_only`, KIS live no-trade ledger 는 아직 없어 live buy-rescue 실패로 단정하지 않는다.
- hold-rescue: `runtime-data/reports/challengers/latest-hold-rescue-paper-replay-h15.json` 기준 `decision.status=diagnostic_only_no_hold_rescue_candidate`, `generated_at=2026-07-06T20:42:14+09:00`다.
- 현재 목표 상태: 진행 중. paper/KIS mismatch 는 다음 장후에도 같은 패턴이 유지되는지 계속 보고, 2026-07-18 이후 첫 거래일 장후 E1/E5 라운드 전까지 신규 threshold/EV tuning, 종목별 주문 정책, h60 정책, active model/gate 변경은 하지 않는다.

### 2026-07-05 최신 스냅샷

- 마지막 갱신: 2026-07-05 20:40 KST, 주말/장외 read-only 점검과 mismatch recheck 주말 차단 보강.
- live runtime: stopped/weekend 로 정상이다. runtime watchdog 은 running 이고 heartbeat fresh 상태다.
- KIS read-only probe: token_refresh, account_snapshot, system_clock 모두 ok 로 복구됐다. system_clock 은 quote endpoint 재호출 대신 account_snapshot read-only 응답의 HTTP Date 를 재사용해 `skew_seconds=0.029246`으로 통과했다. 남은 Phase readiness blocker 는 KIS 3종 probe 가 아니라 `ws_recovery` stale, `market_status`, `kill_switch`다.
- paper/KIS mismatch trace: `runtime-data/reports/reconciliation/latest-paper-kis-mismatch-trace.md` 기준 5종목 모두 로컬 paper 수량과 KIS order-fill 순수량이 일치하지만 KIS 계좌 잔고 snapshot 수량이 다르다. root_cause_scope 는 `kis_account_snapshot_vs_order_fill_ledger_divergence`다. 자동 align 은 보류하고 다음 거래일 장후 계좌 snapshot 과 order-fill snapshot 을 재비교한다. `scripts/recheck_paper_kis_mismatch.py`는 주말/휴장일을 기본 차단해 주말 재실행 결과가 완료 증거로 기록되지 않게 보강했다.
- buy-avoid: review_ver_27 기준 2026-07-18 전까지 신규 실험은 동결하고, 현재는 전체 pytest 결과 보고 한 줄만 닫았다. 07-18 이후 첫 거래일 장후 E1 재측정과 E5 역발상 관찰을 한 라운드로 진행한다.

### 2026-07-05 목표 완료 감사

- 항목 1 KIS read-only probe 3종: 현재 증거상 완료. `token_refresh`, `account_snapshot`, `system_clock` 모두 ok 이며 system_clock 은 계좌 snapshot 응답 Date 재사용으로 quote rate limit 문제를 우회했다.
- 항목 2 paper/KIS mismatch 5종목: 원인 범위는 규명됐지만 최종 종결은 보류. 현재 root_cause_scope 는 5종목 모두 `kis_account_snapshot_vs_order_fill_ledger_divergence`다. 다음 거래일 장후 `./scripts/recheck_paper_kis_mismatch.sh`로 같은지 재측정해야 완료로 볼 수 있다.
- 항목 3 Cybos-KIS 격차와 orderbook 가설: 문서화 완료. `docs/Model-Research-PreRegistration.md` 기준으로 2026-07-18 이후 KIS live 데이터로만 검증한다.
- 항목 4 h60 트랙 사전등록: 초안 완료. h60 주문 정책은 만들지 않았고, 07-18 이후 daily IC, random-control, h15/h60 충돌표, paper-only replay 가능성부터 본다.
- 현재 목표 상태: 진행 중. 남은 필수 증거는 다음 거래일 장후 mismatch 재확인과 07-18 이후 첫 거래일 장후 E1/E5 라운드다.

### 2026-07-04 최신 스냅샷

- 마지막 갱신: 2026-07-04 20:40 KST, `review_ver_22` 대응 후속 점검.
- 현재 장 상태: 토요일/주말. live runtime 은 stopped 로 정상이다.
- runtime watchdog: stale 상태를 확인한 뒤 `scripts/start_runtime_watchdog_background.sh`로 재기동했고, pid `17046`에서 heartbeat 가 fresh 상태다.
- dashboard: stale 상태를 확인한 뒤 `scripts/start_dashboard_background.sh`로 재기동했고, `http://127.0.0.1:8765`에서 응답 중이다. 최신 snapshot 은 `runtime-data/reports/dashboard/latest-dashboard.html` 기준 `generated_at=2026-07-04T20:38:03+09:00`이다.
- 최신 cowork 리뷰: `docs/cowork-reports/2026-07-04-repo-goal-and-direction-deep-review-review_ver_22.md`.
- 최신 Codex 후속 리포트: `docs/cowork-reports/2026-07-04-repo-goal-and-direction-deep-review-work_ver_22.md`.
- buy-avoid shadow: `runtime-data/reports/challengers/latest-lightgbm-defensive-shadow-h15.json` 기준 2026-06-11~2026-07-03, `joined_rows=25,198`, threshold `0.40`, skip `6,694`, net delta `+486.38%p`로 10거래일 checkpoint 는 충족했다. 단, 이것은 손실 축소 관측 후보이지 주문 정책 반영 근거가 아니다.
- gate walk-forward 재검증: `runtime-data/reports/backtests/latest-walk-forward-h15.json` 기준 `walk-forward-h15-20260704201528027664`, `folds=118`, `rows_evaluated=5,900,000`, `three_class_accuracy=0.416342`, gate 는 계속 `needs_review`다.
- challenger 재평가: `runtime-data/reports/challengers/latest-challengers-h15.json` 기준 `challenger-h15-20260704203559674231`, active `baseline-h15-v1`, `recommended_action=keep_active`, `promotion_applied=false`다.
- paper/KIS mismatch trace: `runtime-data/reports/reconciliation/latest-paper-kis-mismatch-trace.json`를 갱신했다. broker sync 는 `status=ok`, open order `0`이지만, position mismatch 는 5종목이 남아 있다.
- live readiness: `runtime-data/reports/live-readiness/latest-readiness.json` 기준 `phase1a_paper_readonly`, `status=blocked`다. synthetic `ws_recovery`, database, disk_space, dashboard, storage_migration_state 는 통과했지만, KIS read-only `token_refresh`, `account_snapshot`, `system_clock` probe 가 `KisApiError`로 실패했다. `market_status`와 `kill_switch`는 비차단 미확인이다.
- social signal shadow: `runtime-data/reports/research/latest-social-signal-shadow-h15.json` 기준 `status=no_events_file`, `event_count=0`, `matched=0`이다. 현재는 인프라만 준비된 상태이며 SNS 효과 검증은 시작되지 않았다.
- 아래 2026-07-04 스냅샷은 보존 기록이며, 현재 기준은 위 2026-07-05 스냅샷이다.

- 마지막 갱신: 2026-07-03 03:50 KST
- 현재 런타임: `overnight`
- live runtime: stopped. 장전 warmup 전 야간 정지 상태가 정상.
- runtime watchdog: running. `live_runtime_should_run=false`, `errors=[]`, heartbeat fresh.
- dashboard: running. `http://127.0.0.1:8765` 서버와 API가 응답 중.
- trading mode: `paper`
- 최신 meta-policy shadow:
  `runtime-data/reports/research/latest-meta-policy-shadow-h15.json`
  기준 Phase 1 적용 방향은 `baseline 주문 판단 유지 + meta filter/router 후보 shadow 관측`이다.
  주문 정책, gate, active model, KIS live shadow 확장은 바꾸지 않는다.
- 최신 social signal shadow:
  `runtime-data/reports/research/latest-social-signal-shadow-h15.json`
  기준 SNS/공개 영향력 이벤트는 Phase 1에서 공식 API, 공개 feed, 수동 export 만 허용하고,
  주문 신호가 아니라 사후 평가/연구 피처 후보로만 본다.
- 최신 cowork 기준:
  `docs/cowork-reports/2026-06-14-repo-goal-and-direction-deep-review-review_ver_21.md`
- 최신 통합/후속 리포트:
  `docs/cowork-reports/2026-06-14-repo-goal-and-direction-deep-review-work_ver_20-10.md`
- 최신 cowork review_ver_21 판정:
  2026-06-14 Codex 작업 주장-실제 일치율은 높음.
  buy-rescue 는 wide/precision grid 모두 탈락했고 KIS live shadow 추가 없음이 타당하다.
  broker mismatch 와 open order backlog 는 현재 해소됐지만, 월요일 장중/장후에 새 broker sync 경로와 EGW00201 재발 여부를 관찰해야 한다.
- 최신 Cybos rescue 실험 계획:
  `docs/cowork-reports/2026-06-14-cybos-rescue-experiment-plan.md`
- 최신 Phase readiness:
  `runtime-data/reports/live-readiness/latest-readiness.json`
  기준 `phase1a_paper_readonly`, `status=ok`, `source=fixture-dry-run`,
  `generated_at=2026-06-13T13:34:06+09:00`.
  token/account/system_clock/ws_synthetic/dashboard/database evidence는 최신 freshness 기준을 통과했다.
  `market_status`와 `kill_switch`는 Phase 1a read-only에서 비차단 관측 실패로 남는다.
- 최신 dashboard snapshot:
  `runtime-data/reports/dashboard/latest-dashboard.html`
  기준 `generated_at=2026-06-15T16:36:56+09:00`.
- 최신 장전 readiness:
  `runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json`
  기준 `generated_at=2026-06-15 08:20:01 +0900`, `status=ok`, warnings/blockers 없음.
- 최신 장후 ML maintenance:
  `runtime-data/reports/ml-maintenance/state/latest-post-close-ml.json`
  기준 `completed_at=2026-06-15 16:12:41 +0900`, `status=ok`, `mode=quick-live-train`.
- 최신 장후 label refresh:
  `runtime-data/reports/ml-maintenance/state/latest-post-close-label-refresh.json`
  기준 `completed_at=2026-06-15 16:36:47 +0900`, `status=ok`.
- 최신 KIS live data quality:
  `runtime-data/reports/data-quality/latest-kis-live-data-quality.json`
  기준 latest trade date `2026-06-15`, `assessment.status=ok`.
- 최신 검증:
  `python -m py_compile scripts/summarize_cybos_buy_avoid_proxy.py tests/test_cybos_buy_avoid_proxy.py` 통과,
  `python -m unittest tests.test_cybos_buy_avoid_proxy -q` 15개 통과,
  `python -m unittest tests.test_cybos_buy_avoid_proxy tests.test_cybos_research_suite_summary tests.test_expected_value_stability -q` 17개 통과,
  `python -m unittest discover -s tests -p "test_*.py" -q` 412개 통과,
  `python -m py_compile app/services/broker_paper_sync.py scripts/summarize_broker_order_backlog.py scripts/summarize_paper_cash_gap.py tests/test_broker_paper_sync.py tests/test_broker_order_backlog_analysis.py tests/test_paper_cash_gap_analysis.py` 통과,
  `python -m unittest tests.test_broker_paper_sync tests.test_broker_order_backlog_analysis tests.test_paper_cash_gap_analysis -q` 19개 통과,
  `python -m unittest tests.test_broker_paper_sync tests.test_broker_order_backlog_analysis tests.test_paper_cash_gap_analysis tests.test_paper_reconciliation tests.test_paper_alignment tests.test_wsl_ops -q` 43개 통과,
  `python -m unittest tests.test_runtime_scope` 4개 통과,
  `python -m unittest tests.test_dashboard -q` 23개 통과,
  `python -m app --build-dashboard` 통과,
  `git diff --check` 통과. CRLF/LF 경고만 확인.
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
  기준 `2026-06-11`~`2026-07-03` KIS live h15 연결 표본 `25,198`건을
  baseline 매수 허용 신호와 같은 시각 LightGBM 하락확률로 걸러 봤다.
  down threshold `0.40`은 매수 회피 `6,694`건, baseline 대비 비용 차감 누적 순수익률 delta
  `+486.3753%p`였지만, 같은 coverage 무작위 회피 기대값 `-711.8525%p`보다 실제 회피 손익
  `-486.3753%p`가 덜 나빠 `excess_vs_random_pct=+225.4772`, `z_score=+4.6278`,
  `verdict=filter_worse_than_random_p95`, `random_control_gate.passed=false`다.
  따라서 KIS live buy-avoid 의 현재 표준 표현은 `재검증 필요, 무작위 대조군 대비 우위 미확인`이다.
  조기청산 shadow 는 기존 기준에서도 실제 paper 청산보다 악화되어 계속 보류다.
  공식 10거래일 checkpoint 는 찼지만, 2026-07-04~2026-07-18 구간까지 같은 기준으로 reverse-selection 패턴 지속 여부를 본다.
- 최신 Cybos buy-avoid / rescue proxy:
  `runtime-data/reports/backtests/latest-cybos-buy-avoid-proxy-h15.json`
  기준 `generated_at=2026-07-05T02:27:46.310251+09:00`, `source=cybos-historical`,
  `feature_set=bar_context_momentum`, `trade_cost_pct=0.13`,
  `decision=follow_up_candidate_proxy_only`.
  KIS `down_threshold=0.40` 수치는 직접 옮기지 않고 skip-rate coverage 로 비교했다.
  KIS shadow 회피율에 맞춘 target skip `0.3665`는 실제 skip `0.3617`,
  baseline net `-538.040362%p`, kept net `-170.325157%p`,
  net 개선 `+367.715205%p`, 개선 fold `12/12`다.
  random-control aggregate 는 `expected_random_skipped_sum_pct=-182.1662`,
  `actual_skipped_cumulative_net_pct=-367.7152`, `excess_vs_random_pct=-185.5490`,
  `z_score=-6.3607`, `verdict=filter_better_than_random_p95`다.
  전체 target `0.20/0.30/0.3665/0.40/0.50`도 모두 aggregate verdict 가 `filter_better_than_random_p95`였다.
  단, 여기서 baseline 은 실제 runtime baseline 주문 판단이 아니라 Cybos LightGBM 이 만든 proxy 매수 후보 집합이다.
  따라서 이 결과는 Cybos proxy 내부의 손실 축소 후보 근거이지, KIS live 주문 정책 전이 근거가 아니다.
  kept net 이 여전히 음수이므로 모델 승격, gate 변경, paper/live 주문 정책 변경 근거도 아니다.
  같은 full 실행에서 생성한 `runtime-data/reports/backtests/latest-cybos-rescue-proxy-h15.json`
  기준 rescue decision 은 `buy_avoid_candidate_only`다.
  `runtime_baseline_replay.status=not_replayed_orderbook_features_missing`이고,
  `buy_rescue_definition.experiment_mode=proxy_buy_rescue`다.
  buy-rescue target `0.05`, `0.10`, `0.20`, `0.30`은 모두 비용 반영 rescued net 이 음수였고,
  target `0.05`도 `rescued_trades=33,135`, `rescued_net_return_pct=-3,526.921975%p`,
  nonnegative fold share `0/12`였다.
  따라서 KIS live 에서는 buy-rescue shadow 를 추가하지 않고, buy-avoid shadow 순차 관측을 유지한다.
- 최신 Cybos regime performance 진단:
  `runtime-data/reports/backtests/latest-cybos-regime-performance-h15.json`
  기준 고변동 구간은 accuracy `0.467210`, buy signal net `-435.709195%p`,
  reference buy-avoid delta `+220.787918%p`로 가장 취약했다.
  이 리포트는 기존 `latest-walk-forward-extreme-fold-regimes-h15`의 gate 극단 fold 분석과 달리
  Cybos 5년 proxy fold 를 범위로 하며, 새 regime별 모델을 만들기 전 원인 후보를 좁히는 진단이다.
- 최신 Cybos rescue 계획:
  `docs/cowork-reports/2026-06-14-cybos-rescue-experiment-plan.md` 기준으로,
  장외 Cybos 에서는 `buy-avoid`와 `buy-rescue`를 같은 리포트에서 함께 보되
  고정 threshold grid 와 다중 검정 guardrail 을 먼저 둔다.
  2026-06-14 Step 0 확인 결과 Cybos bar row 는 runtime baseline 이 요구하는
  `bid_ask_imbalance`, `spread_bps`를 갖지 않으므로, 1차 rescue 실험은
  `baseline_replay_buy_rescue`가 아니라 `proxy_buy_rescue`로 진행한다.
  KIS live 에서는 `buy-avoid`를 최소 10거래일 순차 검증하고,
  `buy-rescue`는 Cybos 결과와 비매수/차단 로그 가용성 확인 뒤 shadow 후보로만 검토한다.
  `hold-rescue`는 포지션 lifecycle 이 달라 별도 설계와 synthetic test 이후에만 진행한다.
- 최신 Cybos rescue full:
  `runtime-data/reports/backtests/latest-cybos-rescue-proxy-h15.json`
  기준 `generated_at=2026-06-14T22:02:31+09:00`, `review=cybos_rescue_proxy`, `decision.status=buy_avoid_candidate_only`,
  `recommended_action=Keep KIS buy-avoid shadow running; do not add KIS buy-rescue shadow yet.`,
  `hold_rescue_lifecycle_spec.status=not_executed_in_this_report`다.
  기존 wide rescue target `0.05`, `0.10`, `0.20`, `0.30`은 모두 비용 반영 순손익이 음수다.
  추가 정밀 rescue target `0.001`, `0.0025`, `0.005`, `0.01`, `0.02`, `0.03`, `0.05`도 모두 통과하지 못했다.
  `0.001` target 은 rescued trade `727`건, 거래당 평균 총수익 `0.005543%`, 거래당 평균 순수익 `-0.124457%`,
  `0.01` target 은 거래당 평균 총수익 `0.047194%`, 거래당 평균 순수익 `-0.082806%`로 비용 `0.13%`를 넘지 못했다.
  따라서 buy-rescue 는 `넓게 잡아서 실패`가 아니라 `현재 상승 신호가 거래비용을 이길 만큼 강하지 않음`으로 본다.
  full 12 fold 실행 시간은 약 `1,610`초였으므로 잦은 재실행이 필요하면 성능 최적화를 먼저 검토한다.
- 최신 hold-rescue lifecycle 준비:
  2026-06-14 기준 `scripts/summarize_cybos_buy_avoid_proxy.py`에
  `_simulate_hold_rescue_lifecycle` synthetic helper 를 추가했다.
  이 helper 는 entry, baseline exit, rescue threshold, 최대 연장 step, 최대 손실 제한,
  거래비용을 받아 baseline 청산 대비 rescue 보유 연장의 손익 차이와 exit reason 을 계산한다.
  `tests/test_cybos_buy_avoid_proxy.py`는 보유 연장, threshold 미충족, probability drop,
  max loss exit 을 합성 경로로 검증한다.
  이는 Cybos full hold-rescue 결과 실험이 아니라 lifecycle 구현 전제 검증이다.
- 최신 hold-rescue paper replay feasibility:
  `runtime-data/reports/challengers/latest-hold-rescue-paper-replay-feasibility-h15.json`
  기준 `generated_at=2026-06-17T22:35:49+09:00`, `decision.status=feasible_for_offline_replay`다.
  `scripts/summarize_hold_rescue_paper_replay_feasibility.py`가 `paper_orders`, `paper_fills`,
  `serving_predictions`, `curated_minute_bars`를 read-only 로 확인했다.
  2026-06-11 이후 닫힌 paper lot `108`건 중 LightGBM exit 예측 매칭 `103`건,
  이후 h15 분봉 매칭 `103`건으로, 다음 단계의 offline hold-rescue replay 리포트 구현은 가능하다.
  단, `orphan_sell_events_present`, `open_lots_remaining`, `non_weekday_exit_lots_present` warning 이 있으므로
  본 replay 에서는 시작 전 보유 lot, 장외/주말 sync 로 닫힌 lot, 미청산 lot 을 분리해야 한다.
  이 판정은 성과 검증이 아니라 원장 연결 준비도이며, KIS live shadow, paper 주문 정책,
  active model, gate 기준값은 바꾸지 않는다.
- 최신 hold-rescue paper-only replay:
  `runtime-data/reports/challengers/latest-hold-rescue-paper-replay-h15.json`
  기준 `generated_at=2026-06-19T00:46:53+09:00`, `decision.status=diagnostic_only_no_hold_rescue_candidate`다.
  `scripts/summarize_hold_rescue_paper_replay.py`가 actual paper exit 을 baseline 으로 두고,
  LightGBM `probability_up` threshold 별 추가 보유 결과를 read-only 로 계산한다.
  replay 가능 lot 은 `97`건이고, exit 시점 `probability_up`은 p50 `0.353297`, p90 `0.422203`,
  max `0.465518`로 강한 상승 지속 신호가 부족했다.
  threshold `0.40`은 적용 lot `20`건에서 `-21,487원`, threshold `0.45`는 적용 lot `3`건에서
  `-6,496원`으로 baseline paper 청산보다 악화됐으며, `0.50` 이상은 적용 lot 이 없다.
  따라서 hold-rescue 는 Phase 0/1 현재 단계에서 KIS live shadow, paper 주문 정책,
  active model, gate 기준값 변경으로 올리지 않는다. buy-avoid 공식 10거래일 shadow 관측을 우선한다.
- 최신 paper/KIS mismatch trace:
  `runtime-data/reports/reconciliation/latest-paper-kis-mismatch-trace.json`
  기준 `assessment.status=ok`, mismatch count `0`, summary `no mismatched symbols`다.
  2026-06-12 15:07~15:08 청산 주문은 2026-06-14 broker paper sync 에서 fill 로 반영되어
  local position 도 브로커 flat 상태와 일치했다.
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
- dashboard bar builder lag 경고 노출:
  `tests/test_dashboard.py::DashboardTests.test_status_alerts_warn_when_regular_session_minute_bars_are_stale`를 추가해,
  live runtime 이 `running`이고 KIS session 이 `regular-session`인데 `latest_market_bar`가 stale이면
  dashboard status alert에 `실시간 분봉 갱신이 지연되고 있습니다` warning 이 노출되는지 잠갔다.
  따라서 review_ver_19의 장외 P1-A는 테스트 기준으로 닫혔다.
- 최신 paper/KIS 정합성:
  최신 `runtime-data/reports/reconciliation/latest-paper-account-sync.json`
  기준 `status=needs_review`, mismatch count `5`다.
  2026-06-15 broker paper sync 재시도는 KIS `EGW00201` 초당 거래건수 초과로 실패했고,
  local/broker 보유 수량이 달라 marker-only alignment 는 적용하지 않았다.
- 최신 broker paper sync:
  `runtime-data/reports/broker-paper/latest-sync.json`
  기준 `status=rate_limited`, `open_order_count=5`, pending symbols 는
  `005930`, `035420`, `068270`, `105560`, `247540`이다.
  같은 KIS order-fill endpoint 반복 호출은 중지하고 다음 장후 또는 제한 해제 뒤 1회만 재시도한다.
- 최신 broker order backlog analysis:
  `runtime-data/reports/broker-paper/latest-open-order-backlog-analysis.json`
  기준 marker 이후 현재 view 는 `submission_rows=0`, `current_open_order_count=0`,
  `projected_open_order_count=0`, 권고 `backlog_cleared_no_action`이다.
- 최신 paper cash gap analysis:
  `runtime-data/reports/reconciliation/latest-paper-cash-gap-analysis.json`
  기준 권고는 `keep_current_alignment`, 다음 조치는 `no_cash_gap_action_required`다.
  `SyncInitialCash`와 추가 `AlignToBroker`는 지금 필요하지 않다.
- 최신 forced NAS backup:
  `/mnt/backup/repos/real-time-stock-price-prediction-program/recovery-exports/real-time-stock-price-prediction-program-recovery-20260528-224455.tar.gz`
  (`5558128973` bytes).
- NAS 백업 실행 기준:
  앞으로 Codex는 주간/강제 NAS 백업을 자율 실행하지 않고,
  사용자가 해당 작업에서 명시적으로 지시했을 때만 실행한다.
- 다음 cowork 리뷰 권장 시점:
  월요일 장후 P0-4 watchdog heartbeat 실측, P0-broker EGW00201 재발 여부,
  broker_paper_sync final-state 보존 경로의 실제 주문 처리 관찰 결과가 생긴 뒤 전달한다.

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
  - KIS live data quality 최신 리포트는 `assessment.status=ok`로 회복됐다.
    2026-06-05, 2026-06-08, 2026-06-09에 반복된 `watch` 원인은
    2026-06-13 read-only 조회로 1차 정리했고, 현재는 2026-06-08처럼
    raw market symbol-minute 가 약한 구간이 재발하는지만 다음 거래일에 관찰한다.
  - 2026-07-10 장후 broker paper sync 는 `status=ok`, open order `0`,
    pending symbol 없음이다.
  - 최신 reconciliation 은 `status=needs_review`, mismatch count `4`다.
    대상은 `035420`, `086520`, `105560`, `247540`이며, local paper 수량은 KIS
    order/fill 원장 순수량과 맞고 KIS 계좌 snapshot 수량만 다르다. root cause scope는
    `kis_account_snapshot_vs_order_fill_ledger_divergence`다.
  - 수량 불일치가 계좌 snapshot과 원장 사이에 남아 있으므로 marker-only alignment와
    `SyncInitialCash`는 적용하지 않는다.
  - 2026-07-10 작업에서 broker paper sync 는 한 실행당 HTTP 1회만 시도하고,
    최초 rate-limit부터 2시간 cooldown을 기록하며 후속 실행은 endpoint를 호출하지 않고
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
  - 2026-06-14 `app/services/broker_paper_sync.py`는 KIS lookback 에서 사라진 주문이
    이전 final/applied fill 상태를 잃고 `pending_lookup`으로 되돌아가지 않도록 보강됐다.
    정상 조회 후 broker row 가 없으면 이전 적용 체결 수량을 보존하고,
    과거 주문일 잔량은 `expired` 또는 `expired_partial`로 닫는다.
  - 2026-06-14 실제 sync 실행으로 기존 open order backlog 153건은
    `open_order_count=0`, `final_order_count=173`, `pending_symbols=[]`까지 닫혔다.
    이후 marker-only alignment 를 적용했고, 최신 `latest-open-order-backlog-analysis.json`은
    현재 view 기준 `backlog_cleared_no_action`이다.
- 2026-07-11 장외 보강:
  - paper/KIS reconciliation 실행 때 계좌 식별자와 원문 응답을 제외한 거래일별 정합성 기록을 `runtime-data/reports/reconciliation/paper-account-history/YYYY-MM-DD.json`에 자동 저장한다.
  - `latest-paper-account-history.json/.md`는 최근 10개 유효 장후 거래일의 정합/불일치, 연속 정합 일수, 현금/총자산 최대 차이를 집계한다.
  - 유효일은 `post-close`, KIS 계좌 조회 성공, 브로커 제출 이력 존재 조건을 모두 만족해야 한다. 불일치가 있으면 표본 부족보다 `needs_review`를 우선 표시한다.
  - dashboard 계좌 영역에 `10거래일 누적 정합성`과 `거래일별 정합성` 카드를 추가했다.
  - 기존 2026-07-10 장후 증거를 최초 기록으로 반영한 현재 상태는 `1/10`, `matched_days=0`, `mismatch_days=1`, mismatch 4종목이라 구현은 완료됐지만 Phase 0 gate는 통과하지 않았다.
- 남은 blocker:
  - 10개 유효 장후 거래일에서 모두 정합한 실제 증거를 누적하고, 현재 mismatch 4종목을 먼저 해소해야 한다.
  - 다음 거래일 첫 신규 제출 뒤에도 stale open 주문이 active open 으로 재발하지 않는지 확인한다.
  - 2026-06-08과 같은 raw market 약한 구간이 다음 거래일에도 반복되는지
    watchdog heartbeat, KIS WS frame, raw market/orderbook coverage 로 비교한다.
  - 장후 label refresh 최신 상태 파일은 2026-07-10 기준 `status=ok`다.
  - 2026-07-10 장후 재확인에서도 paper/KIS position mismatch 4종목이 남았다.
    KIS order/fill 조회는 제한 대기 뒤 완료됐으므로 단순 조회 실패가 아니라 계좌 snapshot과
    order/fill 원장 사이 divergence로 본다. 다음 장후에 1회만 재확인하고 자동 align은 하지 않는다.

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

- 상태: 실제 제한 관측 1회와 전용 readiness 통과, 반복 관측 및 상위 단계 진입 조건 대기
- 목적:
  - 실제 자금 운용 전에 실전 계좌의 조회 권한, 응답 shape, 예수금/주문가능금액,
    T+2 관련 필드가 실제로 어떻게 오는지 확인한다.
- 중요한 경계:
  - 주문 금지.
  - 실전 주문 메서드가 없는 read-only client로만 확인한다.
  - `ALLOW_LIVE_ORDERS=false` 유지.
- 완료:
  - 현재가·호가·과거분봉·계좌 조회와 CLI 조회 경로를 `KisReadOnlyClient` factory로 고정했다.
  - direct `KisRestQuoteClient` 생성은 read-only factory와 paper mirroring 경계 두 곳만 허용한다.
  - `scripts/compare_kis_account_snapshot_checks.sh`로 paper/live sanitized shape를 오프라인 비교할 수 있다.
  - `restore_kis_env_interactive.sh --trading-mode live --include-account-fields --read-only-preparation`은 paper 모드 보존과 live order 비활성화를 강제한다.
  - `run_phase1b_readonly_observation.sh`는 기본 네트워크 0회 사전검사와 명시적 제한 실행을 분리하고 `pre-open`/`regular-session` 실행을 차단한다.
  - `phase1b_live_readonly` 전용 readiness 프로필과 `--phase1b-observation-path` 병합을 구현했다. live token/account/system clock은 paper fixture보다 우선하며 관측 누락·차단 시 fallback하지 않고 dashboard에 별도 표시한다.
  - `run_phase1b_readiness_cycle.sh`로 local premarket, synthetic WS, 관측, fixture, readiness를 장외 한 명령으로 고정했다. 기본은 외부 KIS 네트워크 0회이고 protected session은 step 시작 전에 차단하며 preflight/attempt/actual readiness를 분리 보존한다.
- 현재 확인:
  - 2026-07-10 장후 사전검사에서 paper mode, live order 비활성, paper 계좌 자격정보, 주문 메서드 미노출은 통과했다.
  - live quote 자격정보와 live account 자격정보 두 항목은 미준비로 차단됐다.
  - 네트워크 호출은 0회였고 `TRADING_MODE=paper`, `ALLOW_LIVE_ORDERS=false`는 유지된다.
  - 2026-07-10 당시 전용 readiness는 `blocked`였다. 필수 blocker는 live token 미검증, live account shape 미검증, live system clock 미검증 세 가지였고 fresh synthetic WebSocket recovery만 통과했다.
  - 2026-07-11 주말 기본 cycle을 실제 실행했다. `network_calls_executed=0`, synthetic WS는 fresh/ok였고 preflight readiness blocker는 live token, live account shape, live system clock 미검증 세 가지로 줄었다. `market_status`와 kill switch OFF는 계속 비차단이다.
  - 같은 날 `--execute` cycle도 실행했으나 live quote/account credentials 미준비로 관측 시작 전에 차단됐다. `observation_execution_started=false`, `network_calls_executed=0`, `order_method_calls=0`이며 attempt 파일이 실제 readiness를 덮지 않았다.
- 2026-07-11 실제 제한 관측:
  - `run_phase1b_readiness_cycle.sh --execute --refresh-dashboard`를 주말 장외에 1회 실행했다.
  - live token refresh 1회, paper/live account snapshot 각 1페이지, live current-price/system clock 1회로 네트워크 호출은 총 4회였다.
  - live account는 position row 1개, summary row 1개, paper account는 position row 3개, summary row 1개였고 필수 필드 누락·타입 오류·shape 차이는 없었다. 잔액과 계좌 식별자는 저장하지 않았다.
  - system clock skew는 `0.533151초`로 허용 기준 `2초` 이내였고 live token, account snapshot, system clock이 모두 통과했다.
  - `TRADING_MODE=paper`, `ALLOW_LIVE_ORDERS=false`, 주문 메서드 미노출과 `order_method_calls=0`을 재확인했다.
  - 전용 readiness 필수 항목은 모두 통과했다. `market_status`는 지난 거래일 수동 템플릿, kill switch는 stale 상태라 실패했지만 Phase 1b 조회 전용 프로필에서는 비차단이다. Phase 2 live-submit에서는 그대로 차단 조건이다.
  - dashboard snapshot도 같은 Phase 1b `status=ok`, `passed=true` 결과로 갱신됐다.
  - 로컬 `.env`는 git ignore 상태이며 파일 권한을 `600`으로 제한했다.
- 남은 항목:
  - Phase 0 paper/KIS 계좌 정합성은 현재 유효 증거 `1/10`, mismatch 4종목이라 계속 열린 상태다.
  - Phase 2/3용 실제 WebSocket recovery 증거, 당일 fresh market status, 유효한 kill switch OFF 상태와 전략 수익성 근거는 아직 없다.
  - sanitized NAS 복구 drill 표본은 사용자 명시 지시가 있을 때만 실행한다.
- 권장안:
  - Phase 1b의 자격정보·token·account shape·system clock blocker는 해소된 것으로 기록한다.
  - 필요 시 장외에서 같은 bounded read-only cycle을 반복해 fresh 증거를 만들되, `pre-open`과 `regular-session` 실행 차단은 유지한다.
  - Phase 2 실제 주문 canary는 Phase 0 정합성, 모델/전략 기대값, 실제 WS recovery, market status, kill switch 조건이 모두 닫힐 때까지 시작하지 않는다.

### Phase 2: 실전 1종목 소액 canary

- 상태: 미시작
- 조건:
  - Phase 1a/1b 관측 통과.
  - submit guard, audit, alert, kill switch, model gate 통과.
- 남은 blocker:
  - Phase 0 paper/KIS 계좌 정합성 10거래일 기준 미충족.
  - 비용 차감 양수 기대값과 active model/전략 채택 기준 미충족.
  - 실제 WebSocket recovery, fresh market status, 유효 kill switch OFF 증거 미충족.

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
  - 2026-06-14 Cybos 5년 buy-avoid proxy 는 target skip `0.3665`에서
    12/12 fold 개선을 보여 KIS buy-avoid shadow 지속 근거를 보강했다.
    단, kept net 도 음수이므로 실전/paper 주문 정책 변경이나 모델 승격 근거는 아니다.
- 다음 작업:
  - 새 모델 학습 실험을 즉시 늘리지 않는다.
  - 기존 LightGBM shadow serving 예측과 baseline 매수 허용 신호를 이용해
    `buy-avoid` shadow 를 최소 2주 또는 10거래일 이상 축적한다.
  - walk-forward 재검증은 KIS live h15 labeled row `60,000`행 이상,
    KIS live 고유 거래일 `30거래일` 이상, buy-avoid shadow `10거래일` 이상이
    모두 충족된 뒤 다시 본다.
  - buy-avoid 연결 표본은 최소 `1,000`건 이상이어야 하고,
    `10거래일` 중 `8거래일` 이상은 일별 `50`건 이상이어야 한다.
    종목은 최소 `5`종목, 종목별 `50`건 이상이어야 하며,
    down threshold `0.40`의 회피 후보는 최소 `200`건 이상이고 `5거래일` 이상에 분포해야 한다.
    하나라도 부족하면 성능 실패가 아니라 `표본 부족`으로 보고 관측을 연장한다.
  - Cybos 장외 추가 실험은 `docs/cowork-reports/2026-06-14-cybos-rescue-experiment-plan.md` 기준으로 진행한다.
    `buy-avoid`와 `buy-rescue`는 같은 Cybos 리포트에서 비교하되 탐색 리포트로만 해석하고,
    `hold-rescue`는 포지션 lifecycle 설계와 synthetic test 를 먼저 둔다.
    Step 0 확인 결과, Cybos 에서는 runtime baseline replay 가 불가능하므로
    다음 코드는 `proxy_buy_rescue`로 구현한다.
    2026-06-14 기준 `proxy_buy_rescue` 계산과 `latest-cybos-rescue-proxy-h15` full 12 fold report 출력은 완료했다.
    결과는 `buy_avoid_candidate_only`이므로 buy-rescue live shadow 는 아직 시작하지 않는다.
    hold-rescue 는 synthetic lifecycle helper/test 까지만 완료했고, full Cybos 결과 실험은 아직 하지 않는다.
  - 보합 regime 분리와 변동성 구간별 모델 분리는 위 재검증 뒤에 결정한다.
- 권장안:
  - Phase 2 논의보다 먼저 alpha 연구 스프린트를 진행하되,
    지금은 추가 학습 실험보다 buy-avoid shadow 관측과 재검증 기준 충족을 우선한다.
  - 장외 Cybos 에서는 buy-rescue 를 함께 탐색하되, 결과가 좋아도 KIS live 에서는 buy-avoid 순차 검증을 먼저 유지한다.

### broker paper sync / initial cash mismatch

- 상태: blocker 유지, 계좌 snapshot과 order/fill 원장 divergence 관찰
- 현재 판단:
  - 2026-06-14 장외 broker paper sync 보강과 1회 실제 sync 로 기존 backlog 는 닫혔다.
  - 2026-07-10 장후 broker paper sync는 `status=ok`, open order `0`, pending symbol 없음이다.
  - 최신 reconciliation 은 `status=needs_review`, mismatch count `4`다.
  - 수량 mismatch 가 있으므로 `-SyncInitialCash`와 marker-only `-AlignToBroker`는 실행하지 않는다.
  - 대상은 `035420`, `086520`, `105560`, `247540`이다. local paper 수량은 KIS
    order/fill 원장 순수량과 맞고 KIS 계좌 snapshot 수량만 다르다.
  - root cause scope는 `kis_account_snapshot_vs_order_fill_ledger_divergence`이며,
    단순 order/fill 조회 실패로 보지 않는다.
- 보존되는 기존 판단:
  - 2026-06-14 기준 `runtime-data/reports/reconciliation/latest-paper-kis-mismatch-trace.json`은
    `assessment.status=ok`, mismatch count `0`이었다.
  - `runtime-data/reports/broker-paper/latest-open-order-backlog-analysis.json` 기준
    marker 이후 현재 view 는 `submission_rows=0`, `current_open_order_count=0`,
    `projected_open_order_count=0`, 권고 `backlog_cleared_no_action`이다.
  - `runtime-data/reports/reconciliation/latest-paper-cash-gap-analysis.json` 기준
    권고는 `keep_current_alignment`, 다음 조치 `no_cash_gap_action_required`다.
  - `.env`의 `PAPER_INITIAL_CASH`는 과거 시작값으로 남아 있지만,
    최신 current view 는 marker-only alignment effective cash 기준으로 정합하다.
    브로커 원시 예수금과 유효현금 차이 `29,991원`은 `raw_cash_gap`으로만 표시한다.
  - 기존 153건 open backlog 원인은 KIS lookback 에서 사라진 주문을 이전 final/applied fill 상태로 보존하지 못하고
    `pending_lookup`처럼 다시 보는 해석 문제였다. 수정 뒤 이전 적용 체결이 주문 수량을 덮으면 `filled`,
    과거 주문일 잔량이면 `expired` 또는 `expired_partial`로 닫는다.
- 다음 작업:
  - 같은 KIS order-fill endpoint 반복 호출은 중지한다.
  - 다음 장후 broker paper sync를 1회만 재시도한다.
  - 그 뒤 reconciliation 을 다시 확인한다.
  - 수량 mismatch 가 0으로 닫히기 전까지 `SyncInitialCash`와 추가 `AlignToBroker`는 실행하지 않는다.
  - 누적 자동 집계와 dashboard 표시는 구현 완료됐다. 다음 유효 장후 reconciliation부터 자동 누적되는지 확인하고, `1/10`에서 `10/10`까지 실제 정합 증거를 쌓는다.
- 권장안:
  - Phase 0 계좌 정합성 blocker 는 다시 열린 상태로 본다.
  - 오늘은 추가 KIS order-fill 호출을 멈추고, 다음 장후에 1회만 재확인한다.

### dashboard/watchdog daemon 유지

- 상태: 진행 중
- 현재 판단:
  - `python -m app --build-dashboard`는 정상 통과하고 최신 snapshot도 생성된다.
  - 2026-06-13 장외 복구 후 dashboard 와 runtime watchdog 은 모두 `running`이고,
    dashboard/API 응답과 watchdog heartbeat fresh 를 확인했다.
  - 정규장 중 `latest_market_bar` stale 은 dashboard warning 으로 노출되는지
    `tests/test_dashboard.py`에서 회귀 잠금했다.
  - 단, 정규장 중 장시간 유지 증거는 아직 다음 실제 거래일 장중 실측이 필요하다.
- 다음 작업:
  - 다음 실제 거래일 정규장 중 dashboard/API 응답과 watchdog heartbeat가 10분 이내로 유지되는지 read-only로 확인한다.
  - 재부팅 자동 시작 경로와 Codex 수동 호출 경로의 차이는 계속 분리해서 본다.
- 권장안:
  - 장외 수동 복구는 완료로 보고, 장중 장시간 유지 확인만 별도 운영 blocker로 남긴다.

### read-only 구조적 차단

- 상태: 완료
- 완료:
  - `KisReadOnlyClient` 골격과 isolation 테스트 구현.
  - 조회 전용 KIS 흐름 5곳을 read-only factory로 고정.
  - direct 원본 client 생성 경계를 read-only factory와 paper mirroring 두 곳으로 축소.
  - paper/live sanitized account shape 비교 helper와 wrapper 구현.
  - Phase 1b 네트워크 0회 preflight와 bounded read-only observation wrapper 구현.
- 실제 확인:
  - 2026-07-11 bounded `--execute`로 live token, paper/live account shape, live system clock과 주문 메서드 호출 0건 증거를 생성했다.
- 권장안:
  - 구조적 차단과 Phase 1b 1회 실제 관측은 완료로 보고, 반복 관측·Phase 0 정합성·NAS drill은 별도 항목으로 유지한다.

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
- Phase 1b 전용 readiness 현황:
  - 사전검사 경로: `runtime-data/reports/live-readiness/phase1b/latest-readiness-preflight.json`
  - 실제 관측 경로: `runtime-data/reports/live-readiness/phase1b/latest-phase1b-readonly-observation.json`
  - 최종 경로: `runtime-data/reports/live-readiness/phase1b/latest-readiness.json`
  - 상태: `ok`, `passed=true`
  - 필수 통과: live token, synthetic WebSocket recovery, paper/live account shape, live system clock, database, disk space, dashboard, storage migration state
  - 비차단 실패: `market_status`, `kill_switch`
  - 실제 관측은 읽기 전용 네트워크 4회, 주문 메서드 호출 0회였고 readiness DB 기록은 하지 않았다.
  - preflight/attempt 파일은 실제 관측 결과와 분리해 계속 보존한다.

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
2. 실전 credentials를 `--read-only-preparation`으로 로컬 비밀 저장소에 준비한다.
3. 네트워크 없는 Phase 1b preflight를 통과한다.
4. 승인된 작업 안에서 `--execute` 1회로 token/account/current-price probe를 실행한다.
5. 주문 함수 호출 0건과 paper/live 응답 shape 차이를 문서화한다.
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
