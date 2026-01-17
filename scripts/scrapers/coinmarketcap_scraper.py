#!/usr/bin/env python3
"""
CoinMarketCap Scraper - Market metrics, Fear & Greed, top coins
Requires API key from https://pro.coinmarketcap.com/signup
Free tier: 333 calls/day
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('CoinMarketCapScraper')

try:
    import httpx
    import redis.asyncio as redis
    import asyncpg
except ImportError as e:
    logger.error(f"Missing dependency: {e}")
    raise

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')
POSTGRES_URL = os.environ.get('POSTGRES_URL', 'postgresql://chatos:chatos@localhost:5432/chatos_trading')
CMC_API_KEY = os.environ.get('COINMARKETCAP_API_KEY', '')
CMC_BASE = 'https://pro-api.coinmarketcap.com'
TOP_COINS_LIMIT = int(os.environ.get('TOP_COINS_LIMIT', 100))
INTERVAL_GLOBAL = int(os.environ.get('INTERVAL_GLOBAL', 300))
INTERVAL_COINS = int(os.environ.get('INTERVAL_COINS', 600))


class CoinMarketCapScraper:
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.pg_pool: Optional[asyncpg.Pool] = None
        self.http_client: Optional[httpx.AsyncClient] = None
        self.running = False
        self.daily_calls = 0
        self.last_reset = datetime.now(timezone.utc).date()
    
    async def connect(self):
        if not CMC_API_KEY:
            logger.warning("No COINMARKETCAP_API_KEY set. Using mock data.")
        
        self.redis_client = redis.from_url(REDIS_URL)
        self.pg_pool = await asyncpg.create_pool(POSTGRES_URL, min_size=2, max_size=10)
        self.http_client = httpx.AsyncClient(
            timeout=30,
            headers={
                'X-CMC_PRO_API_KEY': CMC_API_KEY,
                'Accept': 'application/json'
            }
        )
        logger.info("Connected to Redis and PostgreSQL")
    
    async def close(self):
        if self.http_client:
            await self.http_client.aclose()
        if self.redis_client:
            await self.redis_client.close()
        if self.pg_pool:
            await self.pg_pool.close()
    
    def check_rate_limit(self) -> bool:
        today = datetime.now(timezone.utc).date()
        if today != self.last_reset:
            self.daily_calls = 0
            self.last_reset = today
        
        if self.daily_calls >= 300:
            logger.warning("Approaching daily rate limit (333 calls/day)")
            return False
        return True
    
    async def fetch_global_metrics(self) -> Optional[Dict]:
        if not self.check_rate_limit():
            return self._mock_global()
        
        if not CMC_API_KEY:
            return self._mock_global()
        
        try:
            self.daily_calls += 1
            resp = await self.http_client.get(f'{CMC_BASE}/v1/global-metrics/quotes/latest')
            if resp.status_code == 200:
                return resp.json().get('data', {})
            logger.warning(f"Global metrics API returned {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"Error fetching global metrics: {e}")
        return self._mock_global()
    
    async def fetch_fear_greed(self) -> Optional[Dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get('https://api.alternative.me/fng/?limit=1')
                if resp.status_code == 200:
                    data = resp.json().get('data', [])
                    if data:
                        return {
                            'value': int(data[0].get('value', 50)),
                            'classification': data[0].get('value_classification', 'Neutral')
                        }
        except Exception as e:
            logger.debug(f"Error fetching fear & greed: {e}")
        
        return {'value': 50, 'classification': 'Neutral'}
    
    async def fetch_listings(self, limit: int = 100) -> List[Dict]:
        if not self.check_rate_limit():
            return self._mock_listings(limit)
        
        if not CMC_API_KEY:
            return self._mock_listings(limit)
        
        try:
            self.daily_calls += 1
            params = {
                'start': 1,
                'limit': limit,
                'convert': 'USD',
                'sort': 'market_cap',
                'sort_dir': 'desc'
            }
            resp = await self.http_client.get(f'{CMC_BASE}/v1/cryptocurrency/listings/latest', params=params)
            if resp.status_code == 200:
                return resp.json().get('data', [])
            logger.warning(f"Listings API returned {resp.status_code}")
        except Exception as e:
            logger.error(f"Error fetching listings: {e}")
        return self._mock_listings(limit)
    
    def _mock_global(self) -> Dict:
        import random
        return {
            'active_cryptocurrencies': 10000 + random.randint(-100, 100),
            'active_exchanges': 700 + random.randint(-10, 10),
            'quote': {
                'USD': {
                    'total_market_cap': 2.5e12 * (1 + random.uniform(-0.05, 0.05)),
                    'total_volume_24h': 80e9 * (1 + random.uniform(-0.1, 0.1)),
                }
            },
            'btc_dominance': 52 + random.uniform(-2, 2),
            'eth_dominance': 17 + random.uniform(-1, 1),
        }
    
    def _mock_listings(self, limit: int) -> List[Dict]:
        import random
        coins = [
            ('BTC', 'Bitcoin', 100000, 1.95e12),
            ('ETH', 'Ethereum', 3800, 450e9),
            ('SOL', 'Solana', 230, 110e9),
            ('XRP', 'XRP', 2.5, 140e9),
            ('DOGE', 'Dogecoin', 0.4, 60e9),
            ('ADA', 'Cardano', 1.1, 38e9),
            ('AVAX', 'Avalanche', 45, 18e9),
            ('DOT', 'Polkadot', 9, 12e9),
            ('LINK', 'Chainlink', 22, 13e9),
            ('MATIC', 'Polygon', 0.6, 6e9),
        ]
        
        result = []
        for i, (symbol, name, base_price, base_mcap) in enumerate(coins[:limit]):
            mult = 1 + random.uniform(-0.02, 0.02)
            result.append({
                'id': i + 1,
                'symbol': symbol,
                'name': name,
                'quote': {
                    'USD': {
                        'price': base_price * mult,
                        'volume_24h': base_mcap * 0.03 * mult,
                        'market_cap': base_mcap * mult,
                        'percent_change_1h': random.uniform(-2, 2),
                        'percent_change_24h': random.uniform(-5, 5),
                        'percent_change_7d': random.uniform(-10, 10),
                    }
                },
                'cmc_rank': i + 1,
                'circulating_supply': base_mcap / base_price,
                'max_supply': base_mcap / base_price * 1.1 if symbol != 'ETH' else None,
            })
        return result
    
    async def publish_global(self, data: Dict, fear_greed: Dict):
        if not data:
            return
        
        timestamp = datetime.now(timezone.utc)
        quote = data.get('quote', {}).get('USD', {})
        
        record = {
            'total_market_cap': quote.get('total_market_cap'),
            'total_volume_24h': quote.get('total_volume_24h'),
            'btc_dominance': data.get('btc_dominance'),
            'eth_dominance': data.get('eth_dominance'),
            'active_cryptocurrencies': data.get('active_cryptocurrencies'),
            'active_exchanges': data.get('active_exchanges'),
            'fear_greed_index': fear_greed.get('value'),
            'fear_greed_label': fear_greed.get('classification'),
            'timestamp': timestamp.isoformat()
        }
        
        await self.redis_client.publish('cmc:global', json.dumps(record))
        await self.redis_client.set('latest:cmc:global', json.dumps(record), ex=600)
        await self.redis_client.set('latest:fear-greed', json.dumps(fear_greed), ex=600)
        
        async with self.pg_pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO coinmarketcap_global 
                (total_market_cap, total_volume_24h, btc_dominance, eth_dominance,
                 active_cryptocurrencies, active_exchanges, fear_greed_index, 
                 fear_greed_label, timestamp)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ''',
                record['total_market_cap'],
                record['total_volume_24h'],
                record['btc_dominance'],
                record['eth_dominance'],
                record['active_cryptocurrencies'],
                record['active_exchanges'],
                record['fear_greed_index'],
                record['fear_greed_label'],
                timestamp
            )
        
        logger.info(f"Published global: ${record['total_market_cap']/1e12:.2f}T, "
                   f"Fear/Greed: {record['fear_greed_index']} ({record['fear_greed_label']})")
    
    async def publish_coins(self, coins: List[Dict]):
        if not coins:
            return
        
        timestamp = datetime.now(timezone.utc)
        
        async with self.pg_pool.acquire() as conn:
            for coin in coins:
                quote = coin.get('quote', {}).get('USD', {})
                symbol = coin.get('symbol', '')
                
                record = {
                    'cmc_id': coin.get('id'),
                    'symbol': symbol,
                    'name': coin.get('name'),
                    'price': quote.get('price'),
                    'market_cap': quote.get('market_cap'),
                    'volume_24h': quote.get('volume_24h'),
                    'percent_change_1h': quote.get('percent_change_1h'),
                    'percent_change_24h': quote.get('percent_change_24h'),
                    'percent_change_7d': quote.get('percent_change_7d'),
                    'circulating_supply': coin.get('circulating_supply'),
                    'max_supply': coin.get('max_supply'),
                    'market_cap_rank': coin.get('cmc_rank'),
                    'timestamp': timestamp.isoformat()
                }
                
                await self.redis_client.set(f'latest:cmc:coin:{symbol}', json.dumps(record), ex=900)
                
                try:
                    await conn.execute('''
                        INSERT INTO coinmarketcap_coins 
                        (cmc_id, symbol, name, price, market_cap, volume_24h,
                         percent_change_1h, percent_change_24h, percent_change_7d,
                         circulating_supply, max_supply, market_cap_rank, timestamp)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    ''',
                        record['cmc_id'],
                        record['symbol'],
                        record['name'],
                        record['price'],
                        record['market_cap'],
                        record['volume_24h'],
                        record['percent_change_1h'],
                        record['percent_change_24h'],
                        record['percent_change_7d'],
                        record['circulating_supply'],
                        record['max_supply'],
                        record['market_cap_rank'],
                        timestamp
                    )
                except Exception as e:
                    logger.debug(f"Error inserting coin {symbol}: {e}")
        
        logger.info(f"Published {len(coins)} coins")
    
    async def run_global_loop(self):
        while self.running:
            try:
                global_data = await self.fetch_global_metrics()
                fear_greed = await self.fetch_fear_greed()
                await self.publish_global(global_data, fear_greed)
            except Exception as e:
                logger.error(f"Global loop error: {e}")
            
            await asyncio.sleep(INTERVAL_GLOBAL)
    
    async def run_coins_loop(self):
        while self.running:
            try:
                coins = await self.fetch_listings(TOP_COINS_LIMIT)
                await self.publish_coins(coins)
            except Exception as e:
                logger.error(f"Coins loop error: {e}")
            
            await asyncio.sleep(INTERVAL_COINS)
    
    async def run(self):
        self.running = True
        logger.info("Starting CoinMarketCap Scraper")
        logger.info(f"API Key: {'Set' if CMC_API_KEY else 'Not set (using mock data)'}")
        logger.info(f"Top coins: {TOP_COINS_LIMIT}, Global interval: {INTERVAL_GLOBAL}s")
        
        await self.connect()
        
        try:
            await asyncio.gather(
                self.run_global_loop(),
                self.run_coins_loop()
            )
        finally:
            await self.close()
    
    def stop(self):
        self.running = False


async def main():
    scraper = CoinMarketCapScraper()
    try:
        await scraper.run()
    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
        scraper.stop()


if __name__ == '__main__':
    asyncio.run(main())
