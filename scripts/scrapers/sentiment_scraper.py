#!/usr/bin/env python3
"""
Sentiment Scraper - Collects Google Trends data for crypto keywords.
Publishes to Redis and PostgreSQL for trend analysis.
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, List

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('SentimentScraper')

try:
    import redis.asyncio as redis
    import asyncpg
except ImportError as e:
    logger.error(f"Missing dependency: {e}. Install: pip install redis asyncpg")
    sys.exit(1)

try:
    from pytrends.request import TrendReq
    PYTRENDS_AVAILABLE = True
except ImportError:
    PYTRENDS_AVAILABLE = False
    logger.warning("pytrends not available, using mock data")

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')
POSTGRES_URL = os.environ.get('POSTGRES_URL', 'postgresql://chatos:chatos@localhost:5432/chatos_trading')

CRYPTO_KEYWORDS = [
    'bitcoin', 'ethereum', 'crypto', 'solana', 'ripple xrp',
    'dogecoin', 'cardano', 'polkadot', 'chainlink', 'avalanche'
]

KEYWORD_GROUPS = [
    ['bitcoin', 'ethereum', 'crypto', 'blockchain', 'web3'],
    ['solana', 'cardano', 'polkadot', 'avalanche', 'cosmos'],
    ['dogecoin', 'shiba inu', 'pepe', 'memecoin', 'meme crypto'],
    ['defi', 'nft', 'metaverse', 'gamefi', 'play to earn'],
    ['binance', 'coinbase', 'kraken', 'crypto exchange', 'ftx']
]


class SentimentScraper:
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.pg_pool: Optional[asyncpg.Pool] = None
        self.pytrends: Optional[TrendReq] = None

    async def connect(self):
        self.redis_client = redis.from_url(REDIS_URL)
        self.pg_pool = await asyncpg.create_pool(POSTGRES_URL, min_size=2, max_size=10)
        if PYTRENDS_AVAILABLE:
            self.pytrends = TrendReq(hl='en-US', tz=360, timeout=(10, 25), retries=2, backoff_factor=0.5)
        logger.info("Connected to Redis and PostgreSQL")

    async def close(self):
        if self.redis_client:
            await self.redis_client.close()
        if self.pg_pool:
            await self.pg_pool.close()

    async def publish(self, channel: str, data: dict):
        if self.redis_client:
            await self.redis_client.publish(channel, json.dumps(data, default=str))
            await self.redis_client.set(f"latest:{channel}", json.dumps(data, default=str), ex=3600)

    async def persist_trend(self, data: dict):
        if not self.pg_pool:
            return
        async with self.pg_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO google_trends 
                (keyword, search_volume, region, rising_queries, timestamp)
                VALUES ($1, $2, $3, $4, $5)
            """, data['keyword'], data.get('search_volume', 0),
                data.get('region', 'worldwide'),
                json.dumps(data.get('rising_queries', [])),
                datetime.now(timezone.utc))

    def fetch_trends_sync(self, keywords: List[str]) -> Dict:
        if not PYTRENDS_AVAILABLE or not self.pytrends:
            return self._mock_trends(keywords)
        try:
            self.pytrends.build_payload(keywords, cat=0, timeframe='now 7-d', geo='', gprop='')
            interest_df = self.pytrends.interest_over_time()
            if interest_df.empty:
                return self._mock_trends(keywords)
            results = {}
            for kw in keywords:
                if kw in interest_df.columns:
                    values = interest_df[kw].tolist()
                    results[kw] = {
                        'keyword': kw,
                        'search_volume': int(values[-1]) if values else 0,
                        'avg_volume_7d': int(sum(values) / len(values)) if values else 0,
                        'trend_direction': 'up' if len(values) >= 2 and values[-1] > values[-2] else 'down',
                        'region': 'worldwide',
                        'rising_queries': []
                    }
            return results
        except Exception as e:
            logger.error(f"Google Trends error: {e}")
            return self._mock_trends(keywords)

    def fetch_related_queries_sync(self, keyword: str) -> List[Dict]:
        if not PYTRENDS_AVAILABLE or not self.pytrends:
            return []
        try:
            self.pytrends.build_payload([keyword], cat=0, timeframe='now 7-d', geo='', gprop='')
            related = self.pytrends.related_queries()
            if keyword not in related:
                return []
            rising = related[keyword].get('rising')
            if rising is None or rising.empty:
                return []
            queries = []
            for _, row in rising.head(10).iterrows():
                queries.append({
                    'query': row.get('query', ''),
                    'value': int(row.get('value', 0))
                })
            return queries
        except Exception as e:
            logger.debug(f"Related queries error for {keyword}: {e}")
            return []

    def _mock_trends(self, keywords: List[str]) -> Dict:
        logger.info("Using mock Google Trends data")
        import random
        results = {}
        for kw in keywords:
            results[kw] = {
                'keyword': kw,
                'search_volume': random.randint(20, 100),
                'avg_volume_7d': random.randint(30, 80),
                'trend_direction': random.choice(['up', 'down', 'stable']),
                'region': 'worldwide',
                'rising_queries': [
                    {'query': f'{kw} price', 'value': random.randint(100, 500)},
                    {'query': f'{kw} news', 'value': random.randint(50, 200)},
                    {'query': f'{kw} prediction', 'value': random.randint(50, 150)}
                ]
            }
        return results

    async def fetch_trends(self, keywords: List[str]) -> Dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.fetch_trends_sync, keywords)

    async def fetch_related_queries(self, keyword: str) -> List[Dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.fetch_related_queries_sync, keyword)

    async def run_trends_loop(self, interval: int = 3600):
        logger.info(f"Starting Google Trends scraper (interval: {interval}s)")
        while True:
            try:
                all_trends = {}
                for group in KEYWORD_GROUPS:
                    trends = await self.fetch_trends(group)
                    all_trends.update(trends)
                    await asyncio.sleep(60)
                for keyword, trend_data in all_trends.items():
                    if PYTRENDS_AVAILABLE and self.pytrends:
                        related = await self.fetch_related_queries(keyword)
                        trend_data['rising_queries'] = related
                        await asyncio.sleep(30)
                    await self.persist_trend(trend_data)
                    await self.publish(f"trends:{keyword}", trend_data)
                aggregated = {
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'keywords': all_trends,
                    'top_trending': sorted(
                        all_trends.values(),
                        key=lambda x: x.get('search_volume', 0),
                        reverse=True
                    )[:10]
                }
                await self.publish('trends:aggregated', aggregated)
                logger.info(f"Google Trends: Collected {len(all_trends)} keywords")
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"Trends loop error: {e}")
                await asyncio.sleep(300)

    async def run_fear_greed_loop(self, interval: int = 300):
        logger.info(f"Starting alternative Fear & Greed monitor (interval: {interval}s)")
        import httpx
        while True:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get('https://api.alternative.me/fng/')
                    if resp.status_code == 200:
                        data = resp.json()
                        if 'data' in data and len(data['data']) > 0:
                            fg = data['data'][0]
                            fg_data = {
                                'value': int(fg.get('value', 0)),
                                'classification': fg.get('value_classification', 'Unknown'),
                                'timestamp': datetime.now(timezone.utc).isoformat()
                            }
                            await self.publish('sentiment:fear_greed', fg_data)
                            logger.info(f"Fear & Greed: {fg_data['value']} ({fg_data['classification']})")
            except Exception as e:
                logger.error(f"Fear & Greed error: {e}")
            await asyncio.sleep(interval)


async def main():
    scraper = SentimentScraper()
    await scraper.connect()
    try:
        await asyncio.gather(
            scraper.run_trends_loop(interval=3600),
            scraper.run_fear_greed_loop(interval=300)
        )
    except KeyboardInterrupt:
        logger.info("Shutting down sentiment scraper")
    finally:
        await scraper.close()


if __name__ == '__main__':
    asyncio.run(main())
