"""Fetch entries from RSS feeds and blog pages."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urljoin

import feedparser

from src.common.logger import get_logger
from src.common.scraper import fetch_url

LOGGER = get_logger(__name__)


def fetch_rss_entries(
    feed_url: str, since: datetime | None = None, max_items: int = 10
) -> list[dict]:
    """Parse an RSS/Atom feed and return entries newer than *since*."""
    LOGGER.info("Fetching RSS feed: %s", feed_url)
    feed = feedparser.parse(feed_url)

    if feed.bozo and not feed.entries:
        LOGGER.warning("Feed parse error for %s: %s", feed_url, feed.bozo_exception)
        return []

    entries = []
    for entry in feed.entries[:max_items]:
        published = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
            published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

        if since and published and published <= since:
            continue

        entries.append({
            "title": entry.get("title", "Untitled"),
            "url": entry.get("link", ""),
            "published": published,
            "summary": entry.get("summary", ""),
            "source_type": "rss",
        })

    LOGGER.info("Got %d entries from RSS feed", len(entries))
    return entries


def fetch_blog_entries(
    blog_url: str, since: datetime | None = None, max_items: int = 10
) -> list[dict]:
    """Scrape a blog index page for article links. Fallback for non-RSS sources."""
    from bs4 import BeautifulSoup
    import requests

    LOGGER.info("Scraping blog page: %s", blog_url)
    try:
        resp = requests.get(
            blog_url,
            headers={"User-Agent": "ContentAgent/0.1"},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        LOGGER.warning("Failed to fetch blog page %s: %s", blog_url, e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Find article links — common patterns
    article_links = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        # Heuristic: links with date-like patterns or /post/ /blog/ /article/ paths
        if any(seg in href for seg in ["/post/", "/blog/", "/article/", "/p/"]):
            full_url = urljoin(blog_url, href)
            article_links.add(full_url)

    # Also check <article> tags for links
    for article in soup.find_all("article"):
        for a_tag in article.find_all("a", href=True):
            full_url = urljoin(blog_url, a_tag["href"])
            article_links.add(full_url)

    entries = []
    for url in list(article_links)[:max_items]:
        title_text = ""
        # Try to get title from the link text on the page
        for a_tag in soup.find_all("a", href=True):
            if urljoin(blog_url, a_tag["href"]) == url:
                title_text = a_tag.get_text(strip=True)
                if len(title_text) > 10:  # Likely an actual title
                    break

        entries.append({
            "title": title_text or url.split("/")[-1].replace("-", " ").title(),
            "url": url,
            "published": None,
            "summary": "",
            "source_type": "blog",
        })

    LOGGER.info("Found %d article links from blog page", len(entries))
    return entries


def fetch_all_sources(
    sources_config: list[dict], since: datetime | None = None, max_items: int = 10
) -> list[dict]:
    """Fetch entries from all configured sources."""
    all_entries = []
    for source in sources_config:
        source_type = source.get("type", "rss")
        url = source["url"]
        label = source.get("label", url)

        try:
            if source_type == "rss":
                entries = fetch_rss_entries(url, since=since, max_items=max_items)
            else:
                entries = fetch_blog_entries(url, since=since, max_items=max_items)

            # Tag entries with source label
            for entry in entries:
                entry["source_label"] = label

            all_entries.extend(entries)
        except Exception as e:
            LOGGER.error("Failed to fetch source '%s' (%s): %s", label, url, e)

    return all_entries
