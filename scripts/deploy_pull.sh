#!/usr/bin/env bash
# Pull-based auto-deploy. Run by the trading-deploy.timer every couple of
# minutes on the VPS. No inbound SSH required — the server pulls from GitHub.
#
# - Only acts when origin/main is ahead of HEAD.
# - Reinstalls Python deps only if requirements.txt changed.
# - Rebuilds the frontend only if anything under frontend/ changed.
# - Restarts the API service after a successful update.
set -euo pipefail

REPO="/opt/trading"
BRANCH="main"
SERVICE="trading"

cd "$REPO"

git fetch origin "$BRANCH" --quiet
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0   # already up to date — nothing to do
fi

echo "$(date '+%F %T') deploy: $LOCAL -> $REMOTE"

CHANGED="$(git diff --name-only "$LOCAL" "$REMOTE")"

git pull --ff-only origin "$BRANCH"

if echo "$CHANGED" | grep -q '^requirements.txt'; then
    echo "  requirements.txt changed -> pip install"
    .venv/bin/pip install -r requirements.txt -q
fi

if echo "$CHANGED" | grep -q '^frontend/'; then
    echo "  frontend changed -> npm build"
    cd frontend
    npm install --silent
    npm run build
    cd "$REPO"
fi

systemctl restart "$SERVICE"
echo "$(date '+%F %T') deploy complete -> $REMOTE"
