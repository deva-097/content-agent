"""Weekly Brief agent — synthesizes the week into an honest advisor email."""

from __future__ import annotations

import json
import re
from datetime import date

from src.common.config import load_config
from src.common.email import send_html_email
from src.common.llm import LLMClient, SONNET
from src.common.logger import get_logger
from src.common.run_log import append_weekly_brief_run
from src.common.state import StateDB

from .formatter import format_brief
from .reader import gather_all_sources

LOGGER = get_logger(__name__)

_SECTION_LABELS = {
    "time_audit": "TIME AUDIT",
    "task_accountability": "TASK ACCOUNTABILITY",
    "consulting_pulse": "CONSULTING PULSE",
    "week_in_the_machine": "WEEK IN THE MACHINE",
    "upgrade_suggestion": "ONE UPGRADE",
    "honest_call": "THE HONEST CALL",
}


def _format_cos_for_prompt(cos: dict) -> str:
    lines = []

    if cos["done_this_week"]:
        lines.append("COMPLETED THIS WEEK:")
        for t in cos["done_this_week"]:
            lines.append(f"  - [{t['bucket']}] {t['task']}")
        lines.append("")

    if cos["overdue"]:
        lines.append("OVERDUE (scheduled but not done):")
        for t in cos["overdue"]:
            lines.append(f"  - [{t['bucket']}] [{t['priority']}] {t['task']} (due: {t['scheduled_date']})")
        lines.append("")

    if cos["active"]:
        lines.append("ACTIVE TASKS BY BUCKET:")
        current_bucket = None
        for t in cos["active"]:
            if t["bucket"] != current_bucket:
                current_bucket = t["bucket"]
                lines.append(f"  {current_bucket.upper()}:")
            priority_tag = f"[{t['priority']}] " if t["priority"] else ""
            scheduled = f" (scheduled: {t['scheduled_date']})" if t["scheduled_date"] else ""
            lines.append(f"    - {priority_tag}{t['task']}{scheduled}")

    return "\n".join(lines) if lines else "No tasks recorded."


def _build_prompt(sources: dict) -> tuple[str, str]:
    persona = sources["persona"]
    cos_text = _format_cos_for_prompt(sources["cos"])

    system = f"""You are Devashish's Chief of Staff. You read his week and tell him the truth — no softening.

WHO DEVASHISH IS:
{persona}

YOUR JOB: Synthesize what actually happened this week, where he drifted from what matters, and what needs attention next week. Use the data in front of you — don't invent things that aren't there.

TONE: Trusted, blunt advisor. No "it's great that you..." framing. Call out avoidance and drift by name when the data supports it. End with one question he has to sit with.

OUTPUT: Return a single JSON object with exactly these six string keys:
- time_audit: 2-3 sentences interpreting his browsing patterns against his stated priorities. Name the gap if it's there.
- task_accountability: 2-3 sentences on task completion. What got done, what's been sitting untouched, what high-priority thing hasn't moved.
- consulting_pulse: 2-3 sentences on where the consulting pipeline actually stands. Flag anything that looks like it's quietly dying.
- week_in_the_machine: 2-3 sentences on what he and his agents actually worked on vs. what he should have been doing.
- upgrade_suggestion: One specific, concrete improvement to his tech setup or workflow he could do in under 2 hours.
- honest_call: 2-3 blunt sentences summing up the week. Name the pattern. End with one question he should sit with."""

    user = f"""DATE: {date.today().strftime("%A, %B %d, %Y")}

--- MIRROR: BROWSING AUDIT (latest run) ---
{sources['mirror_log'] or "No Mirror data available."}

--- COS: TASK STATE ---
{cos_text}

--- CONSULTING CONTEXT ---
{sources['consulting_context'] or "No consulting context available."}

--- CROSS-AGENT HANDOFF ---
{sources['handoff'] or "No handoff file available."}

--- ECOSYSTEM PLAYBOOK ---
{sources['ecosystem_playbook'] or "No playbook available."}

---
Synthesize the week. Return only the JSON object."""

    return system, user


def _parse_response(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    LOGGER.warning("Could not parse JSON from LLM response, storing raw text")
    return {k: "" for k in _SECTION_LABELS} | {"honest_call": text}


def run_weekly_brief(*, dry_run: bool = False) -> None:
    """Execute a full Weekly Brief run."""
    config = load_config()
    state = StateDB()
    llm = LLMClient()

    model = config["weekly_brief"].get("model", SONNET)
    run_id = state.record_run_start("weekly_brief")
    LOGGER.info("Starting Weekly Brief run")

    try:
        sources = gather_all_sources(config)
        system, user = _build_prompt(sources)

        LOGGER.info("Calling %s for synthesis", model)
        raw = llm.complete(user, system=system, model=model, max_tokens=2000)
        sections = _parse_response(raw)

        cost = llm.estimate_session_cost()
        html = format_brief(sections, cost=cost)

        if dry_run:
            LOGGER.info("[DRY RUN] Would send Weekly Brief email")
            _print_dry_run(sections, cost)
        else:
            send_html_email(
                subject=f"[Stevens] Weekly Brief — {date.today().strftime('%b %d')}",
                html_body=html,
            )
            LOGGER.info("Weekly Brief email sent")

        append_weekly_brief_run(sections, cost)

        state.record_run_end(run_id, "completed", {
            "sections": list(sections.keys()),
            **llm.get_usage_summary(),
        })
        LOGGER.info("Weekly Brief completed · cost: $%.4f", cost)

    except Exception as e:
        state.record_run_end(run_id, "failed", {"error": str(e)})
        LOGGER.exception("Weekly Brief run failed")
        raise
    finally:
        state.close()


def _print_dry_run(sections: dict, cost: float) -> None:
    print(f"\n{'='*60}")
    print(f"STEVENS — WEEKLY BRIEF — {date.today()}")
    print(f"{'='*60}")

    for key, label in _SECTION_LABELS.items():
        text = sections.get(key, "")
        if text:
            print(f"\n{label}:")
            print(f"  {text}")

    print(f"\nAPI cost: ${cost:.4f}")
    print()
