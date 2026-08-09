---
name: daily-ops-check
description: Use for this repository when checking or acting on 장전/장후 자동화, daily runtime status, paper/KIS reconciliation, data quality, or dashboard freshness.
---

# Daily Ops Check

이 skill은 이 저장소의 장전/장후 자동화 결과를 확인하고
필요한 조치를 끝까지 진행할 때 쓴다.

## 1. 시작 안전 확인

먼저 아래를 실행한다.

```bash
./scripts/get_live_runtime_status.sh
./scripts/get_runtime_watchdog_status.sh
./scripts/get_dashboard_status.sh
./scripts/get_runtime_startup_launcher_status.sh
git status --short --branch
```

- `regular-session`, `pre-open`, `live_runtime_should_run=true`,
  live runtime 실행 중이면 장중 보호 모드다.
- 장중 보호 모드에서는 사용자 명시 승인 없이 root 코드 변경,
  전체 테스트, dashboard/runtime 재생성, 운영 DB 쓰기 가능 명령을 피한다.
- `post-close`, `overnight`, 휴장일이고 live runtime 이 꺼져 있으면
  장후/장외 조치를 진행할 수 있다.

## 2. 오늘 자동화 산출물 확인

오늘 날짜 기준으로 아래 파일을 우선 확인한다.

```bash
find runtime-data/reports -type f -newermt "YYYY-MM-DD 00:00:00" \
  \( -name "*.json" -o -name "*.md" \) | sort
```

핵심 파일:

- `runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json`
- `runtime-data/reports/ml-maintenance/state/latest-post-close-ml.json`
- `runtime-data/reports/ml-maintenance/state/latest-post-close-label-refresh.json`
- `runtime-data/reports/data-quality/latest-kis-live-data-quality.json`
- `runtime-data/reports/data-quality/latest-feature-source-drift.json`
- `runtime-data/reports/data-quality/latest-kis-live-feature-diagnostics.json`
- `runtime-data/reports/challengers/latest-lightgbm-defensive-shadow-h15.json`
- `runtime-data/reports/challengers/latest-model-overlay-comparison-h15.json`
- `runtime-data/reports/backtests/latest-cybos-rescue-proxy-h15.json`
- `runtime-data/reports/challengers/latest-hold-rescue-paper-replay-h15.json`
- `runtime-data/reports/broker-paper/latest-sync.json`
- `runtime-data/reports/reconciliation/latest-paper-account-sync.json`
- `runtime-data/reports/reconciliation/latest-paper-account-history.json`
- `runtime-data/reports/reconciliation/latest-paper-dual-account-match.json`
- `runtime-data/reports/recovery/latest-local-setup-check.json`
- `runtime-data/reports/dashboard/latest-dashboard.json`

## 3. 판정 기준

정상으로 볼 수 있는 상태:

- premarket readiness: `status=ok`, blockers/warnings 없음.
- post-close ML: `status=ok`.
- post-close label refresh: `status=ok`.
- KIS live data quality: `assessment.status=ok`. `watch`가 WebSocket 재연결만으로 발생했고 storm=0, raw/feature coverage와 decision lineage가 정상이라면 수집 성공과 연결 주의를 분리해 보고한다.
- local setup: `ok=true`, blockers/warnings 없음.
- live runtime: 장후에는 정지 상태가 정상.
- watchdog: `status=running`, `errors=[]`.

주의로 남길 수 있는 상태:

- source drift: `source_drift_detected`.
  현재는 KIS live와 Cybos historical 차이를 알려주는 진단이다.
- feature diagnostics: `no_clear_single_feature_signal`.
  모델 승격 근거가 아니라 데이터 누적 필요 신호다.
- broker sync `pending_symbols` 존재.
  `status=ok`이고 주문이 아직 open 상태이면 바로 실패로 보지 않는다.

조치가 필요한 상태:

- reconciliation 또는 dual match 가 `needs_review`.
- KIS `EGW00201` rate limit.
- dashboard snapshot 이 조치 전 시각에 머물러 있음.
- post-close status 파일이 `running` 또는 stale 로 남아 있음.
- local setup blockers/warnings 존재.

## 4. 조치 원칙

### KIS rate limit

- 같은 endpoint를 계속 반복 호출하지 않는다.
- order-fill sync는 한 실행에서 HTTP 1회만 시도하며, `EGW00201` 뒤 in-call retry를 하지 않는다.
- `EGW00201`이 나오면 모의투자 REST 제한이 낮은 상황으로 보고, 같은 order-fill endpoint는 기본 2시간 cooldown 뒤 1회만 재시도한다.
- cooldown 중에는 `runtime-data/reports/broker-paper/latest-sync.json`의 `cooldown_active`, `skipped_broker_call`, `retry_after_seconds`, `pending_symbols`를 보고 추가 KIS 호출을 하지 않는다.
- 계속 `EGW00201`이면 추가 호출을 멈추고 logbook에 남긴다.
- 상세 기준은 `docs/KIS-Connection-Runbook.md`를 따른다.

### Phase 1 readiness 장전 증거 갱신

장전 시간대(기본 KST 08:20~08:40)에 Phase 1 readiness 를 확인할 때는 아래 순서로 최신 증거를 만든다. 이 절차는 read-only 또는 offline 증거만 만들며, 실전 주문/취소와 live submit 경로를 바꾸지 않는다.

```bash
./scripts/probe_kis_ws_recovery.sh
./scripts/probe_kis_token_refresh.sh --mode paper --use-cache
./scripts/probe_kis_account_snapshot.sh --mode paper \
  --output-path runtime-data/reports/live-readiness/account-snapshot-check.json \
  --system-clock-output-path runtime-data/reports/live-readiness/system-clock-check.json
./scripts/probe_market_status_snapshot.sh --symbols-file config/watchlist.txt
./scripts/set_live_kill_switch.sh --status
./scripts/build_live_readiness_fixture_snapshot.sh
./scripts/run_live_readiness_dry_run.sh \
  --fixture-path runtime-data/reports/live-readiness/local-fixture-snapshot.json
```

- `market-status-snapshot.json`이 없으면 `./scripts/prepare_market_status_snapshot_template.sh --watchlist-file config/watchlist.txt --trading-day YYYY-MM-DD --stale-after YYYY-MM-DDT08:45:00+09:00`로 fail-closed 템플릿을 만들 수 있다. 템플릿 상태는 `tradable_unknown`으로 차단되는 것이 정상이다.
- kill switch 는 `--status`로만 확인한다. `--disable --apply --confirm-disable`은 계좌 소유자 또는 실전 운용 승인권자가 그 작업에서 명시 승인하기 전에는 실행하지 않는다.
- 장전 재확인에서 `token_refresh`, `account_snapshot`, `system_clock`이 다시 ok인지 별도 줄로 보고한다. 단일 야간 증거가 장전 증거를 대체한다고 쓰지 않는다.

관련 문서/코드 경로: `docs/Manual-Market-Status-Runbook.md`, `docs/KIS-Connection-Runbook.md`, `scripts/probe_kis_ws_recovery.sh`, `scripts/probe_kis_token_refresh.sh`, `scripts/probe_kis_account_snapshot.sh`, `scripts/prepare_market_status_snapshot_template.sh`, `scripts/probe_market_status_snapshot.sh`, `scripts/set_live_kill_switch.sh`, `scripts/build_live_readiness_fixture_snapshot.sh`, `scripts/run_live_readiness_dry_run.sh`

### Phase 1b 실전계좌 read-only

- 일반 daily ops에서는 `./scripts/run_phase1b_readonly_observation.sh` 기본 사전검사만 실행할 수 있다. 이 실행은 네트워크 호출 0회다.
- `--execute`는 계좌 소유자 또는 실전 운용 승인권자가 해당 작업에서 승인했고, 장중 보호 모드가 아니며, 사전검사가 통과한 경우에만 1회 사용한다. wrapper도 `pre-open`/`regular-session`을 `protected_market_session`으로 차단한다.
- 자동화 프롬프트나 watcher에 `--execute`를 상시 등록하지 않는다.
- 결과는 token/account/raw response/계좌 식별자를 출력하지 않고 preflight/attempt/observation 파일을 분리한다.
- 실행 뒤 주문 함수 호출 0건, `TRADING_MODE=paper`, `ALLOW_LIVE_ORDERS=false`를 다시 확인한다.
- 실행/차단 결과 뒤에는 `./scripts/run_live_readiness_dry_run.sh --phase phase1b_live_readonly --fixture-path runtime-data/reports/live-readiness/local-fixture-snapshot.json --phase1b-observation-path <observation-or-attempt.json> --report-path runtime-data/reports/live-readiness/phase1b/latest-readiness.json`으로 전용 판정을 갱신한다.
- Phase 1b 보고에서는 token/account/system clock/WS blocker와 `market_status`·`kill_switch` 비차단 여부를 분리하고, precomputed override가 아니라 sanitized artifact에서 재계산됐는지와 dashboard의 별도 Phase 1b 행까지 확인한다.
- 장외 Phase 1b 통합 점검은 `./scripts/run_phase1b_readiness_cycle.sh`를 우선 사용한다. 기본 실행은 외부 KIS 네트워크 0회다. 실제 관측은 해당 작업 승인과 자격정보 준비 뒤 `--execute`로만 요청하며, dashboard 갱신은 `--execute --refresh-dashboard` 조합에서만 사용한다. protected session이면 cycle 전체가 시작 전에 차단되어야 한다.

### 2026-07-20 장후 E1/E5 사전등록 라운드

- 2026-07-20 최초 실행과 2026-08-09 계좌 소유자 명시 승인 실행은 모두 research snapshot 단계의 180초 timeout으로 안전 종료됐다. `latest-completed-round.json`은 없고 `latest-attempt.json`만 `snapshot_failed/research_snapshot_timeout`으로 남아 있다.
- daily ops와 반복 자동화는 이 라운드를 재실행하지 않는다. 다음 실행은 계좌 소유자가 그 작업에서 다시 명시 승인한 경우에만 장외에서 정확히 1회 수행한다.
- 2026-08-09 이후 8GiB 이상 DB의 기본 snapshot은 WSL `/mnt/d` 9P 복사 대신 repo-local `runtime-data/research-snapshots/`를 사용한다. 현재 WSL 배포판 자체가 D드라이브에 있어 D드라이브 전용 산출물 규칙을 지킨다. timeout이면 해당 실행 token의 partial DB/journal/manifest만 정리하고 final snapshot은 교체하지 않는다.
- 실행기는 `2026-07-04~2026-07-18` 고정 구간만 읽고 E1 전체/분해, 후보 3건 재현성, `105560` p_flat 및 p_down/p_up 일별 IC 관계, E5 threshold `0.40` excess/z를 기록한다.
- 결과는 진단 전용이다. threshold/EV tuning, 종목별 주문 정책, h60 정책, active model/gate 변경으로 자동 연결하지 않는다.

### KIS live 수집·판단 연속성

- 장전에는 `get_live_runtime_status.sh`의 `process_memory.rss_mib`, `peak_rss_mib`를 함께 확인한다. live runtime이 아직 정지 상태면 메모리 증거가 없음을 정상으로 두고 장중 실행 뒤 다시 본다.
- 장후 runtime 정지 뒤 `python3 scripts/summarize_kis_live_data_quality.py --recent-days 10`을 1회 실행한다. 이 명령은 기존 raw/분봉/feature/label coverage에 거래일별 `serving_decision_ledger` 계보와 live runtime 로그의 WebSocket 재연결을 함께 기록한다.
- `latest_session_observability.serving_decision_ledger`에서 rows 증가, `complete_lineage_rows`, `lineage_completion_ratio`, malformed shadow, stage 분포를 확인한다. rows만 많고 lineage가 불완전하면 수집 성공으로 판정하지 않는다.
- `latest_session_observability.websocket_reconnects`에서 count, storm_count, reason을 확인한다. 재연결이 있어도 storm=0이고 raw/feature coverage가 95% 이상이며 lineage가 100%면 데이터 수집은 성공, 연결 안정성은 주의로 분리한다.
- 정규장에는 리포트를 재생성하지 않고 기존 파일과 로그만 읽는다.

### KIS live buy-rescue 진단

장후 또는 장외이고 live runtime이 정지했을 때는 아래 read-only 진단을 1회 갱신한다. 장중 보호 모드에서는 기존 파일만 읽는다.

```bash
python3 scripts/summarize_model_overlay_comparison.py --horizon-min 15
```

- `latest-model-overlay-comparison-h15.json`의 `generated_at`, `decision_ledger.status`, `rows`, `rescue_eligible_rows`, stage 분포를 먼저 확인한다.
- buy-rescue는 safety gate 통과, 주문/체결 없음, baseline 비매수, `decision_stage=signal_blocked`의 실제 행만 대상으로 한다. position/cash/pending 제약은 rescue 대상이 아니며 주문 정책으로 뒤집지 않는다.
- 모델별 `best`는 rescue가 실제로 발생한 threshold만 비교한다. 행이 0인 threshold의 `0.0` 손익을 양호한 결과로 해석하지 않는다.
- KIS live no-trade ledger가 없다는 표현은 비교 리포트가 fresh이고 `decision_ledger.status`가 `empty` 또는 `not_available`일 때만 쓴다. 오래된 리포트만 보고 부재로 단정하지 않는다.
- 보고에는 LightGBM/linear-score의 실제 best threshold, rescued trades, 순손익과 모델 조합 rescue 결과를 함께 적는다. 수익성 판정은 동일 decision episode portfolio replay와 same-count random control 전까지 관측용이다.

### paper/KIS 정합성

장후/장외에는 우선 통합 recheck wrapper 를 실행한다. 이 wrapper 는 broker sync, reconciliation, mismatch trace 를 순서대로 실행하고, align 은 수행하지 않는다. pre-open/regular-session, live runtime 실행 중, weekend/holiday 에는 기본 차단된다. 실제 실행 결과만 `latest-paper-kis-mismatch-recheck.json`에 쓰며, dry-run과 차단된 시도는 `latest-paper-kis-mismatch-recheck-attempt.json`에 분리해 마지막 정상 증거를 덮지 않는다.

실행 전에 `latest-paper-account-history.json`의 마지막 유효 거래일을 먼저 확인한다. 오늘 날짜의 유효 장후 기록이 이미 있으면 broker sync를 중복 실행하지 않는다. 오늘이 실제 거래일 장후이고 유효 기록이 없을 때만 recheck wrapper를 한 번 실행한다. 최신 reconciliation은 오늘 것인데 mismatch trace만 오래됐으면 KIS를 다시 호출하지 않고 `python3 scripts/trace_paper_kis_mismatch.py --limit-per-table 12`만 실행한다. 주말/휴장일 차단은 오류나 유효 거래일로 집계하지 않는다.

```bash
./scripts/recheck_paper_kis_mismatch.sh
```

reconciliation이 실행되면 sanitized 일별 기록과 최근 10개 유효 장후 거래일 집계가 자동 갱신돼야 한다. `post-close`, 브로커 조회 성공, 브로커 제출 이력 존재 조건을 모두 만족한 날만 Phase 0 분모에 포함한다. 불일치가 하나라도 있으면 `insufficient_history`보다 `needs_review`를 우선 보고한다.

기존 최신 reconciliation 증거를 네트워크 호출 없이 이력에 반영하거나 현재 집계만 읽을 때는 아래 명령을 쓴다.

```bash
python scripts/summarize_paper_reconciliation_history.py --record-latest
python scripts/summarize_paper_reconciliation_history.py
```

수동으로 나눠서 확인해야 할 때만 아래 순서로 실행한다.

```bash
python -m app --sync-broker-paper-orders
python -m app --reconcile-paper-accounts
python3 scripts/trace_paper_kis_mismatch.py --limit-per-table 12
```

확인 기준:

- `runtime-data/reports/reconciliation/latest-paper-kis-mismatch-trace.md`의 `root_cause_scope`를 먼저 본다.
- `runtime-data/reports/broker-paper/latest-sync.json`의 식별정보 없는 연결 진단값도 함께 본다.
  - `broker_rows_unlinked_to_submissions > 0`: KIS 조회 행 중 로컬 제출 원장과 연결되지 않은 행이 있으므로 수동/외부 주문 또는 로컬 제출 기록 누락 후보로 본다.
  - `fallback_matched_orders > 0`: 주문일을 포함한 정확 매칭이 아니라 지점번호/주문번호 보조 매칭이 사용된 상태다. 날짜 경계와 lookback 범위를 확인한다.
  - `ambiguous_fallback_key_count > 0`: 보조키가 중복돼 어느 주문과 연결할지 모호한 상태다. 자동 align을 하지 않는다.
  - 세 값이 모두 0인데 mismatch가 유지되면 현재 조회된 주문/체결 원장보다 계좌 snapshot 원천 차이에 무게를 두고 다음 거래일 장후 재확인 또는 KIS 문의 증거로 남긴다.
- `broker_ledger_coverage.status=historical_mirrored_orders_only`이면 보관된 미러링 주문 상태는 과거 제출 증거일 뿐 전체 계좌 활동 원장이 아니다. 이를 `latest KIS order/fill ledger`로 부르지 않는다.
- `phase0_resolution.status=blocked_requires_full_account_history_or_clean_baseline`이면 같은 3일 조회를 반복하거나 자동 align하지 않는다. 해결 근거는 미러링 기간을 덮는 sanitized 전체 계좌 활동 또는 계좌 소유자가 승인한 clean paper-account baseline과 그 뒤의 새 local baseline 중 하나다.
- `kis_account_snapshot_vs_order_fill_ledger_divergence`는 bounded lookup이 실제 비교 기간을 덮는 경우에만 사용한다. 이때도 자동 align 전에 snapshot 원천과 계좌 활동 범위를 확인한다.
- `local_ledger_divergence`이면 로컬 position restore/fill 적용 경로를 먼저 확인한다.
- `broker_order_fill_lookup_blocked_by_rate_limit`이면 cooldown 뒤 order-fill sync를 1회만 재시도한다.

다음 조건이면 marker-only alignment를 권장한다.

- 보유 수량 mismatch 가 0이다.
- broker account 조회가 정상이다.
- local snapshot 이 오래되어 현재가/평가금액만 어긋난다.
- broker sync 의 `open_order_count`가 0이거나,
  남은 open order가 다음 거래일 기준선에 영향을 주지 않는다고 확인됐다.
- `-SyncInitialCash`가 필요한 상황이 아니다.

적용 명령:

```bash
./scripts/verify_paper_dual_account_match.sh -AlignToBroker -AsJson
```

주의:

- 보유 포지션이 있으면 `-SyncInitialCash`를 임의로 붙이지 않는다.
- 수량 mismatch 가 있으면 align으로 덮지 말고 원인을 먼저 확인한다.
- `open_order_count > 0`이고 order-fill 조회가 rate limit이면
  align을 보류하고 `needs_review`를 유지한다.
- 단, 최신 KIS 모의계좌 status snapshot 이 이미 있고 주문일이 현재 점검일보다
  이전이며, 체결수량 0 / 잔량 전체 유지인 prior-day stale open 주문은
  다음 거래일 기준선에 체결로 반영될 수 없는 만료 후보로 본다.
  이때 보유 수량 mismatch 0, broker account 조회 정상, 현금/총자산 gap 이
  평가 기준선 차이로 설명되면 marker-only alignment 를 적용할 수 있다.
- snapshot 이 없는 제출 주문, 당일 open 주문, 부분 체결 후 잔량이 남은 주문은
  stale 로 단정하지 않고 조회 복구 또는 사람 확인 전까지 align 을 보류한다.
- 장후이고 같은 order-fill endpoint 가 cooldown 뒤 1회 재시도에서도
  `EGW00201`로 막혔으며, broker account snapshot 이 정상/최신이고
  다음 거래일 기준선 보호가 필요한 paper mirroring 수량 mismatch 라면
  `-SyncInitialCash` 없이 broker account 기준 marker-only alignment 를 적용할 수 있다.
  이 경우 order-level fill 감사가 복구되지 않았다는 한계를 logbook 에 반드시 남긴다.
- marker-only alignment 뒤 broker/local 모두 flat 이고 reconciliation 이
  `aligned_waiting_first_submission`이면, 현재 예수금과 `PAPER_INITIAL_CASH`가
  다르다는 이유만으로 `-SyncInitialCash`를 붙이지 않는다. 이때
  dual-account 리포트의 `initial_cash_check_skipped_reason`이
  `broker_alignment_marker_active`이면 정상 조치 완료 상태로 본다.
- 실전 계좌 주문/취소는 하지 않는다.

### 리포트와 dashboard

정합성 조치 뒤에는 아래를 갱신한다.

```bash
python -m app --build-runtime-report
python -m app --build-dashboard
./scripts/get_dashboard_status.sh
```

`--build-dashboard`는 오래 걸릴 수 있으므로 장후에는 넉넉한 timeout을 둔다.
timeout이면 최신 `latest-dashboard.json`의 `generated_at`과 남은 프로세스를 확인한다.

## 5. 문서화

작업 종료 전 아래 문서를 갱신한다.

- `docs/logbook.md`: 당일 확인, 조치, 검증, 남은 위험.
- `docs/Production-Transition-Progress.md`: phase 진행이나 P0 보드에 영향이 있을 때.
- `docs/Codex-Operating-Feedback.md`: 반복 누락 또는 skill 기준 변경이 있을 때.

NAS 백업은 사용자가 명시적으로 지시한 경우에만 실행한다.

## 6. 최종 보고 형식

최종 답변에는 아래를 포함한다.

- 장전 readiness 결과.
- 장후 ML/label/data quality 결과.
- 장후 체크에서는 사용자가 별도로 묻지 않아도 `장후 학습 결과`를 별도 줄로 반드시 요약한다.
  - 학습 완료 여부: `latest-post-close-ml.json`의 `status`, `completed_at`, `mode`.
  - label refresh 완료 여부: `latest-post-close-label-refresh.json`의 `status`, `completed_at`.
  - active 유지/승격 없음 여부: `latest-challengers-h15.json`의 `active_model_version`, `recommended_action`, `recommended_model_version`, `promotion_applied`.
  - 핵심 수치 3개: top challenger의 `three_class_accuracy`, `buy_signal_hit_rate` 또는 `trade_hit_rate`, `cumulative_net_return_pct`.
  - 표본 신뢰도 보조값: 가능하면 `trades_taken`도 함께 표시한다. 거래 표본이 작으면 수익률 숫자보다 표본 부족을 먼저 해석한다.
- 장후 체크에서는 `rescue/avoid 관측`을 별도 줄로 반드시 요약한다.
  - `buy-avoid`: `latest-lightgbm-defensive-shadow-h15.json`의 `status`, `date_range`, `joined_rows`, best threshold, `delta_net_pct` 또는 `delta_net` 계열 수치를 요약한다. 파일이 오래됐으면 stale 또는 fresh evidence 부족으로 표시한다.
  - `buy-rescue`: 먼저 `latest-model-overlay-comparison-h15.json`의 freshness와 KIS live `decision_ledger.status/rows/rescue_eligible_rows`, 모델별 실제 best threshold·rescued trades·순손익, 모델 조합 rescue를 요약한다. 이후 `latest-cybos-rescue-proxy-h15.json`의 `decision`, `recommended_action`, target/precision 결과를 보조 근거로 붙인다. overlay가 fresh이고 ledger가 `empty/not_available`일 때만 `live buy-rescue ledger not available`로 표시하며 실패로 단정하지 않는다.
  - `hold-rescue`: 장후/장외이고 안전하면 `python scripts/summarize_hold_rescue_paper_replay.py --horizon-min 15`로 paper-only replay 를 갱신한 뒤 `latest-hold-rescue-paper-replay-h15.json`의 `decision.status`, replay 가능 lot, 적용 lot, `delta_cash_sum`을 요약한다. 장중 보호 모드이면 기존 파일만 읽는다.
  - 세 항목은 모두 관측/진단용이며, 주문 정책, gate, active model, KIS live shadow 확장을 바꾸지 않았는지 함께 적는다.
- paper/KIS 정합성 조치 전후.
- paper/KIS 최근 10거래일 누적 상태: `status`, `days_available/required_days`, `matched_days`, `mismatch_days`, 최근 차이 종목. 표본 부족과 실제 불일치를 구분한다.
- dashboard/runtime 갱신 여부. 장후에는 최신 거래일 raw/feature coverage, decision ledger rows/complete lineage 비율, WebSocket reconnect/storm도 별도 줄로 포함한다.
- 변경 파일과 검증 명령.
- 남은 위험과 다음 권장안.
- commit/push/NAS 백업 상태.
- 현재 작업 모드, 답변 접두어, 체크리스트 갱신,
  기준 문서 반영 여부.
