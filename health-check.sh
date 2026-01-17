#!/bin/bash
# =============================================================================
# ChatOS Server - System Health Check & Validation
# Validates all services and data pipelines are operational
# =============================================================================

set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

INSTALL_DIR="${CHATOS_DIR:-$HOME/chatos-server}"
API_KEY="${CHATOS_API_KEY:-}"

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║      ChatOS Server - System Health Check v2.0            ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

PASSED=0
FAILED=0
WARNINGS=0

check_test() {
    local name=$1
    local result=$2
    local message=$3
    
    if [ $result -eq 0 ]; then
        echo -e "${GREEN}✓ PASS${NC} - $name"
        ((PASSED++))
    else
        echo -e "${RED}✗ FAIL${NC} - $name: $message"
        ((FAILED++))
    fi
}

warn_test() {
    local name=$1
    local message=$2
    echo -e "${YELLOW}⚠ WARN${NC} - $name: $message"
    ((WARNINGS++))
}

echo ""
echo -e "${CYAN}[Docker & Containers]${NC}"

docker info > /dev/null 2>&1
check_test "Docker daemon" $? "Docker is not running"

docker compose version > /dev/null 2>&1
check_test "Docker Compose" $? "Docker Compose not found"

cd "$INSTALL_DIR/docker"
RUNNING=$(docker compose ps --format json 2>/dev/null | grep -c "running" || echo "0")
if [ "$RUNNING" -ge 10 ]; then
    echo -e "${GREEN}✓ PASS${NC} - Services running: $RUNNING/12"
    ((PASSED++))
elif [ "$RUNNING" -ge 5 ]; then
    echo -e "${YELLOW}⚠ WARN${NC} - Services running: $RUNNING/12 (some scrapers may be starting)"
    ((WARNINGS++))
else
    echo -e "${RED}✗ FAIL${NC} - Only $RUNNING/12 services running"
    docker compose ps
    ((FAILED++))
fi

echo ""
echo -e "${CYAN}[Database Connectivity]${NC}"

if nc -z localhost 5432 2>/dev/null; then
    echo -e "${GREEN}✓ PASS${NC} - PostgreSQL (port 5432)"
    ((PASSED++))
else
    echo -e "${RED}✗ FAIL${NC} - PostgreSQL not accessible on port 5432"
    ((FAILED++))
fi

if nc -z localhost 6379 2>/dev/null; then
    echo -e "${GREEN}✓ PASS${NC} - Redis (port 6379)"
    ((PASSED++))
else
    echo -e "${RED}✗ FAIL${NC} - Redis not accessible on port 6379"
    ((FAILED++))
fi

echo ""
echo -e "${CYAN}[API Endpoints]${NC}"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/health 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}✓ PASS${NC} - Data API (port 8080)"
    ((PASSED++))
else
    echo -e "${RED}✗ FAIL${NC} - Data API returned HTTP $HTTP_CODE (expected 200)"
    ((FAILED++))
fi

if [ -z "$API_KEY" ]; then
    if [ -f "$INSTALL_DIR/.env" ]; then
        API_KEY=$(grep "API_KEY=" "$INSTALL_DIR/.env" | cut -d= -f2)
    fi
fi

if [ -n "$API_KEY" ]; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "X-API-Key: $API_KEY" \
        http://localhost:8080/api/symbols 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        echo -e "${GREEN}✓ PASS${NC} - API authentication (X-API-Key)"
        ((PASSED++))
    else
        echo -e "${RED}✗ FAIL${NC} - API auth failed with HTTP $HTTP_CODE"
        ((FAILED++))
    fi
else
    warn_test "API authentication" "Could not find API_KEY to test"
fi

echo ""
echo -e "${CYAN}[Core Data Pipelines]${NC}"

TRADE_COUNT=$(curl -s -H "X-API-Key: ${API_KEY}" \
    http://localhost:8080/api/history/trades/BTCUSDT?limit=1 2>/dev/null | grep -c "symbol" || echo "0")
if [ "$TRADE_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ PASS${NC} - Trade data ingestion"
    ((PASSED++))
else
    warn_test "Trade data ingestion" "No trade data found yet (may be collecting)"
fi

FUNDING_COUNT=$(curl -s -H "X-API-Key: ${API_KEY}" \
    http://localhost:8080/api/history/funding/BTCUSDT?limit=1 2>/dev/null | grep -c "symbol" || echo "0")
if [ "$FUNDING_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ PASS${NC} - Funding rate data"
    ((PASSED++))
else
    warn_test "Funding rate data" "No funding data found yet (may be collecting)"
fi

OI_COUNT=$(curl -s -H "X-API-Key: ${API_KEY}" \
    http://localhost:8080/api/history/oi/BTCUSDT?limit=1 2>/dev/null | grep -c "symbol" || echo "0")
if [ "$OI_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ PASS${NC} - Open interest data"
    ((PASSED++))
else
    warn_test "Open interest data" "No OI data found yet (may be collecting)"
fi

echo ""
echo -e "${CYAN}[Extended Data Sources]${NC}"

FG_DATA=$(curl -s -H "X-API-Key: ${API_KEY}" \
    http://localhost:8080/api/fear-greed 2>/dev/null | grep -c "value" || echo "0")
if [ "$FG_DATA" -gt 0 ]; then
    echo -e "${GREEN}✓ PASS${NC} - Fear & Greed Index"
    ((PASSED++))
else
    warn_test "Fear & Greed Index" "No data yet (CoinMarketCap scraper may be initializing)"
fi

GLOBAL_DATA=$(curl -s -H "X-API-Key: ${API_KEY}" \
    http://localhost:8080/api/global-metrics 2>/dev/null | grep -c "total_market_cap" || echo "0")
if [ "$GLOBAL_DATA" -gt 0 ]; then
    echo -e "${GREEN}✓ PASS${NC} - Global market metrics"
    ((PASSED++))
else
    warn_test "Global market metrics" "No data yet (may be initializing)"
fi

NEWS_DATA=$(curl -s -H "X-API-Key: ${API_KEY}" \
    "http://localhost:8080/api/news?limit=5" 2>/dev/null | grep -c "articles" || echo "0")
if [ "$NEWS_DATA" -gt 0 ]; then
    echo -e "${GREEN}✓ PASS${NC} - News articles"
    ((PASSED++))
else
    warn_test "News articles" "No news data yet (scraper may be initializing)"
fi

SENTIMENT_DATA=$(curl -s -H "X-API-Key: ${API_KEY}" \
    http://localhost:8080/api/sentiment/BTC 2>/dev/null | grep -c "symbol" || echo "0")
if [ "$SENTIMENT_DATA" -gt 0 ]; then
    echo -e "${GREEN}✓ PASS${NC} - Sentiment analysis"
    ((PASSED++))
else
    warn_test "Sentiment analysis" "No sentiment data yet"
fi

TRENDS_DATA=$(curl -s -H "X-API-Key: ${API_KEY}" \
    http://localhost:8080/api/trends 2>/dev/null | grep -c "trends" || echo "0")
if [ "$TRENDS_DATA" -gt 0 ]; then
    echo -e "${GREEN}✓ PASS${NC} - Google Trends"
    ((PASSED++))
else
    warn_test "Google Trends" "No trends data yet (hourly update interval)"
fi

ARB_DATA=$(curl -s -H "X-API-Key: ${API_KEY}" \
    http://localhost:8080/api/arbitrage 2>/dev/null | grep -c "opportunities" || echo "0")
if [ "$ARB_DATA" -gt 0 ]; then
    echo -e "${GREEN}✓ PASS${NC} - Arbitrage detection"
    ((PASSED++))
else
    warn_test "Arbitrage detection" "No arbitrage data yet (CCXT scraper may be initializing)"
fi

TV_DATA=$(curl -s -H "X-API-Key: ${API_KEY}" \
    http://localhost:8080/api/tradingview/BTC 2>/dev/null | grep -c "symbol" || echo "0")
if [ "$TV_DATA" -gt 0 ]; then
    echo -e "${GREEN}✓ PASS${NC} - TradingView data"
    ((PASSED++))
else
    warn_test "TradingView data" "No TradingView data yet"
fi

echo ""
echo -e "${CYAN}[WebSocket Streaming]${NC}"

WS_TEST=$(timeout 3 curl -i -N -H "Connection: Upgrade" \
    -H "Upgrade: websocket" \
    "http://localhost:8080/ws/stream?api_key=${API_KEY}&channels=trades:BTCUSDT" \
    2>/dev/null | grep -i "upgrade" || echo "")

if [ -n "$WS_TEST" ]; then
    echo -e "${GREEN}✓ PASS${NC} - WebSocket endpoint"
    ((PASSED++))
else
    warn_test "WebSocket endpoint" "Could not establish WebSocket connection"
fi

echo ""
echo -e "${CYAN}[Storage & Persistence]${NC}"

TABLE_COUNT=$(docker compose exec -T postgres psql -U chatos -d chatos_trading -tc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | grep -o "[0-9]*" | head -1 || echo "0")

if [ "$TABLE_COUNT" -ge 18 ]; then
    echo -e "${GREEN}✓ PASS${NC} - Database schema ($TABLE_COUNT tables - full schema)"
    ((PASSED++))
elif [ "$TABLE_COUNT" -gt 5 ]; then
    echo -e "${YELLOW}⚠ WARN${NC} - Database schema ($TABLE_COUNT tables - partial, expected 18+)"
    ((WARNINGS++))
else
    echo -e "${RED}✗ FAIL${NC} - Database missing tables (found $TABLE_COUNT, expected 18+)"
    ((FAILED++))
fi

if [ -d "$INSTALL_DIR/data" ] || docker volume inspect chatos-data-api &>/dev/null; then
    echo -e "${GREEN}✓ PASS${NC} - Data volume mounted"
    ((PASSED++))
else
    warn_test "Data volume" "No persistent data volume found"
fi

echo ""
echo -e "${CYAN}[Scraper Status]${NC}"

SCRAPERS="scraper-aggr scraper-coinglass scraper-market scraper-crypto-metrics scraper-coingecko scraper-ccxt scraper-tradingview scraper-news scraper-social scraper-sentiment"
for scraper in $SCRAPERS; do
    STATUS=$(docker compose ps $scraper --format "{{.Status}}" 2>/dev/null || echo "not found")
    if echo "$STATUS" | grep -qi "up"; then
        echo -e "${GREEN}✓ PASS${NC} - $scraper"
        ((PASSED++))
    elif echo "$STATUS" | grep -qi "restarting"; then
        warn_test "$scraper" "Restarting (check logs)"
    else
        warn_test "$scraper" "Not running: $STATUS"
    fi
done

echo ""
echo "════════════════════════════════════════════════════════════"
echo -e "${CYAN}VALIDATION SUMMARY${NC}"
echo "════════════════════════════════════════════════════════════"
echo -e "${GREEN}Passed:${NC}   $PASSED"
echo -e "${RED}Failed:${NC}   $FAILED"
echo -e "${YELLOW}Warnings:${NC} $WARNINGS"
echo "════════════════════════════════════════════════════════════"

echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ SYSTEM HEALTHY${NC}"
    echo ""
    echo -e "${CYAN}Connection Instructions for Mac:${NC}"
    echo ""
    if [ -n "$API_KEY" ]; then
        SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "YOUR_SERVER_IP")
        echo "  export CHATOS_DATA_URL=\"http://$SERVER_IP:8080\""
        echo "  export CHATOS_API_KEY=\"$API_KEY\""
    fi
    echo ""
    echo -e "${CYAN}Available API Endpoints:${NC}"
    echo "  GET /health                    - Health check"
    echo "  GET /api/symbols               - Available symbols"
    echo "  GET /api/fear-greed            - Fear & Greed Index"
    echo "  GET /api/global-metrics        - Global market cap/volume"
    echo "  GET /api/news                  - Crypto news articles"
    echo "  GET /api/sentiment/{symbol}    - Symbol sentiment analysis"
    echo "  GET /api/trends                - Google Trends data"
    echo "  GET /api/arbitrage             - Arbitrage opportunities"
    echo "  GET /api/tradingview/{symbol}  - TradingView indicators"
    echo "  WS  /ws/stream                 - Real-time data stream"
    echo ""
    echo -e "${CYAN}Management Commands:${NC}"
    echo "  cd $INSTALL_DIR/docker"
    echo "  docker compose logs -f                # View logs"
    echo "  docker compose logs -f scraper-news   # View specific scraper logs"
    echo "  docker compose restart                # Restart services"
    echo "  docker compose ps                     # Check status"
    echo ""
    exit 0
else
    echo -e "${RED}✗ SYSTEM ISSUES DETECTED${NC}"
    echo ""
    echo -e "${CYAN}Troubleshooting:${NC}"
    echo "  1. Check service logs:"
    echo "     cd $INSTALL_DIR/docker && docker compose logs"
    echo ""
    echo "  2. Check specific scraper:"
    echo "     docker compose logs scraper-news"
    echo ""
    echo "  3. Restart services:"
    echo "     docker compose down && docker compose up -d"
    echo ""
    echo "  4. Re-run validation:"
    echo "     bash $INSTALL_DIR/health-check.sh"
    echo ""
    exit 1
fi
