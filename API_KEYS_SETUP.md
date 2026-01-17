# ChatOS Server - API Keys Setup Guide

This guide explains how to obtain API keys for all data sources used by the ChatOS server scrapers.

## Required API Keys

| Service | Required? | Cost | Rate Limits | Purpose |
|---------|-----------|------|-------------|---------|
| CoinMarketCap | Recommended | Free / $29/mo | 333 calls/day (free) | Fear & Greed, global metrics |
| CoinGecko | No | Free | 50 calls/min | Coin data, DeFi metrics |
| Twitter/X | Optional | Free | 500k tweets/mo | Social sentiment |
| Reddit | Optional | Free | 60 calls/min | Social sentiment |
| YouTube | Optional | Free | 10k units/day | Video sentiment |

**Note:** All scrapers include mock data fallbacks when API keys are not configured.

---

## 1. CoinMarketCap API Key

**Purpose:** Fear & Greed Index, global market metrics, top 100 coins data

**Steps:**
1. Go to [https://pro.coinmarketcap.com/signup](https://pro.coinmarketcap.com/signup)
2. Create a free account
3. Navigate to "API Key" in the dashboard
4. Copy your API key

**Configuration:**
```bash
export COINMARKETCAP_API_KEY="your-api-key-here"
```

Or add to `.env` file:
```
COINMARKETCAP_API_KEY=your-api-key-here
```

**Rate Limits:**
- Free tier: 333 calls/day, 10,000 calls/month
- Basic ($29/mo): 10,000 calls/day

---

## 2. Twitter/X API Key

**Purpose:** Crypto tweet sentiment analysis, trending hashtags, influencer tracking

**Steps:**
1. Go to [https://developer.twitter.com/en/portal/dashboard](https://developer.twitter.com/en/portal/dashboard)
2. Create a developer account (requires approval)
3. Create a new Project and App
4. Navigate to "Keys and tokens"
5. Generate a "Bearer Token"

**Configuration:**
```bash
export TWITTER_BEARER_TOKEN="your-bearer-token-here"
```

**Rate Limits:**
- Free tier: 500,000 tweets/month
- Basic ($100/mo): 10,000 tweets/month (but more endpoints)

**Note:** Twitter API v2 is required. Free tier provides read-only access.

---

## 3. Reddit API Credentials

**Purpose:** Crypto subreddit sentiment (r/CryptoCurrency, r/Bitcoin, etc.)

**Steps:**
1. Go to [https://www.reddit.com/prefs/apps](https://www.reddit.com/prefs/apps)
2. Scroll down and click "create another app..."
3. Fill in:
   - Name: ChatOS-Scraper
   - Type: Select "script"
   - Redirect URI: http://localhost:8080
4. Click "create app"
5. Copy the Client ID (under the app name) and Client Secret

**Configuration:**
```bash
export REDDIT_CLIENT_ID="your-client-id"
export REDDIT_CLIENT_SECRET="your-client-secret"
export REDDIT_USER_AGENT="ChatOS-Scraper/1.0"
```

**Rate Limits:**
- 60 requests per minute
- No monthly limit

---

## 4. YouTube Data API Key

**Purpose:** Crypto video sentiment, channel monitoring, transcript analysis

**Steps:**
1. Go to [https://console.cloud.google.com/](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Enable the "YouTube Data API v3":
   - Go to "APIs & Services" > "Library"
   - Search for "YouTube Data API v3"
   - Click "Enable"
4. Create credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "API Key"
   - Copy the API key

**Configuration:**
```bash
export YOUTUBE_API_KEY="your-api-key-here"
```

**Rate Limits:**
- 10,000 units/day
- Search: 100 units per request
- Video details: 1 unit per request

---

## 5. CoinGecko (No Key Required)

**Purpose:** Comprehensive coin data, DeFi metrics, exchange volumes

CoinGecko provides a free public API that doesn't require an API key.

**Rate Limits:**
- 50 calls/minute
- No daily limit

The ChatOS scraper implements rate limiting automatically.

---

## Environment File Template

Create a `.env` file in your server-setup directory:

```env
# PostgreSQL
POSTGRES_PASSWORD=your_secure_password_here

# API Authentication
API_KEY=your_chatos_api_key_here

# CoinMarketCap (recommended)
COINMARKETCAP_API_KEY=

# Twitter/X (optional)
TWITTER_BEARER_TOKEN=

# Reddit (optional)
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=ChatOS-Scraper/1.0

# YouTube (optional)
YOUTUBE_API_KEY=
```

---

## Verifying API Keys

After configuring API keys, restart the scrapers and check the logs:

```bash
cd ~/chatos-server/docker
docker compose down
docker compose up -d
docker compose logs -f scraper-crypto-metrics  # Check CoinMarketCap
docker compose logs -f scraper-social          # Check Twitter/Reddit/YouTube
```

Successful connections will show log messages like:
```
INFO - CoinMarketCap: Fetched global metrics (daily calls: 1/333)
INFO - Twitter: Collected 50 posts
INFO - Reddit token acquired
INFO - YouTube: Collected 10 videos
```

---

## Mock Data Fallbacks

All scrapers include mock data fallbacks that activate when:
- API key is not configured
- API rate limit is exceeded
- API returns an error

Mock data is clearly marked in the logs:
```
INFO - Using mock Twitter data
```

This allows the system to remain functional for testing without API keys.

---

## Cost Summary

| Tier | Monthly Cost | Included |
|------|--------------|----------|
| Free | $0 | CoinGecko (unlimited), CoinMarketCap (333/day), Twitter (500k tweets), Reddit (unlimited), YouTube (10k units) |
| Basic | $29 | CoinMarketCap Basic (10k calls/day) + all free tier APIs |

For most use cases, the free tier is sufficient.

---

## Troubleshooting

### CoinMarketCap: "Invalid API key"
- Verify the key is copied correctly (no extra spaces)
- Check if the key is active in your CMC dashboard
- Ensure you haven't exceeded daily limits

### Twitter: "Unauthorized" or "Forbidden"
- Bearer tokens expire; regenerate if needed
- Ensure your developer account is approved
- Check if you're using v2 endpoints (v1.1 is deprecated)

### Reddit: "Invalid credentials"
- Client ID is the short string under your app name, not the app name itself
- Client Secret is labeled "secret" in the app settings
- User agent must be a non-empty string

### YouTube: "API key not valid"
- Ensure YouTube Data API v3 is enabled in your project
- Check for billing issues (free tier doesn't require billing, but check anyway)
- Regenerate the key if it was recently created (can take a few minutes to activate)
