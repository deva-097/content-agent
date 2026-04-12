"""Tuner agent — weekly podcast + newsletter digest."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from datetime import date
from pathlib import Path

from src.common.config import load_config
from src.common.email import send_html_email
from src.common.llm import LLMClient, HAIKU
from src.common.logger import get_logger
from src.common.run_log import append_tuner_run
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


def _load_persona(config: dict) -> str:
    """Load persona file for relevance flagging."""
    path = config.get("persona_file", "")
    if not path:
        return ""
    try:
        return Path(path).read_text()
    except Exception as e:
        LOGGER.warning("Could not read persona file %s: %s", path, e)
        return ""


def _get_deep_digest_labels(sources: list[dict]) -> set[str]:
    """Return set of source labels that have deep_digest: true."""
    return {s["label"] for s in sources if s.get("deep_digest")}


def _best_content(item: dict) -> str:
    """Return the richest text available for an item (full content > summary)."""
    content = item.get("content", "") or ""
    summary = item.get("summary", "") or ""
    # Use content if it's substantially richer than summary
    if len(content) > len(summary) + 100:
        return content
    return summary or content


def _strip_html(text: str) -> str:
    """Remove HTML tags for cleaner LLM input."""
    return re.sub(r"<[^>]+>", "", text)


def _summarize_standard(llm: LLMClient, items: list[dict], model: str) -> list[dict]:
    """Batch LLM call for 2-sentence summaries (standard tier)."""
    if not items:
        return items

    lines = []
    for i, item in enumerate(items):
        notes = item.get("summary", "") or ""
        notes_trunc = notes[:300] if notes else "(no show notes)"
        kind = item.get("kind", "podcast")
        lines.append(f'{i}. [{kind}] "{item["title"]}" ({item.get("source_label", "?")}) — {notes_trunc}')

    prompt = (
        "For each item below (podcast episode or newsletter article), write 2 sentences: "
        "what it's about, and a listen/read signal "
        "(who it's for or why you might skip it).\n\n"
        "Items:\n" + "\n".join(lines) +
        "\n\nReturn a JSON array only, no other text: "
        '[{"index": 0, "summary": "..."}, ...]'
    )

    LOGGER.info("Sending standard summary request for %d items", len(items))
    raw = llm.complete(prompt, model=model, max_tokens=2048)

    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        LOGGER.warning("Could not parse standard summary response")
        return items

    try:
        summaries = json.loads(match.group())
        index_map = {item["index"]: item["summary"] for item in summaries}
        for i, item in enumerate(items):
            item["summary_text"] = index_map.get(i, "")
    except (json.JSONDecodeError, KeyError) as e:
        LOGGER.warning("Failed to parse standard summaries: %s", e)

    return items


def _summarize_deep(llm: LLMClient, items: list[dict], model: str) -> list[dict]:
    """Individual LLM calls for deep digest items — structured extraction."""
    for item in items:
        rich_text = _strip_html(_best_content(item))
        if len(rich_text) < 200:
            # Not enough content for deep treatment, fall back to standard
            item["deep"] = False
            continue

        # Truncate to ~8000 chars to stay within Haiku context cheaply
        rich_text = rich_text[:8000]
        kind = item.get("kind", "podcast")
        verb = "listen to" if kind == "podcast" else "read"

        prompt = (
            f'Given the show notes / article content below for "{item["title"]}" '
            f'from {item.get("source_label", "?")}, extract:\n\n'
            f"1. A 2-sentence summary of what this is about\n"
            f"2. 3-5 key arguments or takeaways (specific — include names, numbers, frameworks)\n"
            f"3. One memorable quote (if findable in the text, otherwise skip)\n"
            f"4. Notable data points or numbers mentioned\n\n"
            f"Content:\n{rich_text}\n\n"
            f"Return JSON only, no other text:\n"
            f'{{"summary": "...", "key_points": ["...", "..."], '
            f'"quote": "..." or null, "data_points": ["...", "..."] or []}}'
        )

        LOGGER.info("Deep digest for: %s", item["title"])
        raw = llm.complete(prompt, model=model, max_tokens=1024)

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            LOGGER.warning("Could not parse deep digest for: %s", item["title"])
            item["deep"] = False
            continue

        try:
            parsed = json.loads(match.group())
            item["summary_text"] = parsed.get("summary", "")
            item["key_points"] = parsed.get("key_points", [])
            item["quote"] = parsed.get("quote")
            item["data_points"] = parsed.get("data_points", [])
            item["deep"] = True
        except (json.JSONDecodeError, KeyError) as e:
            LOGGER.warning("Failed to parse deep digest for %s: %s", item["title"], e)
            item["deep"] = False

    return items


def _flag_must_reads(llm: LLMClient, all_items: list[dict], persona: str, model: str) -> list[dict]:
    """Flag top picks based on persona interests."""
    if not persona or not all_items:
        return all_items

    lines = []
    for i, item in enumerate(all_items):
        blurb = item.get("summary_text", "")[:200]
        kind = item.get("kind", "podcast")
        lines.append(f'{i}. [{kind}] "{item["title"]}" ({item.get("source_label", "?")}) — {blurb}')

    # Keep persona context brief — just interests and professional identity
    persona_brief = persona[:2000]

    prompt = (
        "Given this person's profile:\n"
        f"{persona_brief}\n\n"
        "And these items from this week's digest:\n"
        + "\n".join(lines) +
        "\n\nPick the top 3-5 MUST read/listen items that are most relevant to this person's "
        "interests, work, and goals. Return JSON only:\n"
        '[{"index": 0, "reason": "one-line why"}, ...]'
    )

    LOGGER.info("Flagging must-reads from %d items", len(all_items))
    raw = llm.complete(prompt, model=model, max_tokens=512)

    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        LOGGER.warning("Could not parse must-read flags")
        return all_items

    try:
        picks = json.loads(match.group())
        flagged = {p["index"]: p.get("reason", "") for p in picks}
        for i, item in enumerate(all_items):
            if i in flagged:
                item["must_read"] = True
                item["must_read_reason"] = flagged[i]
    except (json.JSONDecodeError, KeyError) as e:
        LOGGER.warning("Failed to parse must-read flags: %s", e)

    return all_items


def run_tuner(*, dry_run: bool = False) -> None:
    """Execute a full Tuner run: fetch → summarize → flag → email digest."""
    config = load_config()
    tuner_config = config["tuner"]
    state = StateDB()
    llm = LLMClient()

    run_id = state.record_run_start("tuner")
    LOGGER.info("Starting Tuner run")

    try:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        max_items = tuner_config.get("max_items_per_source", 5)
        model = tuner_config.get("llm_model", HAIKU)

        # 1. Fetch podcasts and newsletters
        podcast_sources = tuner_config.get("sources", {}).get("podcasts", [])
        newsletter_sources = tuner_config.get("sources", {}).get("newsletters", [])

        episodes = fetch_all_sources(podcast_sources, since=since, max_items=max_items)
        for ep in episodes:
            ep["kind"] = "podcast"
        LOGGER.info("Fetched %d episodes from %d podcast feeds", len(episodes), len(podcast_sources))

        articles = fetch_all_sources(newsletter_sources, since=since, max_items=max_items)
        for art in articles:
            art["kind"] = "newsletter"
        LOGGER.info("Fetched %d articles from %d newsletter feeds", len(articles), len(newsletter_sources))

        all_items = episodes + articles

        if not all_items:
            LOGGER.info("No new content this week")
            state.record_run_end(run_id, "completed", {"items_found": 0})
            state.close()
            return

        # 2. Set defaults
        for item in all_items:
            item.setdefault("duration", "")
            item.setdefault("summary_text", "")
            item.setdefault("deep", False)
            item.setdefault("must_read", False)
            item.setdefault("key_points", [])
            item.setdefault("quote", None)
            item.setdefault("data_points", [])

        # 3. Split into deep vs standard based on config flags
        deep_labels = _get_deep_digest_labels(podcast_sources + newsletter_sources)
        deep_items = [item for item in all_items if item.get("source_label") in deep_labels]
        standard_items = [item for item in all_items if item.get("source_label") not in deep_labels]

        LOGGER.info("Deep digest: %d items, Standard: %d items", len(deep_items), len(standard_items))

        # 4. LLM: summarize both tiers
        standard_items = _summarize_standard(llm, standard_items, model=model)
        deep_items = _summarize_deep(llm, deep_items, model=model)

        # Deep items that didn't have enough content get standard treatment
        shallow_fallbacks = [item for item in deep_items if not item.get("deep")]
        if shallow_fallbacks:
            shallow_fallbacks = _summarize_standard(llm, shallow_fallbacks, model=model)

        all_items = standard_items + deep_items

        # 5. Flag must-reads using persona
        persona = _load_persona(tuner_config)
        all_items = _flag_must_reads(llm, all_items, persona, model=model)

        # 6. Format HTML
        cost = llm.estimate_session_cost()
        html = format_digest(all_items, cost=cost)

        # 7. Send or dry-run print
        if dry_run:
            LOGGER.info("[DRY RUN] Would send Tuner digest with %d items", len(all_items))
            print(f"\n{'='*60}")
            print(f"TUNER — WEEKLY DIGEST — {date.today()}")
            print(f"{'='*60}")

            # Show must-reads first
            must_reads = [item for item in all_items if item.get("must_read")]
            if must_reads:
                print(f"\n{'★'*3} MUST READ/LISTEN {'★'*3}")
                for item in must_reads:
                    kind = item.get("kind", "podcast")
                    icon = "🎙" if kind == "podcast" else "📝"
                    print(f"  {icon} {item['title']} ({item.get('source_label', '?')})")
                    if item.get("must_read_reason"):
                        print(f"     → {item['must_read_reason']}")

            # Group by show for display
            from itertools import groupby
            for kind_label, kind_key in [("PODCASTS", "podcast"), ("NEWSLETTERS", "newsletter")]:
                kind_items = sorted(
                    [i for i in all_items if i.get("kind") == kind_key],
                    key=lambda e: e.get("source_label", ""),
                )
                if not kind_items:
                    continue
                print(f"\n--- {kind_label} ---")
                for show, group in groupby(kind_items, key=lambda e: e.get("source_label", "Unknown")):
                    print(f"\n{show}")
                    for item in group:
                        star = "★ " if item.get("must_read") else ""
                        pub = item.get("published")
                        pub_str = pub.strftime("%b %d") if pub else "?"
                        dur = item.get("duration", "")
                        print(f"  {star}{item['title']} · {pub_str}{' · ' + dur if dur else ''}")
                        if item.get("summary_text"):
                            print(f"    {item['summary_text']}")
                        if item.get("key_points"):
                            for kp in item["key_points"]:
                                print(f"    • {kp}")
                        if item.get("quote"):
                            print(f'    "{item["quote"]}"')

            print(f"\nAPI cost this run: ${cost:.4f}")
        else:
            send_html_email(
                subject=f"[Tuner] Weekly Digest — {date.today()}",
                html_body=html,
            )

        # 8. Append to persistent log
        append_tuner_run(all_items, cost=cost)

        summary = {
            "items_found": len(all_items),
            "deep_digest_count": len([i for i in all_items if i.get("deep")]),
            "must_read_count": len([i for i in all_items if i.get("must_read")]),
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
