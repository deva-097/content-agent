#!/bin/bash
# Install content-agent launchd schedules
# Usage: bash launchd/install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PLIST_DIR="$HOME/Library/LaunchAgents"
TEMPLATE="$SCRIPT_DIR/plist.template"
PREFIX="com.content-agent"

# Schedule definitions: label-suffix command weekday hour logname
SCHEDULES=(
    "scout-wed scout 3 19 scout-wed"
    "scout-sat scout 6 9 scout-sat"
    "mirror mirror 6 10 mirror"
    "tuner tuner 1 11 tuner"
    "weekly-brief weekly-brief 6 11 weekly-brief"
)

echo "Installing content-agent schedules..."
echo "  Project: $PROJECT_DIR"
echo ""

mkdir -p "$PROJECT_DIR/data/logs"

for schedule in "${SCHEDULES[@]}"; do
    read -r suffix command weekday hour logname <<< "$schedule"
    label="${PREFIX}.${suffix}"
    plist_file="$PLIST_DIR/${label}.plist"

    # Unload if already loaded
    if launchctl list 2>/dev/null | grep -q "$label"; then
        echo "  Unloading existing $label..."
        launchctl unload "$plist_file" 2>/dev/null || true
    fi

    # Generate plist from template
    sed -e "s|__LABEL__|${label}|g" \
        -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
        -e "s|__COMMAND__|${command}|g" \
        -e "s|__WEEKDAY__|${weekday}|g" \
        -e "s|__HOUR__|${hour}|g" \
        -e "s|__LOGNAME__|${logname}|g" \
        "$TEMPLATE" > "$plist_file"

    launchctl load "$plist_file"
    echo "  Loaded $label (${command} — weekday ${weekday} at ${hour}:00)"
done

echo ""
echo "Schedules installed:"
echo "  Scout (Wed 7 PM)        — ${PREFIX}.scout-wed"
echo "  Scout (Sat 9 AM)        — ${PREFIX}.scout-sat"
echo "  Mirror (Sat 10 AM)      — ${PREFIX}.mirror"
echo "  Tuner (Mon 11 AM)       — ${PREFIX}.tuner"
echo "  Weekly Brief (Sat 11 AM) — ${PREFIX}.weekly-brief"
echo ""
echo "Verify with: launchctl list | grep content-agent"
