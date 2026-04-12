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
- Replay WebSocket sample runs now use `kis-ws-replay` provenance and replay-scoped IDs
- Dashboard actual-runtime filtering now excludes contaminated minutes where real and test sources are mixed
- Root `.env` auto-loading for local execution
- Paper account product code defaulting for 8-digit account numbers
- KIS REST snapshot retry/backoff for short rate-limit bursts
- Hourly repository audit automation with carry-forward state files

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

Background start / status / stop:

```powershell
.\scripts\start_dashboard_background.ps1
.\scripts\get_dashboard_status.ps1
.\scripts\stop_dashboard.ps1
```

The dashboard currently shows:

- active model and latest training summary
- KIS connection readiness and session note
- latest portfolio snapshot and recorded positions
- actual-runtime-only recent predictions, signals, orders, fills, minute bars
- latest automation backlog and next actions

The dashboard now filters out `sample`, `synthetic`, and `demo` runtime rows by default.
It also excludes replay-scoped runtime rows and mixed minutes that contain both actual and non-actual sources.
If older test-serving rows are already mixed into SQLite, clean them first:

```powershell
.\scripts\cleanup_runtime_test_data.ps1
```

If an old dashboard server is still holding port `8765`, the start / status / stop scripts now detect the actual port owner and replace it cleanly.

### 10. Monday runtime starter

```powershell
.\scripts\start_monday_runtime.ps1
```

This currently:

- starts the dashboard server when it is not already running
- refreshes runtime report and dashboard snapshot
- runs shadow ML refresh unless skipped
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

If the account is written like `12345678-01`, the loader will split it into:

- `KIS_ACCOUNT_NO_PAPER=12345678`
- `KIS_PRODUCT_CODE_PAPER=01`
