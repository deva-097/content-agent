"""Scout agent — internet scanner for content discovery."""

from __future__ import annotations

from datetime import date

from src.common.config import load_config
from src.common.email import send_html_email
from src.common.llm import LLMClient
from src.common.logger import get_logger
from src.common.run_log import append_scout_run
from src.common.state import StateDB

from .digest import filter_and_pick
from .formatter import format_digest
from .sources import fetch_all_sources

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
    """Execute a full Scout run: fetch → filter → pick → email digest."""
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
        max_items = scout_config.get("max_items_per_source", 15)
        entries = fetch_all_sources(blog_sources, since=last_run, max_items=max_items)
        LOGGER.info("Fetched %d entries from sources", len(entries))

        # 2. Deduplicate
        entries = _deduplicate(entries)
        LOGGER.info("After dedup: %d entries", len(entries))

        # 3. Filter already-processed
        entries = [e for e in entries if not state.is_url_processed(e["url"], "scout")]
        LOGGER.info("After filtering processed: %d new entries", len(entries))

        if not entries:
            LOGGER.info("No new entries to process")
            state.record_run_end(run_id, "completed", {
                "items_found": 0, "items_kept": 0,
                **llm.get_usage_summary(),
            })
            return

        # 4. Filter and pick with LLM
        model = scout_config.get("llm_model")
        picked = filter_and_pick(llm, entries, model=model) if model else filter_and_pick(llm, entries)
        LOGGER.info("Picked %d items for digest", len(picked))

        # 5. Format + send email
        cost = llm.estimate_session_cost()
        html = format_digest(picked, cost=cost)

        if dry_run:
            LOGGER.info("[DRY RUN] Would send Scout digest with %d items", len(picked))
            print(f"\n{'='*60}")
            print(f"SCOUT — 5 READS — {date.today()}")
            print(f"{'='*60}")
            for item in picked:
                print(f"\n{item['title']}")
                print(f"  {item.get('source_label', '?')} · {item['url']}")
                print(f"  {item.get('why_read', '')}")
            print(f"\nAPI cost this run: ${cost:.4f}")
        else:
            send_html_email(
                subject=f"[Scout] 5 Reads — {date.today()}",
                html_body=html,
            )

        # Append to persistent log regardless of dry_run
        append_scout_run(picked, cost)

        # 6. Mark picked entries as processed
        for item in picked:
            state.mark_url_processed(
                item["url"], "scout",
                category="picked",
                title=item.get("title"),
                summary=item.get("why_read", ""),
            )

        summary = {
            "items_found": len(entries),
            "items_picked": len(picked),
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
