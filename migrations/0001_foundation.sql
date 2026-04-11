CREATE SCHEMA IF NOT EXISTS master;
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS curated;
CREATE SCHEMA IF NOT EXISTS feature;
CREATE SCHEMA IF NOT EXISTS serving;
CREATE SCHEMA IF NOT EXISTS paper;
CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS master.symbols (
    symbol TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    market TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS master.universe_membership (
    universe_version TEXT NOT NULL,
    symbol TEXT NOT NULL,
    rank_no INTEGER NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE NOT NULL,
    PRIMARY KEY (universe_version, symbol, effective_from)
);

CREATE TABLE IF NOT EXISTS raw.market_ticks (
    symbol TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    price NUMERIC(18, 4) NOT NULL,
    volume BIGINT NOT NULL,
    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw.orderbook_ticks (
    symbol TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    bid_price NUMERIC(18, 4) NOT NULL,
    ask_price NUMERIC(18, 4) NOT NULL,
    bid_size BIGINT NOT NULL,
    ask_size BIGINT NOT NULL,
    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS curated.minute_bars (
    symbol TEXT NOT NULL,
    bar_time TIMESTAMPTZ NOT NULL,
    open NUMERIC(18, 4) NOT NULL,
    high NUMERIC(18, 4) NOT NULL,
    low NUMERIC(18, 4) NOT NULL,
    close NUMERIC(18, 4) NOT NULL,
    volume BIGINT NOT NULL,
    trade_count INTEGER NOT NULL,
    PRIMARY KEY (symbol, bar_time)
);

CREATE TABLE IF NOT EXISTS feature.model_inputs (
    symbol TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    feature_set_version TEXT NOT NULL,
    values_json JSONB NOT NULL,
    PRIMARY KEY (symbol, event_time, feature_set_version)
);

CREATE TABLE IF NOT EXISTS feature.labels (
    symbol TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    horizon_min INTEGER NOT NULL,
    label TEXT NOT NULL,
    threshold_pct NUMERIC(10, 4) NOT NULL,
    PRIMARY KEY (symbol, event_time, horizon_min)
);

CREATE TABLE IF NOT EXISTS serving.predictions (
    prediction_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    horizon_min INTEGER NOT NULL,
    model_version TEXT NOT NULL,
    probability_up NUMERIC(12, 8) NOT NULL,
    probability_flat NUMERIC(12, 8) NOT NULL,
    probability_down NUMERIC(12, 8) NOT NULL
);

CREATE TABLE IF NOT EXISTS serving.trade_signals (
    signal_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    side TEXT NOT NULL,
    confidence NUMERIC(12, 8) NOT NULL,
    reason TEXT NOT NULL,
    allowed BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS serving.target_positions (
    target_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    side TEXT NOT NULL,
    target_qty BIGINT NOT NULL,
    target_notional NUMERIC(18, 4) NOT NULL,
    portfolio_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper.orders (
    order_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    side TEXT NOT NULL,
    qty BIGINT NOT NULL,
    limit_price NUMERIC(18, 4) NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper.order_events (
    order_event_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    detail TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper.fills (
    fill_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    fill_price NUMERIC(18, 4) NOT NULL,
    fill_qty BIGINT NOT NULL,
    commission NUMERIC(18, 4) NOT NULL,
    tax NUMERIC(18, 4) NOT NULL
);

CREATE TABLE IF NOT EXISTS paper.positions (
    symbol TEXT PRIMARY KEY,
    opened_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL,
    qty BIGINT NOT NULL,
    avg_price NUMERIC(18, 4) NOT NULL,
    last_price NUMERIC(18, 4) NOT NULL,
    market_value NUMERIC(18, 4) NOT NULL,
    cost_basis NUMERIC(18, 4) NOT NULL,
    realized_pnl NUMERIC(18, 4) NOT NULL,
    unrealized_pnl NUMERIC(18, 4) NOT NULL
);

CREATE TABLE IF NOT EXISTS paper.portfolio_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    event_time TIMESTAMPTZ NOT NULL,
    cash_balance NUMERIC(18, 4) NOT NULL,
    gross_market_value NUMERIC(18, 4) NOT NULL,
    net_liquidation_value NUMERIC(18, 4) NOT NULL,
    open_positions INTEGER NOT NULL,
    realized_pnl NUMERIC(18, 4) NOT NULL,
    unrealized_pnl NUMERIC(18, 4) NOT NULL
);

CREATE TABLE IF NOT EXISTS ops.risk_events (
    risk_event_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    gate TEXT NOT NULL,
    detail TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ops.reconciliation_runs (
    reconciliation_id TEXT PRIMARY KEY,
    as_of TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    mismatch_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS ops.replay_runs (
    replay_id TEXT PRIMARY KEY,
    as_of TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    drift_count INTEGER NOT NULL
);
