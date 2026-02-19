"""Broad web search for configured topics via DuckDuckGo."""

from __future__ import annotations

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

from src.common.logger import get_logger

LOGGER = get_logger(__name__)


def search_topics(
    topics: list[str], max_results_per_topic: int = 5
) -> list[dict]:
    """Search DuckDuckGo for each topic and return combined results."""
    all_results = []

    with DDGS() as ddgs:
        for topic in topics:
            LOGGER.info("Searching for: %s", topic)
            try:
                results = list(ddgs.text(topic, max_results=max_results_per_topic))
                for r in results:
                    all_results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "published": None,
                        "summary": r.get("body", ""),
                        "source_type": "web_search",
                        "source_label": f"Search: {topic}",
                    })
                LOGGER.info("Got %d results for '%s'", len(results), topic)
            except Exception as e:
                LOGGER.warning("Search failed for '%s': %s", topic, e)

    return all_results
