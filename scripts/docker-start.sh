#!/bin/bash
# Quick start script for Speculum Docker

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Create .env from example if not exists
if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

# Use docker compose v2 if available
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

echo "Starting Speculum..."
$COMPOSE_CMD up -d --build

echo ""
echo "Speculum is starting..."
echo "Web UI: http://localhost:5050"
echo ""
echo "To view logs: $COMPOSE_CMD logs -f speculum"
echo "To stop: $COMPOSE_CMD down"
