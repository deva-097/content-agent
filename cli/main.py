"""CLI entry point for content-agent."""

from __future__ import annotations

import click

from src.common.logger import get_logger

LOGGER = get_logger(__name__)


@click.group()
def cli():
    """Content Agent — personal content discovery and drafting pipeline."""
    pass


@cli.command()
@click.option("--dry-run", is_flag=True, help="Print digest instead of emailing")
def scout(dry_run: bool):
    """Run the Scout agent (internet scanner)."""
    from src.scout.agent import run_scout

    run_scout(dry_run=dry_run)


@cli.command()
@click.option("--dry-run", is_flag=True, help="Print digest instead of emailing")
def tuner(dry_run: bool):
    """Run the Tuner agent (weekly podcast digest)."""
    from src.tuner.agent import run_tuner

    run_tuner(dry_run=dry_run)


@cli.command()
@click.option("--dry-run", is_flag=True, help="Print report instead of emailing")
def mirror(dry_run: bool):
    """Run the Mirror agent (Chrome history analyzer)."""
    from src.mirror.agent import run_mirror

    run_mirror(dry_run=dry_run)


@cli.command()
@click.argument("topic", required=False)
@click.option(
    "--type", "content_type",
    type=click.Choice(["blog", "linkedin"]),
    default="blog",
    help="Type of content to generate",
)
@click.option("--context", default="", help="Additional context or angle")
@click.option("--notes", default="", help="Personal notes to incorporate")
@click.option("--from-ideas", is_flag=True, help="Generate from stored content ideas")
def scribe(topic, content_type, context, notes, from_ideas):
    """Run the Scribe agent (draft publisher)."""
    from src.scribe.agent import run_scribe

    if not topic and not from_ideas:
        click.echo("Provide a topic or use --from-ideas")
        return

    run_scribe(
        topic=topic,
        content_type=content_type,
        context=context,
        notes=notes,
        from_ideas=from_ideas,
    )


@cli.command("weekly-brief")
@click.option("--dry-run", is_flag=True, help="Print brief instead of emailing")
def weekly_brief(dry_run: bool):
    """Run the Stevens agent (weekly advisor brief)."""
    from src.weekly_brief.agent import run_weekly_brief

    run_weekly_brief(dry_run=dry_run)


@cli.command()
@click.option("--last", default=5, type=int, help="Number of recent runs to show per agent")
def status(last: int):
    """Show run history, costs, and stats for all agents."""
    import json
    from src.common.state import StateDB

    with StateDB() as db:
        runs = db.get_all_run_stats()
        if not runs:
            click.echo("No agent runs recorded yet.")
            return

        # Group runs by agent
        by_agent: dict[str, list[dict]] = {}
        for run in runs:
            name = run["agent_name"]
            by_agent.setdefault(name, []).append(run)

        total_cost = 0.0
        total_runs = 0

        for agent_name in sorted(by_agent):
            agent_runs = by_agent[agent_name][:last]
            click.echo(f"\n  {agent_name.upper()}")
            click.echo(f"  {'─' * 60}")
            for run in agent_runs:
                summary = {}
                if run["summary"]:
                    try:
                        summary = json.loads(run["summary"])
                    except (json.JSONDecodeError, TypeError):
                        pass

                cost = summary.get("estimated_cost_usd", 0)
                total_cost += cost
                total_runs += 1

                # Build a compact notes string from summary keys
                notes_parts = []
                for key in ("articles_picked", "items_found", "total_entries", "drafts_created"):
                    if key in summary:
                        label = key.replace("_", " ")
                        notes_parts.append(f"{summary[key]} {label}")
                notes_str = " · ".join(notes_parts) if notes_parts else ""

                date_str = run["run_start"][:10]
                status_icon = "+" if run["status"] == "completed" else "x" if run["status"] == "failed" else "~"
                cost_str = f"${cost:.4f}" if cost else "  --"

                line = f"  {status_icon} {date_str}  {cost_str:>8s}"
                if notes_str:
                    line += f"  {notes_str}"
                click.echo(line)

        click.echo(f"\n  {'─' * 60}")
        click.echo(f"  Total: {total_runs} runs | ${total_cost:.4f}")
        click.echo()


@cli.command()
def ideas():
    """List unused content ideas from Scout and Mirror."""
    from src.common.state import StateDB

    with StateDB() as db:
        ideas_list = db.get_unused_ideas()
        if not ideas_list:
            click.echo("No unused content ideas.")
            return

        for idea in ideas_list:
            click.echo(
                f"  [{idea['id']}] ({idea['source_agent']}) {idea['idea']}"
            )
            if idea.get("context"):
                click.echo(f"       → {idea['context']}")


@cli.command()
def cost():
    """Show estimated API cost for the current month."""
    from src.common.state import StateDB
    import json

    with StateDB() as db:
        usage = db.get_monthly_token_usage()
        if not usage:
            click.echo("No API usage recorded this month.")
            return

        total_cost = 0.0
        for run in usage:
            run_cost = run.get("estimated_cost_usd", 0)
            total_cost += run_cost

        click.echo(f"  Monthly API cost estimate: ${total_cost:.4f}")
        click.echo(f"  Runs this month: {len(usage)}")


@cli.group()
def compass():
    """Compass — manage your content idea repository."""
    pass


@compass.command("add")
@click.argument("idea")
@click.option("--format", "fmt", type=click.Choice(["blog", "linkedin", "both"]), default=None)
@click.option("--target-date", default=None, help="Target publish date (YYYY-MM-DD)")
@click.option("--tags", default=None, help="Comma-separated tags")
@click.option("--notes", default=None, help="Free-text notes")
def compass_add(idea, fmt, target_date, tags, notes):
    """Add a new content idea."""
    from src.common.state import StateDB
    from src.compass.store import add_idea

    with StateDB() as db:
        idea_id = add_idea(db._conn, idea, format=fmt, target_date=target_date, tags=tags, notes=notes)
        click.echo(f"Added idea #{idea_id}: {idea}")


@compass.command("list")
@click.option("--status", default=None, help="Filter by status")
@click.option("--tag", default=None, help="Filter by tag")
def compass_list(status, tag):
    """List content ideas."""
    from src.common.state import StateDB
    from src.compass.store import list_ideas

    with StateDB() as db:
        ideas = list_ideas(db._conn, status=status, tag=tag)
        if not ideas:
            click.echo("No ideas found.")
            return
        for i in ideas:
            status_str = i["status"]
            date_str = f" | due {i['target_date']}" if i["target_date"] else ""
            tags_str = f" | [{i['tags']}]" if i["tags"] else ""
            click.echo(f"  #{i['id']} [{status_str}] {i['idea']}{date_str}{tags_str}")


@compass.command("show")
@click.argument("idea_id", type=int)
def compass_show(idea_id):
    """Show full details of a content idea."""
    from src.common.state import StateDB
    from src.compass.store import get_idea

    with StateDB() as db:
        idea = get_idea(db._conn, idea_id)
        if not idea:
            click.echo(f"Idea #{idea_id} not found.")
            return
        click.echo(f"  ID:          {idea['id']}")
        click.echo(f"  Idea:        {idea['idea']}")
        click.echo(f"  Format:      {idea['format'] or '-'}")
        click.echo(f"  Status:      {idea['status']}")
        click.echo(f"  Target date: {idea['target_date'] or '-'}")
        click.echo(f"  Tags:        {idea['tags'] or '-'}")
        click.echo(f"  Notes:       {idea['notes'] or '-'}")
        click.echo(f"  Created:     {idea['created_at'][:19]}")
        click.echo(f"  Updated:     {idea['updated_at'][:19]}")


@compass.command("update")
@click.argument("idea_id", type=int)
@click.option("--idea", default=None, help="New idea text")
@click.option("--format", "fmt", type=click.Choice(["blog", "linkedin", "both"]), default=None)
@click.option("--status", type=click.Choice(["backlog", "planned", "in-progress", "published"]), default=None)
@click.option("--target-date", default=None, help="Target publish date (YYYY-MM-DD)")
@click.option("--tags", default=None, help="Comma-separated tags")
@click.option("--notes", default=None, help="Free-text notes")
def compass_update(idea_id, idea, fmt, status, target_date, tags, notes):
    """Update fields on a content idea."""
    from src.common.state import StateDB
    from src.compass.store import update_idea, get_idea

    fields = {}
    if idea is not None:
        fields["idea"] = idea
    if fmt is not None:
        fields["format"] = fmt
    if status is not None:
        fields["status"] = status
    if target_date is not None:
        fields["target_date"] = target_date
    if tags is not None:
        fields["tags"] = tags
    if notes is not None:
        fields["notes"] = notes

    if not fields:
        click.echo("No fields to update. Use --help to see options.")
        return

    with StateDB() as db:
        if not get_idea(db._conn, idea_id):
            click.echo(f"Idea #{idea_id} not found.")
            return
        update_idea(db._conn, idea_id, **fields)
        click.echo(f"Updated idea #{idea_id}.")


@compass.command("delete")
@click.argument("idea_id", type=int)
def compass_delete(idea_id):
    """Delete a content idea."""
    from src.common.state import StateDB
    from src.compass.store import get_idea, delete_idea

    with StateDB() as db:
        if not get_idea(db._conn, idea_id):
            click.echo(f"Idea #{idea_id} not found.")
            return
        delete_idea(db._conn, idea_id)
        click.echo(f"Deleted idea #{idea_id}.")


if __name__ == "__main__":
    cli()
