"""LLM-based summarization and relevance scoring for Scout entries."""

from __future__ import annotations

import json

from src.common.llm import LLMClient, HAIKU
from src.common.logger import get_logger
from src.common.scraper import fetch_url

LOGGER = get_logger(__name__)

_SYSTEM_PROMPT = """\
You are a content research assistant for a professional building thought leadership \
in AI, SaaS strategy, and management consulting.

Your job is to evaluate articles for relevance and provide concise summaries."""

_BATCH_PROMPT_TEMPLATE = """\
Evaluate the following articles. For each one, provide:
1. A 2-3 sentence summary
2. A relevance score from 1-5 (5 = highly relevant for AI/strategy/consulting thought leadership)
3. A brief note on why it matters (1 sentence)

If the article text is empty or unintelligible, score it 1.

Respond as a JSON array with objects having keys: "index", "summary", "score", "why_it_matters"

Articles:
{articles}"""


def _prepare_article_text(entry: dict) -> str:
    """Get article text — use RSS summary if available, otherwise fetch."""
    if entry.get("summary") and len(entry["summary"]) > 200:
        return entry["summary"][:3000]

    # Try fetching the full article
    if entry.get("url"):
        content = fetch_url(entry["url"])
        if content:
            return content[:3000]  # Cap at ~3000 chars to limit tokens

    return entry.get("summary", "") or entry.get("title", "")


def summarize_and_score(
    llm: LLMClient,
    entries: list[dict],
    model: str = HAIKU,
    min_score: int = 3,
    batch_size: int = 10,
) -> list[dict]:
    """Summarize entries in batches and return those scoring >= min_score."""
    if not entries:
        return []

    scored_entries = []

    for i in range(0, len(entries), batch_size):
        batch = entries[i : i + batch_size]

        # Build article text for the batch
        articles_text = ""
        for idx, entry in enumerate(batch):
            text = _prepare_article_text(entry)
            articles_text += f"\n---\nArticle {idx + 1}: \"{entry['title']}\"\nSource: {entry.get('source_label', 'Unknown')}\nURL: {entry['url']}\nText: {text[:2000]}\n"

        prompt = _BATCH_PROMPT_TEMPLATE.format(articles=articles_text)

        try:
            response = llm.complete(prompt, system=_SYSTEM_PROMPT, model=model, max_tokens=2048)

            # Parse JSON from response
            json_start = response.find("[")
            json_end = response.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                scores = json.loads(response[json_start:json_end])
            else:
                LOGGER.warning("Could not parse JSON from LLM response, skipping batch")
                continue

            for score_entry in scores:
                idx = score_entry.get("index", 0) - 1  # 1-indexed to 0-indexed
                if 0 <= idx < len(batch) and score_entry.get("score", 0) >= min_score:
                    entry = batch[idx].copy()
                    entry["llm_summary"] = score_entry.get("summary", "")
                    entry["relevance_score"] = score_entry.get("score", 0)
                    entry["why_it_matters"] = score_entry.get("why_it_matters", "")
                    scored_entries.append(entry)

        except (json.JSONDecodeError, KeyError) as e:
            LOGGER.warning("Failed to parse LLM scoring response: %s", e)
        except Exception as e:
            LOGGER.error("LLM scoring failed for batch: %s", e)

    scored_entries.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    LOGGER.info(
        "Scored %d entries, %d passed threshold (>= %d)",
        len(entries), len(scored_entries), min_score,
    )
    return scored_entries
