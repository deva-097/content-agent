"""CRUD operations for the compass_ideas table."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_idea(
    conn: sqlite3.Connection,
    idea: str,
    format: str | None = None,
    target_date: str | None = None,
    tags: str | None = None,
    notes: str | None = None,
) -> int:
    now = _now_iso()
    cur = conn.execute(
        "INSERT INTO compass_ideas (idea, format, target_date, tags, notes, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (idea, format, target_date, tags, notes, now, now),
    )
    conn.commit()
    return cur.lastrowid


def list_ideas(
    conn: sqlite3.Connection,
    status: str | None = None,
    tag: str | None = None,
) -> list[dict]:
    query = "SELECT * FROM compass_ideas WHERE 1=1"
    params: list[str] = []

    if status:
        query += " AND status = ?"
        params.append(status)
    if tag:
        query += " AND (',' || tags || ',') LIKE ?"
        params.append(f"%,{tag},%")

    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_idea(conn: sqlite3.Connection, idea_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM compass_ideas WHERE id = ?", (idea_id,)
    ).fetchone()
    return dict(row) if row else None


def update_idea(conn: sqlite3.Connection, idea_id: int, **fields) -> None:
    fields["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [idea_id]
    conn.execute(
        f"UPDATE compass_ideas SET {set_clause} WHERE id = ?", values
    )
    conn.commit()


def delete_idea(conn: sqlite3.Connection, idea_id: int) -> None:
    conn.execute("DELETE FROM compass_ideas WHERE id = ?", (idea_id,))
    conn.commit()
