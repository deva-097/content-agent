"""Tuner agent — weekly podcast digest."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from datetime import date

from src.common.config import load_config
from src.common.email import send_html_email
from src.common.llm import LLMClient, HAIKU
from src.common.logger import get_logger
from src.common.state import StateDB
from src.scout.sources import fetch_all_sources

from .formatter import format_digest

LOGGER = get_logger(__name__)


def _parse_duration(raw: str | None) -> str:
    """Parse itunes:duration into human-readable form like '3h 12m' or '45m'."""
    if not raw:
        return ""
    raw = raw.strip()

    # Try HH:MM:SS or MM:SS format
    if ":" in raw:
        parts = raw.split(":")
        try:
            parts = [int(p) for p in parts]
            if len(parts) == 3:
                h, m, _ = parts
            elif len(parts) == 2:
                h, m = 0, parts[0]
            else:
                return ""
            if h and m:
                return f"{h}h {m}m"
            elif h:
                return f"{h}h"
            elif m:
                return f"{m}m"
        except ValueError:
            return ""

    # Raw seconds
    try:
        total_secs = int(raw)
        h = total_secs // 3600
        m = (total_secs % 3600) // 60
        if h and m:
            return f"{h}h {m}m"
        elif h:
            return f"{h}h"
        elif m:
            return f"{m}m"
    except ValueError:
        pass

    return ""


def _summarize_episodes(llm: LLMClient, episodes: list[dict], model: str) -> list[dict]:
    """One batch LLM call to get 2-sentence summaries for all episodes."""
    if not episodes:
        return episodes

    lines = []
    for i, ep in enumerate(episodes):
        notes = ep.get("summary", "") or ""
        notes_trunc = notes[:300] if notes else "(no show notes)"
        lines.append(f'{i}. "{ep["title"]}" ({ep.get("source_label", "?")}) — {notes_trunc}')

    prompt = (
        "For each podcast episode below, write 2 sentences: "
        "what the episode is about, and a listen/skip signal "
        "(who it's for or why you might skip it).\n\n"
        "Episodes:\n" + "\n".join(lines) +
        "\n\nReturn a JSON array only, no other text: "
        '[{"index": 0, "summary": "..."}, ...]'
    )

    LOGGER.info("Sending batch summary request for %d episodes", len(episodes))
    raw = llm.complete(prompt, model=model, max_tokens=2048)

    # Extract JSON array from response
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        LOGGER.warning("Could not parse LLM summary response, skipping summaries")
        return episodes

    try:
        summaries = json.loads(match.group())
        index_map = {item["index"]: item["summary"] for item in summaries}
        for i, ep in enumerate(episodes):
            ep["summary_text"] = index_map.get(i, "")
    except (json.JSONDecodeError, KeyError) as e:
        LOGGER.warning("Failed to parse summaries: %s", e)

    return episodes


def run_tuner(*, dry_run: bool = False) -> None:
    """Execute a full Tuner run: fetch → summarize → email digest."""
    config = load_config()
    tuner_config = config["tuner"]
    state = StateDB()
    llm = LLMClient()

    run_id = state.record_run_start("tuner")
    LOGGER.info("Starting Tuner run")

    try:
        # 1. Fetch from all podcast feeds — always look back 7 days
        since = datetime.now(timezone.utc) - timedelta(days=7)
        podcast_sources = tuner_config.get("sources", {}).get("podcasts", [])
        max_items = tuner_config.get("max_items_per_source", 5)

        episodes = fetch_all_sources(podcast_sources, since=since, max_items=max_items)
        LOGGER.info("Fetched %d episodes from %d feeds", len(episodes), len(podcast_sources))

        if not episodes:
            LOGGER.info("No new episodes this week")
            state.record_run_end(run_id, "completed", {"episodes_found": 0})
            state.close()
            return

        # 2. Extract duration from raw feed data (feedparser stores in itunes_duration)
        # Note: fetch_all_sources doesn't pass through itunes fields, so duration
        # won't be available unless we fetch directly — leave blank for now,
        # summary_text is the key value-add.
        for ep in episodes:
            ep.setdefault("duration", "")
            ep.setdefault("summary_text", "")

        # 3. LLM: batch summarize all episodes
        model = tuner_config.get("llm_model", HAIKU)
        episodes = _summarize_episodes(llm, episodes, model=model)

        # 4. Format HTML
        cost = llm.estimate_session_cost()
        html = format_digest(episodes, cost=cost)

        # 5. Send or dry-run print
        if dry_run:
            LOGGER.info("[DRY RUN] Would send Tuner digest with %d episodes", len(episodes))
            print(f"\n{'='*60}")
            print(f"TUNER — PODCAST WEEK — {date.today()}")
            print(f"{'='*60}")
            # Group by show for display
            from itertools import groupby
            eps_sorted = sorted(episodes, key=lambda e: e.get("source_label", ""))
            for show, group in groupby(eps_sorted, key=lambda e: e.get("source_label", "Unknown")):
                print(f"\n{show}")
                for ep in group:
                    pub = ep.get("published")
                    pub_str = pub.strftime("%b %d") if pub else "?"
                    dur = ep.get("duration", "")
                    print(f"  {ep['title']} · {pub_str}{' · ' + dur if dur else ''}")
                    if ep.get("summary_text"):
                        print(f"  {ep['summary_text']}")
            print(f"\nAPI cost this run: ${cost:.4f}")
        else:
            send_html_email(
                subject=f"[Tuner] Podcast Week — {date.today()}",
                html_body=html,
            )

        summary = {
            "episodes_found": len(episodes),
            **llm.get_usage_summary(),
        }
        state.record_run_end(run_id, "completed", summary)
        LOGGER.info("Tuner run completed: %s", summary)

    except Exception as e:
        state.record_run_end(run_id, "failed", {"error": str(e)})
        LOGGER.exception("Tuner run failed")
        raise
    finally:
        state.close()
