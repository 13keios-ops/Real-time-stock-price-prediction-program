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
- KIS WebSocket verification report generation
- KIS verification separation between connection readiness and market-data flow
- Local monitoring dashboard snapshot generation and HTTP serving
- Dashboard top status area and 10-tab layout for account, ML, prediction, signal/order, fills/bars, report, and misc views
- Every top-level dashboard tab now uses the same left-side vertical subtab layout instead of mixing layouts by tab
- Dashboard date / period filtering for today, specific day, recent 3/7/30 days, and all accumulated runtime data
- Dashboard learning view separation between actual runtime status and validation/comparison results
- Dashboard prediction view now shows baseline price, expected move amount, actual outcome amount, and success status
- Dashboard prediction view now supports up to 100 recent rows and adds AM/PM, hour-slot, and up/down stats
- Dashboard signal/order view now explains blocked sell signals and combines signal, order, and fill context
- Dashboard daily-report view now summarizes selected-period performance, insights, and next actions
- Virtual-paper account view now uses vertical subtabs for overview, holdings, and trade activity
- Virtual-paper holdings now show recent closed positions when no open positions remain
- Virtual-paper trade activity now expands into buy-order, sell-order, fill, and recent-signal subtabs
- Long dashboard tables and lists now render inside scrollable panels so accumulated rows can be reviewed without collapsing the page layout
- Replay WebSocket sample runs now use `kis-ws-replay` provenance and replay-scoped IDs
- Dashboard actual-runtime filtering now excludes contaminated minutes where real and test sources are mixed
- Dashboard actual-runtime filtering now also excludes out-of-session KIS REST snapshot minutes and raw rows
- Dashboard background launch now resolves a real Python executable instead of relying on the Windows app alias
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
- Live runtime background start / status / stop scripts are available
- Runtime autoboot script and Windows startup-launcher install/remove/status scripts are available
- Online runtime now records both 15-minute and 60-minute predictions, while signals and order decisions stay on the 15-minute horizon
- Dashboard trading tab now shows program state, symbol names, prediction result text, blocked sell-signal reasons, and local paper-engine operating status
- Dashboard trading tab now defaults to 5-minute auto-refresh and provides a manual `?곹깭 ?낅뜲?댄듃` button
- Recent predictions now show baseline-price-relative expected move amounts and actual outcome amounts when the horizon has elapsed
- KIS REST snapshot retry/backoff for short rate-limit bursts
- Hourly repository audit automation with carry-forward state files
- Actual-only runtime cleanup now removes demo/replay/test rows from raw ticks, orderbooks, minute bars, serving tables, and paper tables
- Actual-only ML rebuild now recreates feature rows, labels, LightGBM training, backtest, walk-forward, challenger, runtime report, and dashboard from real runtime data only

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

PC 재부팅 후 자동 시작 helper:

```powershell
.\scripts\start_runtime_autoboot.ps1
.\scripts\install_runtime_startup_launcher.ps1
.\scripts\get_runtime_startup_launcher_status.ps1
.\scripts\remove_runtime_startup_launcher.ps1
```

`start_runtime_autoboot.ps1` 는 PC 로그인 직후 가볍게 복구용 루틴만 수행한다.

- dashboard background start
- live runtime background start
- broker paper-account refresh
- paper-account reconciliation refresh
- runtime report refresh
- dashboard rebuild

Optional broker-paper mirroring:

```powershell
$env:ENABLE_BROKER_PAPER_MIRRORING="true"
.\scripts\start_runtime_autoboot.ps1
```

When enabled, the local paper engine still records its own simulated fills immediately, while the broker paper account receives matching order submissions through KIS REST. Dashboard sync cards show whether balances and holdings still match.

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

- auto-refresh every 5 minutes
- manual refresh from the `상태 업데이트` button
- recent predictions show `기준가`, `예상 변동`, and `실제 결과`
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

If an old dashboard server is still holding port `8765`, the start / status / stop scripts now detect the actual port owner and replace it cleanly.
The background launcher now prefers `pythonw.exe` when available, falls back to the real `python.exe` when needed, and waits for `/health` before marking the server as running.

### 10. Monday runtime starter

```powershell
.\scripts\start_monday_runtime.ps1
```

This currently:

- starts the dashboard server when it is not already running
- starts the live runtime listener when it is not already running
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
- Hourly audit review history: `runtime-data/reports/codex/automation/history/`
- Hourly audit research notes: `runtime-data/reports/codex/automation/research/`
- Hourly audit draft: `runtime-data/reports/codex/automation/drafts/latest-improvement-draft.md`
- Hourly audit context: `runtime-data/reports/codex/automation/state/latest-context.md`
- Hourly audit progress JSON: `runtime-data/reports/codex/automation/state/latest-progress.json`
- Hourly audit backlog JSON: `runtime-data/reports/codex/automation/backlog/latest-priority-backlog.json`
- Dashboard snapshot HTML: `runtime-data/reports/dashboard/latest-dashboard.html`
- Dashboard snapshot JSON: `runtime-data/reports/dashboard/latest-dashboard.json`
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

For paper mode, if the account information is only available as an 8-digit account number, the settings loader now treats `KIS_PRODUCT_CODE_PAPER` as `01` by default.

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

