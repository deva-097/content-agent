"""Read Chrome browsing history from the local SQLite database."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from src.common.logger import get_logger

LOGGER = get_logger(__name__)

# Chrome stores timestamps as microseconds since 1601-01-01 00:00:00 UTC
_CHROME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


def chrome_time_to_datetime(chrome_time: int) -> datetime:
    """Convert Chrome's WebKit timestamp to Python datetime."""
    if chrome_time <= 0:
        return _CHROME_EPOCH
    return _CHROME_EPOCH + timedelta(microseconds=chrome_time)


def datetime_to_chrome_time(dt: datetime) -> int:
    """Convert Python datetime to Chrome's WebKit timestamp."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int((dt - _CHROME_EPOCH).total_seconds() * 1_000_000)


def read_history(
    since: datetime | None,
    config: dict,
) -> list[dict]:
    """Copy Chrome History DB to temp location, query, return results.

    Chrome locks its DB while running, so we copy it first.
    """
    source = Path(config["mirror"]["chrome_history_path"]).expanduser()
    if not source.exists():
        LOGGER.error("Chrome History DB not found at %s", source)
        return []

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
    tmp_file = Path(tmp_path)

    try:
        shutil.copy2(source, tmp_file)
        LOGGER.info("Copied Chrome History DB to %s", tmp_file)

        conn = sqlite3.connect(f"file:{tmp_file}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        if since:
            chrome_since = datetime_to_chrome_time(since)
        else:
            # Default: last 14 days if no prior run
            fallback = datetime.now(timezone.utc) - timedelta(days=14)
            chrome_since = datetime_to_chrome_time(fallback)

        query = """
            SELECT
                u.url,
                u.title,
                u.visit_count,
                v.visit_time,
                v.visit_duration,
                v.transition
            FROM urls u
            JOIN visits v ON u.id = v.url
            WHERE v.visit_time > ?
            ORDER BY v.visit_time DESC
        """
        rows = conn.execute(query, (chrome_since,)).fetchall()
        conn.close()

        # Filter out excluded domains and audit-excluded domains
        exclude = set(config["mirror"].get("exclude_domains", []))
        exclude_audit = set(config["mirror"].get("excluded_from_audit", []))
        all_exclude = exclude | exclude_audit
        results = []
        for row in rows:
            url = row["url"]
            if _should_exclude(url, all_exclude):
                continue

            visit_time = chrome_time_to_datetime(row["visit_time"])
            # visit_duration is in microseconds; cap at 30 min
            duration_secs = min(
                (row["visit_duration"] or 0) / 1_000_000,
                1800,
            )

            results.append({
                "url": url,
                "title": row["title"] or "",
                "visit_count": row["visit_count"],
                "visit_time": visit_time,
                "duration_seconds": duration_secs,
                "domain": urlparse(url).netloc,
                "transition_type": row["transition"] or 0,
            })

        results = _deduplicate_rapid_visits(results)

        LOGGER.info(
            "Read %d history entries (filtered from %d raw rows)",
            len(results), len(rows),
        )
        return results

    except Exception as e:
        LOGGER.error("Failed to read Chrome history: %s", e)
        return []
    finally:
        tmp_file.unlink(missing_ok=True)


def _deduplicate_rapid_visits(
    results: list[dict],
    window_seconds: int = 300,
) -> list[dict]:
    """Merge visits to the same URL that happen within *window_seconds*.

    Tab-switching causes Chrome to log a new visit every time a tab regains
    focus.  This collapses those into a single visit: earliest timestamp,
    summed duration (already capped upstream), highest visit_count.
    """
    from collections import defaultdict

    # Group by URL
    by_url: dict[str, list[dict]] = defaultdict(list)
    for entry in results:
        by_url[entry["url"]].append(entry)

    merged: list[dict] = []
    for url, visits in by_url.items():
        # Sort by visit_time ascending
        visits.sort(key=lambda v: v["visit_time"])

        cluster = [visits[0]]
        for visit in visits[1:]:
            gap = (visit["visit_time"] - cluster[-1]["visit_time"]).total_seconds()
            if gap <= window_seconds:
                cluster.append(visit)
            else:
                merged.append(_merge_cluster(cluster))
                cluster = [visit]
        merged.append(_merge_cluster(cluster))

    # Restore original descending order
    merged.sort(key=lambda v: v["visit_time"], reverse=True)
    return merged


def _merge_cluster(cluster: list[dict]) -> dict:
    """Merge a cluster of rapid re-visits into a single entry."""
    base = dict(cluster[0])
    base["duration_seconds"] = sum(v["duration_seconds"] for v in cluster)
    base["visit_count"] = max(v["visit_count"] for v in cluster)
    return base


def _get_transition_core(transition_type: int) -> int:
    """Return the core transition type (lower 8 bits), stripping qualifier flags."""
    return transition_type & 0xFF


def _should_exclude(url: str, exclude_domains: set[str]) -> bool:
    """Check if a URL should be excluded based on domain rules."""
    for pattern in exclude_domains:
        if pattern.endswith("://"):
            # Scheme-based exclusion (e.g. "chrome://")
            if url.startswith(pattern):
                return True
        elif pattern in url:
            return True
    return False
