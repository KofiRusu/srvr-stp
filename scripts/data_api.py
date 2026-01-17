#!/usr/bin/env python3
"""
ChatOS Data API - Streams live market data to remote clients (Mac).
Provides REST endpoints and WebSocket streaming from Redis pub/sub.
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('DataAPI')

try:
    import redis.asyncio as redis
    import asyncpg
except ImportError as e:
    logger.error(f"Missing dependency: {e}")

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')
POSTGRES_URL = os.environ.get('POSTGRES_URL', 'postgresql://chatos:chatos@localhost:5432/chatos_trading')
API_KEY = os.environ.get('API_KEY', 'chatos_api_key_change_me')

redis_client: Optional[redis.Redis] = None
pg_pool: Optional[asyncpg.Pool] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, pg_pool
    redis_client = redis.from_url(REDIS_URL)
    pg_pool = await asyncpg.create_pool(POSTGRES_URL, min_size=2, max_size=10)
    logger.info("Connected to Redis and PostgreSQL")
    yield
    if redis_client:
        await redis_client.close()
    if pg_pool:
        await pg_pool.close()


app = FastAPI(
    title="ChatOS Data API",
    description="Real-time market data streaming for ChatOS clients",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


class LatestData(BaseModel):
    symbol: str
    data: dict
    timestamp: str


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/latest/{data_type}/{symbol}", response_model=LatestData)
async def get_latest(data_type: str, symbol: str, api_key: str = Depends(verify_api_key)):
    key = f"latest:{data_type}:{symbol}"
    data = await redis_client.get(key)
    if not data:
        raise HTTPException(status_code=404, detail=f"No data for {data_type}:{symbol}")
    return LatestData(
        symbol=symbol,
        data=json.loads(data),
        timestamp=datetime.now(timezone.utc).isoformat()
    )


@app.get("/api/symbols")
async def get_symbols(api_key: str = Depends(verify_api_key)):
    keys = await redis_client.keys("latest:*")
    symbols = set()
    for key in keys:
        parts = key.decode().split(':')
        if len(parts) >= 3:
            symbols.add(parts[2])
    return {"symbols": sorted(list(symbols))}


@app.get("/api/fear-greed")
async def get_fear_greed(api_key: str = Depends(verify_api_key)):
    cached = await redis_client.get("latest:sentiment:fear_greed")
    if cached:
        return json.loads(cached)
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT fear_greed_index as value, fear_greed_label as classification, timestamp
            FROM coinmarketcap_global
            WHERE fear_greed_index IS NOT NULL
            ORDER BY timestamp DESC LIMIT 1
        """)
        if row:
            return {
                "value": row['value'],
                "classification": row['classification'],
                "timestamp": row['timestamp'].isoformat() if row['timestamp'] else None
            }
    return {"value": 50, "classification": "Neutral", "timestamp": datetime.now(timezone.utc).isoformat(), "mock": True}


@app.get("/api/global-metrics")
async def get_global_metrics(api_key: str = Depends(verify_api_key)):
    cached = await redis_client.get("latest:cmc:global")
    if cached:
        return json.loads(cached)
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT total_market_cap, total_volume_24h, btc_dominance, 
                   fear_greed_index, fear_greed_label, timestamp
            FROM coinmarketcap_global
            ORDER BY timestamp DESC LIMIT 1
        """)
        if row:
            return {
                "total_market_cap": float(row['total_market_cap']) if row['total_market_cap'] else 0,
                "total_volume_24h": float(row['total_volume_24h']) if row['total_volume_24h'] else 0,
                "btc_dominance": float(row['btc_dominance']) if row['btc_dominance'] else 0,
                "fear_greed_index": row['fear_greed_index'],
                "fear_greed_label": row['fear_greed_label'],
                "timestamp": row['timestamp'].isoformat() if row['timestamp'] else None
            }
        cg_row = await conn.fetchrow("""
            SELECT total_market_cap, total_volume, market_cap_percentage, 
                   defi_market_cap, defi_volume_24h, timestamp
            FROM coingecko_global
            ORDER BY timestamp DESC LIMIT 1
        """)
        if cg_row:
            total_mc = cg_row['total_market_cap']
            if isinstance(total_mc, str):
                total_mc = json.loads(total_mc)
            return {
                "total_market_cap": total_mc.get('usd', 0) if isinstance(total_mc, dict) else 0,
                "total_volume_24h": 0,
                "btc_dominance": 0,
                "defi_market_cap": float(cg_row['defi_market_cap']) if cg_row['defi_market_cap'] else 0,
                "timestamp": cg_row['timestamp'].isoformat() if cg_row['timestamp'] else None
            }
    return {"total_market_cap": 0, "total_volume_24h": 0, "btc_dominance": 0, "mock": True}


@app.get("/api/news")
async def get_news(
    limit: int = Query(20, ge=1, le=100),
    source: Optional[str] = Query(None),
    api_key: str = Depends(verify_api_key)
):
    async with pg_pool.acquire() as conn:
        if source:
            rows = await conn.fetch("""
                SELECT id, source, title, url, content, author, published_at, 
                       category, sentiment_score, related_symbols, scraped_at
                FROM news_articles
                WHERE source = $1
                ORDER BY published_at DESC
                LIMIT $2
            """, source, limit)
        else:
            rows = await conn.fetch("""
                SELECT id, source, title, url, content, author, published_at, 
                       category, sentiment_score, related_symbols, scraped_at
                FROM news_articles
                ORDER BY published_at DESC
                LIMIT $1
            """, limit)
        articles = []
        for row in rows:
            articles.append({
                "id": row['id'],
                "source": row['source'],
                "title": row['title'],
                "url": row['url'],
                "content": row['content'][:500] if row['content'] else None,
                "author": row['author'],
                "published_at": row['published_at'].isoformat() if row['published_at'] else None,
                "sentiment_score": float(row['sentiment_score']) if row['sentiment_score'] else None,
                "related_symbols": row['related_symbols'] or []
            })
        return {"count": len(articles), "articles": articles}


@app.get("/api/sentiment/{symbol}")
async def get_sentiment(symbol: str, api_key: str = Depends(verify_api_key)):
    symbol_upper = symbol.upper()
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    async with pg_pool.acquire() as conn:
        news_stats = await conn.fetchrow("""
            SELECT COUNT(*) as count, 
                   AVG(sentiment_score) as avg_sentiment,
                   SUM(CASE WHEN sentiment_score > 0.2 THEN 1 ELSE 0 END) as positive,
                   SUM(CASE WHEN sentiment_score < -0.2 THEN 1 ELSE 0 END) as negative,
                   SUM(CASE WHEN sentiment_score >= -0.2 AND sentiment_score <= 0.2 THEN 1 ELSE 0 END) as neutral
            FROM news_articles
            WHERE $1 = ANY(related_symbols) AND published_at > $2
        """, symbol_upper, since)
        social_stats = await conn.fetchrow("""
            SELECT COUNT(*) as count,
                   AVG(sentiment_score) as avg_sentiment,
                   SUM(CASE WHEN sentiment_score > 0.2 THEN 1 ELSE 0 END) as positive,
                   SUM(CASE WHEN sentiment_score < -0.2 THEN 1 ELSE 0 END) as negative,
                   SUM(CASE WHEN sentiment_score >= -0.2 AND sentiment_score <= 0.2 THEN 1 ELSE 0 END) as neutral
            FROM social_posts
            WHERE $1 = ANY(related_symbols) AND posted_at > $2
        """, symbol_upper, since)
        news_count = news_stats['count'] if news_stats else 0
        social_count = social_stats['count'] if social_stats else 0
        total_count = news_count + social_count
        if total_count == 0:
            return {
                "symbol": symbol_upper,
                "period": "24h",
                "total_mentions": 0,
                "avg_sentiment": 0,
                "sentiment_label": "neutral",
                "breakdown": {"news": {}, "social": {}}
            }
        news_avg = float(news_stats['avg_sentiment']) if news_stats and news_stats['avg_sentiment'] else 0
        social_avg = float(social_stats['avg_sentiment']) if social_stats and social_stats['avg_sentiment'] else 0
        combined_avg = (news_avg * news_count + social_avg * social_count) / total_count if total_count > 0 else 0
        if combined_avg > 0.2:
            sentiment_label = "bullish"
        elif combined_avg < -0.2:
            sentiment_label = "bearish"
        else:
            sentiment_label = "neutral"
        return {
            "symbol": symbol_upper,
            "period": "24h",
            "total_mentions": total_count,
            "avg_sentiment": round(combined_avg, 4),
            "sentiment_label": sentiment_label,
            "breakdown": {
                "news": {
                    "count": news_count,
                    "avg_sentiment": round(news_avg, 4),
                    "positive": news_stats['positive'] if news_stats else 0,
                    "negative": news_stats['negative'] if news_stats else 0,
                    "neutral": news_stats['neutral'] if news_stats else 0
                },
                "social": {
                    "count": social_count,
                    "avg_sentiment": round(social_avg, 4),
                    "positive": social_stats['positive'] if social_stats else 0,
                    "negative": social_stats['negative'] if social_stats else 0,
                    "neutral": social_stats['neutral'] if social_stats else 0
                }
            }
        }


@app.get("/api/trends")
async def get_trends(api_key: str = Depends(verify_api_key)):
    cached = await redis_client.get("latest:trends:aggregated")
    if cached:
        return json.loads(cached)
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT ON (keyword) keyword, search_volume, region, rising_queries, timestamp
            FROM google_trends
            ORDER BY keyword, timestamp DESC
        """)
        trends = []
        for row in rows:
            rising = row['rising_queries']
            if isinstance(rising, str):
                rising = json.loads(rising)
            trends.append({
                "keyword": row['keyword'],
                "search_volume": row['search_volume'],
                "region": row['region'],
                "rising_queries": rising or [],
                "timestamp": row['timestamp'].isoformat() if row['timestamp'] else None
            })
        return {
            "count": len(trends),
            "trends": sorted(trends, key=lambda x: x.get('search_volume', 0) or 0, reverse=True)
        }


@app.get("/api/arbitrage")
async def get_arbitrage_opportunities(
    min_spread: float = Query(0.5, ge=0),
    limit: int = Query(20, ge=1, le=100),
    api_key: str = Depends(verify_api_key)
):
    cached = await redis_client.get("latest:ccxt:arbitrage")
    if cached:
        data = json.loads(cached)
        filtered = [opp for opp in data.get('opportunities', []) if opp.get('spread_pct', 0) >= min_spread]
        return {"count": len(filtered), "opportunities": filtered[:limit]}
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT symbol, buy_exchange, buy_price, sell_exchange, sell_price, 
                   spread_pct, potential_profit_usd, timestamp
            FROM ccxt_arbitrage
            WHERE spread_pct >= $1 AND timestamp > NOW() - INTERVAL '5 minutes'
            ORDER BY spread_pct DESC
            LIMIT $2
        """, min_spread, limit)
        opportunities = []
        for row in rows:
            opportunities.append({
                "symbol": row['symbol'],
                "buy_exchange": row['buy_exchange'],
                "buy_price": float(row['buy_price']),
                "sell_exchange": row['sell_exchange'],
                "sell_price": float(row['sell_price']),
                "spread_pct": float(row['spread_pct']),
                "potential_profit_usd": float(row['potential_profit_usd']) if row['potential_profit_usd'] else None,
                "timestamp": row['timestamp'].isoformat() if row['timestamp'] else None
            })
        return {"count": len(opportunities), "opportunities": opportunities}


@app.get("/api/tradingview/{symbol}")
async def get_tradingview_data(symbol: str, api_key: str = Depends(verify_api_key)):
    symbol_upper = symbol.upper()
    cached = await redis_client.get(f"latest:tradingview:BINANCE_{symbol_upper}USDT")
    if cached:
        return json.loads(cached)
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT symbol, price, volume, rsi_14, macd, macd_signal, 
                   bb_upper, bb_lower, timestamp
            FROM tradingview_prices
            WHERE symbol ILIKE $1 OR symbol ILIKE $2
            ORDER BY timestamp DESC LIMIT 1
        """, f"%{symbol_upper}%", f"BINANCE:{symbol_upper}USDT")
        if row:
            return {
                "symbol": row['symbol'],
                "price": float(row['price']) if row['price'] else 0,
                "volume": float(row['volume']) if row['volume'] else 0,
                "indicators": {
                    "rsi_14": float(row['rsi_14']) if row['rsi_14'] else None,
                    "macd": float(row['macd']) if row['macd'] else None,
                    "macd_signal": float(row['macd_signal']) if row['macd_signal'] else None,
                    "bb_upper": float(row['bb_upper']) if row['bb_upper'] else None,
                    "bb_lower": float(row['bb_lower']) if row['bb_lower'] else None
                },
                "timestamp": row['timestamp'].isoformat() if row['timestamp'] else None
            }
    return {"symbol": symbol_upper, "price": 0, "indicators": {}, "mock": True}


@app.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket):
    await websocket.accept()
    api_key = websocket.query_params.get('api_key', '')
    if api_key != API_KEY:
        await websocket.close(code=4001, reason="Invalid API key")
        return
    channels = websocket.query_params.get('channels', 'trades:BTCUSDT').split(',')
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(*channels)
    logger.info(f"Client subscribed to: {channels}")
    try:
        async def receive_messages():
            try:
                while True:
                    msg = await websocket.receive_text()
                    data = json.loads(msg)
                    if data.get('type') == 'subscribe':
                        new_channels = data.get('channels', [])
                        await pubsub.subscribe(*new_channels)
                        logger.info(f"Added subscriptions: {new_channels}")
                    elif data.get('type') == 'unsubscribe':
                        rm_channels = data.get('channels', [])
                        await pubsub.unsubscribe(*rm_channels)
            except WebSocketDisconnect:
                pass
        async def send_messages():
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    await websocket.send_text(json.dumps({
                        'channel': message['channel'].decode() if isinstance(message['channel'], bytes) else message['channel'],
                        'data': json.loads(message['data'])
                    }))
        await asyncio.gather(receive_messages(), send_messages())
    except WebSocketDisconnect:
        logger.info("Client disconnected")
    finally:
        await pubsub.close()


@app.get("/api/history/{data_type}/{symbol}")
async def get_history(
    data_type: str,
    symbol: str,
    limit: int = 100,
    api_key: str = Depends(verify_api_key)
):
    table_map = {
        'trades': 'trade_history',
        'funding': 'funding_rates',
        'oi': 'open_interest',
        'depth': 'orderbook_snapshots',
        'coingecko': 'coingecko_coins',
        'tradingview': 'tradingview_prices',
        'ccxt': 'ccxt_tickers'
    }
    table = table_map.get(data_type)
    if not table:
        raise HTTPException(status_code=400, detail=f"Unknown data type: {data_type}")
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM {table} WHERE symbol ILIKE $1 ORDER BY timestamp DESC LIMIT $2",
            f"%{symbol}%", limit
        )
        return {"symbol": symbol, "data": [dict(r) for r in rows]}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8080)
