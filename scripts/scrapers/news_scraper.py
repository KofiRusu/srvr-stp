#!/usr/bin/env python3
"""
News Scraper - Aggregates crypto/finance news from Bloomberg, CNN, Yahoo Finance
Uses RSS feeds and basic web scraping
"""

import os
import re
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
import hashlib

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('NewsScraper')

try:
    import httpx
    import feedparser
    import redis.asyncio as redis
    import asyncpg
    from bs4 import BeautifulSoup
except ImportError as e:
    logger.error(f"Missing dependency: {e}")
    raise

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')
POSTGRES_URL = os.environ.get('POSTGRES_URL', 'postgresql://chatos:chatos@localhost:5432/chatos_trading')
INTERVAL = int(os.environ.get('INTERVAL', 300))

CRYPTO_KEYWORDS = [
    'bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'cryptocurrency', 'blockchain',
    'solana', 'sol', 'xrp', 'ripple', 'dogecoin', 'doge', 'cardano', 'ada',
    'defi', 'nft', 'web3', 'binance', 'coinbase', 'altcoin', 'stablecoin',
    'usdt', 'usdc', 'trading', 'exchange', 'wallet', 'mining', 'halving'
]

SYMBOL_PATTERNS = {
    r'\bbitcoin\b|\bbtc\b': 'BTC',
    r'\bethereum\b|\beth\b': 'ETH',
    r'\bsolana\b|\bsol\b': 'SOL',
    r'\bxrp\b|\bripple\b': 'XRP',
    r'\bdogecoin\b|\bdoge\b': 'DOGE',
    r'\bcardano\b|\bada\b': 'ADA',
    r'\bpolkadot\b|\bdot\b': 'DOT',
    r'\bavalanch\w*\b|\bavax\b': 'AVAX',
    r'\bchainlink\b|\blink\b': 'LINK',
    r'\bpolygon\b|\bmatic\b': 'MATIC',
}

RSS_FEEDS = {
    'yahoo_finance': [
        'https://finance.yahoo.com/news/rssindex',
    ],
    'cnn_money': [
        'http://rss.cnn.com/rss/money_latest.rss',
        'http://rss.cnn.com/rss/money_markets.rss',
    ],
    'bloomberg': [
        'https://feeds.bloomberg.com/markets/news.rss',
    ],
    'coindesk': [
        'https://www.coindesk.com/arc/outboundfeeds/rss/',
    ],
    'cointelegraph': [
        'https://cointelegraph.com/rss',
    ],
}


def extract_symbols(text: str) -> List[str]:
    if not text:
        return []
    text_lower = text.lower()
    symbols = set()
    for pattern, symbol in SYMBOL_PATTERNS.items():
        if re.search(pattern, text_lower):
            symbols.add(symbol)
    return list(symbols)


def is_crypto_related(text: str) -> bool:
    if not text:
        return False
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in CRYPTO_KEYWORDS)


def simple_sentiment(text: str) -> tuple:
    if not text:
        return 0.0, 'neutral'
    
    text_lower = text.lower()
    
    positive_words = ['surge', 'rally', 'gain', 'bull', 'rise', 'up', 'high', 'record', 
                     'growth', 'profit', 'win', 'success', 'boost', 'soar', 'jump']
    negative_words = ['crash', 'drop', 'fall', 'bear', 'down', 'low', 'loss', 'fail',
                     'decline', 'plunge', 'sell', 'fear', 'risk', 'warning', 'concern']
    
    pos_count = sum(1 for word in positive_words if word in text_lower)
    neg_count = sum(1 for word in negative_words if word in text_lower)
    
    total = pos_count + neg_count
    if total == 0:
        return 0.0, 'neutral'
    
    score = (pos_count - neg_count) / total
    
    if score > 0.2:
        label = 'positive'
    elif score < -0.2:
        label = 'negative'
    else:
        label = 'neutral'
    
    return round(score, 4), label


class NewsScraper:
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.pg_pool: Optional[asyncpg.Pool] = None
        self.http_client: Optional[httpx.AsyncClient] = None
        self.running = False
        self.seen_urls = set()
    
    async def connect(self):
        self.redis_client = redis.from_url(REDIS_URL)
        self.pg_pool = await asyncpg.create_pool(POSTGRES_URL, min_size=2, max_size=10)
        self.http_client = httpx.AsyncClient(
            timeout=30,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            follow_redirects=True
        )
        
        async with self.pg_pool.acquire() as conn:
            rows = await conn.fetch('SELECT url FROM news_articles ORDER BY scraped_at DESC LIMIT 1000')
            self.seen_urls = {row['url'] for row in rows if row['url']}
        
        logger.info(f"Connected. Loaded {len(self.seen_urls)} seen URLs")
    
    async def close(self):
        if self.http_client:
            await self.http_client.aclose()
        if self.redis_client:
            await self.redis_client.close()
        if self.pg_pool:
            await self.pg_pool.close()
    
    async def fetch_rss_feed(self, url: str) -> List[Dict]:
        try:
            resp = await self.http_client.get(url)
            if resp.status_code != 200:
                return []
            
            feed = feedparser.parse(resp.text)
            articles = []
            
            for entry in feed.entries[:20]:
                title = entry.get('title', '')
                summary = entry.get('summary', entry.get('description', ''))
                link = entry.get('link', '')
                
                if link in self.seen_urls:
                    continue
                
                combined_text = f"{title} {summary}"
                
                if not is_crypto_related(combined_text):
                    continue
                
                published = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    except:
                        pass
                
                symbols = extract_symbols(combined_text)
                sentiment_score, sentiment_label = simple_sentiment(combined_text)
                
                if summary:
                    soup = BeautifulSoup(summary, 'html.parser')
                    summary = soup.get_text()[:500]
                
                articles.append({
                    'title': title[:500],
                    'url': link,
                    'summary': summary,
                    'published_at': published,
                    'symbols': symbols,
                    'sentiment_score': sentiment_score,
                    'sentiment_label': sentiment_label,
                })
            
            return articles
        except Exception as e:
            logger.debug(f"Error fetching RSS {url}: {e}")
            return []
    
    async def scrape_all_feeds(self) -> Dict[str, List[Dict]]:
        all_articles = {}
        
        for source, feeds in RSS_FEEDS.items():
            source_articles = []
            for feed_url in feeds:
                articles = await self.fetch_rss_feed(feed_url)
                for article in articles:
                    article['source'] = source
                source_articles.extend(articles)
            all_articles[source] = source_articles
            
            await asyncio.sleep(1)
        
        return all_articles
    
    async def publish_articles(self, articles_by_source: Dict[str, List[Dict]]):
        timestamp = datetime.now(timezone.utc)
        total_new = 0
        
        async with self.pg_pool.acquire() as conn:
            for source, articles in articles_by_source.items():
                for article in articles:
                    if article['url'] in self.seen_urls:
                        continue
                    
                    try:
                        await conn.execute('''
                            INSERT INTO news_articles 
                            (source, title, url, summary, published_at, 
                             sentiment_score, sentiment_label, related_symbols, scraped_at)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                            ON CONFLICT (url) DO NOTHING
                        ''',
                            source,
                            article['title'],
                            article['url'],
                            article.get('summary'),
                            article.get('published_at'),
                            article['sentiment_score'],
                            article['sentiment_label'],
                            article['symbols'],
                            timestamp
                        )
                        
                        self.seen_urls.add(article['url'])
                        total_new += 1
                        
                        record = {
                            'source': source,
                            'title': article['title'],
                            'url': article['url'],
                            'symbols': article['symbols'],
                            'sentiment_score': article['sentiment_score'],
                            'sentiment_label': article['sentiment_label'],
                            'published_at': article['published_at'].isoformat() if article['published_at'] else None,
                            'scraped_at': timestamp.isoformat()
                        }
                        await self.redis_client.publish('news:article', json.dumps(record))
                        
                    except Exception as e:
                        logger.debug(f"Error inserting article: {e}")
        
        all_articles = []
        for articles in articles_by_source.values():
            all_articles.extend(articles)
        
        recent = sorted(all_articles, key=lambda x: x.get('published_at') or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[:20]
        recent_json = []
        for a in recent:
            recent_json.append({
                'source': a.get('source'),
                'title': a['title'],
                'url': a['url'],
                'symbols': a['symbols'],
                'sentiment_score': a['sentiment_score'],
                'sentiment_label': a['sentiment_label'],
                'published_at': a['published_at'].isoformat() if a.get('published_at') else None
            })
        
        await self.redis_client.set('latest:news', json.dumps(recent_json), ex=600)
        
        if total_new > 0:
            logger.info(f"Published {total_new} new articles from {len(articles_by_source)} sources")
        else:
            logger.info("No new articles found")
    
    async def run(self):
        self.running = True
        logger.info("Starting News Scraper")
        logger.info(f"Sources: {list(RSS_FEEDS.keys())}")
        logger.info(f"Interval: {INTERVAL}s")
        
        await self.connect()
        
        try:
            while self.running:
                try:
                    articles = await self.scrape_all_feeds()
                    await self.publish_articles(articles)
                except Exception as e:
                    logger.error(f"Scrape cycle error: {e}")
                
                await asyncio.sleep(INTERVAL)
        finally:
            await self.close()
    
    def stop(self):
        self.running = False


async def main():
    scraper = NewsScraper()
    try:
        await scraper.run()
    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
        scraper.stop()


if __name__ == '__main__':
    asyncio.run(main())
