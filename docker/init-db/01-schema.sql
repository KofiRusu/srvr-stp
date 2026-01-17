-- ChatOS Database Schema
-- Historical data stores for A/B/C context types

-- Trade History (Context A - Orderflow)
CREATE TABLE IF NOT EXISTS trade_history (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    price DECIMAL(20, 8) NOT NULL,
    quantity DECIMAL(20, 8) NOT NULL,
    side VARCHAR(4) NOT NULL,
    trade_id BIGINT,
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_trade_history_symbol_time ON trade_history(symbol, timestamp DESC);

-- Funding Rates (Context A)
CREATE TABLE IF NOT EXISTS funding_rates (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    funding_rate DECIMAL(20, 10) NOT NULL,
    mark_price DECIMAL(20, 8),
    index_price DECIMAL(20, 8),
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_funding_symbol_time ON funding_rates(symbol, timestamp DESC);

-- Open Interest (Context A)
CREATE TABLE IF NOT EXISTS open_interest (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    open_interest DECIMAL(30, 8) NOT NULL,
    open_interest_usd DECIMAL(30, 2),
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_oi_symbol_time ON open_interest(symbol, timestamp DESC);

-- Liquidations (Context A)
CREATE TABLE IF NOT EXISTS liquidations (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(5) NOT NULL,
    price DECIMAL(20, 8) NOT NULL,
    quantity DECIMAL(20, 8) NOT NULL,
    usd_value DECIMAL(20, 2),
    exchange VARCHAR(20),
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_liq_symbol_time ON liquidations(symbol, timestamp DESC);

-- Orderbook Snapshots (Context A)
CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    bids JSONB NOT NULL,
    asks JSONB NOT NULL,
    spread DECIMAL(20, 8),
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ob_symbol_time ON orderbook_snapshots(symbol, timestamp DESC);

-- Regime Classifications (Context B)
CREATE TABLE IF NOT EXISTS regime_history (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    regime VARCHAR(30) NOT NULL,
    confidence DECIMAL(5, 4),
    volatility_1h DECIMAL(10, 6),
    volatility_24h DECIMAL(10, 6),
    trend_strength DECIMAL(5, 4),
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_regime_symbol_time ON regime_history(symbol, timestamp DESC);

-- Trading Decisions (Context C)
CREATE TABLE IF NOT EXISTS trading_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thought_id VARCHAR(100) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    action VARCHAR(10) NOT NULL,
    entry_price DECIMAL(20, 8),
    stop_loss DECIMAL(20, 8),
    take_profit DECIMAL(20, 8),
    size DECIMAL(20, 8),
    leverage DECIMAL(5, 2),
    confidence DECIMAL(5, 4),
    reasoning TEXT,
    context_hash VARCHAR(64),
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_decisions_symbol_time ON trading_decisions(symbol, timestamp DESC);

-- Trade Outcomes (Context C)
CREATE TABLE IF NOT EXISTS trade_outcomes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_id UUID REFERENCES trading_decisions(id),
    exit_price DECIMAL(20, 8) NOT NULL,
    pnl_usd DECIMAL(20, 2),
    pnl_pct DECIMAL(10, 4),
    slippage_bps DECIMAL(10, 4),
    latency_ms INTEGER,
    exit_reason VARCHAR(50),
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_outcomes_decision ON trade_outcomes(decision_id);

-- Audit Trail
CREATE TABLE IF NOT EXISTS audit_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cycle_id VARCHAR(100) NOT NULL,
    input_hash VARCHAR(64) NOT NULL,
    inputs JSONB NOT NULL,
    thoughts JSONB NOT NULL,
    arbiter_decision JSONB,
    risk_result JSONB,
    execution_result JSONB,
    model_versions JSONB,
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_cycle ON audit_records(cycle_id);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_records(timestamp DESC);
