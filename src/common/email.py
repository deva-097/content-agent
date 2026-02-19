"""Email sender for content-agent digests and reports."""

from __future__ import annotations

import os
import re
import smtplib
from email.message import EmailMessage
from typing import Sequence

from .logger import get_logger

LOGGER = get_logger(__name__)
DEFAULT_ENV_PREFIX = "CONTENT_AGENT"


def _env_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env(prefix: str, key: str, default: str | None = None) -> str | None:
    return os.environ.get(f"{prefix}_{key}", default)


def parse_recipients(candidates: str | Sequence[str] | None) -> list[str]:
    """Split a comma/semicolon separated string into recipient list."""
    if candidates is None:
        return []
    if isinstance(candidates, str):
        parts = re.split(r"[;,]", candidates)
    else:
        parts = list(candidates)
    return [p.strip() for p in parts if p and p.strip()]


def send_html_email(
    *,
    subject: str,
    html_body: str,
    plain_body: str | None = None,
    env_prefix: str = DEFAULT_ENV_PREFIX,
    recipients: Sequence[str] | None = None,
    sender: str | None = None,
) -> None:
    """Send an HTML email via SMTP using env-backed credentials."""
    recipients = parse_recipients(recipients) or parse_recipients(
        _env(env_prefix, "EMAIL_TO")
    )
    if not recipients:
        raise ValueError("No email recipients configured.")

    sender = sender or _env(env_prefix, "EMAIL_FROM")
    if not sender:
        raise ValueError(f"Missing sender email (set {env_prefix}_EMAIL_FROM).")

    smtp_host = _env(env_prefix, "SMTP_HOST")
    smtp_port = int(_env(env_prefix, "SMTP_PORT", "465"))
    smtp_user = _env(env_prefix, "SMTP_USERNAME")
    smtp_pass = _env(env_prefix, "SMTP_PASSWORD")
    use_starttls = _env_bool(_env(env_prefix, "SMTP_STARTTLS"))
    dry_run = _env_bool(_env(env_prefix, "SMTP_DRY_RUN"))

    if not smtp_host:
        raise ValueError(f"Missing SMTP host (set {env_prefix}_SMTP_HOST).")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)

    if plain_body:
        msg.set_content(plain_body)
        msg.add_alternative(html_body, subtype="html")
    else:
        msg.set_content(html_body, subtype="html")

    if dry_run:
        LOGGER.info(
            "[DRY RUN] Would send '%s' to %s via %s:%s",
            subject, recipients, smtp_host, smtp_port,
        )
        LOGGER.info("[DRY RUN] Body preview:\n%s", html_body[:500])
        return

    if use_starttls:
        with smtplib.SMTP(smtp_host, smtp_port) as client:
            client.starttls()
            if smtp_user and smtp_pass:
                client.login(smtp_user, smtp_pass)
            client.send_message(msg)
    else:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as client:
            if smtp_user and smtp_pass:
                client.login(smtp_user, smtp_pass)
            client.send_message(msg)

    LOGGER.info("Sent email '%s' to %s", subject, recipients)
