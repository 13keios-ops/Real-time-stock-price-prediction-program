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
- `runtime-data/reports/backtests/latest-cybos-rescue-proxy-h15.json`
- `runtime-data/reports/challengers/latest-hold-rescue-paper-replay-h15.json`
- `runtime-data/reports/broker-paper/latest-sync.json`
- `runtime-data/reports/reconciliation/latest-paper-account-sync.json`
- `runtime-data/reports/reconciliation/latest-paper-dual-account-match.json`
- `runtime-data/reports/recovery/latest-local-setup-check.json`
- `runtime-data/reports/dashboard/latest-dashboard.json`

## 3. 판정 기준

정상으로 볼 수 있는 상태:

- premarket readiness: `status=ok`, blockers/warnings 없음.
- post-close ML: `status=ok`.
- post-close label refresh: `status=ok`.
- KIS live data quality: `assessment.status=ok`.
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
### paper/KIS 정합성

장후/장외에는 우선 통합 recheck wrapper 를 실행한다. 이 wrapper 는 broker sync, reconciliation, mismatch trace 를 순서대로 실행하고, align 은 수행하지 않는다. pre-open/regular-session, live runtime 실행 중, weekend/holiday 에는 기본 차단된다. 실제 실행 결과만 `latest-paper-kis-mismatch-recheck.json`에 쓰며, dry-run과 차단된 시도는 `latest-paper-kis-mismatch-recheck-attempt.json`에 분리해 마지막 정상 증거를 덮지 않는다.

```bash
./scripts/recheck_paper_kis_mismatch.sh
```

수동으로 나눠서 확인해야 할 때만 아래 순서로 실행한다.

```bash
python -m app --sync-broker-paper-orders
python -m app --reconcile-paper-accounts
python3 scripts/trace_paper_kis_mismatch.py --limit-per-table 12
```

확인 기준:

- `runtime-data/reports/reconciliation/latest-paper-kis-mismatch-trace.md`의 `root_cause_scope`를 먼저 본다.
- `kis_account_snapshot_vs_order_fill_ledger_divergence`이면 로컬 paper 수량과 KIS order-fill 순수량은 맞고 KIS 계좌 snapshot만 다른 상태다. 이 경우 자동 align을 하지 않고 다음 거래일 장후 account snapshot과 order-fill snapshot을 다시 비교한다.
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
  - `buy-rescue`: `latest-cybos-rescue-proxy-h15.json`의 `decision`, `recommended_action`, buy-rescue target/precision 결과를 요약한다. KIS live no-trade ledger 가 아직 없으면 `live buy-rescue ledger not available`로 표시하고 실패로 단정하지 않는다.
  - `hold-rescue`: 장후/장외이고 안전하면 `python scripts/summarize_hold_rescue_paper_replay.py --horizon-min 15`로 paper-only replay 를 갱신한 뒤 `latest-hold-rescue-paper-replay-h15.json`의 `decision.status`, replay 가능 lot, 적용 lot, `delta_cash_sum`을 요약한다. 장중 보호 모드이면 기존 파일만 읽는다.
  - 세 항목은 모두 관측/진단용이며, 주문 정책, gate, active model, KIS live shadow 확장을 바꾸지 않았는지 함께 적는다.
- paper/KIS 정합성 조치 전후.
- dashboard/runtime 갱신 여부.
- 변경 파일과 검증 명령.
- 남은 위험과 다음 권장안.
- commit/push/NAS 백업 상태.
- 현재 작업 모드, 답변 접두어, 체크리스트 갱신,
  기준 문서 반영 여부.
