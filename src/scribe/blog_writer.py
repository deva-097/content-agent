"""Blog post draft generator with Astro-compatible frontmatter."""

from __future__ import annotations

import re
from datetime import date

from src.common.llm import LLMClient, SONNET
from src.common.logger import get_logger

from .templates import BLOG_SYSTEM, BLOG_USER

LOGGER = get_logger(__name__)


def _slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r'["\':;,.!?()]+', "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:60]


def generate_blog_draft(
    llm: LLMClient,
    topic: str,
    *,
    context: str = "",
    notes: str = "",
    tags: list[str] | None = None,
    model: str = SONNET,
) -> str:
    """Generate a blog post draft with Astro frontmatter."""
    context_section = f"Context/angle: {context}\n" if context else ""
    notes_section = f"Additional notes from the author: {notes}\n" if notes else ""
    tags_str = ", ".join(f'"{t}"' for t in (tags or ["ai"]))

    prompt = BLOG_USER.format(
        topic=topic,
        context_section=context_section,
        notes_section=notes_section,
        date=date.today().isoformat(),
        tags=tags_str,
    )

    LOGGER.info("Generating blog draft for: %s", topic)
    content = llm.complete(prompt, system=BLOG_SYSTEM, model=model, max_tokens=4096)

    # Validate that frontmatter is present
    if not content.strip().startswith("---"):
        LOGGER.warning("LLM output missing frontmatter, adding it")
        slug = _slugify(topic)
        content = (
            f'---\n'
            f'title: "{topic}"\n'
            f'slug: "{slug}"\n'
            f'date: "{date.today().isoformat()}"\n'
            f'description: "Draft post about {topic}"\n'
            f'tags: [{tags_str}]\n'
            f'---\n\n'
            f'{content}'
        )

    return content
