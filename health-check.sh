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
echo "║      ChatOS Server - System Health Check                 ║"
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

# 1. Docker running
docker info > /dev/null 2>&1
check_test "Docker daemon" $? "Docker is not running"

# 2. Docker Compose available
docker compose version > /dev/null 2>&1
check_test "Docker Compose" $? "Docker Compose not found"

# 3. Check services running
cd "$INSTALL_DIR/docker"
RUNNING=$(docker compose ps --format json 2>/dev/null | grep -c "running" || echo "0")
if [ "$RUNNING" -ge 4 ]; then
    echo -e "${GREEN}✓ PASS${NC} - Services running: $RUNNING/5"
    ((PASSED++))
else
    echo -e "${RED}✗ FAIL${NC} - Only $RUNNING/5 services running"
    docker compose ps
    ((FAILED++))
fi

echo ""
echo -e "${CYAN}[Database Connectivity]${NC}"

# 4. PostgreSQL port accessible
if nc -z localhost 5432 2>/dev/null; then
    echo -e "${GREEN}✓ PASS${NC} - PostgreSQL (port 5432)"
    ((PASSED++))
else
    echo -e "${RED}✗ FAIL${NC} - PostgreSQL not accessible on port 5432"
    ((FAILED++))
fi

# 5. Redis port accessible
if nc -z localhost 6379 2>/dev/null; then
    echo -e "${GREEN}✓ PASS${NC} - Redis (port 6379)"
    ((PASSED++))
else
    echo -e "${RED}✗ FAIL${NC} - Redis not accessible on port 6379"
    ((FAILED++))
fi

echo ""
echo -e "${CYAN}[API Endpoints]${NC}"

# 6. Data API health
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/health 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}✓ PASS${NC} - Data API (port 8080)"
    ((PASSED++))
else
    echo -e "${RED}✗ FAIL${NC} - Data API returned HTTP $HTTP_CODE (expected 200)"
    ((FAILED++))
fi

# 7. API authentication
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
echo -e "${CYAN}[Data Pipelines]${NC}"

# 8. Check scrapers are collecting data
TRADE_COUNT=$(curl -s -H "X-API-Key: ${API_KEY}" \
    http://localhost:8080/api/history/trades/BTCUSDT?limit=1 2>/dev/null | grep -c "symbol" || echo "0")
if [ "$TRADE_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ PASS${NC} - Trade data ingestion (found data)"
    ((PASSED++))
else
    warn_test "Trade data ingestion" "No trade data found yet (may be collecting)"
fi

# 9. Check funding rate data
FUNDING_COUNT=$(curl -s -H "X-API-Key: ${API_KEY}" \
    http://localhost:8080/api/history/funding/BTCUSDT?limit=1 2>/dev/null | grep -c "symbol" || echo "0")
if [ "$FUNDING_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ PASS${NC} - Funding rate data (found data)"
    ((PASSED++))
else
    warn_test "Funding rate data" "No funding data found yet (may be collecting)"
fi

# 10. Check open interest data
OI_COUNT=$(curl -s -H "X-API-Key: ${API_KEY}" \
    http://localhost:8080/api/history/oi/BTCUSDT?limit=1 2>/dev/null | grep -c "symbol" || echo "0")
if [ "$OI_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ PASS${NC} - Open interest data (found data)"
    ((PASSED++))
else
    warn_test "Open interest data" "No OI data found yet (may be collecting)"
fi

echo ""
echo -e "${CYAN}[WebSocket Streaming]${NC}"

# 11. WebSocket connectivity check
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

# 12. Database tables exist
TABLE_COUNT=$(docker compose exec -T postgres psql -U chatos -d chatos_trading -tc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | grep -o "[0-9]*" | head -1 || echo "0")

if [ "$TABLE_COUNT" -gt 5 ]; then
    echo -e "${GREEN}✓ PASS${NC} - Database schema ($TABLE_COUNT tables)"
    ((PASSED++))
else
    echo -e "${RED}✗ FAIL${NC} - Database missing tables (found $TABLE_COUNT, expected >5)"
    ((FAILED++))
fi

# 13. Data directory
if [ -d "$INSTALL_DIR/data" ] || docker volume inspect chatos-data-api &>/dev/null; then
    echo -e "${GREEN}✓ PASS${NC} - Data volume mounted"
    ((PASSED++))
else
    warn_test "Data volume" "No persistent data volume found"
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo -e "${CYAN}VALIDATION SUMMARY${NC}"
echo "════════════════════════════════════════════════════════════"
echo -e "${GREEN}Passed:${NC}  $PASSED"
echo -e "${RED}Failed:${NC}  $FAILED"
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
    echo -e "${CYAN}Management Commands:${NC}"
    echo "  cd $INSTALL_DIR/docker"
    echo "  docker compose logs -f                # View logs"
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
    echo "  2. Restart services:"
    echo "     docker compose down && docker compose up -d"
    echo ""
    echo "  3. Re-run validation:"
    echo "     bash $INSTALL_DIR/health-check.sh"
    echo ""
    exit 1
fi
