"""Scribe agent — draft publisher for blog posts and LinkedIn."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from src.common.config import load_config
from src.common.llm import LLMClient
from src.common.logger import get_logger
from src.common.state import StateDB

from .blog_writer import generate_blog_draft
from .linkedin_writer import generate_linkedin_draft

LOGGER = get_logger(__name__)


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r'["\':;,.!?()]+', "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:60]


def run_scribe(
    topic: str | None = None,
    *,
    content_type: str = "blog",
    context: str = "",
    notes: str = "",
    from_ideas: bool = False,
) -> list[Path]:
    """Generate draft(s) and save to Obsidian vault.

    Returns list of paths to created draft files.
    """
    config = load_config()
    scribe_config = config["scribe"]
    output_dir = Path(scribe_config["output_dir"]).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    state = StateDB()
    llm = LLMClient()
    model = scribe_config.get("llm_model")

    created_files: list[Path] = []

    try:
        if from_ideas:
            ideas = state.get_unused_ideas()
            if not ideas:
                LOGGER.info("No unused content ideas available")
                print("No unused content ideas. Run Scout or Mirror first.")
                return []

            LOGGER.info("Generating drafts from %d stored ideas", len(ideas))
            for idea in ideas:
                path = _generate_and_save(
                    llm=llm,
                    topic=idea["idea"],
                    content_type=content_type,
                    context=idea.get("context", ""),
                    notes=notes,
                    output_dir=output_dir,
                    model=model,
                )
                if path:
                    created_files.append(path)
                    state.mark_idea_used(idea["id"])

        elif topic:
            path = _generate_and_save(
                llm=llm,
                topic=topic,
                content_type=content_type,
                context=context,
                notes=notes,
                output_dir=output_dir,
                model=model,
            )
            if path:
                created_files.append(path)

        else:
            print("Provide a topic or use --from-ideas")
            return []

        # Log cost
        cost = llm.estimate_session_cost()
        LOGGER.info(
            "Scribe: created %d draft(s), API cost: $%.4f",
            len(created_files), cost,
        )
        for f in created_files:
            print(f"  Draft saved: {f}")
        print(f"  API cost: ${cost:.4f}")

    finally:
        state.close()

    return created_files


def _generate_and_save(
    *,
    llm: LLMClient,
    topic: str,
    content_type: str,
    context: str,
    notes: str,
    output_dir: Path,
    model: str | None,
) -> Path | None:
    """Generate a single draft and save it."""
    kwargs = {}
    if model:
        kwargs["model"] = model

    try:
        if content_type == "blog":
            content = generate_blog_draft(
                llm, topic, context=context, notes=notes, **kwargs
            )
            slug = _slugify(topic)
            filename = f"{date.today().isoformat()}-{slug}.md"
        else:
            content = generate_linkedin_draft(
                llm, topic, context=context, notes=notes, **kwargs
            )
            slug = _slugify(topic)
            filename = f"{date.today().isoformat()}-linkedin-{slug}.md"

        output_path = output_dir / filename
        output_path.write_text(content, encoding="utf-8")
        LOGGER.info("Draft saved to %s", output_path)
        return output_path

    except Exception as e:
        LOGGER.error("Failed to generate draft for '%s': %s", topic, e)
        return None
