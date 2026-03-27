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


def _ensure_header(path: Path, header: str) -> None:
    """Write header to file if it doesn't exist yet."""
    if not path.exists():
        path.write_text(header, encoding="utf-8")
