"""Append agent run outputs to persistent markdown log files."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .config import get_project_root


def _log_path(filename: str) -> Path:
    return get_project_root() / "data" / filename


def append_scout_run(picked: list[dict], cost: float) -> None:
    """Append a Scout run's picked articles to data/scout_log.md."""
    if not picked:
        return

    lines = [f"\n## {date.today()}\n"]
    for i, item in enumerate(picked, 1):
        title = item.get("title", "Untitled")
        url = item.get("url", "")
        source = item.get("source_label", "")
        why = item.get("why_read", "").strip()

        lines.append(f"{i}. **{title}**")
        if source:
            lines.append(f"   *{source}*")
        lines.append(f"   {url}")
        if why:
            lines.append(f"   > {why}")
        lines.append("")

    lines.append(f"*Cost: ${cost:.4f}*\n")

    log_file = _log_path("scout_log.md")
    _ensure_header(log_file, "# Scout Log\n\nAll picked articles, most recent first.\n")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))


def append_mirror_run(
    audit: dict,
    reading_list: list[dict],
    week_summary: str,
    cost: float,
) -> None:
    """Append a Mirror run's report to data/mirror_log.md."""
    lines = [f"\n## {date.today()}\n"]

    # Distractions
    distractions = audit.get("distraction_summary", {})
    if distractions:
        distraction_str = " · ".join(
            f"{d}: {h:.1f}h" for d, h in distractions.items()
        )
        lines.append(f"**Distractions:** {distraction_str}\n")

    # Week summary
    if week_summary:
        lines.append("**Week in Review:**")
        lines.append(week_summary)
        lines.append("")

    # Reading list
    if reading_list:
        lines.append(f"**Reading List ({len(reading_list)} articles):**")
        for item in reading_list:
            title = item.get("title", "")
            url = item.get("url", "")
            domain = item.get("domain", "")
            lines.append(f"- [{title}]({url}) ({domain})")
        lines.append("")

    lines.append(f"*{audit.get('total_entries', 0)} entries · Cost: ${cost:.4f}*\n")

    log_file = _log_path("mirror_log.md")
    _ensure_header(log_file, "# Mirror Log\n\nAll browsing reports, most recent first.\n")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))


def append_tuner_run(
    all_items: list[dict],
    cost: float,
) -> None:
    """Append a Tuner run's highlights to data/tuner_log.md."""
    if not all_items:
        return

    lines = [f"\n## {date.today()}\n"]

    # Must-reads first
    must_reads = [item for item in all_items if item.get("must_read")]
    if must_reads:
        lines.append("**Must read/listen:**")
        for item in must_reads:
            kind = item.get("kind", "podcast")
            icon = "🎙" if kind == "podcast" else "📝"
            title = item.get("title", "Untitled")
            source = item.get("source_label", "?")
            reason = item.get("must_read_reason", "")
            lines.append(f"- {icon} **{title}** ({source})")
            if reason:
                lines.append(f"  → {reason}")
        lines.append("")

    # Counts
    deep_count = len([i for i in all_items if i.get("deep")])
    podcast_count = len([i for i in all_items if i.get("kind") == "podcast"])
    newsletter_count = len([i for i in all_items if i.get("kind") == "newsletter"])
    lines.append(
        f"*{len(all_items)} items ({podcast_count} podcasts, {newsletter_count} newsletters)"
        f"{f', {deep_count} deep digests' if deep_count else ''}"
        f" · Cost: ${cost:.4f}*\n"
    )

    log_file = _log_path("tuner_log.md")
    _ensure_header(log_file, "# Tuner Log\n\nWeekly digest highlights, most recent first.\n")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))


def append_weekly_brief_run(sections: dict, cost: float) -> None:
    """Append a Weekly Brief run to data/weekly_brief_log.md."""
    lines = [f"\n## {date.today()}\n"]

    labels = {
        "time_audit": "Time Audit",
        "task_accountability": "Task Accountability",
        "consulting_pulse": "Consulting Pulse",
        "week_in_the_machine": "Week in the Machine",
        "upgrade_suggestion": "One Upgrade",
        "honest_call": "The Honest Call",
    }

    for key, label in labels.items():
        text = sections.get(key, "").strip()
        if text:
            lines.append(f"**{label}:** {text}\n")

    lines.append(f"*Cost: ${cost:.4f}*\n")

    log_file = _log_path("weekly_brief_log.md")
    _ensure_header(log_file, "# Weekly Brief Log\n\nAll weekly briefs, most recent last.\n")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _ensure_header(path: Path, header: str) -> None:
    """Write header to file if it doesn't exist yet."""
    if not path.exists():
        path.write_text(header, encoding="utf-8")
