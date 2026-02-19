"""Web content fetcher with rate limiting and retry."""

from __future__ import annotations

import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .logger import get_logger

LOGGER = get_logger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_TIMEOUT = 10
_MAX_RETRIES = 3
_BACKOFF_BASE = 2
_RATE_LIMIT_SECONDS = 1.0

_last_request_time: float = 0


def _rate_limit() -> None:
    """Enforce minimum delay between requests."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _RATE_LIMIT_SECONDS:
        time.sleep(_RATE_LIMIT_SECONDS - elapsed)
    _last_request_time = time.time()


def fetch_url(url: str, *, timeout: int = _TIMEOUT) -> str | None:
    """Fetch a URL and return cleaned text content. Returns None on failure."""
    _rate_limit()

    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=timeout,
                allow_redirects=True,
            )
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            # Remove non-content elements
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()

            # Try to find article body
            article = (
                soup.find("article")
                or soup.find("main")
                or soup.find(class_="post-content")
                or soup.find(class_="entry-content")
                or soup.find(class_="article-body")
                or soup.body
            )

            if article is None:
                return None

            text = article.get_text(separator="\n", strip=True)
            # Collapse excessive whitespace
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            return "\n".join(lines)

        except requests.RequestException as e:
            LOGGER.warning(
                "Fetch attempt %d/%d failed for %s: %s",
                attempt + 1, _MAX_RETRIES, url, e,
            )
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_BACKOFF_BASE ** attempt)

    LOGGER.error("All fetch attempts failed for %s", url)
    return None


def fetch_page_title(url: str) -> str | None:
    """Fetch just the page title from a URL."""
    _rate_limit()
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        title_tag = soup.find("title")
        return title_tag.get_text(strip=True) if title_tag else None
    except requests.RequestException:
        return None


def extract_domain(url: str) -> str:
    """Extract the domain from a URL."""
    return urlparse(url).netloc
