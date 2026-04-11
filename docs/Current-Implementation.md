# Current Implementation

## Current Status

The project now has a working local foundation for:

- KIS REST quote and orderbook collection
- KIS WebSocket parsing and replay-based online processing
- SQLite and JSONL runtime storage
- Minute-bar generation
- Feature and label generation
- Centroid baseline training
- Validation-tail backtesting with trading-cost assumptions
- Expanding-window walk-forward backtesting
- Multi-model challenger evaluation and ranking
- Conservative challenger promotion recommendation and leaderboard history
- Paper-trading state updates for replay and online flows
- Runtime and backtest report generation
- KIS WebSocket listening with reconnect handling and control-frame skipping
- KIS WebSocket verification report generation
- KIS verification separation between connection readiness and market-data flow
- Root `.env` auto-loading for local execution
- Paper account product code defaulting for 8-digit account numbers

## Recommended Dev Flow

### 1. Synthetic end-to-end check

```powershell
.\scripts\run_full_synthetic_cycle.ps1
```

This now runs:

- synthetic data seeding
- minute-bar creation
- feature/label creation
- centroid training
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

### 4. KIS REST development cycle

```powershell
.\scripts\run_full_kis_cycle.ps1
```

This runs:

- watchlist polling
- minute-bar creation
- feature/label creation
- training when enough labels exist
- validation-tail backtest when training succeeds
- walk-forward backtest when training succeeds
- challenger review when training succeeds
- runtime report generation

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
- freshly fitted centroid challenger
- recommendation, reason, and leaderboard history

## Useful CLI Commands

```powershell
python -m app --kis-current-price --symbol 005930
python -m app --kis-orderbook --symbol 005930
python -m app --kis-watchlist-poll --iterations 5 --interval-seconds 5
python -m app --build-minute-bars
python -m app --build-feature-dataset
python -m app --train-baseline --horizon-min 15
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
- Model registry: `runtime-data/ml/registry.json`
- Centroid artifacts: `runtime-data/ml/models/`

## Current Recommendation

The main remaining step is true intraday KIS WebSocket validation in an environment that has:

- a populated root `.env` with KIS credentials
- network access
- the `websockets` Python package installed

The challenger framework is now in place, so the best follow-up after live verification is adding stronger challenger models on top of the current baseline, linear-score, and centroid comparison flow.

## KIS Paper Account Note

For paper mode, if the account information is only available as an 8-digit account number, the settings loader now treats `KIS_PRODUCT_CODE_PAPER` as `01` by default.

If the account is written like `12345678-01`, the loader will split it into:

- `KIS_ACCOUNT_NO_PAPER=12345678`
- `KIS_PRODUCT_CODE_PAPER=01`
