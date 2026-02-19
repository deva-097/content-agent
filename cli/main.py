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


@cli.command()
def status():
    """Show last run times and stats for all agents."""
    from src.common.state import StateDB

    with StateDB() as db:
        runs = db.get_all_run_stats()
        if not runs:
            click.echo("No agent runs recorded yet.")
            return

        # Show latest run per agent
        seen = set()
        for run in runs:
            name = run["agent_name"]
            if name in seen:
                continue
            seen.add(name)
            click.echo(
                f"  {name:8s} | {run['status']:10s} | "
                f"started {run['run_start'][:19]} | "
                f"ended {(run['run_end'] or 'running')[:19]}"
            )


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


if __name__ == "__main__":
    cli()
