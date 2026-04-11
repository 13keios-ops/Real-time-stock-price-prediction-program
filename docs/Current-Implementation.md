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
- Paper-trading state updates for replay and online flows
- Runtime and backtest report generation
- KIS WebSocket listening with reconnect handling and control-frame skipping

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
python -m app --build-runtime-report
python -m app --replay-sample-ws --symbol 005930
python -m app --kis-ws-listen --max-frames 50 --max-reconnects 2
```

## Important Output Paths

- Runtime report: `runtime-data/reports/runtime/latest-runtime-report.md`
- Runtime report JSON: `runtime-data/reports/runtime/latest-runtime-report.json`
- Backtest report: `runtime-data/reports/backtests/latest-backtest-h15.md`
- Backtest report JSON: `runtime-data/reports/backtests/latest-backtest-h15.json`
- Walk-forward report: `runtime-data/reports/backtests/latest-walk-forward-h15.md`
- Walk-forward report JSON: `runtime-data/reports/backtests/latest-walk-forward-h15.json`
- Model registry: `runtime-data/ml/registry.json`
- Centroid artifacts: `runtime-data/ml/models/`

## Current Recommendation

The next highest-value step is live KIS WebSocket verification in an environment that has:

- valid KIS credentials
- network access
- the `websockets` Python package installed

After that, the best follow-up is upgrading the current walk-forward logic from an expanding-window centroid baseline into a richer rolling retrain loop with multiple challenger models.
