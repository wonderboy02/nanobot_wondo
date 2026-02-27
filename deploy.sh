#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# --- Detect docker compose command (V2 plugin or V1 standalone) ---
if docker compose version &>/dev/null; then
    DC="docker compose"
elif command -v docker-compose &>/dev/null; then
    echo "WARNING: docker-compose V1 detected. V1 is incompatible with Docker Engine 25+."
    echo "==> Attempting to install Docker Compose V2 plugin..."
    mkdir -p ~/.docker/cli-plugins
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)  ARCH="x86_64" ;;
        aarch64) ARCH="aarch64" ;;
        armv7l)  ARCH="armv7" ;;
        *)       echo "ERROR: Unsupported architecture: $ARCH"; exit 1 ;;
    esac
    COMPOSE_URL="https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${ARCH}"
    if curl -fsSL "$COMPOSE_URL" -o ~/.docker/cli-plugins/docker-compose; then
        chmod +x ~/.docker/cli-plugins/docker-compose
        echo "==> Docker Compose V2 installed successfully."
        DC="docker compose"
    else
        echo "ERROR: Failed to install Docker Compose V2."
        echo "  Install manually: https://docs.docker.com/compose/install/linux/"
        echo "  Or upgrade docker-compose V1: pip install docker-compose --upgrade"
        exit 1
    fi
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
    sed -e 's|~/.nanobot/workspace|/app/workspace|g' \
        -e 's|~/.nanobot/google|/app/data/google|g' \
        config.example.json > data/config.json.tmp
    mv data/config.json.tmp data/config.json

    # Create google credentials directory
    mkdir -p data/google

    echo ""
    echo "============================================"
    echo "  Setup complete!"
    echo "  Edit data/config.json with your API keys,"
    echo "  then run ./deploy.sh again to start."
    echo ""
    echo "  Google Calendar (optional):"
    echo "    1. Put client_secret.json in data/google/"
    echo "    2. Run locally to get token.json first"
    echo "       (Docker can't open a browser for OAuth)"
    echo "    3. Copy token.json to data/google/"
    echo "    4. Set google.calendar.enabled=true in config"
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

# ─── Migration: workspace .md → nanobot/prompts/ (one-time) ───
PROMPTS_MIGRATED_MARKER="workspace/.prompts_migrated"
if [ ! -f "$PROMPTS_MIGRATED_MARKER" ]; then
    echo "📦 Migrating: workspace instruction files now in nanobot/prompts/"
    rm -f workspace/AGENTS.md workspace/SOUL.md workspace/USER.md \
          workspace/TOOLS.md workspace/DASHBOARD.md workspace/WORKER.md \
          workspace/NOTION_SETUP.md
    # HEARTBEAT.md 유지 — 런타임 데이터
    mkdir -p workspace
    touch "$PROMPTS_MIGRATED_MARKER"
    echo "✅ Migration complete"
fi

echo "==> Building and starting container..."
$DC up --build --force-recreate -d

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
