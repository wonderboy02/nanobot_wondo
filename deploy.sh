#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# --- Detect docker compose command (V2 plugin or V1 standalone) ---
if docker compose version &>/dev/null; then
    DC="docker compose"
elif command -v docker-compose &>/dev/null; then
    DC="docker-compose"
else
    echo "ERROR: Neither 'docker compose' nor 'docker-compose' found."
    exit 1
fi

# --- First run: bootstrap data directory ---
if [ ! -d "data" ]; then
    echo "==> First run detected. Creating data/ directory..."
    mkdir -p data

    if [ ! -f "config.example.json" ]; then
        echo "ERROR: config.example.json not found. Is this the repo root?"
        exit 1
    fi

    echo "==> Copying config.example.json -> data/config.json"
    # Write to temp file first — if sed fails, we don't leave an empty config.
    sed 's|~/.nanobot/workspace|/app/workspace|g' config.example.json > data/config.json.tmp
    mv data/config.json.tmp data/config.json

    echo ""
    echo "============================================"
    echo "  Setup complete!"
    echo "  Edit data/config.json with your API keys,"
    echo "  then run ./deploy.sh again to start."
    echo "============================================"
    exit 0
fi

# --- Subsequent runs: pull & deploy ---
echo "==> Pulling latest code..."
if ! git pull --ff-only; then
    echo "ERROR: git pull --ff-only failed. Resolve manually:"
    echo "  git fetch origin && git reset --hard origin/main"
    exit 1
fi

echo "==> Building and starting container..."
$DC up --build -d

echo "==> Verifying container health..."
sleep 3
if $DC ps | grep -q "Up"; then
    echo "==> Deploy successful."
    $DC ps
else
    echo "ERROR: Container is not running."
    $DC logs --tail=30
    exit 1
fi
