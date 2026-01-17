#!/bin/bash
# ChatOS Server Deployment Script
# Run this on your Linux server

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "  ChatOS Server Setup"
echo "=========================================="

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker $USER
    echo "Please log out and back in, then re-run this script."
    exit 0
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "Installing Docker Compose..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
fi

# Create .env if not exists
if [ ! -f .env ]; then
    echo "Creating .env file..."
    cat > .env << EOF
POSTGRES_PASSWORD=$(openssl rand -hex 16)
API_KEY=$(openssl rand -hex 32)
EOF
    echo "Generated secure credentials in .env"
    echo "IMPORTANT: Save these values!"
    cat .env
fi

# Build and start
echo ""
echo "Building containers..."
cd docker
docker compose build

echo ""
echo "Starting services..."
docker compose up -d

echo ""
echo "Waiting for services to be healthy..."
sleep 10

docker compose ps

echo ""
echo "=========================================="
echo "  ChatOS Server is now running!"
echo "=========================================="
echo ""
echo "Services:"
echo "  - PostgreSQL: localhost:5432"
echo "  - Redis:      localhost:6379"
echo "  - Data API:   localhost:8080"
echo ""
echo "To check logs:"
echo "  docker compose logs -f"
echo ""
echo "To stop:"
echo "  docker compose down"
echo ""
echo "API Key (save this for your Mac client):"
grep API_KEY ../.env | cut -d= -f2
