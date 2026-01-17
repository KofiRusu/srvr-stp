#!/usr/bin/env python3
"""
Scraper Runner - Dynamically runs the appropriate scraper based on SCRAPER_TYPE env var.
Publishes data to Redis for real-time streaming and PostgreSQL for persistence.
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('ScraperRunner')

try:
    import redis.asyncio as redis
    import asyncpg
except ImportError as e:
    logger.error(f"Missing dependency: {e}")
    sys.exit(1)

SCRAPER_TYPE = os.environ.get('SCRAPER_TYPE', 'aggr')
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')
POSTGRES_URL = os.environ.get('POSTGRES_URL', 'postgresql://chatos:chatos@localhost:5432/chatos_trading')
OUTPUT_DIR = Path(os.environ.get('OUTPUT_DIR', '/data'))
SYMBOLS = os.environ.get('SYMBOLS', 'BTC,ETH,SOL').split(',')


class DataPublisher:
    def __init__(self):
        self.redis_client = None
        self.pg_pool = None
    
    async def connect(self):
        self.redis_client = redis.from_url(REDIS_URL)
        self.pg_pool = await asyncpg.create_pool(POSTGRES_URL, min_size=2, max_size=10)
        logger.info("Connected to Redis and PostgreSQL")
    
    async def publish(self, channel: str, data: dict):
        if self.redis_client:
            await self.redis_client.publish(channel, json.dumps(data))
            await self.redis_client.set(f"latest:{channel}", json.dumps(data), ex=300)
    
    async def persist(self, table: str, data: dict):
        if self.pg_pool:
            async with self.pg_pool.acquire() as conn:
                columns = ', '.join(data.keys())
                placeholders = ', '.join(f'${i+1}' for i in range(len(data)))
                query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
                try:
                    await conn.execute(query, *data.values())
                except Exception as e:
                    logger.warning(f"Persist error: {e}")
    
    async def close(self):
        if self.redis_client:
            await self.redis_client.close()
        if self.pg_pool:
            await self.pg_pool.close()


async def run_aggr_scraper(publisher: DataPublisher):
    """WebSocket connection to Binance for real-time trades"""
    import websockets
    
    symbols_lower = [f"{s.lower()}usdt@aggTrade" for s in SYMBOLS]
    ws_url = f"wss://fstream.binance.com/stream?streams={'/'.join(symbols_lower)}"
    
    while True:
        try:
            async with websockets.connect(ws_url) as ws:
                logger.info(f"AGGR: Connected to Binance WebSocket")
                async for msg in ws:
                    data = json.loads(msg)
                    if 'data' in data:
                        trade = data['data']
                        normalized = {
                            'symbol': trade['s'],
                            'price': float(trade['p']),
                            'quantity': float(trade['q']),
                            'side': 'SELL' if trade['m'] else 'BUY',
                            'timestamp': datetime.fromtimestamp(trade['T']/1000, tz=timezone.utc).isoformat(),
                            'trade_id': trade['a']
                        }
                        await publisher.publish(f"trades:{trade['s']}", normalized)
        except Exception as e:
            logger.error(f"AGGR WebSocket error: {e}")
            await asyncio.sleep(5)


async def run_coinglass_scraper(publisher: DataPublisher):
    """Fetch derivatives data (funding, OI, liquidations) periodically"""
    import httpx
    
    interval = int(os.environ.get('INTERVAL_SECONDS', 60))
    
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            try:
                for symbol in SYMBOLS:
                    pair = f"{symbol}USDT"
                    
                    fr_resp = await client.get(
                        f"https://fapi.binance.com/fapi/v1/premiumIndex",
                        params={'symbol': pair}
                    )
                    if fr_resp.status_code == 200:
                        fr = fr_resp.json()
                        data = {
                            'symbol': pair,
                            'funding_rate': float(fr.get('lastFundingRate', 0)),
                            'mark_price': float(fr.get('markPrice', 0)),
                            'index_price': float(fr.get('indexPrice', 0)),
                            'timestamp': datetime.now(timezone.utc).isoformat()
                        }
                        await publisher.publish(f"funding:{pair}", data)
                    
                    oi_resp = await client.get(
                        f"https://fapi.binance.com/fapi/v1/openInterest",
                        params={'symbol': pair}
                    )
                    if oi_resp.status_code == 200:
                        oi = oi_resp.json()
                        data = {
                            'symbol': pair,
                            'open_interest': float(oi.get('openInterest', 0)),
                            'timestamp': datetime.now(timezone.utc).isoformat()
                        }
                        await publisher.publish(f"oi:{pair}", data)
                
                logger.info(f"CoinGlass cycle complete for {SYMBOLS}")
                await asyncio.sleep(interval)
                
            except Exception as e:
                logger.error(f"CoinGlass error: {e}")
                await asyncio.sleep(10)


async def run_market_scraper(publisher: DataPublisher):
    """WebSocket for orderbook and klines"""
    import websockets
    
    symbols_lower = [f"{s.lower()}@depth5@100ms" for s in os.environ.get('SYMBOLS', 'BTCUSDT,ETHUSDT,SOLUSDT').split(',')]
    ws_url = f"wss://fstream.binance.com/stream?streams={'/'.join(symbols_lower)}"
    
    while True:
        try:
            async with websockets.connect(ws_url) as ws:
                logger.info("MARKET: Connected to Binance depth WebSocket")
                async for msg in ws:
                    data = json.loads(msg)
                    if 'data' in data:
                        depth = data['data']
                        symbol = data['stream'].split('@')[0].upper()
                        normalized = {
                            'symbol': symbol,
                            'bids': depth.get('b', [])[:5],
                            'asks': depth.get('a', [])[:5],
                            'timestamp': datetime.now(timezone.utc).isoformat()
                        }
                        await publisher.publish(f"depth:{symbol}", normalized)
        except Exception as e:
            logger.error(f"MARKET WebSocket error: {e}")
            await asyncio.sleep(5)


SCRAPERS = {
    'aggr': run_aggr_scraper,
    'coinglass': run_coinglass_scraper,
    'market': run_market_scraper,
}


async def main():
    logger.info(f"Starting {SCRAPER_TYPE} scraper")
    
    publisher = DataPublisher()
    await publisher.connect()
    
    scraper_fn = SCRAPERS.get(SCRAPER_TYPE)
    if not scraper_fn:
        logger.error(f"Unknown scraper type: {SCRAPER_TYPE}")
        sys.exit(1)
    
    try:
        await scraper_fn(publisher)
    finally:
        await publisher.close()


if __name__ == '__main__':
    asyncio.run(main())
