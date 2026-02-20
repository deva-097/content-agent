"""Mirror agent — Chrome history analyzer and time auditor."""

from __future__ import annotations

from datetime import date

from src.common.config import load_config
from src.common.email import send_html_email
from src.common.llm import LLMClient
from src.common.logger import get_logger
from src.common.state import StateDB

from .analyzer import generate_time_audit
from .chrome import read_history
from .classifier import classify_entries
from .formatter import format_report
from .ideas import generate_ideas

LOGGER = get_logger(__name__)


def run_mirror(*, dry_run: bool = False) -> None:
    """Execute a full Mirror run: read history → classify → analyze → email."""
    config = load_config()
    state = StateDB()
    llm = LLMClient()

    last_run = state.get_last_run_time("mirror")
    run_id = state.record_run_start("mirror")

    LOGGER.info("Starting Mirror run (last run: %s)", last_run or "never")

    try:
        # 1. Read Chrome history since last run
        entries = read_history(since=last_run, config=config)
        if not entries:
            LOGGER.info("No new browsing history to analyze")
            state.record_run_end(run_id, "completed", {
                "entries": 0, **llm.get_usage_summary(),
            })
            return

        LOGGER.info("Read %d history entries", len(entries))

        # 2. Classify URLs (rule-based + LLM)
        model = config["mirror"].get("llm_model")
        classifications = classify_entries(entries, config, llm=llm, model=model)
        LOGGER.info("Classified %d URLs", len(classifications))

        # 3. Generate time audit (pure Python)
        audit = generate_time_audit(entries, classifications)
        LOGGER.info(
            "Time audit: %.1fh productive, %.1fh neutral, %.1fh waste",
            audit["time_by_category"].get("productive", 0),
            audit["time_by_category"].get("neutral", 0),
            audit["time_by_category"].get("waste", 0),
        )

        # 4. Generate content ideas from productive reading
        ideas = generate_ideas(entries, classifications, llm, model=model)

        # 5. Save ideas to state DB
        for idea in ideas:
            context = idea.get("inspired_by", "")
            if isinstance(context, list):
                context = ", ".join(str(c) for c in context)
            state.save_content_idea("mirror", idea["title"], str(context))

        # 6. Format + send report
        cost = llm.estimate_session_cost()
        html = format_report(audit, ideas=ideas, cost=cost)

        if dry_run:
            LOGGER.info("[DRY RUN] Would send Mirror report")
            _print_dry_run(audit, ideas, cost)
        else:
            send_html_email(
                subject=f"[Mirror] Browsing Report — {date.today()}",
                html_body=html,
            )

        # 7. Mark URLs as processed
        for entry in entries:
            category = classifications.get(entry["url"], "neutral")
            state.mark_url_processed(
                entry["url"], "mirror",
                category=category,
                title=entry.get("title"),
            )

        summary = {
            "entries": len(entries),
            "productive": sum(1 for c in classifications.values() if c == "productive"),
            "waste": sum(1 for c in classifications.values() if c == "waste"),
            "ideas_generated": len(ideas),
            **llm.get_usage_summary(),
        }
        state.record_run_end(run_id, "completed", summary)
        LOGGER.info("Mirror run completed: %s", summary)

    except Exception as e:
        state.record_run_end(run_id, "failed", {"error": str(e)})
        LOGGER.exception("Mirror run failed")
        raise
    finally:
        state.close()


def _print_dry_run(audit: dict, ideas: list[dict], cost: float) -> None:
    """Print a console-friendly version of the report."""
    print(f"\n{'='*60}")
    print(f"MIRROR — BROWSING REPORT — {date.today()}")
    print(f"{'='*60}")

    print(f"\nTotal: {audit['total_entries']} visits, {audit['total_hours']:.1f}h")
    for cat in ("productive", "neutral", "waste"):
        hours = audit["time_by_category"].get(cat, 0)
        pct = (hours / audit["total_hours"] * 100) if audit["total_hours"] > 0 else 0
        print(f"  {cat:12s}: {hours:5.1f}h ({pct:.0f}%)")

    print("\nTop domains:")
    for domain, hours, cat in audit["top_domains"][:10]:
        print(f"  {domain:30s} {hours:5.1f}h  [{cat}]")

    if audit["waste_highlights"]:
        print("\nTime sinks:")
        for item in audit["waste_highlights"][:5]:
            print(f"  {item['duration_minutes']:5.1f}min  {item['domain']} — {item.get('title', '')[:50]}")

    if ideas:
        print("\nContent ideas:")
        for idea in ideas:
            print(f"  - {idea['title']}")
            print(f"    {idea.get('angle', '')}")

    print(f"\nAPI cost this run: ${cost:.4f}")
