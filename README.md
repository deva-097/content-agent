# content-agent

Personal content pipeline with three agents: **Scout** (discover), **Mirror** (analyze), **Scribe** (draft).

Built for personal brand building across an Astro blog and LinkedIn.

## Agents

**Scout** — Scans RSS feeds + web for relevant content, emails a curated digest.
- Schedule: Wednesday 7 PM + Saturday 9 AM
- Model: Haiku (~$0.05/run)

**Mirror** — Reads Chrome browsing history, classifies URLs, generates a time audit and content ideas.
- Schedule: Saturday 10 AM
- Model: Haiku (~$0.03/run)

**Scribe** — Generates blog post or LinkedIn drafts, saves to Obsidian for review.
- On-demand via CLI
- Model: Sonnet (~$0.03/draft)

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # Fill in ANTHROPIC_API_KEY + SMTP credentials
```

## Usage

```bash
# Run agents
python -m cli.main scout --dry-run
python -m cli.main mirror --dry-run
python -m cli.main scribe "AI agents replacing SaaS" --type blog
python -m cli.main scribe "Why RAG still matters" --type linkedin --context "Counter the 'RAG is dead' narrative"
python -m cli.main scribe --from-ideas --type blog

# Utilities
python -m cli.main status    # Last run times
python -m cli.main ideas     # Unused content ideas
python -m cli.main cost      # Monthly API spend
```

## Configuration

Edit `config.yaml` to add RSS feeds, search topics, productive/waste domains, and output paths.

## Scheduling

```bash
bash launchd/install.sh                       # Install macOS schedules
launchctl list | grep content-agent           # Verify
```

launchd runs missed jobs when the machine wakes from sleep.

## Cost

~$1/month with default settings.

## Roadmap

See [GitHub Issues](https://github.com/deva-097/content-agent/issues) for planned improvements and new agents.
