"""LinkedIn post draft generator."""

from __future__ import annotations

from src.common.llm import LLMClient, SONNET
from src.common.logger import get_logger

from .templates import LINKEDIN_SYSTEM, LINKEDIN_USER

LOGGER = get_logger(__name__)


def generate_linkedin_draft(
    llm: LLMClient,
    topic: str,
    *,
    context: str = "",
    notes: str = "",
    model: str = SONNET,
) -> str:
    """Generate a LinkedIn post draft."""
    context_section = f"Key point to make: {context}\n" if context else ""
    notes_section = f"Additional notes: {notes}\n" if notes else ""

    prompt = LINKEDIN_USER.format(
        topic=topic,
        context_section=context_section,
        notes_section=notes_section,
    )

    LOGGER.info("Generating LinkedIn draft for: %s", topic)
    return llm.complete(prompt, system=LINKEDIN_SYSTEM, model=model, max_tokens=1024)
