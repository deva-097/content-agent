"""Scout agent — internet scanner for content discovery."""

from __future__ import annotations

from datetime import date

from src.common.config import load_config
from src.common.email import send_html_email
from src.common.llm import LLMClient
from src.common.logger import get_logger
from src.common.state import StateDB

from .digest import summarize_and_score
from .formatter import format_digest
from .sources import fetch_all_sources
from .web_search import search_topics

LOGGER = get_logger(__name__)


def _deduplicate(entries: list[dict]) -> list[dict]:
    """Remove duplicate entries by URL."""
    seen = set()
    unique = []
    for entry in entries:
        url = entry.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(entry)
    return unique


def run_scout(*, dry_run: bool = False) -> None:
    """Execute a full Scout run: fetch → score → email digest."""
    config = load_config()
    scout_config = config["scout"]
    state = StateDB()
    llm = LLMClient()

    last_run = state.get_last_run_time("scout")
    run_id = state.record_run_start("scout")

    LOGGER.info("Starting Scout run (last run: %s)", last_run or "never")

    try:
        # 1. Fetch from configured sources
        blog_sources = scout_config.get("sources", {}).get("blogs", [])
        max_items = scout_config.get("max_items_per_source", 10)
        entries = fetch_all_sources(blog_sources, since=last_run, max_items=max_items)
        LOGGER.info("Fetched %d entries from sources", len(entries))

        # 2. Fetch from web searches
        topics = scout_config.get("topics", [])
        if topics:
            search_results = search_topics(topics)
            entries.extend(search_results)
            LOGGER.info("Added %d entries from web searches", len(search_results))

        # 3. Deduplicate
        entries = _deduplicate(entries)
        LOGGER.info("After dedup: %d entries", len(entries))

        # 4. Filter already-processed
        entries = [e for e in entries if not state.is_url_processed(e["url"], "scout")]
        LOGGER.info("After filtering processed: %d new entries", len(entries))

        if not entries:
            LOGGER.info("No new entries to process")
            state.record_run_end(run_id, "completed", {
                "items_found": 0, "items_kept": 0,
                **llm.get_usage_summary(),
            })
            return

        # 5. Summarize + score with LLM
        model = scout_config.get("llm_model")
        scored = summarize_and_score(llm, entries, model=model) if model else summarize_and_score(llm, entries)
        LOGGER.info("Scored entries: %d passed relevance threshold", len(scored))

        # 6. Save content ideas to state DB
        for item in scored:
            idea = f"{item['title']} — {item.get('why_it_matters', '')}"
            state.save_content_idea("scout", idea, item["url"])

        # 7. Format + send email
        cost = llm.estimate_session_cost()
        html = format_digest(scored, cost=cost)

        if dry_run:
            LOGGER.info("[DRY RUN] Would send Scout digest with %d items", len(scored))
            print(f"\n{'='*60}")
            print(f"SCOUT DIGEST — {date.today()}")
            print(f"{'='*60}")
            for item in scored:
                print(f"\n[{item['relevance_score']}/5] {item['title']}")
                print(f"  Source: {item.get('source_label', '?')}")
                print(f"  URL: {item['url']}")
                print(f"  {item['llm_summary']}")
                if item.get("why_it_matters"):
                    print(f"  → {item['why_it_matters']}")
            print(f"\nAPI cost this run: ${cost:.4f}")
        else:
            send_html_email(
                subject=f"[Scout] Content Digest — {date.today()}",
                html_body=html,
            )

        # 8. Mark all fetched entries as processed
        for item in scored:
            state.mark_url_processed(
                item["url"], "scout",
                category="relevant",
                title=item.get("title"),
                summary=item.get("llm_summary"),
            )

        summary = {
            "items_found": len(entries),
            "items_scored": len(scored),
            **llm.get_usage_summary(),
        }
        state.record_run_end(run_id, "completed", summary)
        LOGGER.info("Scout run completed: %s", summary)

    except Exception as e:
        state.record_run_end(run_id, "failed", {"error": str(e)})
        LOGGER.exception("Scout run failed")
        raise
    finally:
        state.close()
