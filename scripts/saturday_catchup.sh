#!/bin/bash
# Monday catch-up for Saturday agents.
# For each agent (Mirror, Stevens), check if its log contains the most recent
# Saturday's date. If not, run the agent. Idempotent — safe to run any time.

set -u

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"

# Most recent Saturday on or before today (today included if today is Saturday).
LAST_SAT=$(/bin/date -v-sat +%Y-%m-%d)

run_if_missed() {
    local name="$1"
    local log="$2"
    local cli_command="$3"

    if [ ! -f "$log" ]; then
        echo "[$name] log missing ($log) — running."
    elif grep -q "^## $LAST_SAT" "$log"; then
        echo "[$name] $LAST_SAT already in log — skipping."
        return 0
    else
        echo "[$name] $LAST_SAT not in log — running."
    fi

    cd "$PROJECT_DIR" && "$PYTHON" -m cli.main $cli_command
}

run_if_missed "Mirror"  "$PROJECT_DIR/data/mirror_log.md"        "mirror"
run_if_missed "Stevens" "$PROJECT_DIR/data/weekly_brief_log.md"  "weekly-brief"
