"""SQLite state management for content-agent."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import get_project_root
from .logger import get_logger

LOGGER = get_logger(__name__)
_DEFAULT_DB = get_project_root() / "data" / "state.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    run_start TEXT NOT NULL,
    run_end TEXT,
    status TEXT DEFAULT 'running',
    summary TEXT
);

CREATE TABLE IF NOT EXISTS processed_urls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    category TEXT,
    title TEXT,
    summary TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_processed_url
    ON processed_urls(url, agent_name);

CREATE TABLE IF NOT EXISTS content_ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_agent TEXT NOT NULL,
    idea TEXT NOT NULL,
    context TEXT,
    created_at TEXT NOT NULL,
    used INTEGER DEFAULT 0
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateDB:
    """Thin wrapper around SQLite for agent state tracking."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- Agent runs ---

    def record_run_start(self, agent_name: str) -> int:
        """Record a new agent run and return the run ID."""
        cur = self._conn.execute(
            "INSERT INTO agent_runs (agent_name, run_start) VALUES (?, ?)",
            (agent_name, _now_iso()),
        )
        self._conn.commit()
        return cur.lastrowid

    def record_run_end(
        self, run_id: int, status: str, summary: dict | None = None
    ) -> None:
        """Finalize a run with status and optional summary."""
        self._conn.execute(
            "UPDATE agent_runs SET run_end = ?, status = ?, summary = ? WHERE id = ?",
            (_now_iso(), status, json.dumps(summary) if summary else None, run_id),
        )
        self._conn.commit()

    def get_last_run_time(self, agent_name: str) -> datetime | None:
        """Return the start time of the last successful run, or None."""
        row = self._conn.execute(
            "SELECT run_start FROM agent_runs "
            "WHERE agent_name = ? AND status = 'completed' "
            "ORDER BY run_start DESC LIMIT 1",
            (agent_name,),
        ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row["run_start"])

    def get_all_run_stats(self) -> list[dict]:
        """Return last run info for each agent."""
        rows = self._conn.execute(
            "SELECT agent_name, run_start, run_end, status, summary "
            "FROM agent_runs ORDER BY run_start DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Processed URLs ---

    def is_url_processed(self, url: str, agent_name: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM processed_urls WHERE url = ? AND agent_name = ?",
            (url, agent_name),
        ).fetchone()
        return row is not None

    def mark_url_processed(
        self,
        url: str,
        agent_name: str,
        category: str | None = None,
        title: str | None = None,
        summary: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO processed_urls "
            "(url, agent_name, processed_at, category, title, summary) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (url, agent_name, _now_iso(), category, title, summary),
        )
        self._conn.commit()

    # --- Content ideas ---

    def save_content_idea(
        self, source_agent: str, idea: str, context: str | None = None
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO content_ideas (source_agent, idea, context, created_at) "
            "VALUES (?, ?, ?, ?)",
            (source_agent, idea, context, _now_iso()),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_unused_ideas(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, source_agent, idea, context, created_at "
            "FROM content_ideas WHERE used = 0 ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_idea_used(self, idea_id: int) -> None:
        self._conn.execute(
            "UPDATE content_ideas SET used = 1 WHERE id = ?", (idea_id,)
        )
        self._conn.commit()

    # --- Cost tracking ---

    def get_monthly_token_usage(self) -> list[dict]:
        """Return run summaries for the current month (for cost estimation)."""
        month_start = datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        rows = self._conn.execute(
            "SELECT agent_name, summary FROM agent_runs "
            "WHERE run_start >= ? AND status = 'completed' AND summary IS NOT NULL",
            (month_start,),
        ).fetchall()
        results = []
        for row in rows:
            data = json.loads(row["summary"]) if row["summary"] else {}
            data["agent_name"] = row["agent_name"]
            results.append(data)
        return results
