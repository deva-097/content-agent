"""Generate a brief narrative summary of the week's browsing patterns."""

from __future__ import annotations

from src.common.llm import LLMClient, HAIKU
from src.common.logger import get_logger

LOGGER = get_logger(__name__)

_SYSTEM = """\
You write brief, conversational summaries of someone's week based on their \
browsing patterns. You infer what they were up to from the domains they visited \
and time spent. Be specific and observational — not generic. \
Never use bullet points or headers. Just 1-2 short paragraphs."""

_PROMPT = """\
Here's how someone spent their time online this week (domain, hours, category):

{domain_lines}

Write 1-2 short paragraphs describing what they seemed to be doing. \
Infer context from the domains — e.g. booking.com → planning a trip, \
github.com → building something, hbr.org → thinking through a strategy problem. \
Be brief and conversational. Don't list every domain — synthesise into a narrative."""


def generate_week_summary(
    audit: dict,
    llm: LLMClient,
    model: str = HAIKU,
) -> str:
    """Return a 1-2 paragraph narrative summary of the week's browsing."""
    top_domains = audit.get("top_domains", [])
    if not top_domains:
        return ""

    # Build domain lines: only include domains with > 2 min total time
    lines = []
    for domain, hours, category in top_domains:
        if hours < 2 / 60:  # skip under 2 min
            continue
        lines.append(f"  {domain}: {hours:.1f}h ({category})")

    if not lines:
        return ""

    domain_lines = "\n".join(lines)

    try:
        summary = llm.complete(
            _PROMPT.format(domain_lines=domain_lines),
            system=_SYSTEM,
            model=model,
            max_tokens=300,
        )
        LOGGER.info("Generated week summary (%d chars)", len(summary))
        return summary.strip()
    except Exception as e:
        LOGGER.warning("Failed to generate week summary: %s", e)
        return ""
