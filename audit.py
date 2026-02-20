"""One-time deep audit of Chrome browsing history (July 2025 – now)."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.common.llm import LLMClient, HAIKU, SONNET
from src.common.logger import get_logger
from src.common.config import load_config, get_project_root
from src.mirror.chrome import read_history

LOGGER = get_logger(__name__)

# Use Opus for the final commentary
OPUS = "claude-opus-4-20250514"

SINCE = datetime(2025, 7, 1, tzinfo=timezone.utc)
OUTPUT_PATH = get_project_root() / "data" / "browsing-audit-jul2025-feb2026.md"


def main():
    config = load_config()
    llm = LLMClient()

    # --- 1. Read all history since July 2025 ---
    print("Reading Chrome history since July 2025...")
    entries = read_history(since=SINCE, config=config)
    print(f"  {len(entries)} entries found\n")

    # --- 2. Aggregate by domain ---
    domain_stats: dict[str, dict] = defaultdict(lambda: {
        "visits": 0, "total_hours": 0.0, "titles": [], "urls": set(),
    })
    for e in entries:
        d = e["domain"]
        domain_stats[d]["visits"] += 1
        domain_stats[d]["total_hours"] += e["duration_seconds"] / 3600
        if e["title"] and len(domain_stats[d]["titles"]) < 20:
            domain_stats[d]["titles"].append(e["title"])
        domain_stats[d]["urls"].add(e["url"])

    # Top 50 by visit count
    top_domains = sorted(
        domain_stats.items(), key=lambda x: x[1]["visits"], reverse=True
    )[:50]

    print("Top 50 domains aggregated.")

    # --- 3. Find recurring content (visited 3+ times) ---
    url_visits: dict[str, dict] = defaultdict(lambda: {"count": 0, "title": "", "domain": ""})
    for e in entries:
        url_visits[e["url"]]["count"] += 1
        url_visits[e["url"]]["title"] = e["title"] or url_visits[e["url"]]["title"]
        url_visits[e["url"]]["domain"] = e["domain"]

    recurring = sorted(
        [(url, info) for url, info in url_visits.items() if info["count"] >= 3],
        key=lambda x: x[1]["count"], reverse=True,
    )[:100]

    print(f"Found {len(recurring)} recurring URLs (3+ visits).\n")

    # --- 4. Classify top domains with Haiku (batch) ---
    print("Classifying domains...")
    domain_list = "\n".join(
        f"{i+1}. {d} ({s['visits']} visits) — sample titles: {'; '.join(s['titles'][:3])}"
        for i, (d, s) in enumerate(top_domains)
    )
    classification_response = llm.complete(
        f"Classify each domain into one of: learning, professional, social, entertainment, "
        f"shopping, tools, news, other. Also add a 3-word description of what the site is.\n\n"
        f"Respond as JSON array with keys: index, domain, category, description.\n\n{domain_list}",
        system="You classify websites based on domain and content titles.",
        model=HAIKU,
        max_tokens=2048,
    )
    domain_classifications = _parse_json_array(classification_response)
    print(f"  Classified {len(domain_classifications)} domains.\n")

    # --- 5. Generate content ideas with Haiku (batched) ---
    print("Generating content ideas...")
    # Build a rich reading list from productive/learning domains
    productive_titles = []
    for e in entries:
        if e["title"] and len(e["title"]) > 15:
            productive_titles.append(f"{e['title']} ({e['domain']})")

    # Deduplicate titles
    seen = set()
    unique_titles = []
    for t in productive_titles:
        key = t[:50].lower()
        if key not in seen:
            seen.add(key)
            unique_titles.append(t)

    all_ideas = []
    # Generate in batches of ~40 titles, ask for 15 ideas each
    batch_size = 40
    ideas_per_batch = 15
    for i in range(0, min(len(unique_titles), 280), batch_size):
        batch = unique_titles[i:i + batch_size]
        reading_list = "\n".join(f"- {t}" for t in batch)
        print(f"  Ideas batch {i // batch_size + 1}...")

        response = llm.complete(
            f"Based on this reading list, suggest {ideas_per_batch} content ideas for a professional "
            f"building thought leadership in AI, SaaS strategy, and management consulting.\n\n"
            f"Each idea should have: title, angle (1 sentence), type (blog/linkedin/thread).\n"
            f"Respond as JSON array with keys: title, angle, type.\n\n"
            f"Reading:\n{reading_list}",
            system="You generate content ideas from reading patterns. Be specific and creative. "
                   "Avoid generic ideas — each should have a clear, opinionated angle.",
            model=HAIKU,
            max_tokens=2048,
        )
        batch_ideas = _parse_json_array(response)
        all_ideas.extend(batch_ideas)

    # Deduplicate ideas by title similarity
    unique_ideas = _dedup_ideas(all_ideas)[:100]
    print(f"  Generated {len(unique_ideas)} unique content ideas.\n")

    # --- 6. Generate detailed commentary with Opus ---
    print("Generating detailed commentary with Opus (this may take a minute)...")

    # Prepare summary data for Opus
    domain_summary = "\n".join(
        f"- {d}: {s['visits']} visits, {s['total_hours']:.1f}h | "
        f"Sample: {'; '.join(s['titles'][:5])}"
        for d, s in top_domains[:30]
    )

    recurring_summary = "\n".join(
        f"- [{info['count']}x] \"{info['title']}\" ({info['domain']})"
        for url, info in recurring[:50]
    )

    category_hours = defaultdict(float)
    category_visits = defaultdict(int)
    for dc in domain_classifications:
        idx = dc.get("index", 0) - 1
        if 0 <= idx < len(top_domains):
            cat = dc.get("category", "other")
            domain, stats = top_domains[idx]
            category_hours[cat] += stats["total_hours"]
            category_visits[cat] += stats["visits"]

    category_summary = "\n".join(
        f"- {cat}: {category_visits[cat]} visits, {category_hours[cat]:.1f}h"
        for cat in sorted(category_hours, key=category_hours.get, reverse=True)
    )

    commentary = llm.complete(
        f"Write a detailed, insightful commentary on this person's browsing and content "
        f"consumption from July 2025 to February 2026. This is a personal audit for the person "
        f"themselves — be honest, specific, and useful.\n\n"
        f"Cover:\n"
        f"1. Overall patterns — what are they spending their time on?\n"
        f"2. Key themes and interests that emerge\n"
        f"3. Content they kept returning to (recurring URLs) — what does this say about their obsessions?\n"
        f"4. Balance between learning/professional vs entertainment/distraction\n"
        f"5. Notable shifts or emerging interests over the ~8 month period\n"
        f"6. Blind spots — what's missing given their stated interests (AI, strategy, consulting)?\n"
        f"7. Specific recommendations for what to read more/less of\n\n"
        f"Be specific — reference actual domains, titles, and patterns. Not generic advice.\n\n"
        f"## Data\n\n"
        f"### Category breakdown\n{category_summary}\n\n"
        f"### Top domains (by visits)\n{domain_summary}\n\n"
        f"### Content visited 3+ times (obsessions)\n{recurring_summary}\n\n"
        f"### Total entries: {len(entries)} page visits over ~8 months",
        system="You are a thoughtful analyst writing a personal content consumption audit. "
               "Be specific, honest, and insightful. Write in second person ('you'). "
               "Use markdown formatting with headers and bullet points.",
        model=OPUS,
        max_tokens=4096,
    )

    # --- 7. Assemble output markdown ---
    print("Writing output...")
    md = _build_markdown(
        entries=entries,
        top_domains=top_domains,
        domain_classifications=domain_classifications,
        recurring=recurring,
        ideas=unique_ideas,
        commentary=commentary,
        cost=llm.estimate_session_cost(),
        usage=llm.get_usage_summary(),
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(md, encoding="utf-8")
    print(f"\nAudit written to: {OUTPUT_PATH}")
    print(f"API cost: ${llm.estimate_session_cost():.4f}")
    print(f"Token usage: {llm.get_usage_summary()}")


def _build_markdown(
    entries, top_domains, domain_classifications, recurring, ideas, commentary, cost, usage
) -> str:
    lines = [
        "# Browsing Audit: July 2025 – February 2026\n",
        f"*Generated {datetime.now().strftime('%B %d, %Y')} | "
        f"{len(entries)} page visits analyzed | API cost: ${cost:.4f}*\n",
        "---\n",

        "## Commentary\n",
        commentary,
        "\n---\n",

        "## Top 50 Domains\n",
        "| # | Domain | Visits | Hours | Category |",
        "|---|--------|--------|-------|----------|",
    ]

    # Build classification lookup
    class_lookup = {}
    for dc in domain_classifications:
        idx = dc.get("index", 0) - 1
        if 0 <= idx < len(top_domains):
            domain = top_domains[idx][0]
            class_lookup[domain] = (dc.get("category", ""), dc.get("description", ""))

    for i, (domain, stats) in enumerate(top_domains):
        cat, desc = class_lookup.get(domain, ("", ""))
        lines.append(
            f"| {i+1} | {domain} | {stats['visits']} | {stats['total_hours']:.1f}h | {cat} — {desc} |"
        )

    lines.append("\n---\n")
    lines.append("## Recurring Content (visited 3+ times)\n")
    lines.append("Content you kept coming back to:\n")

    for url, info in recurring:
        lines.append(f"- **[{info['count']}x]** {info['title'] or 'Untitled'} — `{info['domain']}`")

    lines.append("\n---\n")
    lines.append(f"## Content Ideas ({len(ideas)})\n")

    for i, idea in enumerate(ideas, 1):
        idea_type = idea.get("type", "blog")
        lines.append(f"### {i}. {idea.get('title', 'Untitled')}")
        lines.append(f"*Type: {idea_type}*\n")
        lines.append(f"{idea.get('angle', '')}\n")

    lines.append("---\n")
    lines.append(f"*Token usage: {json.dumps(usage, indent=2)}*\n")

    return "\n".join(lines)


def _parse_json_array(text: str) -> list[dict]:
    """Extract JSON array from LLM response."""
    start = text.find("[")
    end = text.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            LOGGER.warning("Failed to parse JSON array from response")
    return []


def _dedup_ideas(ideas: list[dict]) -> list[dict]:
    """Remove near-duplicate ideas by title similarity."""
    seen = set()
    unique = []
    for idea in ideas:
        key = idea.get("title", "").lower()[:40]
        if key and key not in seen:
            seen.add(key)
            unique.append(idea)
    return unique


if __name__ == "__main__":
    main()
