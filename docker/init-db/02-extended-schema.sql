-- ChatOS Extended Database Schema
-- 14 new tables for comprehensive data collection

-- ============================================================================
-- COINMARKETCAP TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS coinmarketcap_global (
    id BIGSERIAL PRIMARY KEY,
    total_market_cap DECIMAL(30, 2),
    total_volume_24h DECIMAL(30, 2),
    btc_dominance DECIMAL(5, 2),
    eth_dominance DECIMAL(5, 2),
    active_cryptocurrencies INTEGER,
    active_exchanges INTEGER,
    fear_greed_index INTEGER,
    fear_greed_label VARCHAR(20),
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cmc_global_time ON coinmarketcap_global(timestamp DESC);

CREATE TABLE IF NOT EXISTS coinmarketcap_coins (
    id BIGSERIAL PRIMARY KEY,
    cmc_id INTEGER,
    symbol VARCHAR(20) NOT NULL,
    name VARCHAR(100),
    price DECIMAL(20, 8),
    market_cap DECIMAL(30, 2),
    volume_24h DECIMAL(30, 2),
    percent_change_1h DECIMAL(10, 4),
    percent_change_24h DECIMAL(10, 4),
    percent_change_7d DECIMAL(10, 4),
    circulating_supply DECIMAL(30, 2),
    max_supply DECIMAL(30, 2),
    market_cap_rank INTEGER,
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cmc_coins_symbol ON coinmarketcap_coins(symbol);
CREATE INDEX IF NOT EXISTS idx_cmc_coins_time ON coinmarketcap_coins(timestamp DESC);

-- ============================================================================
-- TRADINGVIEW TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS tradingview_prices (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    price DECIMAL(20, 8),
    volume DECIMAL(30, 2),
    rsi_14 DECIMAL(5, 2),
    macd DECIMAL(10, 4),
    macd_signal DECIMAL(10, 4),
    macd_histogram DECIMAL(10, 4),
    bb_upper DECIMAL(20, 8),
    bb_middle DECIMAL(20, 8),
    bb_lower DECIMAL(20, 8),
    ema_20 DECIMAL(20, 8),
    sma_50 DECIMAL(20, 8),
    sma_200 DECIMAL(20, 8),
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tv_prices_symbol ON tradingview_prices(symbol);
CREATE INDEX IF NOT EXISTS idx_tv_prices_time ON tradingview_prices(timestamp DESC);

CREATE TABLE IF NOT EXISTS tradingview_news (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT UNIQUE,
    source VARCHAR(100),
    content TEXT,
    summary TEXT,
    symbols TEXT[],
    published_at TIMESTAMPTZ,
    scraped_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tv_news_time ON tradingview_news(published_at DESC);

-- ============================================================================
-- COINGECKO TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS coingecko_coins (
    id BIGSERIAL PRIMARY KEY,
    coin_id VARCHAR(100) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    name VARCHAR(100),
    current_price DECIMAL(20, 8),
    market_cap DECIMAL(30, 2),
    total_volume DECIMAL(30, 2),
    price_change_24h DECIMAL(10, 4),
    price_change_percentage_24h DECIMAL(10, 4),
    market_cap_rank INTEGER,
    circulating_supply DECIMAL(30, 2),
    total_supply DECIMAL(30, 2),
    max_supply DECIMAL(30, 2),
    ath DECIMAL(20, 8),
    ath_change_percentage DECIMAL(10, 4),
    ath_date TIMESTAMPTZ,
    atl DECIMAL(20, 8),
    atl_date TIMESTAMPTZ,
    high_24h DECIMAL(20, 8),
    low_24h DECIMAL(20, 8),
    sparkline_7d JSONB,
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cg_coins_symbol ON coingecko_coins(symbol);
CREATE INDEX IF NOT EXISTS idx_cg_coins_time ON coingecko_coins(timestamp DESC);

CREATE TABLE IF NOT EXISTS coingecko_global (
    id BIGSERIAL PRIMARY KEY,
    active_cryptocurrencies INTEGER,
    upcoming_icos INTEGER,
    ongoing_icos INTEGER,
    ended_icos INTEGER,
    markets INTEGER,
    total_market_cap JSONB,
    total_volume JSONB,
    market_cap_percentage JSONB,
    market_cap_change_percentage_24h DECIMAL(10, 4),
    defi_market_cap DECIMAL(30, 2),
    defi_volume_24h DECIMAL(30, 2),
    defi_dominance DECIMAL(10, 4),
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cg_global_time ON coingecko_global(timestamp DESC);

-- ============================================================================
-- AGGR EXTENDED TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS aggr_cvd (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    exchange VARCHAR(50),
    cvd DECIMAL(30, 2),
    cvd_change_1m DECIMAL(30, 2),
    cvd_change_5m DECIMAL(30, 2),
    cvd_change_1h DECIMAL(30, 2),
    buy_volume DECIMAL(30, 2),
    sell_volume DECIMAL(30, 2),
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_aggr_cvd_symbol ON aggr_cvd(symbol);
CREATE INDEX IF NOT EXISTS idx_aggr_cvd_time ON aggr_cvd(timestamp DESC);

CREATE TABLE IF NOT EXISTS aggr_large_trades (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    exchange VARCHAR(50),
    side VARCHAR(4) NOT NULL,
    size DECIMAL(20, 8),
    price DECIMAL(20, 8),
    usd_value DECIMAL(20, 2),
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_aggr_large_symbol ON aggr_large_trades(symbol);
CREATE INDEX IF NOT EXISTS idx_aggr_large_time ON aggr_large_trades(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_aggr_large_usd ON aggr_large_trades(usd_value DESC);

-- ============================================================================
-- CCXT TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS ccxt_tickers (
    id BIGSERIAL PRIMARY KEY,
    exchange VARCHAR(50) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    bid DECIMAL(20, 8),
    ask DECIMAL(20, 8),
    last DECIMAL(20, 8),
    open DECIMAL(20, 8),
    high DECIMAL(20, 8),
    low DECIMAL(20, 8),
    close DECIMAL(20, 8),
    volume DECIMAL(30, 2),
    quote_volume DECIMAL(30, 2),
    vwap DECIMAL(20, 8),
    percentage DECIMAL(10, 4),
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ccxt_tickers_exchange ON ccxt_tickers(exchange);
CREATE INDEX IF NOT EXISTS idx_ccxt_tickers_symbol ON ccxt_tickers(symbol);
CREATE INDEX IF NOT EXISTS idx_ccxt_tickers_time ON ccxt_tickers(timestamp DESC);

CREATE TABLE IF NOT EXISTS ccxt_arbitrage (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    buy_exchange VARCHAR(50) NOT NULL,
    buy_price DECIMAL(20, 8) NOT NULL,
    sell_exchange VARCHAR(50) NOT NULL,
    sell_price DECIMAL(20, 8) NOT NULL,
    spread_pct DECIMAL(10, 4) NOT NULL,
    potential_profit_usd DECIMAL(20, 2),
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ccxt_arb_symbol ON ccxt_arbitrage(symbol);
CREATE INDEX IF NOT EXISTS idx_ccxt_arb_spread ON ccxt_arbitrage(spread_pct DESC);
CREATE INDEX IF NOT EXISTS idx_ccxt_arb_time ON ccxt_arbitrage(timestamp DESC);

-- ============================================================================
-- NEWS TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS news_articles (
    id BIGSERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    title TEXT NOT NULL,
    url TEXT UNIQUE,
    content TEXT,
    summary TEXT,
    author VARCHAR(200),
    published_at TIMESTAMPTZ,
    category VARCHAR(50),
    sentiment_score DECIMAL(5, 4),
    sentiment_label VARCHAR(20),
    related_symbols TEXT[],
    keywords TEXT[],
    scraped_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_news_source ON news_articles(source);
CREATE INDEX IF NOT EXISTS idx_news_time ON news_articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_sentiment ON news_articles(sentiment_score);

-- ============================================================================
-- SOCIAL MEDIA TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS social_posts (
    id BIGSERIAL PRIMARY KEY,
    platform VARCHAR(20) NOT NULL,
    post_id VARCHAR(100) UNIQUE,
    author VARCHAR(200),
    author_followers INTEGER,
    content TEXT,
    url TEXT,
    likes INTEGER DEFAULT 0,
    retweets INTEGER DEFAULT 0,
    replies INTEGER DEFAULT 0,
    views INTEGER DEFAULT 0,
    sentiment_score DECIMAL(5, 4),
    sentiment_label VARCHAR(20),
    related_symbols TEXT[],
    hashtags TEXT[],
    posted_at TIMESTAMPTZ,
    scraped_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_social_platform ON social_posts(platform);
CREATE INDEX IF NOT EXISTS idx_social_time ON social_posts(posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_social_sentiment ON social_posts(sentiment_score);

CREATE TABLE IF NOT EXISTS social_trends (
    id BIGSERIAL PRIMARY KEY,
    platform VARCHAR(20) NOT NULL,
    keyword VARCHAR(100) NOT NULL,
    volume INTEGER,
    sentiment_avg DECIMAL(5, 4),
    positive_pct DECIMAL(5, 2),
    negative_pct DECIMAL(5, 2),
    neutral_pct DECIMAL(5, 2),
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_social_trends_platform ON social_trends(platform);
CREATE INDEX IF NOT EXISTS idx_social_trends_keyword ON social_trends(keyword);
CREATE INDEX IF NOT EXISTS idx_social_trends_time ON social_trends(timestamp DESC);

-- ============================================================================
-- GOOGLE TRENDS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS google_trends (
    id BIGSERIAL PRIMARY KEY,
    keyword VARCHAR(100) NOT NULL,
    search_volume INTEGER,
    relative_interest INTEGER,
    region VARCHAR(10) DEFAULT 'US',
    timeframe VARCHAR(20),
    rising_queries JSONB,
    related_topics JSONB,
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_gtrends_keyword ON google_trends(keyword);
CREATE INDEX IF NOT EXISTS idx_gtrends_time ON google_trends(timestamp DESC);

-- ============================================================================
-- AGGREGATED SENTIMENT VIEW
-- ============================================================================

CREATE OR REPLACE VIEW aggregated_sentiment AS
SELECT 
    symbol,
    AVG(sentiment_score) as avg_sentiment,
    COUNT(*) as mention_count,
    SUM(CASE WHEN sentiment_label = 'positive' THEN 1 ELSE 0 END) as positive_count,
    SUM(CASE WHEN sentiment_label = 'negative' THEN 1 ELSE 0 END) as negative_count,
    SUM(CASE WHEN sentiment_label = 'neutral' THEN 1 ELSE 0 END) as neutral_count,
    MAX(scraped_at) as last_updated
FROM (
    SELECT unnest(related_symbols) as symbol, sentiment_score, sentiment_label, scraped_at
    FROM social_posts
    WHERE scraped_at > NOW() - INTERVAL '24 hours'
    UNION ALL
    SELECT unnest(related_symbols) as symbol, sentiment_score, sentiment_label, scraped_at
    FROM news_articles
    WHERE scraped_at > NOW() - INTERVAL '24 hours'
) combined
GROUP BY symbol;
