#!/bin/bash
# Install content-agent launchd schedules
# Usage: bash launchd/install.sh

set -e

PLIST_DIR="$HOME/Library/LaunchAgents"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Installing content-agent schedules..."

for plist in "$SCRIPT_DIR"/*.plist; do
    name=$(basename "$plist")
    target="$PLIST_DIR/$name"

    # Unload if already loaded
    if launchctl list | grep -q "${name%.plist}" 2>/dev/null; then
        echo "  Unloading existing $name..."
        launchctl unload "$target" 2>/dev/null || true
    fi

    # Symlink and load
    ln -sf "$plist" "$target"
    launchctl load "$target"
    echo "  Loaded $name"
done

echo ""
echo "Schedules installed:"
echo "  Scout (Wed 7 PM)  — com.devashish.content-agent.scout-wed"
echo "  Scout (Sat 9 AM)  — com.devashish.content-agent.scout-sat"
echo "  Mirror (Sat 10 AM) — com.devashish.content-agent.mirror"
echo ""
echo "Verify with: launchctl list | grep content-agent"
