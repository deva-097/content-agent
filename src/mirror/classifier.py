"""Two-tier URL classification: rule-based first, then LLM fallback."""

from __future__ import annotations

import json
from urllib.parse import urlparse

from src.common.llm import LLMClient, HAIKU
from src.common.logger import get_logger

LOGGER = get_logger(__name__)

CATEGORIES = ("productive", "neutral", "waste")

_LLM_SYSTEM = """\
You classify browsing URLs into categories for a professional building \
thought leadership in AI, SaaS strategy, and management consulting.

Categories:
- productive: professional reading, learning, research, coding, career
- neutral: personal but not wasteful (news, weather, personal finance, communication)
- waste: mindless browsing, entertainment rabbit holes, impulse shopping"""

_LLM_PROMPT = """\
Classify each URL below. Respond as a JSON array of objects with keys "index" and "category".
Category must be one of: productive, neutral, waste.

URLs:
{urls}"""


def classify_entries(
    entries: list[dict],
    config: dict,
    llm: LLMClient | None = None,
    model: str = HAIKU,
) -> dict[str, str]:
    """Classify entries and return a dict of {url: category}.

    Tier 1: Rule-based matching against config domains.
    Tier 2: LLM batch classification for unmatched URLs.
    """
    productive_domains = set(config["mirror"].get("productive_domains", []))
    waste_domains = set(config["mirror"].get("waste_domains", []))

    classifications: dict[str, str] = {}
    unclassified: list[dict] = []

    # Tier 1: Rule-based
    for entry in entries:
        domain = entry.get("domain", urlparse(entry["url"]).netloc)
        category = _rule_classify(domain, productive_domains, waste_domains)
        if category:
            classifications[entry["url"]] = category
        else:
            unclassified.append(entry)

    LOGGER.info(
        "Rule-based: %d classified, %d need LLM",
        len(classifications), len(unclassified),
    )

    # Tier 2: LLM for remaining (deduplicate by domain first)
    if unclassified and llm:
        llm_results = _llm_classify(unclassified, llm, model)
        classifications.update(llm_results)

    return classifications


def _rule_classify(
    domain: str,
    productive: set[str],
    waste: set[str],
) -> str | None:
    """Match domain against known lists. Returns category or None."""
    for d in productive:
        if d in domain:
            return "productive"
    for d in waste:
        if d in domain:
            return "waste"
    return None


def _llm_classify(
    entries: list[dict],
    llm: LLMClient,
    model: str,
    batch_size: int = 50,
) -> dict[str, str]:
    """Batch classify URLs using the LLM."""
    results: dict[str, str] = {}

    # Deduplicate by domain to reduce tokens
    domain_entries: dict[str, list[dict]] = {}
    for entry in entries:
        domain = entry.get("domain", "")
        if domain not in domain_entries:
            domain_entries[domain] = []
        domain_entries[domain].append(entry)

    # Build URL list for classification (one per domain)
    unique_items = []
    for domain, domain_group in domain_entries.items():
        representative = domain_group[0]
        unique_items.append({
            "domain": domain,
            "title": representative.get("title", ""),
            "url": representative["url"],
            "entries": domain_group,
        })

    for i in range(0, len(unique_items), batch_size):
        batch = unique_items[i : i + batch_size]
        urls_text = "\n".join(
            f"{idx + 1}. {item['domain']} — \"{item['title']}\" ({item['url']})"
            for idx, item in enumerate(batch)
        )

        try:
            response = llm.complete(
                _LLM_PROMPT.format(urls=urls_text),
                system=_LLM_SYSTEM,
                model=model,
                max_tokens=1024,
            )

            json_start = response.find("[")
            json_end = response.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                scores = json.loads(response[json_start:json_end])
                for item in scores:
                    idx = item.get("index", 0) - 1
                    category = item.get("category", "neutral")
                    if category not in CATEGORIES:
                        category = "neutral"
                    if 0 <= idx < len(batch):
                        # Apply to all entries with this domain
                        for entry in batch[idx]["entries"]:
                            results[entry["url"]] = category

        except Exception as e:
            LOGGER.warning("LLM classification failed for batch: %s", e)
            # Default unclassified to neutral
            for item in batch:
                for entry in item["entries"]:
                    results[entry["url"]] = "neutral"

    return results
