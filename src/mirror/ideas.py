"""Generate content ideas from productive browsing patterns."""

from __future__ import annotations

import json

from src.common.llm import LLMClient, HAIKU
from src.common.logger import get_logger

LOGGER = get_logger(__name__)

_SYSTEM = """\
You help a professional in AI, SaaS strategy, and management consulting \
generate content ideas from their recent reading patterns."""

_PROMPT = """\
Based on this person's recent productive browsing, suggest 3-5 content ideas \
they could write about. Each idea should include:
- A working title
- The angle or hook (1 sentence)
- Which readings inspired it

Respond as a JSON array with keys: "title", "angle", "inspired_by"

Recent productive reading:
{reading_list}"""


def generate_ideas(
    entries: list[dict],
    classifications: dict[str, str],
    llm: LLMClient,
    model: str = HAIKU,
) -> list[dict]:
    """Extract content ideas from productive browsing history."""
    productive = [
        e for e in entries
        if classifications.get(e["url"]) == "productive"
        and e.get("title")
    ]

    if not productive:
        LOGGER.info("No productive entries to generate ideas from")
        return []

    # Deduplicate by title, keep most recent
    seen_titles = set()
    unique = []
    for entry in productive:
        title = entry["title"].strip()
        if title and title not in seen_titles:
            seen_titles.add(title)
            unique.append(entry)

    # Build reading list (cap to avoid token explosion)
    reading_lines = []
    for entry in unique[:30]:
        reading_lines.append(
            f"- \"{entry['title']}\" ({entry.get('domain', '')})"
        )
    reading_list = "\n".join(reading_lines)

    try:
        response = llm.complete(
            _PROMPT.format(reading_list=reading_list),
            system=_SYSTEM,
            model=model,
            max_tokens=1024,
        )

        json_start = response.find("[")
        json_end = response.rfind("]") + 1
        if json_start >= 0 and json_end > json_start:
            ideas = json.loads(response[json_start:json_end])
            LOGGER.info("Generated %d content ideas from browsing history", len(ideas))
            return ideas

    except Exception as e:
        LOGGER.warning("Failed to generate ideas: %s", e)

    return []
