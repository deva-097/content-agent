"""Browsing pattern analysis and time audit — pure Python, no LLM."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse

from src.mirror.chrome import _get_transition_core


def generate_time_audit(
    entries: list[dict],
    classifications: dict[str, str],
    config: dict | None = None,
) -> dict:
    """Analyze browsing patterns and return a time audit report.

    Returns dict with:
        - time_by_category: {productive: hours, neutral: hours, waste: hours}
        - top_domains: [(domain, hours, category), ...]
        - daily_pattern: {weekday_name: {productive: hours, waste: hours, neutral: hours}}
        - longest_sessions: top 5 single-domain sessions
        - waste_highlights: specific time-wasting entries
        - total_entries: total count
        - total_hours: total browsing hours
    """
    time_by_category: dict[str, float] = defaultdict(float)
    time_by_domain: dict[str, float] = defaultdict(float)
    domain_categories: dict[str, str] = {}
    daily_pattern: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    all_sessions: list[dict] = []
    waste_domain_list = (config or {}).get("mirror", {}).get("waste_domains", [])
    distraction_time: dict[str, float] = defaultdict(float)

    for entry in entries:
        url = entry["url"]
        domain = entry.get("domain", "")
        duration = entry.get("duration_seconds", 0)
        category = classifications.get(url, "neutral")
        visit_time: datetime = entry.get("visit_time")

        # Accumulate time
        hours = duration / 3600
        time_by_category[category] += hours
        time_by_domain[domain] += hours
        domain_categories[domain] = category

        # Track distraction time per waste domain
        for wd in waste_domain_list:
            if wd in domain:
                distraction_time[wd] += hours
                break

        # Daily pattern
        if visit_time:
            day_name = visit_time.strftime("%A")
            daily_pattern[day_name][category] += hours

        # Track sessions for longest-session report
        if duration > 60:  # Only sessions > 1 min
            all_sessions.append({
                "domain": domain,
                "title": entry.get("title", ""),
                "url": url,
                "duration_minutes": round(duration / 60, 1),
                "category": category,
                "visit_time": visit_time,
            })

    # Top domains by time
    top_domains = sorted(
        [
            (domain, hours, domain_categories.get(domain, "neutral"))
            for domain, hours in time_by_domain.items()
        ],
        key=lambda x: x[1],
        reverse=True,
    )[:15]

    # Longest single sessions
    longest_sessions = sorted(
        all_sessions, key=lambda x: x["duration_minutes"], reverse=True
    )[:10]

    # Waste highlights — wasteful entries with significant time
    waste_highlights = [
        s for s in all_sessions
        if s["category"] == "waste" and s["duration_minutes"] > 5
    ]
    waste_highlights.sort(key=lambda x: x["duration_minutes"], reverse=True)
    waste_highlights = waste_highlights[:10]

    # Normalize daily pattern to regular dict
    daily = {}
    for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
        if day in daily_pattern:
            daily[day] = dict(daily_pattern[day])
        else:
            daily[day] = {}

    return {
        "time_by_category": dict(time_by_category),
        "top_domains": top_domains,
        "daily_pattern": daily,
        "longest_sessions": longest_sessions,
        "waste_highlights": waste_highlights,
        "total_entries": len(entries),
        "total_hours": sum(time_by_category.values()),
        "distraction_summary": dict(distraction_time),
    }


def generate_reading_list(entries: list[dict], config: dict) -> list[dict]:
    """Return articles the user actually clicked on and read.

    Filters to link-clicks (transition_core 0) and typed URLs (transition_core 1),
    excluding waste/audit-excluded domains and entries with trivial titles.
    """
    mirror_cfg = config.get("mirror", {})
    excluded = set(
        mirror_cfg.get("exclude_domains", [])
        + mirror_cfg.get("excluded_from_audit", [])
        + mirror_cfg.get("waste_domains", [])
    )

    seen_urls: set[str] = set()
    reading_list: list[dict] = []

    for entry in entries:
        transition_core = _get_transition_core(entry.get("transition_type", 0))
        if transition_core not in (0, 1):
            continue

        url = entry.get("url", "")
        title = entry.get("title", "")
        domain = entry.get("domain", "")

        if not title or len(title) <= 10:
            continue

        # Skip excluded domains
        skip = False
        for pattern in excluded:
            if pattern in domain or pattern in url:
                skip = True
                break
        if skip:
            continue

        if url in seen_urls:
            continue
        seen_urls.add(url)

        reading_list.append({
            "title": title,
            "url": url,
            "domain": domain,
            "visit_time": entry.get("visit_time"),
        })

    reading_list.sort(key=lambda x: x["visit_time"] or 0, reverse=True)
    return reading_list
