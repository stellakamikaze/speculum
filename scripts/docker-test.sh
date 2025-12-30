#!/bin/bash
# Speculum Docker Testing Script
# Testa il build e l'avvio del container Docker

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN} Speculum Docker Testing${NC}"
echo -e "${GREEN}======================================${NC}"

cd "$PROJECT_DIR"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running${NC}"
    exit 1
fi

# Check if docker-compose exists
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${RED}Error: docker-compose is not installed${NC}"
    exit 1
fi

# Use docker compose (v2) if available, otherwise docker-compose
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

echo -e "\n${YELLOW}Step 1: Cleaning up previous containers...${NC}"
$COMPOSE_CMD down --remove-orphans 2>/dev/null || true

echo -e "\n${YELLOW}Step 2: Building Docker image...${NC}"
$COMPOSE_CMD build --no-cache speculum

echo -e "\n${YELLOW}Step 3: Starting containers...${NC}"
$COMPOSE_CMD up -d

echo -e "\n${YELLOW}Step 4: Waiting for services to start...${NC}"
sleep 10

# Check container health
echo -e "\n${YELLOW}Step 5: Checking container status...${NC}"
if docker ps | grep -q "speculum"; then
    echo -e "${GREEN}✓ Speculum container is running${NC}"
else
    echo -e "${RED}✗ Speculum container failed to start${NC}"
    echo -e "${YELLOW}Logs:${NC}"
    $COMPOSE_CMD logs speculum
    exit 1
fi

# Test HTTP endpoint
echo -e "\n${YELLOW}Step 6: Testing HTTP endpoint...${NC}"
MAX_RETRIES=12
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:5050/ | grep -q "200"; then
        echo -e "${GREEN}✓ Web server is responding (HTTP 200)${NC}"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo -e "${YELLOW}  Waiting for web server... (attempt $RETRY_COUNT/$MAX_RETRIES)${NC}"
    sleep 5
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo -e "${RED}✗ Web server is not responding${NC}"
    echo -e "${YELLOW}Container logs:${NC}"
    $COMPOSE_CMD logs speculum
    exit 1
fi

# Test API endpoint
echo -e "\n${YELLOW}Step 7: Testing API endpoint...${NC}"
API_RESPONSE=$(curl -s http://localhost:5050/api/stats)
if echo "$API_RESPONSE" | grep -q "total_sites"; then
    echo -e "${GREEN}✓ API endpoint is working${NC}"
    echo -e "  Response: $API_RESPONSE"
else
    echo -e "${RED}✗ API endpoint failed${NC}"
fi

# Show container logs
echo -e "\n${YELLOW}Container logs (last 20 lines):${NC}"
$COMPOSE_CMD logs --tail=20 speculum

echo -e "\n${GREEN}======================================${NC}"
echo -e "${GREEN} Testing Complete!${NC}"
echo -e "${GREEN}======================================${NC}"
echo -e "\nAccess Speculum at: ${YELLOW}http://localhost:5050${NC}"
echo -e "Default login: ${YELLOW}admin / admin123${NC}"
echo -e "\nTo stop: ${YELLOW}$COMPOSE_CMD down${NC}"
echo -e "To view logs: ${YELLOW}$COMPOSE_CMD logs -f speculum${NC}"
