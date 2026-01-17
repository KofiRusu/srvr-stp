#!/usr/bin/env python3
"""
CoinGecko Scraper - Comprehensive crypto data from CoinGecko API
Free API: 50 calls/min, no key required
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('CoinGeckoScraper')

try:
    import httpx
    import redis.asyncio as redis
    import asyncpg
except ImportError as e:
    logger.error(f"Missing dependency: {e}")
    raise

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')
POSTGRES_URL = os.environ.get('POSTGRES_URL', 'postgresql://chatos:chatos@localhost:5432/chatos_trading')
COINGECKO_BASE = 'https://api.coingecko.com/api/v3'
TOP_COINS_LIMIT = int(os.environ.get('TOP_COINS_LIMIT', 100))
INTERVAL_COINS = int(os.environ.get('INTERVAL_COINS', 120))
INTERVAL_GLOBAL = int(os.environ.get('INTERVAL_GLOBAL', 60))


class RateLimiter:
    def __init__(self, max_calls: int = 50, period: int = 60):
        self.max_calls = max_calls
        self.period = period
        self.calls: List[float] = []
    
    async def wait(self):
        import time
        now = time.time()
        self.calls = [c for c in self.calls if c > now - self.period]
        if len(self.calls) >= self.max_calls:
            sleep_time = self.period - (now - self.calls[0]) + 1
            logger.info(f"Rate limit reached, sleeping {sleep_time:.1f}s")
            await asyncio.sleep(sleep_time)
        self.calls.append(time.time())


class CoinGeckoScraper:
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.pg_pool: Optional[asyncpg.Pool] = None
        self.http_client: Optional[httpx.AsyncClient] = None
        self.rate_limiter = RateLimiter(max_calls=45, period=60)
        self.running = False
    
    async def connect(self):
        self.redis_client = redis.from_url(REDIS_URL)
        self.pg_pool = await asyncpg.create_pool(POSTGRES_URL, min_size=2, max_size=10)
        self.http_client = httpx.AsyncClient(
            timeout=30,
            headers={'Accept': 'application/json'}
        )
        logger.info("Connected to Redis and PostgreSQL")
    
    async def close(self):
        if self.http_client:
            await self.http_client.aclose()
        if self.redis_client:
            await self.redis_client.close()
        if self.pg_pool:
            await self.pg_pool.close()
    
    async def fetch_global_data(self) -> Optional[Dict]:
        await self.rate_limiter.wait()
        try:
            resp = await self.http_client.get(f'{COINGECKO_BASE}/global')
            if resp.status_code == 200:
                return resp.json().get('data', {})
            logger.warning(f"Global API returned {resp.status_code}")
        except Exception as e:
            logger.error(f"Error fetching global data: {e}")
        return None
    
    async def fetch_defi_data(self) -> Optional[Dict]:
        await self.rate_limiter.wait()
        try:
            resp = await self.http_client.get(f'{COINGECKO_BASE}/global/decentralized_finance_defi')
            if resp.status_code == 200:
                return resp.json().get('data', {})
        except Exception as e:
            logger.error(f"Error fetching DeFi data: {e}")
        return None
    
    async def fetch_coins_markets(self, page: int = 1, per_page: int = 100) -> List[Dict]:
        await self.rate_limiter.wait()
        try:
            params = {
                'vs_currency': 'usd',
                'order': 'market_cap_desc',
                'per_page': per_page,
                'page': page,
                'sparkline': 'true',
                'price_change_percentage': '1h,24h,7d'
            }
            resp = await self.http_client.get(f'{COINGECKO_BASE}/coins/markets', params=params)
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"Markets API returned {resp.status_code}")
        except Exception as e:
            logger.error(f"Error fetching coins markets: {e}")
        return []
    
    async def publish_global(self, data: Dict):
        if not data:
            return
        
        timestamp = datetime.now(timezone.utc)
        
        defi_data = await self.fetch_defi_data()
        
        record = {
            'active_cryptocurrencies': data.get('active_cryptocurrencies'),
            'upcoming_icos': data.get('upcoming_icos'),
            'ongoing_icos': data.get('ongoing_icos'),
            'ended_icos': data.get('ended_icos'),
            'markets': data.get('markets'),
            'total_market_cap': json.dumps(data.get('total_market_cap', {})),
            'total_volume': json.dumps(data.get('total_volume', {})),
            'market_cap_percentage': json.dumps(data.get('market_cap_percentage', {})),
            'market_cap_change_percentage_24h': data.get('market_cap_change_percentage_24h_usd'),
            'defi_market_cap': float(defi_data.get('defi_market_cap', 0)) if defi_data else None,
            'defi_volume_24h': float(defi_data.get('trading_volume_24h', 0)) if defi_data else None,
            'defi_dominance': float(defi_data.get('defi_dominance', 0)) if defi_data else None,
            'timestamp': timestamp.isoformat()
        }
        
        await self.redis_client.publish('coingecko:global', json.dumps(record))
        await self.redis_client.set('latest:coingecko:global', json.dumps(record), ex=300)
        
        async with self.pg_pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO coingecko_global 
                (active_cryptocurrencies, upcoming_icos, ongoing_icos, ended_icos, markets,
                 total_market_cap, total_volume, market_cap_percentage, 
                 market_cap_change_percentage_24h, defi_market_cap, defi_volume_24h, 
                 defi_dominance, timestamp)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ''', 
                record['active_cryptocurrencies'],
                record['upcoming_icos'],
                record['ongoing_icos'],
                record['ended_icos'],
                record['markets'],
                record['total_market_cap'],
                record['total_volume'],
                record['market_cap_percentage'],
                record['market_cap_change_percentage_24h'],
                record['defi_market_cap'],
                record['defi_volume_24h'],
                record['defi_dominance'],
                timestamp
            )
        
        logger.info(f"Published global data: {data.get('active_cryptocurrencies')} coins, "
                   f"${data.get('total_market_cap', {}).get('usd', 0)/1e12:.2f}T market cap")
    
    async def publish_coins(self, coins: List[Dict]):
        if not coins:
            return
        
        timestamp = datetime.now(timezone.utc)
        
        for coin in coins:
            record = {
                'coin_id': coin.get('id'),
                'symbol': coin.get('symbol', '').upper(),
                'name': coin.get('name'),
                'current_price': coin.get('current_price'),
                'market_cap': coin.get('market_cap'),
                'total_volume': coin.get('total_volume'),
                'price_change_24h': coin.get('price_change_24h'),
                'price_change_percentage_24h': coin.get('price_change_percentage_24h'),
                'market_cap_rank': coin.get('market_cap_rank'),
                'circulating_supply': coin.get('circulating_supply'),
                'total_supply': coin.get('total_supply'),
                'max_supply': coin.get('max_supply'),
                'ath': coin.get('ath'),
                'ath_change_percentage': coin.get('ath_change_percentage'),
                'ath_date': coin.get('ath_date'),
                'atl': coin.get('atl'),
                'atl_date': coin.get('atl_date'),
                'high_24h': coin.get('high_24h'),
                'low_24h': coin.get('low_24h'),
                'sparkline_7d': json.dumps(coin.get('sparkline_in_7d', {}).get('price', [])),
                'timestamp': timestamp.isoformat()
            }
            
            symbol = record['symbol']
            await self.redis_client.publish(f'coingecko:coin:{symbol}', json.dumps(record))
            await self.redis_client.set(f'latest:coingecko:coin:{symbol}', json.dumps(record), ex=300)
        
        async with self.pg_pool.acquire() as conn:
            for coin in coins:
                try:
                    await conn.execute('''
                        INSERT INTO coingecko_coins 
                        (coin_id, symbol, name, current_price, market_cap, total_volume,
                         price_change_24h, price_change_percentage_24h, market_cap_rank,
                         circulating_supply, total_supply, max_supply, ath, ath_change_percentage,
                         ath_date, atl, atl_date, high_24h, low_24h, sparkline_7d, timestamp)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, 
                                $15, $16, $17, $18, $19, $20, $21)
                    ''',
                        coin.get('id'),
                        coin.get('symbol', '').upper(),
                        coin.get('name'),
                        coin.get('current_price'),
                        coin.get('market_cap'),
                        coin.get('total_volume'),
                        coin.get('price_change_24h'),
                        coin.get('price_change_percentage_24h'),
                        coin.get('market_cap_rank'),
                        coin.get('circulating_supply'),
                        coin.get('total_supply'),
                        coin.get('max_supply'),
                        coin.get('ath'),
                        coin.get('ath_change_percentage'),
                        coin.get('ath_date'),
                        coin.get('atl'),
                        coin.get('atl_date'),
                        coin.get('high_24h'),
                        coin.get('low_24h'),
                        json.dumps(coin.get('sparkline_in_7d', {}).get('price', [])),
                        timestamp
                    )
                except Exception as e:
                    logger.warning(f"Error inserting coin {coin.get('symbol')}: {e}")
        
        logger.info(f"Published {len(coins)} coins")
    
    async def run_global_loop(self):
        while self.running:
            try:
                data = await self.fetch_global_data()
                if data:
                    await self.publish_global(data)
            except Exception as e:
                logger.error(f"Global loop error: {e}")
            
            await asyncio.sleep(INTERVAL_GLOBAL)
    
    async def run_coins_loop(self):
        while self.running:
            try:
                all_coins = []
                pages_needed = (TOP_COINS_LIMIT + 99) // 100
                
                for page in range(1, pages_needed + 1):
                    coins = await self.fetch_coins_markets(page=page, per_page=100)
                    all_coins.extend(coins)
                    if len(coins) < 100:
                        break
                
                if all_coins:
                    await self.publish_coins(all_coins[:TOP_COINS_LIMIT])
            except Exception as e:
                logger.error(f"Coins loop error: {e}")
            
            await asyncio.sleep(INTERVAL_COINS)
    
    async def run(self):
        self.running = True
        logger.info("Starting CoinGecko Scraper")
        logger.info(f"Settings: {TOP_COINS_LIMIT} coins, global interval: {INTERVAL_GLOBAL}s, "
                   f"coins interval: {INTERVAL_COINS}s")
        
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
    scraper = CoinGeckoScraper()
    try:
        await scraper.run()
    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
        scraper.stop()


if __name__ == '__main__':
    asyncio.run(main())
