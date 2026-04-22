"""Read and prepare all input sources for the Weekly Brief."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.common.config import get_project_root, load_config
from src.common.logger import get_logger

LOGGER = get_logger(__name__)


def _resolve_path(path_str: str) -> Path:
    p = Path(path_str).expanduser()
    if p.is_absolute():
        return p
    return (get_project_root() / path_str).resolve()


def read_mirror_log(config: dict) -> str:
    """Extract the most recent Mirror run from mirror_log.md."""
    log_path = _resolve_path(config["weekly_brief"]["mirror_log"])
    if not log_path.exists():
        LOGGER.warning("Mirror log not found at %s", log_path)
        return ""

    content = log_path.read_text(encoding="utf-8")
    # Sections are appended newest-last, split by \n##
    parts = content.split("\n## ")
    if len(parts) <= 1:
        return content.strip()

    latest = parts[-1].strip()
    return f"## {latest}"


def read_cos_tasks(config: dict) -> dict[str, Any]:
    """Query CoS SQLite for task state."""
    db_path = _resolve_path(config["weekly_brief"]["cos_db"])
    if not db_path.exists():
        LOGGER.warning("CoS DB not found at %s", db_path)
        return {"active": [], "done_this_week": [], "overdue": []}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    week_ago = (date.today() - timedelta(days=7)).isoformat()
    today = date.today().isoformat()

    cursor.execute("""
        SELECT id, task, bucket, priority, status, scheduled_date, due_date, notes
        FROM tasks
        WHERE status NOT IN ('done', 'dropped') AND bucket != 'park'
        ORDER BY
            CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
            scheduled_date ASC NULLS LAST
    """)
    active = [dict(row) for row in cursor.fetchall()]

    cursor.execute("""
        SELECT id, task, bucket, priority, updated_at
        FROM tasks
        WHERE status = 'done' AND updated_at >= ?
        ORDER BY updated_at DESC
    """, (week_ago,))
    done_this_week = [dict(row) for row in cursor.fetchall()]

    cursor.execute("""
        SELECT id, task, bucket, priority, scheduled_date
        FROM tasks
        WHERE status NOT IN ('done', 'dropped')
          AND scheduled_date < ?
          AND scheduled_date IS NOT NULL
          AND bucket != 'park'
        ORDER BY scheduled_date ASC
    """, (today,))
    overdue = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return {"active": active, "done_this_week": done_this_week, "overdue": overdue}


def read_file(path_str: str) -> str:
    """Read a file and return its contents."""
    p = _resolve_path(path_str)
    if not p.exists():
        LOGGER.warning("File not found: %s", p)
        return ""
    return p.read_text(encoding="utf-8")


def gather_all_sources(config: dict) -> dict[str, Any]:
    """Collect all input sources for the Weekly Brief."""
    wb = config["weekly_brief"]
    return {
        "mirror_log": read_mirror_log(config),
        "cos": read_cos_tasks(config),
        "consulting_context": read_file(wb["consulting_context"]),
        "handoff": read_file(wb["handoff_file"]),
        "ecosystem_playbook": read_file(wb["ecosystem_playbook"]),
        "persona": read_file(wb["persona_file"]),
    }
