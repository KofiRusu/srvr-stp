#!/usr/bin/env python3
"""
Social Media Scraper - Collects crypto sentiment from X/Twitter, Reddit, YouTube.
Publishes to Redis and PostgreSQL for real-time and historical analysis.
"""

import os
import sys
import json
import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('SocialScraper')

try:
    import redis.asyncio as redis
    import asyncpg
    import httpx
except ImportError as e:
    logger.error(f"Missing dependency: {e}. Install: pip install redis asyncpg httpx")
    sys.exit(1)

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')
POSTGRES_URL = os.environ.get('POSTGRES_URL', 'postgresql://chatos:chatos@localhost:5432/chatos_trading')

TWITTER_BEARER_TOKEN = os.environ.get('TWITTER_BEARER_TOKEN', '')
REDDIT_CLIENT_ID = os.environ.get('REDDIT_CLIENT_ID', '')
REDDIT_CLIENT_SECRET = os.environ.get('REDDIT_CLIENT_SECRET', '')
REDDIT_USER_AGENT = os.environ.get('REDDIT_USER_AGENT', 'ChatOS-Scraper/1.0')
YOUTUBE_API_KEY = os.environ.get('YOUTUBE_API_KEY', '')

CRYPTO_SUBREDDITS = ['CryptoCurrency', 'Bitcoin', 'ethereum', 'altcoin', 'solana', 'defi']
CRYPTO_KEYWORDS = ['bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'blockchain', 'solana', 'sol', 
                   'xrp', 'ripple', 'doge', 'shiba', 'defi', 'nft', 'web3', 'altcoin']

POSITIVE_WORDS = ['bullish', 'moon', 'pump', 'buy', 'long', 'breakout', 'surge', 'rally',
                  'bullrun', 'gain', 'profit', 'hodl', 'diamond', 'rocket', 'lambo', 'ath',
                  'undervalued', 'gem', '100x', 'accumulate', 'up']
NEGATIVE_WORDS = ['bearish', 'dump', 'crash', 'sell', 'short', 'scam', 'rug', 'rugpull',
                  'dead', 'loss', 'fear', 'panic', 'blood', 'rekt', 'fail', 'overvalued',
                  'down', 'collapse', 'drop', 'bubble']

SYMBOL_PATTERNS = {
    r'\bbitcoin\b|\bbtc\b': 'BTC',
    r'\bethereum\b|\beth\b': 'ETH',
    r'\bsolana\b|\bsol\b': 'SOL',
    r'\bripple\b|\bxrp\b': 'XRP',
    r'\bdoge\b|\bdogecoin\b': 'DOGE',
    r'\bcardano\b|\bada\b': 'ADA',
    r'\bpolkadot\b|\bdot\b': 'DOT',
    r'\bchainlink\b|\blink\b': 'LINK',
    r'\bavax\b|\bavalanche\b': 'AVAX',
    r'\bmatic\b|\bpolygon\b': 'MATIC',
}


def extract_symbols(text: str) -> List[str]:
    text_lower = text.lower()
    symbols = set()
    for pattern, symbol in SYMBOL_PATTERNS.items():
        if re.search(pattern, text_lower):
            symbols.add(symbol)
    return list(symbols)


def simple_sentiment(text: str) -> Tuple[float, str]:
    text_lower = text.lower()
    pos_count = sum(1 for word in POSITIVE_WORDS if word in text_lower)
    neg_count = sum(1 for word in NEGATIVE_WORDS if word in text_lower)
    total = pos_count + neg_count
    if total == 0:
        return (0.0, 'neutral')
    score = (pos_count - neg_count) / total
    if score > 0.2:
        label = 'positive'
    elif score < -0.2:
        label = 'negative'
    else:
        label = 'neutral'
    return (round(score, 4), label)


class SocialScraper:
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.pg_pool: Optional[asyncpg.Pool] = None
        self.http_client: Optional[httpx.AsyncClient] = None
        self.reddit_token: Optional[str] = None
        self.reddit_token_expires: Optional[datetime] = None

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

    async def publish(self, channel: str, data: dict):
        if self.redis_client:
            await self.redis_client.publish(channel, json.dumps(data, default=str))
            await self.redis_client.set(f"latest:{channel}", json.dumps(data, default=str), ex=300)

    async def persist_post(self, data: dict):
        if not self.pg_pool:
            return
        async with self.pg_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO social_posts 
                (platform, post_id, author, content, url, likes, retweets, replies, views,
                 sentiment_score, related_symbols, posted_at, scraped_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                ON CONFLICT (post_id) DO NOTHING
            """, data['platform'], data['post_id'], data.get('author', ''),
                data.get('content', ''), data.get('url', ''),
                data.get('likes', 0), data.get('retweets', 0), data.get('replies', 0),
                data.get('views', 0), data.get('sentiment_score', 0.0),
                data.get('related_symbols', []), data.get('posted_at'),
                datetime.now(timezone.utc))

    async def persist_trend(self, data: dict):
        if not self.pg_pool:
            return
        async with self.pg_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO social_trends (platform, keyword, volume, sentiment_avg, timestamp)
                VALUES ($1, $2, $3, $4, $5)
            """, data['platform'], data['keyword'], data.get('volume', 0),
                data.get('sentiment_avg', 0.0), datetime.now(timezone.utc))

    async def get_reddit_token(self) -> Optional[str]:
        if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
            return None
        if self.reddit_token and self.reddit_token_expires and datetime.now() < self.reddit_token_expires:
            return self.reddit_token
        try:
            auth = httpx.BasicAuth(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET)
            resp = await self.http_client.post(
                'https://www.reddit.com/api/v1/access_token',
                auth=auth,
                data={'grant_type': 'client_credentials'},
                headers={'User-Agent': REDDIT_USER_AGENT}
            )
            if resp.status_code == 200:
                data = resp.json()
                self.reddit_token = data['access_token']
                self.reddit_token_expires = datetime.now() + timedelta(seconds=data.get('expires_in', 3600) - 60)
                logger.info("Reddit token acquired")
                return self.reddit_token
        except Exception as e:
            logger.error(f"Reddit auth error: {e}")
        return None

    async def fetch_reddit_posts(self, subreddit: str, limit: int = 25) -> List[Dict]:
        token = await self.get_reddit_token()
        if not token:
            return self._mock_reddit_posts(subreddit)
        try:
            headers = {
                'Authorization': f'Bearer {token}',
                'User-Agent': REDDIT_USER_AGENT
            }
            resp = await self.http_client.get(
                f'https://oauth.reddit.com/r/{subreddit}/hot',
                params={'limit': limit},
                headers=headers
            )
            if resp.status_code != 200:
                logger.warning(f"Reddit API error {resp.status_code} for r/{subreddit}")
                return []
            data = resp.json()
            posts = []
            for child in data.get('data', {}).get('children', []):
                post = child.get('data', {})
                title = post.get('title', '')
                selftext = post.get('selftext', '')
                content = f"{title} {selftext}"
                score, label = simple_sentiment(content)
                symbols = extract_symbols(content)
                posts.append({
                    'platform': 'reddit',
                    'post_id': f"reddit_{post.get('id', '')}",
                    'author': post.get('author', '[deleted]'),
                    'content': content[:2000],
                    'url': f"https://reddit.com{post.get('permalink', '')}",
                    'likes': post.get('ups', 0),
                    'retweets': 0,
                    'replies': post.get('num_comments', 0),
                    'views': 0,
                    'sentiment_score': score,
                    'related_symbols': symbols,
                    'posted_at': datetime.fromtimestamp(post.get('created_utc', 0), tz=timezone.utc)
                })
            return posts
        except Exception as e:
            logger.error(f"Reddit fetch error for r/{subreddit}: {e}")
            return []

    def _mock_reddit_posts(self, subreddit: str) -> List[Dict]:
        logger.info(f"Using mock Reddit data for r/{subreddit}")
        return [
            {
                'platform': 'reddit',
                'post_id': f'reddit_mock_{subreddit}_1',
                'author': 'crypto_trader',
                'content': f'Bitcoin looking bullish! Time to accumulate BTC before the next rally.',
                'url': f'https://reddit.com/r/{subreddit}/mock1',
                'likes': 150,
                'retweets': 0,
                'replies': 42,
                'views': 0,
                'sentiment_score': 0.75,
                'related_symbols': ['BTC'],
                'posted_at': datetime.now(timezone.utc)
            }
        ]

    async def fetch_twitter_posts(self, query: str = 'bitcoin OR ethereum crypto', limit: int = 50) -> List[Dict]:
        if not TWITTER_BEARER_TOKEN:
            return self._mock_twitter_posts()
        try:
            headers = {'Authorization': f'Bearer {TWITTER_BEARER_TOKEN}'}
            params = {
                'query': f'{query} -is:retweet lang:en',
                'max_results': min(limit, 100),
                'tweet.fields': 'created_at,public_metrics,author_id',
                'expansions': 'author_id',
                'user.fields': 'username'
            }
            resp = await self.http_client.get(
                'https://api.twitter.com/2/tweets/search/recent',
                params=params,
                headers=headers
            )
            if resp.status_code != 200:
                logger.warning(f"Twitter API error {resp.status_code}: {resp.text}")
                return self._mock_twitter_posts()
            data = resp.json()
            users = {u['id']: u['username'] for u in data.get('includes', {}).get('users', [])}
            posts = []
            for tweet in data.get('data', []):
                content = tweet.get('text', '')
                score, label = simple_sentiment(content)
                symbols = extract_symbols(content)
                metrics = tweet.get('public_metrics', {})
                posts.append({
                    'platform': 'twitter',
                    'post_id': f"twitter_{tweet.get('id', '')}",
                    'author': users.get(tweet.get('author_id', ''), 'unknown'),
                    'content': content[:2000],
                    'url': f"https://twitter.com/i/status/{tweet.get('id', '')}",
                    'likes': metrics.get('like_count', 0),
                    'retweets': metrics.get('retweet_count', 0),
                    'replies': metrics.get('reply_count', 0),
                    'views': metrics.get('impression_count', 0),
                    'sentiment_score': score,
                    'related_symbols': symbols,
                    'posted_at': datetime.fromisoformat(tweet.get('created_at', '').replace('Z', '+00:00'))
                })
            return posts
        except Exception as e:
            logger.error(f"Twitter fetch error: {e}")
            return self._mock_twitter_posts()

    def _mock_twitter_posts(self) -> List[Dict]:
        logger.info("Using mock Twitter data")
        return [
            {
                'platform': 'twitter',
                'post_id': 'twitter_mock_1',
                'author': 'cryptowhale',
                'content': '$BTC breaking out! This is the start of the next bull run. #Bitcoin #crypto',
                'url': 'https://twitter.com/i/status/mock1',
                'likes': 2500,
                'retweets': 500,
                'replies': 150,
                'views': 50000,
                'sentiment_score': 0.8,
                'related_symbols': ['BTC'],
                'posted_at': datetime.now(timezone.utc)
            }
        ]

    async def fetch_youtube_videos(self, query: str = 'bitcoin crypto', limit: int = 10) -> List[Dict]:
        if not YOUTUBE_API_KEY:
            return self._mock_youtube_videos()
        try:
            params = {
                'part': 'snippet,statistics',
                'q': query,
                'type': 'video',
                'order': 'date',
                'maxResults': min(limit, 50),
                'key': YOUTUBE_API_KEY
            }
            resp = await self.http_client.get(
                'https://www.googleapis.com/youtube/v3/search',
                params=params
            )
            if resp.status_code != 200:
                logger.warning(f"YouTube API error {resp.status_code}")
                return self._mock_youtube_videos()
            data = resp.json()
            video_ids = [item['id']['videoId'] for item in data.get('items', []) if item.get('id', {}).get('videoId')]
            if not video_ids:
                return []
            stats_resp = await self.http_client.get(
                'https://www.googleapis.com/youtube/v3/videos',
                params={
                    'part': 'statistics',
                    'id': ','.join(video_ids),
                    'key': YOUTUBE_API_KEY
                }
            )
            stats_map = {}
            if stats_resp.status_code == 200:
                for item in stats_resp.json().get('items', []):
                    stats_map[item['id']] = item.get('statistics', {})
            posts = []
            for item in data.get('items', []):
                video_id = item.get('id', {}).get('videoId', '')
                snippet = item.get('snippet', {})
                title = snippet.get('title', '')
                description = snippet.get('description', '')
                content = f"{title} {description}"
                score, label = simple_sentiment(content)
                symbols = extract_symbols(content)
                stats = stats_map.get(video_id, {})
                posts.append({
                    'platform': 'youtube',
                    'post_id': f"youtube_{video_id}",
                    'author': snippet.get('channelTitle', 'Unknown'),
                    'content': content[:2000],
                    'url': f"https://www.youtube.com/watch?v={video_id}",
                    'likes': int(stats.get('likeCount', 0)),
                    'retweets': 0,
                    'replies': int(stats.get('commentCount', 0)),
                    'views': int(stats.get('viewCount', 0)),
                    'sentiment_score': score,
                    'related_symbols': symbols,
                    'posted_at': datetime.fromisoformat(snippet.get('publishedAt', '').replace('Z', '+00:00'))
                })
            return posts
        except Exception as e:
            logger.error(f"YouTube fetch error: {e}")
            return self._mock_youtube_videos()

    def _mock_youtube_videos(self) -> List[Dict]:
        logger.info("Using mock YouTube data")
        return [
            {
                'platform': 'youtube',
                'post_id': 'youtube_mock_1',
                'author': 'Coin Bureau',
                'content': 'Bitcoin Price Analysis - This Is What You NEED To Know! BTC showing strength',
                'url': 'https://www.youtube.com/watch?v=mock1',
                'likes': 15000,
                'retweets': 0,
                'replies': 2000,
                'views': 250000,
                'sentiment_score': 0.65,
                'related_symbols': ['BTC'],
                'posted_at': datetime.now(timezone.utc)
            }
        ]

    async def calculate_trends(self, posts: List[Dict]) -> List[Dict]:
        keyword_stats: Dict[str, Dict] = {}
        for post in posts:
            for symbol in post.get('related_symbols', []):
                if symbol not in keyword_stats:
                    keyword_stats[symbol] = {'count': 0, 'sentiment_sum': 0.0}
                keyword_stats[symbol]['count'] += 1
                keyword_stats[symbol]['sentiment_sum'] += post.get('sentiment_score', 0.0)
        trends = []
        for keyword, stats in keyword_stats.items():
            trends.append({
                'platform': 'aggregated',
                'keyword': keyword,
                'volume': stats['count'],
                'sentiment_avg': round(stats['sentiment_sum'] / stats['count'], 4) if stats['count'] > 0 else 0.0
            })
        return sorted(trends, key=lambda x: x['volume'], reverse=True)

    async def run_twitter_loop(self, interval: int = 300):
        logger.info(f"Starting Twitter scraper (interval: {interval}s)")
        while True:
            try:
                posts = await self.fetch_twitter_posts()
                for post in posts:
                    await self.persist_post(post)
                    await self.publish(f"social:twitter:{post.get('related_symbols', ['GENERAL'])[0] if post.get('related_symbols') else 'GENERAL'}", post)
                logger.info(f"Twitter: Collected {len(posts)} posts")
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"Twitter loop error: {e}")
                await asyncio.sleep(60)

    async def run_reddit_loop(self, interval: int = 300):
        logger.info(f"Starting Reddit scraper (interval: {interval}s)")
        while True:
            try:
                all_posts = []
                for subreddit in CRYPTO_SUBREDDITS:
                    posts = await self.fetch_reddit_posts(subreddit)
                    all_posts.extend(posts)
                    await asyncio.sleep(2)
                for post in all_posts:
                    await self.persist_post(post)
                    await self.publish(f"social:reddit:{post.get('related_symbols', ['GENERAL'])[0] if post.get('related_symbols') else 'GENERAL'}", post)
                trends = await self.calculate_trends(all_posts)
                for trend in trends:
                    await self.persist_trend(trend)
                logger.info(f"Reddit: Collected {len(all_posts)} posts, {len(trends)} trends")
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"Reddit loop error: {e}")
                await asyncio.sleep(60)

    async def run_youtube_loop(self, interval: int = 600):
        logger.info(f"Starting YouTube scraper (interval: {interval}s)")
        queries = ['bitcoin crypto', 'ethereum defi', 'solana nft', 'crypto trading']
        while True:
            try:
                all_posts = []
                for query in queries:
                    posts = await self.fetch_youtube_videos(query)
                    all_posts.extend(posts)
                    await asyncio.sleep(2)
                for post in all_posts:
                    await self.persist_post(post)
                    await self.publish(f"social:youtube:{post.get('related_symbols', ['GENERAL'])[0] if post.get('related_symbols') else 'GENERAL'}", post)
                logger.info(f"YouTube: Collected {len(all_posts)} videos")
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"YouTube loop error: {e}")
                await asyncio.sleep(60)


async def main():
    scraper = SocialScraper()
    await scraper.connect()
    try:
        await asyncio.gather(
            scraper.run_twitter_loop(interval=300),
            scraper.run_reddit_loop(interval=300),
            scraper.run_youtube_loop(interval=600)
        )
    except KeyboardInterrupt:
        logger.info("Shutting down social scraper")
    finally:
        await scraper.close()


if __name__ == '__main__':
    asyncio.run(main())
