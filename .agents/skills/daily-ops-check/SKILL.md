---
name: daily-ops-check
description: Use for this repository when checking or acting on 장전/장후 자동화, daily runtime status, paper/KIS reconciliation, data quality, or dashboard freshness.
---

# Daily Ops Check

이 skill은 장전/장후 운영 확인의 유일한 실행 절차다.
장기 정책과 과거 사건은 canonical docs에 두고, scheduled automation prompt는 이 skill과 mode만 지정한다.

## 1. Common safety check

항상 다음 순서로 시작한다.

```bash
./scripts/get_live_runtime_status.sh
./scripts/get_runtime_watchdog_status.sh
./scripts/get_dashboard_status.sh
./scripts/get_runtime_startup_launcher_status.sh
git status --short --branch
```

- 현재 KST, 거래일/휴장일, `market_session`, `live_runtime_should_run`, 실제 process를 함께 확인한다.
- `regular-session`, 실제 장전 `pre-open`, `live_runtime_should_run=true`, live runtime 실행 중이면 장중 수집 보호 모드다.
- 보호 모드에서는 기존 파일을 읽는 것 외에 tracked file, DB, runtime-data, dashboard/runtime report를 쓰거나 component를 재시작하지 않는다.
- 예외는 pre-open 절차에 명시한 네트워크 0회 Phase 1b preflight뿐이다. `--execute`는 반복 자동화에서 금지한다.
- scheduled automation은 application code, 전략, 설정, DB를 수정하거나 commit/push하지 않는다.
- 실전 주문/취소와 NAS 백업은 수행하지 않는다.

핵심 최신 증거:

- `runtime-data/reports/ml-maintenance/state/latest-post-close-ml.json`
- `runtime-data/reports/ml-maintenance/state/latest-post-close-label-refresh.json`
- `runtime-data/reports/data-quality/latest-kis-live-data-quality.json`
- `runtime-data/reports/reconciliation/latest-paper-account-history.json`
- `runtime-data/reports/reconciliation/latest-paper-account-sync.json`
- `runtime-data/reports/broker-paper/latest-sync.json`
- `runtime-data/reports/broker-paper/latest-kis-paper-orderability.json`
- `runtime-data/reports/research/e7/latest-e7-daily-evidence.json`
- `runtime-data/reports/challengers/latest-lightgbm-defensive-shadow-h15.json`
- `runtime-data/reports/challengers/latest-model-overlay-comparison-h15.json`
- `runtime-data/reports/backtests/latest-cybos-rescue-proxy-h15.json`
- `runtime-data/reports/challengers/latest-hold-rescue-paper-replay-h15.json`
- `runtime-data/reports/dashboard/latest-dashboard.json`

## 2. Pre-open procedure

KST 07:20~07:40의 실제 장전 점검에만 수행한다.

1. 공통 안전 확인을 실행한다.
2. 전 거래일 post-close ML, label refresh, data quality, dashboard, Phase 0 누적과 당일 readiness를 읽는다.
3. 아래 기본 preflight를 정확히 1회 실행한다.

```bash
./scripts/run_phase1b_readonly_observation.sh
```

4. `latest-phase1b-readonly-preflight.json`의 `status`, `passed`, `blocking_reasons`를 보고한다.
5. 기본 preflight의 KIS network call과 order call은 각각 0회여야 한다.
6. live runtime이 실행 중이면 `process_memory.rss_mib`, `peak_rss_mib`를 보고한다.

Pre-open에서는 post-close data-quality 재집계, E7 artifact 생성, hold-rescue 갱신, Phase 0 recheck, dashboard 재생성을 실행하지 않는다.
`run_phase1b_readonly_observation.sh --execute`도 실행하지 않는다.

## 3. Post-close procedure

KST 20:20~20:40, 실제 거래일, `post-close`, live runtime 정지를 모두 확인한 뒤 수행한다.
protected post-close no write: 보호 조건이나 runtime 실행이 남아 있으면 기존 증거만 읽고 쓰기성 report refresh를 모두 건너뛴다.

안전 조건이 맞으면 아래 순서로 각 항목을 최대 1회 실행한다.

1. Phase 0 중복 방지 판단과 필요한 recheck.
2. KIS live data quality 집계.

```bash
python3 scripts/summarize_kis_live_data_quality.py --recent-days 10
```

3. E7 일일 증적 생성.

```bash
./scripts/generate_e7_daily_evidence.sh
```

4. model overlay와 hold-rescue paper-only 진단.

```bash
python3 scripts/summarize_model_overlay_comparison.py --horizon-min 15
python3 scripts/summarize_hold_rescue_paper_replay.py --horizon-min 15
```

5. post-close ML, label refresh, challenger, buy-avoid/buy-rescue/hold-rescue 최신 증거를 읽는다.
6. dashboard/watchdog/startup launcher freshness를 다시 확인한다.

E7 writer는 현재 실제 거래일 artifact가 이미 있으면 같은 파일을 재사용하며 DB는 read-only다.
E7 artifact가 생성되지 않았다는 사실은 전략 실패가 아니다. 안전 조건, entrypoint, 원천 DB와 report 경로를 운영 주의로 분리한다.

## 4. Phase 0 check

항상 현재 계좌 lifecycle과 `latest-paper-account-history.json`을 먼저 확인한다.

```bash
python3 scripts/check_kis_paper_account_lifecycle.py
```

- 현재 paper account epoch는 `paper-2026-09-03`, 활성일은 `2026-09-03`, 만료일은 `2026-12-03`이다.
- 갱신 준비 경고는 `2026-11-03`부터, 긴급 경고는 `2026-11-26`부터 표시한다. `2026-12-03`부터는 만료로 fail-closed 한다.
- lifecycle report의 `phase0_baseline.compatible=false`이면 이전 계좌 epoch와 현재 계좌 epoch를 섞지 않는다. broker sync/reconciliation을 반복하지 않고 `baseline_review_required`로 보고한다.
- 현재 clean baseline은 계좌 소유자 승인으로 2026-09-06 생성했으며 `paper-2026-09-03` epoch와 호환된다. 같은 baseline을 자동 재생성하지 않는다.
- 2026-09-03 새 계좌의 자연 KIS cash-order submission 36건은 성공했고, 2026-09-05 order-fill sync가 3페이지/38행, submission 38/38 exact-linked, open 0/final 38/pending 0으로 완결됐다. `068270` 매도 체결 1건·2주도 로컬에 적용됐다.
- 2026-09-04 이전 baseline 비교 mismatch 5건과 2026-09-05 후속 체결 동기화는 과거 진단으로 보존한다.
- 2026-09-06 baseline 직후 reconciliation은 `aligned_waiting_first_submission`, mismatch/effective cash/total asset gap `0`이다. 현재 epoch는 `no_history`, 유효일 `0/10`이며 휴장일 baseline 생성일은 분모에 넣지 않는다.
- 오늘 `eligible_for_phase0_gate=true` 기록이 이미 있으면 broker sync/reconciliation을 중복 호출하지 않는다.
- lifecycle과 baseline이 현재 계좌에 호환되고, 오늘 유효 기록이 없고, 실제 거래일 post-close이며 live runtime이 정지한 경우에만 아래 wrapper를 최대 1회 실행한다.

```bash
./scripts/recheck_paper_kis_mismatch.sh
```

- reconciliation은 최신인데 trace만 오래됐으면 KIS를 다시 부르지 않고 아래만 실행할 수 있다.

```bash
python3 scripts/trace_paper_kis_mismatch.py --limit-per-table 12
```

- 유효일은 post-close, broker 조회 성공, broker submission 이력 존재를 모두 만족해야 한다.
- weekend/holiday, no-submission day, 차단된 시도는 10거래일 분모를 늘리지 않는다.
- 성공 submission 0건은 자동으로 버그가 아니며 강제 거래로 채우지 않는다.
- 불일치가 있으면 표본 부족보다 먼저 보고한다.
- auto align, `SyncInitialCash`, `AlignToBroker`, clean baseline 재생성, 강제 주문/취소를 자동 수행하지 않는다.
- full-period activity `--execute`는 계좌 소유자가 해당 작업에서 명시 승인한 장외 1회에만 허용한다.
- 현재/과거 epoch와 상세 정합 정책은 `docs/KIS-Connection-Runbook.md`를 따른다.

## 5. E7 check

공식 identity:

- evaluator: `portfolio-replay-v2-minute-mtm`
- manifest SHA-256: `1d61b288a715d3cde63f6ccf1e4dcc42d6affebd14fe9d4beaf3319a9e0dd3fa`
- future start: `2026-08-31 09:15 KST`
- 공식 최신 증거: `runtime-data/reports/research/e7/latest-e7-daily-evidence.json`

장후에는 다음을 별도 줄로 보고한다.

- evaluator/manifest 일치
- future trading days, episodes, symbols와 symbol count
- mark observation, missing, stale, invalid count
- normal cost, double cost의 status/prerequisite status
- random control required/completed/not-run reason
- 두 future interval status
- minimum sample progress
- `official_evaluation_status`

`collecting_future_sample`과 최소 표본 부족은 정상적인 표본 축적이며 수익성 pass/fail이 아니다.
evidence health와 profitability result를 섞지 않는다.
evaluator/manifest/cost/constraint/random/interval identity drift, invalid mark, incompatible result mixing은 공식 평가를 fail-closed하고 `CRITICAL`로 올린다.
E7 미래 데이터로 threshold 0.55, model, feature, signal/gate, allocator, portfolio, horizon, exit, symbol, cost, manifest를 변경하거나 재탐색하지 않는다.
상세 기준은 `docs/Portfolio-Replay-Evaluator.md`와 `docs/Model-Research-PreRegistration.md`를 따른다.

## 6. KIS paper account lifecycle and orderability

현재 기준 사실:

- 이전 paper 계좌는 실제로 만료됐고, 그 계좌에서 수집된 `broker_account_not_orderable`은 이전 계좌 무효 상태가 root cause였을 가능성이 높다.
- 새 paper APP key/secret과 계좌는 `paper-2026-09-03` epoch로 분리한다.
- 새 계좌의 auth-only token refresh와 account snapshot이 통과했다.
- 새 계좌의 `VTTC8908R`, `ORD_DVSN=00` read-only orderability는 `orderability_ok`, `rt_cd=0`, 양수 value presence로 통과했고 주문/취소 호출은 0회였다.
- 2026-09-03 새 계좌에서 동일 cash-order 경로의 자연 submission 36건이 성공했다. 이전 `broker_account_not_orderable`의 주원인은 만료·무효 상태였던 이전 계좌로 사실상 확인됐고, endpoint entitlement 지원 문의는 같은 오류가 새 계좌에서 재발할 때까지 닫아 둔다.
- 같은 날 invalid tick 4건은 `broker_invalid_request`와 `invalid_price_tick`으로, network timeout 1건은 `broker_network_error`로 구분한다. 둘을 account hard rejection과 섞지 않는다.

기본 lifecycle 확인은 네트워크 0회다.

```bash
python3 scripts/check_kis_paper_account_lifecycle.py
```

기존 orderability probe dry-run도 네트워크 0회다. `--execute`는 계좌 소유자가 해당 작업에서 명시 승인했고 장외이며 live runtime이 정지했을 때만 정확히 1회 사용한다. 반복 자동화는 `--execute`를 사용하지 않는다.

```bash
python3 scripts/probe_kis_paper_orderability.py
```

분류는 `orderability_ok`, `orderability_zero`, `account_not_orderable`, `auth_error`, `invalid_request`, `rate_limited`, `network_error`, `unknown_error`를 사용한다.
계좌번호, app key/secret, token, raw response는 출력하지 않는다.
새 계좌에서 자연 발생한 broker cash order가 성공하면 이전 account-orderability blocker는 종료한다. 같은 오류가 재발할 때만 sanitized KIS error, submission attempt, circuit 상태를 근거로 별도 entitlement 조사를 다시 연다.

## 7. Post-close ML/research observation

장후 학습 줄:

- `latest-post-close-ml.json`: status, completed_at, mode
- `latest-post-close-label-refresh.json`: status, completed_at
- challenger: active_model_version, recommended_action/model, promotion_applied
- top challenger: three_class_accuracy, buy/trade hit rate, cumulative_net_return_pct, trades_taken

표본이 작으면 수익률보다 표본 부족을 먼저 해석한다.

Rescue/avoid 줄:

- buy-avoid: status, date_range, joined_rows, best threshold, delta와 freshness
- buy-rescue: fresh overlay decision ledger rows/rescue rows, 실제 best threshold/trades/net, 모델 조합, Cybos proxy decision/target/precision
- hold-rescue: decision.status, replay 가능 lot, 적용 lot, delta_cash_sum

세 항목은 관측용이며 주문 정책, gate, threshold, active model에 반영하지 않는다.
과거 E1/E5는 자동 재실행하지 않는다. 역사와 결과는 `docs/logbook.md`와 사전등록 문서를 따른다.

## 8. Recovery policy

장중 보호 모드가 아니고 원인이 명확할 때만 dashboard/watchdog/startup launcher를 기존 helper로 안전 복구할 수 있다.
복구 뒤 status와 freshness를 재확인한다.
live runtime은 장전 warmup/정규장 외에는 새로 시작하지 않는다.
전략, 평가기 identity, Phase 0 기준, 실전 설정은 운영 복구 대상으로 보지 않는다.

## 9. Protected actions

다음을 daily ops에서 변경하지 않는다.

- `app/risk/`, `config/`, `VERSION`, `ALLOW_LIVE_ORDERS`, trading mode
- threshold, active model, feature, signal/gate, allocator, portfolio/cost/E7 manifest
- Phase 0 baseline
- 실전 주문/취소와 NAS backup
- application code와 canonical docs

종료된 날짜 one-off branch를 현재 절차로 되살리지 않는다.
E1/E5와 과거 Phase 0 recovery를 자동 재실행하지 않는다.

## 10. Status classification

- 우선순위는 `CRITICAL > ATTENTION > NORMAL`이다. 하나라도 CRITICAL 조건이 있으면 양호한 coverage나 lineage가 이를 낮추지 못하며 첫 줄은 반드시 `실패`다.
- `NORMAL`: runtime 상태가 장 상태와 맞고, coverage 95% 이상, lineage 100%, storm 0, 핵심 증거 identity가 일치한다.
- reconnect > 0이어도 storm=0, coverage>=95%, lineage=100%이면 `collection ok / connection watch`로 분리한다.
- `ATTENTION`: reconnect 관찰, stale/missing 운영 report, E7 `not_available_yet`, Phase 0 표본 부족/no submission, orderability 미확정처럼 즉시 데이터 무결성을 깨지 않는 후속 확인이다.
- `CRITICAL`: lineage 불완전, storm, coverage 기준 미달, E7 identity/mark/result mixing invalid, reconciliation mismatch, 보호 모드 위반이다.
- `storm_count > 0`은 coverage 95% 이상·lineage 100% 여부와 무관하게 항상 `CRITICAL`이다.
- 정규장 중 예상 밖 전 종목 공통 market/orderbook gap도 항상 `CRITICAL`이다. `forced_flat_time` 뒤 명시된 종가 동시호가 예상 market gap만 이 규칙에서 제외한다.
- E7 최소 표본 부족이나 수익성 숫자만으로 전략 변경을 권고하지 않는다.

최종 한국어 접두어는 `NORMAL=정상`, `ATTENTION=주의`, `CRITICAL=실패`다.

## 11. Final report

첫 줄은 `정상`, `주의`, `실패` 중 하나다.
이후 간결하게 다음을 포함한다.

- 장 상태와 runtime/watchdog/dashboard/startup launcher
- 데이터 coverage, decision ledger lineage, reconnect/storm
- Phase 0 최근 10 유효 거래일 누적, 오늘 broker submission/failure taxonomy, reconciliation
- E7 progress와 evaluator/manifest/evidence health
- 장후 ML과 buy-avoid/buy-rescue/hold-rescue
- 자동화가 실제 조치한 것
- 사람이 검토할 남은 조치
- 변경 금지 범위를 지켰는지

현재 작업 모드, 답변 접두어, 활성 체크리스트 갱신 여부, 기준 문서 반영 여부도 마지막에 확인한다.
