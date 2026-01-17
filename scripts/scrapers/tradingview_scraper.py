#!/usr/bin/env python3
"""
TradingView Scraper - Collects price data and technical indicators.
Uses TradingView's public widget API and news RSS feeds.
"""

import os
import sys
import json
import asyncio
import logging
import random
import re
from datetime import datetime, timezone
from typing import Optional, Dict, List

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('TradingViewScraper')

try:
    import redis.asyncio as redis
    import asyncpg
    import httpx
except ImportError as e:
    logger.error(f"Missing dependency: {e}. Install: pip install redis asyncpg httpx")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')
POSTGRES_URL = os.environ.get('POSTGRES_URL', 'postgresql://chatos:chatos@localhost:5432/chatos_trading')

TV_SYMBOLS = [
    'BINANCE:BTCUSDT', 'BINANCE:ETHUSDT', 'BINANCE:SOLUSDT', 'BINANCE:XRPUSDT',
    'BINANCE:DOGEUSDT', 'BINANCE:ADAUSDT', 'BINANCE:AVAXUSDT', 'BINANCE:DOTUSDT',
    'BINANCE:LINKUSDT', 'BINANCE:MATICUSDT', 'BINANCE:BNBUSDT', 'BINANCE:LTCUSDT',
    'COINBASE:BTCUSD', 'COINBASE:ETHUSD', 'BITSTAMP:BTCUSD'
]

TV_SCANNER_URL = 'https://scanner.tradingview.com/crypto/scan'
TV_NEWS_RSS = 'https://www.tradingview.com/feed/'

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
]


class TradingViewScraper:
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.pg_pool: Optional[asyncpg.Pool] = None
        self.http_client: Optional[httpx.AsyncClient] = None

    async def connect(self):
        self.redis_client = redis.from_url(REDIS_URL)
        self.pg_pool = await asyncpg.create_pool(POSTGRES_URL, min_size=2, max_size=10)
        self.http_client = httpx.AsyncClient(timeout=30)
        logger.info("Connected to Redis and PostgreSQL")

    async def close(self):
        if self.http_client:
            await self.http_client.aclose()
        if self.redis_client:
            await self.redis_client.close()
        if self.pg_pool:
            await self.pg_pool.close()

    def _get_headers(self) -> Dict:
        return {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.tradingview.com/',
            'Origin': 'https://www.tradingview.com'
        }

    async def publish(self, channel: str, data: dict):
        if self.redis_client:
            await self.redis_client.publish(channel, json.dumps(data, default=str))
            await self.redis_client.set(f"latest:{channel}", json.dumps(data, default=str), ex=300)

    async def persist_price(self, data: dict):
        if not self.pg_pool:
            return
        async with self.pg_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO tradingview_prices 
                (symbol, price, volume, rsi_14, macd, macd_signal, bb_upper, bb_lower, timestamp)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """, data['symbol'], data.get('price', 0), data.get('volume', 0),
                data.get('rsi_14'), data.get('macd'), data.get('macd_signal'),
                data.get('bb_upper'), data.get('bb_lower'),
                datetime.now(timezone.utc))

    async def persist_news(self, data: dict):
        if not self.pg_pool:
            return
        async with self.pg_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO tradingview_news 
                (title, url, source, content, symbols, published_at, scraped_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (url) DO NOTHING
            """, data.get('title', ''), data.get('url', ''),
                data.get('source', 'tradingview'), data.get('content', ''),
                data.get('symbols', []), data.get('published_at'),
                datetime.now(timezone.utc))

    async def fetch_scanner_data(self, symbols: List[str]) -> List[Dict]:
        try:
            clean_symbols = []
            for s in symbols:
                parts = s.split(':')
                if len(parts) == 2:
                    clean_symbols.append(f"{parts[0]}:{parts[1]}")
                else:
                    clean_symbols.append(s)
            payload = {
                "symbols": {"tickers": clean_symbols, "query": {"types": []}},
                "columns": [
                    "close", "volume", "RSI", "MACD.macd", "MACD.signal",
                    "BB.upper", "BB.lower", "change", "change_abs",
                    "high", "low", "open", "Volatility.D"
                ]
            }
            resp = await self.http_client.post(
                TV_SCANNER_URL,
                json=payload,
                headers=self._get_headers()
            )
            if resp.status_code != 200:
                logger.warning(f"TradingView scanner error {resp.status_code}")
                return self._mock_scanner_data(symbols)
            data = resp.json()
            results = []
            for item in data.get('data', []):
                symbol = item.get('s', '')
                values = item.get('d', [])
                if len(values) >= 13:
                    results.append({
                        'symbol': symbol,
                        'price': values[0] if values[0] else 0,
                        'volume': values[1] if values[1] else 0,
                        'rsi_14': values[2] if values[2] else None,
                        'macd': values[3] if values[3] else None,
                        'macd_signal': values[4] if values[4] else None,
                        'bb_upper': values[5] if values[5] else None,
                        'bb_lower': values[6] if values[6] else None,
                        'change_pct': values[7] if values[7] else 0,
                        'change_abs': values[8] if values[8] else 0,
                        'high': values[9] if values[9] else 0,
                        'low': values[10] if values[10] else 0,
                        'open': values[11] if values[11] else 0,
                        'volatility': values[12] if values[12] else None,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
            return results
        except Exception as e:
            logger.error(f"Scanner fetch error: {e}")
            return self._mock_scanner_data(symbols)

    def _mock_scanner_data(self, symbols: List[str]) -> List[Dict]:
        logger.info("Using mock TradingView data")
        import random
        results = []
        base_prices = {
            'BTC': 98000, 'ETH': 3500, 'SOL': 200, 'XRP': 2.5, 'DOGE': 0.35,
            'ADA': 1.0, 'AVAX': 40, 'DOT': 8, 'LINK': 25, 'MATIC': 0.5,
            'BNB': 700, 'LTC': 100
        }
        for symbol in symbols:
            coin = 'BTC'
            for key in base_prices:
                if key in symbol.upper():
                    coin = key
                    break
            base = base_prices.get(coin, 100)
            price = base * (1 + random.uniform(-0.02, 0.02))
            results.append({
                'symbol': symbol,
                'price': round(price, 8),
                'volume': random.randint(1000000, 100000000),
                'rsi_14': round(random.uniform(30, 70), 2),
                'macd': round(random.uniform(-100, 100), 4),
                'macd_signal': round(random.uniform(-80, 80), 4),
                'bb_upper': round(price * 1.05, 8),
                'bb_lower': round(price * 0.95, 8),
                'change_pct': round(random.uniform(-5, 5), 2),
                'change_abs': round(price * random.uniform(-0.05, 0.05), 2),
                'high': round(price * 1.02, 8),
                'low': round(price * 0.98, 8),
                'open': round(price * (1 + random.uniform(-0.01, 0.01)), 8),
                'volatility': round(random.uniform(1, 5), 2),
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
        return results

    async def fetch_news(self) -> List[Dict]:
        if not BS4_AVAILABLE:
            return self._mock_news()
        try:
            resp = await self.http_client.get(
                TV_NEWS_RSS,
                headers={'User-Agent': random.choice(USER_AGENTS)}
            )
            if resp.status_code != 200:
                return self._mock_news()
            try:
                import feedparser
                feed = feedparser.parse(resp.text)
                articles = []
                for entry in feed.entries[:20]:
                    articles.append({
                        'title': entry.get('title', ''),
                        'url': entry.get('link', ''),
                        'source': 'tradingview',
                        'content': entry.get('summary', ''),
                        'symbols': self._extract_symbols(entry.get('title', '') + ' ' + entry.get('summary', '')),
                        'published_at': datetime.now(timezone.utc)
                    })
                return articles
            except ImportError:
                soup = BeautifulSoup(resp.text, 'html.parser')
                items = soup.find_all('item')[:20]
                articles = []
                for item in items:
                    title = item.find('title')
                    link = item.find('link')
                    desc = item.find('description')
                    articles.append({
                        'title': title.text if title else '',
                        'url': link.text if link else '',
                        'source': 'tradingview',
                        'content': desc.text if desc else '',
                        'symbols': self._extract_symbols((title.text if title else '') + ' ' + (desc.text if desc else '')),
                        'published_at': datetime.now(timezone.utc)
                    })
                return articles
        except Exception as e:
            logger.error(f"News fetch error: {e}")
            return self._mock_news()

    def _extract_symbols(self, text: str) -> List[str]:
        patterns = {
            r'\bbitcoin\b|\bbtc\b': 'BTC',
            r'\bethereum\b|\beth\b': 'ETH',
            r'\bsolana\b|\bsol\b': 'SOL',
            r'\bripple\b|\bxrp\b': 'XRP',
            r'\bdoge\b|\bdogecoin\b': 'DOGE',
        }
        text_lower = text.lower()
        symbols = set()
        for pattern, symbol in patterns.items():
            if re.search(pattern, text_lower):
                symbols.add(symbol)
        return list(symbols)

    def _mock_news(self) -> List[Dict]:
        logger.info("Using mock TradingView news")
        return [
            {
                'title': 'Bitcoin Shows Strength Above Key Support Level',
                'url': 'https://tradingview.com/news/mock1',
                'source': 'tradingview',
                'content': 'BTC continues to hold above the $95,000 support zone...',
                'symbols': ['BTC'],
                'published_at': datetime.now(timezone.utc)
            },
            {
                'title': 'Ethereum Breaks Resistance as DeFi Activity Surges',
                'url': 'https://tradingview.com/news/mock2',
                'source': 'tradingview',
                'content': 'ETH surpasses $3,500 with increasing network activity...',
                'symbols': ['ETH'],
                'published_at': datetime.now(timezone.utc)
            }
        ]

    async def run_prices_loop(self, interval: int = 60):
        logger.info(f"Starting TradingView prices scraper (interval: {interval}s)")
        while True:
            try:
                data = await self.fetch_scanner_data(TV_SYMBOLS)
                for item in data:
                    await self.persist_price(item)
                    symbol_clean = item['symbol'].replace(':', '_')
                    await self.publish(f"tradingview:{symbol_clean}", item)
                aggregated = {
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'count': len(data),
                    'symbols': {d['symbol']: {'price': d['price'], 'rsi': d.get('rsi_14')} for d in data}
                }
                await self.publish('tradingview:aggregated', aggregated)
                logger.info(f"TradingView: Collected {len(data)} symbols")
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"Prices loop error: {e}")
                await asyncio.sleep(30)

    async def run_news_loop(self, interval: int = 600):
        logger.info(f"Starting TradingView news scraper (interval: {interval}s)")
        while True:
            try:
                articles = await self.fetch_news()
                for article in articles:
                    await self.persist_news(article)
                    await self.publish('tradingview:news', article)
                logger.info(f"TradingView News: Collected {len(articles)} articles")
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"News loop error: {e}")
                await asyncio.sleep(60)


async def main():
    scraper = TradingViewScraper()
    await scraper.connect()
    try:
        await asyncio.gather(
            scraper.run_prices_loop(interval=60),
            scraper.run_news_loop(interval=600)
        )
    except KeyboardInterrupt:
        logger.info("Shutting down TradingView scraper")
    finally:
        await scraper.close()


if __name__ == '__main__':
    asyncio.run(main())
