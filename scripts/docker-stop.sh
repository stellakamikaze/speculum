#!/bin/bash
# Stop Speculum Docker containers

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Use docker compose v2 if available
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

echo "Stopping Speculum..."
$COMPOSE_CMD down

echo "Speculum stopped."
