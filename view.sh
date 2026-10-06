#!/usr/bin/env bash
# Quick launcher to pull latest Garmin data and open the dashboard in browser

set -e
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

echo "🔄 Pulling latest Garmin data from GitHub..."
git pull --quiet || true

if [ -f "$REPO_DIR/docs/index.html" ]; then
    echo "📊 Opening Garmin Weight Dashboard..."
    open "$REPO_DIR/docs/index.html"
else
    echo "Generating dashboard..."
    python3 "$REPO_DIR/scripts/fetch_garmin_data.py"
    open "$REPO_DIR/docs/index.html"
fi
