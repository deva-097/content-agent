"""Filter and pick Scout entries — no relevance scoring, random selection."""

from __future__ import annotations

import json
import random
import re

from src.common.llm import LLMClient, HAIKU
from src.common.logger import get_logger

LOGGER = get_logger(__name__)

_PAYWALL_DOMAINS = {
    "nytimes.com", "theatlantic.com", "ft.com", "economist.com",
    "newyorker.com", "wsj.com", "bloomberg.com", "washingtonpost.com",
    "thetimes.co.uk",
}

_LISTICLE_RE = re.compile(
    r"^(\d+\s+(best|ways|things|tips|reasons|ideas|steps|tricks)|(top|best)\s+\d+)",
    re.IGNORECASE,
)

_POLITICS_SYSTEM = "You are a content filter. Respond only with valid JSON."

_POLITICS_PROMPT = """\
Below is a list of articles. Return a JSON object with key "exclude" whose value is a list \
of 0-based indices for articles that are PRIMARILY about US electoral politics, political parties, \
or current geopolitical events (wars, elections, sanctions).

Do NOT exclude articles about political philosophy, political theory, or historical politics.

Articles:
{articles}

Respond only with: {{"exclude": [list of integer indices]}}"""

_WHY_SYSTEM = "You are a concise editorial guide for a curious, intellectually broad reader."

_WHY_PROMPT = """\
For each article below, write one sentence explaining why a curious, intellectually broad reader \
would want to read it. Focus on what makes it interesting or surprising, not just its topic.

Articles:
{articles}

Respond as a JSON array: [{{"index": 0, "why": "..."}}, ...]"""


def _is_paywalled(url: str) -> bool:
    return any(domain in url for domain in _PAYWALL_DOMAINS)


def _is_listicle(title: str) -> bool:
    return bool(_LISTICLE_RE.match(title.strip()))


def filter_and_pick(
    llm: LLMClient,
    entries: list[dict],
    model: str = HAIKU,
    count: int = 5,
) -> list[dict]:
    """Filter entries and return up to `count` with a why_read field."""
    if not entries:
        return []

    # Stage 1 — Python filters (no LLM)
    filtered = []
    for e in entries:
        if _is_paywalled(e.get("url", "")):
            LOGGER.debug("Paywall skip: %s", e.get("url"))
            continue
        if _is_listicle(e.get("title", "")):
            LOGGER.debug("Listicle skip: %s", e.get("title"))
            continue
        filtered.append(e)

    LOGGER.info("After Python filters: %d entries (from %d)", len(filtered), len(entries))

    if not filtered:
        return []

    # Stage 2 — LLM politics filter (one batch call)
    articles_text = "\n".join(
        f"{i}. \"{e['title']}\" — {(e.get('summary') or '')[:200]}"
        for i, e in enumerate(filtered)
    )
    try:
        response = llm.complete(
            _POLITICS_PROMPT.format(articles=articles_text),
            system=_POLITICS_SYSTEM,
            model=model,
            max_tokens=512,
        )
        j_start = response.find("{")
        j_end = response.rfind("}") + 1
        if j_start >= 0 and j_end > j_start:
            exclude_indices = set(json.loads(response[j_start:j_end]).get("exclude", []))
        else:
            exclude_indices = set()
    except Exception as e:
        LOGGER.warning("Politics filter failed, skipping: %s", e)
        exclude_indices = set()

    filtered = [e for i, e in enumerate(filtered) if i not in exclude_indices]
    LOGGER.info("After politics filter: %d entries", len(filtered))

    if not filtered:
        return []

    # Stage 3 — Random sample
    picked = random.sample(filtered, min(count, len(filtered)))

    # Stage 4 — "Why read this" (one batch call for all picked)
    articles_text = "\n".join(
        f"{i}. \"{e['title']}\" — {(e.get('summary') or '')[:200]}"
        for i, e in enumerate(picked)
    )
    try:
        response = llm.complete(
            _WHY_PROMPT.format(articles=articles_text),
            system=_WHY_SYSTEM,
            model=model,
            max_tokens=512,
        )
        j_start = response.find("[")
        j_end = response.rfind("]") + 1
        if j_start >= 0 and j_end > j_start:
            why_list = json.loads(response[j_start:j_end])
            for item in why_list:
                idx = item.get("index")
                if idx is not None and 0 <= idx < len(picked):
                    picked[idx] = {**picked[idx], "why_read": item.get("why", "")}
    except Exception as e:
        LOGGER.warning("Why-read generation failed: %s", e)

    # Ensure every picked entry has a why_read field
    for i, e in enumerate(picked):
        if "why_read" not in e:
            picked[i] = {**e, "why_read": ""}

    return picked
