#!/bin/bash
# =============================================================================
# ChatOS Server - One-Command Auto Setup
# Run: curl -sSL https://raw.githubusercontent.com/KofiRusu/srvr-stp/main/setup.sh | bash
# =============================================================================

set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║           ChatOS Server - Auto Setup                     ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

INSTALL_DIR="${CHATOS_DIR:-$HOME/chatos-server}"

# 1. Check/Install Docker
echo -e "${YELLOW}[1/6] Checking Docker...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${CYAN}Installing Docker...${NC}"
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker $USER
    echo -e "${YELLOW}Docker installed. Please log out and back in, then re-run this script.${NC}"
    exit 0
fi
echo -e "${GREEN}✓ Docker found${NC}"

# 2. Check/Install Docker Compose
echo -e "${YELLOW}[2/6] Checking Docker Compose...${NC}"
if ! docker compose version &> /dev/null 2>&1; then
    echo -e "${CYAN}Installing Docker Compose plugin...${NC}"
    sudo apt-get update -qq && sudo apt-get install -y -qq docker-compose-plugin
fi
echo -e "${GREEN}✓ Docker Compose found${NC}"

# 3. Clone/Update Repository
echo -e "${YELLOW}[3/6] Setting up ChatOS Server...${NC}"
if [ -d "$INSTALL_DIR" ]; then
    echo -e "${CYAN}Updating existing installation...${NC}"
    cd "$INSTALL_DIR"
    git pull --quiet
else
    echo -e "${CYAN}Cloning repository...${NC}"
    git clone --quiet https://github.com/KofiRusu/srvr-stp.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi
echo -e "${GREEN}✓ Repository ready at $INSTALL_DIR${NC}"

# 4. Generate credentials
echo -e "${YELLOW}[4/6] Configuring credentials...${NC}"
if [ ! -f .env ]; then
    POSTGRES_PASSWORD=$(openssl rand -hex 16)
    API_KEY=$(openssl rand -hex 32)
    cat > .env << EOF
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
API_KEY=$API_KEY
EOF
    echo -e "${GREEN}✓ Generated secure credentials${NC}"
else
    echo -e "${GREEN}✓ Using existing credentials${NC}"
fi

# 5. Build containers
echo -e "${YELLOW}[5/6] Building Docker containers...${NC}"
cd docker
docker compose build --quiet
echo -e "${GREEN}✓ Containers built${NC}"

# 6. Start services
echo -e "${YELLOW}[6/6] Starting services...${NC}"
docker compose up -d
echo -e "${GREEN}✓ Services started${NC}"

# Wait for health
echo -e "${CYAN}Waiting for services to be healthy...${NC}"
sleep 10

# Run health check
cd "$INSTALL_DIR"
chmod +x health-check.sh
echo ""
echo -e "${CYAN}Running system validation...${NC}"
bash health-check.sh || echo -e "${YELLOW}Note: Data collection may take a few minutes${NC}"

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         ChatOS Server is now running!                    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}Services:${NC}"
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || docker compose ps
echo ""
echo -e "${CYAN}Endpoints:${NC}"
echo -e "  Data API:   http://localhost:8080"
echo -e "  PostgreSQL: localhost:5432"
echo -e "  Redis:      localhost:6379"
echo ""
echo -e "${CYAN}Your API Key (save this for your Mac):${NC}"
echo -e "  ${YELLOW}$(grep API_KEY "$INSTALL_DIR/.env" | cut -d= -f2)${NC}"
echo ""
echo -e "${CYAN}Commands:${NC}"
echo -e "  Health check:   bash $INSTALL_DIR/health-check.sh"
echo -e "  View logs:      cd $INSTALL_DIR/docker && docker compose logs -f"
echo -e "  Stop services:  cd $INSTALL_DIR/docker && docker compose down"
echo ""
