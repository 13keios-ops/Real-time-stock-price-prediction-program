# Current Implementation

## Current Status

The project now has a working local foundation for:

- KIS REST quote and orderbook collection
- KIS WebSocket parsing and replay-based online processing
- SQLite and JSONL runtime storage
- Minute-bar generation
- Feature and label generation
- Centroid baseline training
- LightGBM artifact training
- Validation-tail backtesting with trading-cost assumptions
- Gap/max-train aware walk-forward backtesting
- Multi-model challenger evaluation and ranking
- Walk-forward-gated challenger recommendation and leaderboard history
- Explicit active-model registry with builtin baseline fallback
- LightGBM challenger evaluation without automatic promotion
- Paper-trading state updates for replay and online flows
- Runtime and backtest report generation
- KIS WebSocket listening with reconnect handling and control-frame skipping
- KIS WebSocket listening now times out and reconnects when a subscribed connection produces no frames, instead of staying indefinitely connected-but-idle
- KIS WebSocket verification report generation
- KIS verification separation between connection readiness and market-data flow
- Local monitoring dashboard snapshot generation and HTTP serving
- Dashboard top status area and 10-tab layout for account, ML, prediction, signal/order, fills/bars, report, and misc views
- Every top-level dashboard tab now uses the same left-side vertical subtab layout instead of mixing layouts by tab
- Dashboard date / period filtering for today, specific day, recent 3/7/30 days, and all accumulated runtime data
- Dashboard learning view separation between actual runtime status and validation/comparison results
- Dashboard status tab now shows freshness for KIS verification, market bars, predictions, signals, training/evaluation, and dashboard generation
- Dashboard top hero now surfaces immediate alert cards when live runtime appears stale or KIS verification is too old
- Dashboard top alerts now distinguish regular-session failures from off-session informational states, so post-close verification records do not look like a live outage
- Dashboard top alerts no longer raise `오늘 학습 부재` by default; they only surface training/evaluation when the latest artifact is actually missing or stale
- Dashboard status script now normalizes the saved server-state file after a successful health check so stale `starting` state does not linger
- Dashboard prediction view now shows baseline price, expected move amount, actual outcome amount, and success status
- Dashboard prediction view now resolves actual outcomes with the first same-day minute bar at or after the target horizon, and marks post-close impossible outcomes as `결과 없음` instead of leaving them permanently `대기 중`
- Dashboard prediction view keeps the recent summary capped but the prediction-detail tab now shows all selected-period prediction rows
- Dashboard signal/order view now explains blocked sell signals and combines signal, order, and fill context
- Dashboard daily-report view now summarizes selected-period performance, insights, and next actions
- Virtual-paper account view now uses vertical subtabs for overview, holdings, and trade activity
- Virtual-paper holdings now show recent closed positions when no open positions remain
- Virtual-paper trade activity now expands into buy-order, sell-order, fill, and recent-signal subtabs
- Long dashboard tables and lists now render inside scrollable panels so accumulated rows can be reviewed without collapsing the page layout
- Replay WebSocket sample runs now use `kis-ws-replay` provenance and replay-scoped IDs
- Dashboard actual-runtime filtering now excludes contaminated minutes where real and test sources are mixed
- Dashboard actual-runtime filtering now also excludes out-of-session KIS REST snapshot minutes and raw rows
- Dashboard SQLite reads now skip schema initialization, use lock-aware retry, and are less likely to fail under live runtime writes
- Dashboard HTTP endpoints now return a temporary-unavailable response instead of dropping the connection when SQLite is briefly locked
- Dashboard default page and default JSON API now prefer the latest cached snapshot so the UI responds faster under load
- Dashboard manual refresh and 10-minute auto refresh now rebuild the snapshot through `/api/refresh` before reloading the page
- Dashboard ML tab now keeps showing the latest overall backtest / walk-forward / challenger artifacts even when the selected day has no new training or evaluation rows
- Dashboard background launch now resolves a real Python executable instead of relying on the Windows app alias
- Dashboard foreground and background launch scripts now both avoid the Windows `WindowsApps\python.exe` alias and prefer a real Python interpreter path
- Dashboard reads now treat a newly moved or empty SQLite runtime store as a valid zero-state instead of failing on missing tables
- Dashboard, live-runtime, watchdog, and review helper scripts now resolve `WorkspaceRoot` from the script location by default instead of relying on the caller's current directory
- Dashboard tab selection now persists across refresh with browser localStorage
- Root `.env` auto-loading for local execution
- Paper account product code defaulting for 8-digit account numbers
- Placeholder product codes such as `?ш린???곹뭹肄붾뱶` are treated as blank and default to `01` for paper mode
- KIS broker paper-account balance refresh and cached report generation
- Local virtual paper account vs broker paper-account reconciliation report generation
- Dashboard trading tab now separates local paper-engine state and broker paper-account balance
- Local paper-engine state and broker paper-account balance are intentionally shown as separate account views
- Local paper orders can now be mirrored into the broker paper account when `ENABLE_BROKER_PAPER_MIRRORING=true`
- Broker paper-order submissions are persisted and shown in the dashboard sync view
- Dashboard sync cards now show the latest reconciliation status, mismatch count, cash gap, and position gap details
- Online runtime now restores the previous local paper portfolio state from SQLite on restart
- The local paper-account summary now counts only post-alignment orders, fills, and broker submissions, so stale pre-alignment activity does not look like current state
- Live runtime background start / status / stop scripts are available
- Runtime autoboot script and Windows startup-launcher install/remove/status scripts are available
- Runtime watchdog background start / status / stop scripts are available
- Repo review until deadline background start / status / stop scripts are available
- Midday Codex review now keeps only `run_codex_review_iteration_v4.ps1` as the active runner; older broken variants were removed
- Live runtime status and watchdog scripts now parse the cached dashboard snapshot with a serializer-based reader instead of relying on PowerShell `ConvertFrom-Json`
- Live runtime status now verifies that the recorded pid is still the actual `python -m app --kis-ws-listen` process, so stale pid reuse no longer looks like a healthy listener
- Live runtime start/status helpers now persist blocked reasons such as missing KIS credentials, including the common `root .env missing` recovery case
- Live runtime status now also reevaluates current KIS app key/secret readiness, so a stale `missing_kis_credentials` failure clears automatically after `.env` recovery instead of pinning watchdog in a permanently blocked state
- Dashboard, watchdog, hourly-audit, and deadline-review helpers now verify their saved pid against the real command line before trusting `running` state or stopping a process
- Runtime startup-launcher status now validates the saved `WorkspaceRoot`, `RuntimeDataDir`, and autoboot script path instead of checking only that the launcher file exists
- Local setup recovery preflight is now available through `scripts/check_local_setup.ps1`, which checks root `.env`, Python modules, dashboard, live runtime, watchdog, runtime startup launcher, and NAS recovery-root reachability
- Interactive KIS env restore is now available through `scripts/restore_kis_env_interactive.ps1`, which defaults to `paper` mode, prompts only for app key/secret in a visible PowerShell window, writes root `.env`, and immediately reruns live-runtime/watchdog/KIS verification checks
- Paper account connection is now available through `scripts/connect_kis_paper_account_interactive.ps1`, which keeps existing paper app key/secret, asks only for the 8-digit paper account number, leaves `KIS_PRODUCT_CODE_PAPER` blank, enables broker paper mirroring, refreshes reconciliation, and restarts runtime helpers
- `scripts/check_local_setup.ps1` now reports whether the paper account number is present and shaped as 8 digits or 8 digits-2 digits; explicit paper product code is optional
- Paper dual-account verification is now available through `scripts/verify_paper_dual_account_match.ps1`, which can sync root `.env` `PAPER_INITIAL_CASH` to the KIS paper-account cash, align the local marker baseline, and write a local-vs-broker match report
- Online runtime IDs now include a per-process unique namespace, so restarted live listeners do not reuse `paper-order-online-*` IDs and overwrite old SQLite rows
- Broker paper sync now ignores broker submissions at or before the latest paper-alignment marker, so old broker fills are not reapplied to a fresh broker baseline
- Paper alignment baseline positions are merged by symbol with post-alignment position updates, so a new fill in one symbol does not hide unchanged baseline holdings in reconciliation
- Online runtime and broker paper sync now adjust restored cash from fills newer than the restored snapshot, so a stale baseline snapshot does not inflate local virtual equity after restart.
- Runtime helper scripts now `return` control to the caller instead of terminating the parent PowerShell session, so autoboot/watchdog/post-close flows can compose dashboard/live-runtime helpers safely
- Runtime autoboot and Monday startup now fail fast when a nested `python -m app ...` command fails instead of silently continuing
- Paper reconciliation now uses a longer SQLite write timeout and retry window under live-runtime contention
- Online runtime now records both 15-minute and 60-minute predictions, while signals and order decisions stay on the 15-minute horizon
- Dashboard trading tab now shows program state, symbol names, prediction result text, blocked sell-signal reasons, and local paper-engine operating status
- Dashboard trading tab now defaults to 10-minute auto-refresh and provides a manual `상태 업데이트` button
- Recent predictions now show baseline-price-relative expected move amounts and actual outcome amounts when the horizon has elapsed
- KIS REST snapshot retry/backoff for short rate-limit bursts
- Hourly repository audit automation with carry-forward state files
- Hourly repository audit now resolves GitHub Desktop's bundled `git.exe` when `git` is not available on PATH
- Midday Codex review `v4` now uses the same non-interactive Codex CLI invocation pattern as the hourly audit path, so long prompts complete and return reliably
- Git autopush helper scripts now default their scan root to `D:\GitHub`, and watcher state prunes repos that are no longer inside the active scan root
- Actual-only runtime cleanup now removes demo/replay/test rows from raw ticks, orderbooks, minute bars, serving tables, and paper tables
- Actual-only runtime cleanup now keeps portfolio snapshots written at actual broker fill minutes, not only order minutes.
- Actual-only ML rebuild now recreates feature rows, labels, LightGBM training, backtest, walk-forward, challenger, runtime report, and dashboard from real runtime data only
- Dashboard `today` range now falls back to the latest real market date when the current calendar date has no intraday data yet, while ML `today` counts still follow the actual calendar day of training/evaluation runs
- Post-close ML maintenance now uses a lock-aware batch rebuild path, so real-data-only feature/label regeneration and LightGBM retraining finish without the earlier SQLite lock/stall behavior
- Post-close ML maintenance no longer restarts live runtime outside the regular session
- Runtime watchdog now tolerates dashboard snapshots that do not yet have a KIS verification record, instead of crashing on a null access during zero-state recovery
- Runtime watchdog now refreshes the dashboard snapshot through `/api/refresh`, uses the current market session plus the latest KIS verification file, and restarts regular-session live runtime when market bars are `missing` or `stale`
- Runtime watchdog regular-session stale recovery restarts live runtime with the configured watchlist instead of narrowing the production listener to the single KIS verification symbol.
- Runtime watchdog allows a longer dashboard `/api/refresh` timeout because a full snapshot rebuild can take around a minute on the current runtime dataset
- Runtime watchdog now throttles full dashboard `/api/refresh` rebuilds to a 10-minute default and uses live-runtime freshness first, reducing sustained CPU load from repeated snapshot rebuilds.
- Runtime watchdog now holds or stops live runtime during pre-open, post-close, and weekend sessions instead of keeping an idle WebSocket reconnect loop alive.
- Live runtime status now clears harmless INFO log tails when the listener is intentionally stopped.
- The paper-trading spread gate default is now `MAX_SPREAD_BPS=25.0`, matching the observed 2026-04-29 Samsung Electronics paper feed spread while keeping confidence/time/long-only gates active.

## Recommended Dev Flow

### 1. Synthetic end-to-end check

```powershell
.\scripts\run_full_synthetic_cycle.ps1
```

This now runs:

- synthetic data seeding
- minute-bar creation
- feature/label creation
- LightGBM training first
- centroid fallback training when LightGBM cannot train
- validation-tail backtest
- walk-forward backtest
- runtime report generation

### 2. Explicit backtest rerun

```powershell
.\scripts\run_backtest.ps1
```

### 3. Explicit walk-forward rerun

```powershell
.\scripts\run_walk_forward_backtest.ps1
```

Recommended variant for the current dataset:

```powershell
python -m app --run-walk-forward --horizon-min 15 --walk-forward-min-train-rows 30 --walk-forward-test-rows 10 --walk-forward-step-rows 10 --walk-forward-gap-rows 15 --walk-forward-max-train-rows 40
```

### 4. KIS REST development cycle

```powershell
.\scripts\run_full_kis_cycle.ps1
```

This runs:

- watchlist polling
- minute-bar creation
- feature/label creation
- LightGBM training when enough labels exist
- centroid fallback training when LightGBM cannot train
- validation-tail backtest when training succeeds
- walk-forward backtest when training succeeds
- challenger review when training succeeds
- runtime report generation

The collector now adds a short gap between current-price and orderbook requests and retries short KIS rate-limit bursts instead of failing immediately.

### 4-1. Safe active-model reset

```powershell
python -m app --set-active-builtin --builtin-model baseline --horizon-min 15
```

Use this when we want Monday runtime prediction and paper trading to stay on the stable builtin baseline while newer ML challengers are still being evaluated.

### 4-2. Shadow ML refresh

```powershell
.\scripts\run_ml_shadow_cycle.ps1
```

This runs:

- safe baseline activation
- LightGBM training artifact refresh
- active-model backtest
- walk-forward refresh
- challenger comparison
- runtime report update

### 4-3. Actual-data-only rebuild

```powershell
.\scripts\rebuild_actual_ml_state.ps1
```

This now runs:

- removal of demo / replay / synthetic runtime rows
- rebuild of actual-only feature and label rows
- baseline active-model reset
- LightGBM retraining without auto-promotion
- fresh backtest / walk-forward / challenger outputs
- runtime report and dashboard rebuild

Latest verified actual-only rebuild result:

- feature rows written: `3888`
- label rows written: `7189`
- latest LightGBM:
  - `train_rows=3052`
  - `validation_rows=763`
  - `validation_accuracy=0.667104`
- latest backtest:
  - `rows_evaluated=763`
  - `trades_taken=255`
  - `overall_accuracy=0.162516`
  - `cumulative_net_return_pct=11.815401`
- latest walk-forward:
  - `folds=377`
  - `rows_evaluated=3770`
  - `overall_accuracy=0.434748`
  - `cumulative_net_return_pct=26.58323`
- latest challenger:
  - `best_candidate=fresh_centroid`
  - `recommended_action=review_required`
  - `decision_reason=Walk-forward overall accuracy is too low (0.4347).`
  - `walk_forward_gate_status=needs_review`

### 5. KIS WebSocket live listener

```powershell
.\scripts\run_kis_ws_listener.ps1
```

This uses:

- watchlist symbols by default
- trade and orderbook channels
- reconnect attempts
- control-frame skipping
- online pipeline processing into runtime storage

Background runtime helpers:

```powershell
.\scripts\start_live_runtime_background.ps1
.\scripts\get_live_runtime_status.ps1
.\scripts\stop_live_runtime.ps1
```

Bounded repo review helpers:

```powershell
.\scripts\start_repo_review_until_deadline_background.ps1
.\scripts\get_repo_review_until_deadline_status.ps1
.\scripts\stop_repo_review_until_deadline.ps1
```

기본값은 `오늘 오전 10시 KST`까지이고, 이미 10시가 지난 시각이면 다음날 오전 10시까지로 자동 맞춘다.
workspace 경로에 공백이 있어도 하위 iteration 호출이 끊기지 않도록 quoting 을 보강했고, iteration timeout 기본값은 `600초`다.

PC 재부팅 후 자동 시작 helper:

```powershell
.\scripts\start_runtime_autoboot.ps1
.\scripts\install_runtime_startup_launcher.ps1
.\scripts\get_runtime_startup_launcher_status.ps1
.\scripts\remove_runtime_startup_launcher.ps1
.\\scripts\\check_local_setup.ps1
```

To restore KIS app key/secret and account fields together, rerun:

```powershell
.\scripts\restore_kis_env_interactive.ps1 -IncludeAccountFields
```

To connect or repair only the KIS paper account number, use:

```powershell
.\scripts\connect_kis_paper_account_interactive.ps1
```

This paper-account connector does not ask for `KIS_PRODUCT_CODE_PAPER`. If the KIS paper-account screen has no product code, keep it blank; the app applies the paper default internally when a KIS REST call needs it.
After a successful broker balance refresh, it also syncs root `.env` `PAPER_INITIAL_CASH` to the broker paper cash so the local virtual book and KIS paper account start from the same cash baseline.

`start_runtime_autoboot.ps1` 는 PC 로그인 직후 가볍게 복구용 루틴만 수행한다.

- dashboard background start
- live runtime background start
- demo/sample runtime cleanup
- broker paper-account refresh
- paper-account reconciliation refresh
- runtime report refresh
- dashboard rebuild

It now validates each nested `python -m app ...` command and stops immediately if one of them fails.

Broker-paper mirroring:

```powershell
$env:ENABLE_BROKER_PAPER_MIRRORING="true"
.\scripts\start_runtime_autoboot.ps1
```

The current strategy default is `ENABLE_BROKER_PAPER_MIRRORING=true`.

When enabled, local virtual orders are submitted to the KIS paper account and broker status/fill sync is used to keep the local virtual book aligned with the broker result. Dashboard sync cards show whether balances and holdings still match.

Broker baseline alignment:

```powershell
.\scripts\align_local_paper_to_broker.ps1
python -m app --align-local-paper-to-broker
```

This path now uses marker-based alignment instead of destructive row deletion. The latest marker is written to `runtime-data/reports/broker-paper/latest-alignment.json`.

즉, 기존 `start_monday_runtime.ps1` 처럼 shadow ML 학습과 KIS verification까지 모두 돌리는 무거운 준비 루틴이 아니라, 부팅 직후 서비스 복구 중심의 가벼운 경로다.

When the live runtime is running:

- watchlist symbols are streamed continuously
- 15-minute and 60-minute predictions are both written
- signals and order gating remain 15-minute only
- the dashboard trading tab should move from `대기 중` to `운용 중`

### 6. KIS WebSocket readiness and live verification

```powershell
.\scripts\verify_kis_ws.ps1
```

This now checks:

- `.env` presence
- credential readiness
- `websockets` package availability
- approval key issuance
- live listen attempt when prerequisites are met
- separation between `connection_ready` and `market_data_flow_ok`
- session-aware interpretation for weekend / pre-open / post-close runs
- verification report generation

### 7. Challenger review

```powershell
.\scripts\run_challenger_review.ps1
```

This compares:

- current active model
- baseline builtin model
- linear-score builtin model
- latest LightGBM artifact challenger
- freshly fitted centroid challenger
- recommendation, reason, walk-forward gate status, and leaderboard history

### 8. Hourly repository audit automation

```powershell
.\scripts\run_hourly_repo_audit_iteration.ps1
```

Background runner:

```powershell
.\scripts\start_hourly_repo_audit_background.ps1
```

Recommended scheduler:

- prefer Codex automations for hourly scheduling
- use the PowerShell background runner only as a fallback
- Codex automations are easier to stop from the app UI

Status:

```powershell
.\scripts\get_hourly_repo_audit_status.ps1
```

Stop:

```powershell
.\scripts\stop_hourly_repo_audit.ps1
```

This automation now:

- rereads canonical docs every run
- inspects repo structure, runtime-data, and git status
- optionally runs KIS verification only during regular session hours
- asks Codex CLI to produce review, web notes, draft, context, progress, and backlog outputs
- stores all state under `runtime-data/reports/codex/automation/`
- carries forward stable open item ids across repeated runs
- has a dedicated background launcher that leaves runner state in `runtime-data/reports/codex/automation/state/runner-state.json`
- reports `stale` when the saved runner pid is no longer alive
- verifies the saved runner pid against the actual PowerShell script command line before reporting `running` or stopping the runner

### 9. Local monitoring dashboard

```powershell
python -m app --build-dashboard
```

This writes:

- `runtime-data/reports/dashboard/latest-dashboard.html`
- `runtime-data/reports/dashboard/latest-dashboard.json`

Live server:

```powershell
.\scripts\run_dashboard.ps1
```

This serves:

- `http://127.0.0.1:8765`

Default dashboard behavior:

- auto-refresh every 10 minutes
- manual refresh from the `상태 업데이트` button
- recent predictions show `기준가`, `예상 변동`, and `실제 결과`; prediction detail shows all selected-period rows
- top area shows current runtime state, version, and period filter
- tabs are `모의투자(가상)`, `모의계좌(실제)`, `실 운용계좌`, `머신러닝 현황`, `상태 및 설정`, `예측현황`, `신호 & 주문현황`, `체결과 분봉`, `오늘의 리포트`, `기타`
- `모의투자(가상)` tab shows local virtual-book status, holdings, buy/sell/fill summary, and strategy summary
- the virtual-paper tab now uses a left-side vertical selector instead of stacking all sections at once
- the other top-level tabs now follow the same vertical-selector pattern for consistency
- `모의계좌(실제)` and `실 운용계좌` tabs show broker account state, holdings, and account notes separately
- `예측현황` aggregates the selected period, while the table focuses on recent rows
- `오늘의 리포트` summarizes the selected period rather than only the latest few events
- long tables and bullet lists use an internal scroll panel instead of forcing the whole page to grow endlessly

Background start / status / stop:

```powershell
.\scripts\start_dashboard_background.ps1
.\scripts\get_dashboard_status.ps1
.\scripts\stop_dashboard.ps1
```

The dashboard currently shows:

- `거래 현황`
  - 현재 프로그램 상태
  - 최근 예측, 최근 신호, 최근 주문, 최근 체결과 분봉
  - 로컬 모의운용 계좌, 브로커 모의계좌 잔고, KIS 연결 상태
- `머신러닝 현황`
  - 실운용 학습 상태, 현재 운용 모델 상태
  - 오프라인 검증 결과, 최신 학습, 최신 평가, 백테스트, 워크포워드, 챌린저 비교
- `기타`
  - 프로젝트 정보, 상세 집계, 자동 점검 backlog 와 다음 작업

The dashboard now filters out `sample`, `synthetic`, and `demo` runtime rows by default.
It also excludes replay-scoped runtime rows and mixed minutes that contain both actual and non-actual sources.
If older test-serving rows are already mixed into SQLite, clean them first:

```powershell
.\scripts\cleanup_runtime_test_data.ps1
```

Refresh only the broker paper-account cache:

```powershell
.\scripts\refresh_kis_account.ps1
python -m app --kis-account-balance
```

Reconcile the local virtual paper book against the broker paper account:

```powershell
.\scripts\reconcile_paper_accounts.ps1
python -m app --reconcile-paper-accounts
```

This comparison uses the current full local virtual-paper account state, not the date-filtered dashboard slice.

Sync the local starting cash to the broker paper account and verify the two books match:

```powershell
.\scripts\verify_paper_dual_account_match.ps1 -SyncInitialCash -AlignToBroker -AsJson
.\scripts\verify_paper_dual_account_match.ps1 -AsJson
```

The first command is the 장 시작 전 reset/check path. The second command is the non-mutating status check after runtime starts. The latest result is written to `runtime-data/reports/reconciliation/latest-paper-dual-account-match.{md,json}`.

If an old dashboard server is still holding port `8765`, the start / status / stop scripts now detect the actual port owner and replace it cleanly.
The background launcher now prefers `pythonw.exe` when available, falls back to the real `python.exe` when needed, and waits for `/health` before marking the server as running.
The dashboard status script now also checks `/api/dashboard.json`, not only `/health`, so a port-listening process without real payload responses no longer counts as healthy.
Dashboard start/status/stop helpers now also verify that a saved pid still belongs to the real `python -m app --serve-dashboard` process before trusting or stopping it.
The default page and `/api/dashboard.json` now serve the most recent cached snapshot first, while `/api/refresh` rebuilds the snapshot on demand.
The dashboard snapshot can now be read reliably from PowerShell status scripts even when it contains long Korean text and large nested JSON blocks.

Runtime watchdog start / status / stop:

```powershell
.\scripts\start_runtime_watchdog_background.ps1
.\scripts\get_runtime_watchdog_status.ps1
.\scripts\stop_runtime_watchdog.ps1
```

The watchdog keeps `dashboard` alive and keeps `live runtime` alive only during the regular session.
Outside the regular session, it leaves live runtime stopped or stops an already-running listener to prevent post-close WebSocket reconnect churn.
It asks the dashboard server to rebuild the cached snapshot through `/api/refresh` when the cached snapshot is older than the 10-minute default, so status scripts are not pinned to an old JSON file without forcing a rebuild on every watchdog cycle.
Watchdog state is written to `runtime-data/reports/runtime-watchdog/state/watchdog-state.json`.
The watchdog reads market-bar freshness from the refreshed dashboard snapshot and uses the current market session plus the latest KIS verification file before deciding whether to restart live runtime.
During the regular session, `missing` or `stale` market bars trigger a live-runtime restart after a short startup grace period.
When root `.env` is missing or KIS credentials are not configured, the watchdog now records a blocked live-runtime state instead of retrying the same failing restart every cycle.
If `.env` is restored later and the active trading-mode app key/secret become available again, the stale blocked state is cleared back to `stopped` so the next watchdog cycle can retry the listener automatically.

### 10. Monday runtime starter

```powershell
.\scripts\start_monday_runtime.ps1
```

This currently:

- starts the dashboard server when it is not already running
- starts the live runtime listener when it is not already running
- starts the runtime watchdog when it is not already running
- removes demo/sample SQLite runtime rows unless skipped
- refreshes runtime report and dashboard snapshot
- runs shadow ML refresh unless skipped
- refreshes the broker paper-account cache
- refreshes paper-account reconciliation
- runs KIS verification unless skipped
- prints a compact JSON summary for Monday startup checks

## Useful CLI Commands

```powershell
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
python -m app --replay-sample-ws --symbol 005930
python -m app --kis-ws-listen --max-frames 50 --max-reconnects 2
python -m app --verify-kis-ws --symbols 005930 --max-frames 5 --max-reconnects 0
```

## Important Output Paths

- Runtime report: `runtime-data/reports/runtime/latest-runtime-report.md`
- Runtime report JSON: `runtime-data/reports/runtime/latest-runtime-report.json`
- Backtest report: `runtime-data/reports/backtests/latest-backtest-h15.md`
- Backtest report JSON: `runtime-data/reports/backtests/latest-backtest-h15.json`
- Walk-forward report: `runtime-data/reports/backtests/latest-walk-forward-h15.md`
- Walk-forward report JSON: `runtime-data/reports/backtests/latest-walk-forward-h15.json`
- Challenger report: `runtime-data/reports/challengers/latest-challengers-h15.md`
- Challenger report JSON: `runtime-data/reports/challengers/latest-challengers-h15.json`
- Challenger leaderboard JSON: `runtime-data/reports/challengers/leaderboard-h15.json`
- KIS verification report: `runtime-data/reports/kis-ws/latest-verification.md`
- KIS verification report JSON: `runtime-data/reports/kis-ws/latest-verification.json`
- Paper reconciliation report: `runtime-data/reports/reconciliation/latest-paper-account-sync.md`
- Paper reconciliation report JSON: `runtime-data/reports/reconciliation/latest-paper-account-sync.json`
- Paper dual-account match report: `runtime-data/reports/reconciliation/latest-paper-dual-account-match.md`
- Paper dual-account match report JSON: `runtime-data/reports/reconciliation/latest-paper-dual-account-match.json`
- Hourly audit review history: `runtime-data/reports/codex/automation/history/`
- Hourly audit research notes: `runtime-data/reports/codex/automation/research/`
- Hourly audit draft: `runtime-data/reports/codex/automation/drafts/latest-improvement-draft.md`
- Hourly audit context: `runtime-data/reports/codex/automation/state/latest-context.md`
- Hourly audit progress JSON: `runtime-data/reports/codex/automation/state/latest-progress.json`
- Hourly audit backlog JSON: `runtime-data/reports/codex/automation/backlog/latest-priority-backlog.json`
- Dashboard snapshot HTML: `runtime-data/reports/dashboard/latest-dashboard.html`
- Dashboard snapshot JSON: `runtime-data/reports/dashboard/latest-dashboard.json`
- Recovery setup check JSON: `runtime-data/reports/recovery/latest-local-setup-check.json`
- Recovery setup check Markdown: `runtime-data/reports/recovery/latest-local-setup-check.md`
- Model registry: `runtime-data/ml/registry.json`
- Centroid artifacts: `runtime-data/ml/models/`

## Current Recommendation

The main remaining step is true intraday KIS WebSocket validation in an environment that has:

- a populated root `.env` with KIS credentials
- network access
- the `websockets` Python package installed

The challenger framework is now in place, so the best follow-up after live verification is adding stronger challenger models on top of the current baseline, linear-score, and centroid comparison flow.

At the moment, challenger output can deliberately stop at `review_required` when the latest walk-forward report is still weak even if the best candidate beats the active model on the validation slice.

The agreed next ML direction is:

- main model: `LightGBM`
- support models: `baseline`, `centroid`, `linear-score`
- operating window: `recent 60 trading days + today`
- runtime mode: `intraday inference`, `end-of-day retraining`

The current operational posture is:

- `baseline-h15-v1` remains the active runtime model
- `lightgbm-h15-v1` is trained and stored as a challenger artifact
- challenger reports now include `latest_lightgbm` even when baseline stays active
- automatic activation from a newly written LightGBM artifact is intentionally disabled

This does not mean older data should be deleted. The rolling 60-day window is for active training, while older data should stay available for replay, drift checks, regime comparison, and challenger validation.

## KIS Paper Account Note

For paper mode, if the account information is only available as an 8-digit account number, leave `KIS_PRODUCT_CODE_PAPER` blank. The settings loader treats it as the paper default internally when a KIS REST account/order call needs a product code.

If `.env` still contains the template placeholder `?ш린???곹뭹肄붾뱶`, the loader also treats that as blank and falls back to `01`.

If the account is written like `12345678-01`, the loader will split it into:

- `KIS_ACCOUNT_NO_PAPER=12345678`
- `KIS_PRODUCT_CODE_PAPER=01`

The broker paper-account balance can now be refreshed with:

```powershell
.\scripts\refresh_kis_account.ps1
python -m app --kis-account-balance
```

The cached report is written to:

- `runtime-data/reports/kis-account/latest-account.md`
- `runtime-data/reports/kis-account/latest-account.json`



