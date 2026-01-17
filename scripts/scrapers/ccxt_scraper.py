#!/usr/bin/env python3
"""
CCXT Multi-Exchange Scraper - Unified data from 120+ exchanges
Supports arbitrage detection, multi-exchange tickers, and order books
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('CCXTScraper')

try:
    import ccxt.async_support as ccxt
    import redis.asyncio as redis
    import asyncpg
except ImportError as e:
    logger.error(f"Missing dependency: {e}")
    raise

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')
POSTGRES_URL = os.environ.get('POSTGRES_URL', 'postgresql://chatos:chatos@localhost:5432/chatos_trading')
EXCHANGES = os.environ.get('EXCHANGES', 'binance,coinbase,kraken,bybit,okx,bitget,gateio').split(',')
SYMBOLS = os.environ.get('SYMBOLS', 'BTC/USDT,ETH/USDT,SOL/USDT,XRP/USDT,DOGE/USDT').split(',')
INTERVAL = int(os.environ.get('INTERVAL', 30))
ARBITRAGE_THRESHOLD = float(os.environ.get('ARBITRAGE_THRESHOLD', 0.5))


class CCXTScraper:
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.pg_pool: Optional[asyncpg.Pool] = None
        self.exchanges: Dict[str, ccxt.Exchange] = {}
        self.running = False
    
    async def connect(self):
        self.redis_client = redis.from_url(REDIS_URL)
        self.pg_pool = await asyncpg.create_pool(POSTGRES_URL, min_size=2, max_size=10)
        
        for exchange_id in EXCHANGES:
            try:
                exchange_class = getattr(ccxt, exchange_id.lower())
                exchange = exchange_class({
                    'enableRateLimit': True,
                    'timeout': 30000,
                })
                await exchange.load_markets()
                self.exchanges[exchange_id] = exchange
                logger.info(f"Loaded {exchange_id} with {len(exchange.markets)} markets")
            except Exception as e:
                logger.warning(f"Could not load {exchange_id}: {e}")
        
        logger.info(f"Connected to {len(self.exchanges)} exchanges")
    
    async def close(self):
        for exchange in self.exchanges.values():
            await exchange.close()
        if self.redis_client:
            await self.redis_client.close()
        if self.pg_pool:
            await self.pg_pool.close()
    
    async def fetch_ticker(self, exchange_id: str, symbol: str) -> Optional[Dict]:
        exchange = self.exchanges.get(exchange_id)
        if not exchange:
            return None
        
        try:
            if symbol in exchange.markets:
                ticker = await exchange.fetch_ticker(symbol)
                return {
                    'exchange': exchange_id,
                    'symbol': symbol.replace('/', ''),
                    'bid': ticker.get('bid'),
                    'ask': ticker.get('ask'),
                    'last': ticker.get('last'),
                    'open': ticker.get('open'),
                    'high': ticker.get('high'),
                    'low': ticker.get('low'),
                    'close': ticker.get('close'),
                    'volume': ticker.get('baseVolume'),
                    'quote_volume': ticker.get('quoteVolume'),
                    'vwap': ticker.get('vwap'),
                    'percentage': ticker.get('percentage'),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
        except Exception as e:
            logger.debug(f"Error fetching {symbol} from {exchange_id}: {e}")
        return None
    
    async def fetch_all_tickers(self) -> List[Dict]:
        tasks = []
        for exchange_id in self.exchanges:
            for symbol in SYMBOLS:
                tasks.append(self.fetch_ticker(exchange_id, symbol))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        tickers = [r for r in results if isinstance(r, dict)]
        return tickers
    
    def detect_arbitrage(self, tickers: List[Dict]) -> List[Dict]:
        by_symbol = defaultdict(list)
        for ticker in tickers:
            if ticker.get('bid') and ticker.get('ask'):
                by_symbol[ticker['symbol']].append(ticker)
        
        opportunities = []
        timestamp = datetime.now(timezone.utc)
        
        for symbol, symbol_tickers in by_symbol.items():
            if len(symbol_tickers) < 2:
                continue
            
            for i, buy_ticker in enumerate(symbol_tickers):
                for sell_ticker in symbol_tickers[i+1:]:
                    buy_price = buy_ticker['ask']
                    sell_price = sell_ticker['bid']
                    
                    if buy_price and sell_price and buy_price > 0:
                        spread_pct = ((sell_price - buy_price) / buy_price) * 100
                        
                        if spread_pct >= ARBITRAGE_THRESHOLD:
                            opportunities.append({
                                'symbol': symbol,
                                'buy_exchange': buy_ticker['exchange'],
                                'buy_price': buy_price,
                                'sell_exchange': sell_ticker['exchange'],
                                'sell_price': sell_price,
                                'spread_pct': round(spread_pct, 4),
                                'potential_profit_usd': round((sell_price - buy_price) * 1000, 2),
                                'timestamp': timestamp.isoformat()
                            })
                        
                        reverse_spread = ((buy_price - sell_price) / sell_price) * 100
                        if reverse_spread >= ARBITRAGE_THRESHOLD:
                            opportunities.append({
                                'symbol': symbol,
                                'buy_exchange': sell_ticker['exchange'],
                                'buy_price': sell_ticker['ask'],
                                'sell_exchange': buy_ticker['exchange'],
                                'sell_price': buy_ticker['bid'],
                                'spread_pct': round(reverse_spread, 4),
                                'potential_profit_usd': round((buy_ticker['bid'] - sell_ticker['ask']) * 1000, 2),
                                'timestamp': timestamp.isoformat()
                            })
        
        opportunities.sort(key=lambda x: x['spread_pct'], reverse=True)
        return opportunities[:20]
    
    async def publish_tickers(self, tickers: List[Dict]):
        if not tickers:
            return
        
        timestamp = datetime.now(timezone.utc)
        
        for ticker in tickers:
            channel = f"ccxt:{ticker['exchange']}:{ticker['symbol']}"
            await self.redis_client.publish(channel, json.dumps(ticker))
            await self.redis_client.set(f'latest:{channel}', json.dumps(ticker), ex=120)
        
        async with self.pg_pool.acquire() as conn:
            for ticker in tickers:
                try:
                    await conn.execute('''
                        INSERT INTO ccxt_tickers 
                        (exchange, symbol, bid, ask, last, open, high, low, close,
                         volume, quote_volume, vwap, percentage, timestamp)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                    ''',
                        ticker['exchange'],
                        ticker['symbol'],
                        ticker.get('bid'),
                        ticker.get('ask'),
                        ticker.get('last'),
                        ticker.get('open'),
                        ticker.get('high'),
                        ticker.get('low'),
                        ticker.get('close'),
                        ticker.get('volume'),
                        ticker.get('quote_volume'),
                        ticker.get('vwap'),
                        ticker.get('percentage'),
                        timestamp
                    )
                except Exception as e:
                    logger.debug(f"Error inserting ticker: {e}")
        
        logger.info(f"Published {len(tickers)} tickers from {len(set(t['exchange'] for t in tickers))} exchanges")
    
    async def publish_arbitrage(self, opportunities: List[Dict]):
        if not opportunities:
            return
        
        timestamp = datetime.now(timezone.utc)
        
        await self.redis_client.set('latest:ccxt:arbitrage', json.dumps(opportunities), ex=120)
        await self.redis_client.publish('ccxt:arbitrage', json.dumps(opportunities))
        
        async with self.pg_pool.acquire() as conn:
            for opp in opportunities:
                try:
                    await conn.execute('''
                        INSERT INTO ccxt_arbitrage 
                        (symbol, buy_exchange, buy_price, sell_exchange, sell_price,
                         spread_pct, potential_profit_usd, timestamp)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ''',
                        opp['symbol'],
                        opp['buy_exchange'],
                        opp['buy_price'],
                        opp['sell_exchange'],
                        opp['sell_price'],
                        opp['spread_pct'],
                        opp.get('potential_profit_usd'),
                        timestamp
                    )
                except Exception as e:
                    logger.debug(f"Error inserting arbitrage: {e}")
        
        if opportunities:
            top = opportunities[0]
            logger.info(f"Found {len(opportunities)} arbitrage opportunities. "
                       f"Best: {top['symbol']} {top['spread_pct']:.2f}% "
                       f"({top['buy_exchange']} -> {top['sell_exchange']})")
    
    async def run(self):
        self.running = True
        logger.info("Starting CCXT Multi-Exchange Scraper")
        logger.info(f"Exchanges: {EXCHANGES}")
        logger.info(f"Symbols: {SYMBOLS}")
        logger.info(f"Interval: {INTERVAL}s, Arbitrage threshold: {ARBITRAGE_THRESHOLD}%")
        
        await self.connect()
        
        try:
            while self.running:
                try:
                    tickers = await self.fetch_all_tickers()
                    await self.publish_tickers(tickers)
                    
                    opportunities = self.detect_arbitrage(tickers)
                    await self.publish_arbitrage(opportunities)
                    
                except Exception as e:
                    logger.error(f"Cycle error: {e}")
                
                await asyncio.sleep(INTERVAL)
        finally:
            await self.close()
    
    def stop(self):
        self.running = False


async def main():
    scraper = CCXTScraper()
    try:
        await scraper.run()
    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
        scraper.stop()


if __name__ == '__main__':
    asyncio.run(main())
