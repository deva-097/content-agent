"""HTML email formatter for Tuner digests."""

from __future__ import annotations

from datetime import date, timedelta
from itertools import groupby

from jinja2 import Template

from src.common.logger import get_logger

LOGGER = get_logger(__name__)

_DIGEST_TEMPLATE = Template("""\
<!DOCTYPE html>
<html>
<head>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 680px; margin: 0 auto; padding: 20px; color: #292524; }
  h1 { color: #0f766e; font-size: 24px; }
  h2 { color: #44403c; font-size: 18px; margin-top: 32px; border-bottom: 2px solid #0f766e; padding-bottom: 6px; }
  .meta { font-size: 13px; color: #78716c; margin-bottom: 28px; }
  .must-read-box { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px; margin-bottom: 28px; }
  .must-read-box h3 { color: #0f766e; font-size: 15px; margin: 0 0 10px 0; }
  .must-read-item { font-size: 14px; margin-bottom: 6px; }
  .must-read-item .reason { color: #78716c; font-size: 12px; }
  .show { margin-bottom: 32px; }
  .show-name { font-size: 15px; font-weight: 700; color: #0f766e; margin-bottom: 10px; border-bottom: 1px solid #e7e5e4; padding-bottom: 4px; }
  .episode { margin-bottom: 18px; padding-left: 8px; }
  .episode.starred { border-left: 3px solid #0f766e; padding-left: 10px; }
  .episode-title a { font-size: 15px; font-weight: 600; color: #292524; text-decoration: none; }
  .episode-title a:hover { color: #0f766e; }
  .star { color: #0f766e; font-weight: 700; }
  .episode-meta { font-size: 12px; color: #78716c; margin: 3px 0; }
  .episode-summary { font-size: 14px; line-height: 1.6; color: #44403c; margin-top: 4px; }
  .deep-section { margin-top: 8px; padding: 10px; background: #fafaf9; border-radius: 6px; }
  .deep-section .label { font-size: 11px; font-weight: 700; color: #78716c; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
  .key-points { margin: 4px 0 8px 0; padding-left: 16px; }
  .key-points li { font-size: 13px; line-height: 1.5; color: #44403c; margin-bottom: 3px; }
  .quote { font-style: italic; font-size: 13px; color: #57534e; margin: 6px 0; padding-left: 12px; border-left: 2px solid #d6d3d1; }
  .data-points { font-size: 12px; color: #78716c; margin-top: 4px; }
  .section-divider { border: none; border-top: 1px solid #e7e5e4; margin: 32px 0; }
  .footer { margin-top: 40px; font-size: 12px; color: #a8a29e; border-top: 1px solid #e7e5e4; padding-top: 12px; }
</style>
</head>
<body>
<h1>Tuner — Weekly Digest</h1>
<p class="meta">{{ date_range }}{% if cost %} &middot; API cost: ${{ "%.4f" | format(cost) }}{% endif %}</p>

{% if must_reads %}
<div class="must-read-box">
  <h3>★ This Week's Top Picks</h3>
  {% for item in must_reads %}
  <div class="must-read-item">
    {% if item.kind == "podcast" %}🎙{% else %}📝{% endif %}
    <strong>{{ item.title }}</strong> ({{ item.source_label }})
    {% if item.must_read_reason %}<br><span class="reason">→ {{ item.must_read_reason }}</span>{% endif %}
  </div>
  {% endfor %}
</div>
{% endif %}

{% if podcast_groups %}
<h2>🎙 Podcasts</h2>
{% for show_name, episodes in podcast_groups %}
<div class="show">
  <div class="show-name">{{ show_name }}</div>
  {% for ep in episodes %}
  <div class="episode{{ ' starred' if ep.must_read else '' }}">
    <div class="episode-title">
      {% if ep.must_read %}<span class="star">★ </span>{% endif %}
      {% if ep.url %}<a href="{{ ep.url }}">{{ ep.title }}</a>{% else %}{{ ep.title }}{% endif %}
    </div>
    <div class="episode-meta">
      {% if ep.published %}{{ ep.published.strftime('%b %d') }}{% endif %}
      {% if ep.duration %} &middot; {{ ep.duration }}{% endif %}
    </div>
    {% if ep.summary_text %}<div class="episode-summary">{{ ep.summary_text }}</div>{% endif %}
    {% if ep.deep and (ep.key_points or ep.quote) %}
    <div class="deep-section">
      {% if ep.key_points %}
      <div class="label">Key Takeaways</div>
      <ul class="key-points">
        {% for kp in ep.key_points %}<li>{{ kp }}</li>{% endfor %}
      </ul>
      {% endif %}
      {% if ep.quote %}
      <div class="label">Memorable Quote</div>
      <div class="quote">"{{ ep.quote }}"</div>
      {% endif %}
      {% if ep.data_points %}
      <div class="data-points">📊 {{ ep.data_points | join(' · ') }}</div>
      {% endif %}
    </div>
    {% endif %}
  </div>
  {% endfor %}
</div>
{% endfor %}
{% endif %}

{% if newsletter_groups %}
<hr class="section-divider">
<h2>📝 Newsletters</h2>
{% for pub_name, articles in newsletter_groups %}
<div class="show">
  <div class="show-name">{{ pub_name }}</div>
  {% for art in articles %}
  <div class="episode{{ ' starred' if art.must_read else '' }}">
    <div class="episode-title">
      {% if art.must_read %}<span class="star">★ </span>{% endif %}
      {% if art.url %}<a href="{{ art.url }}">{{ art.title }}</a>{% else %}{{ art.title }}{% endif %}
    </div>
    <div class="episode-meta">
      {% if art.published %}{{ art.published.strftime('%b %d') }}{% endif %}
    </div>
    {% if art.summary_text %}<div class="episode-summary">{{ art.summary_text }}</div>{% endif %}
    {% if art.deep and (art.key_points or art.quote) %}
    <div class="deep-section">
      {% if art.key_points %}
      <div class="label">Key Takeaways</div>
      <ul class="key-points">
        {% for kp in art.key_points %}<li>{{ kp }}</li>{% endfor %}
      </ul>
      {% endif %}
      {% if art.quote %}
      <div class="label">Memorable Quote</div>
      <div class="quote">"{{ art.quote }}"</div>
      {% endif %}
      {% if art.data_points %}
      <div class="data-points">📊 {{ art.data_points | join(' · ') }}</div>
      {% endif %}
    </div>
    {% endif %}
  </div>
  {% endfor %}
</div>
{% endfor %}
{% endif %}

{% if not podcast_groups and not newsletter_groups %}
<p>No new content this week.</p>
{% endif %}

<div class="footer">
  Generated by Content Agent &middot; Tuner
</div>
</body>
</html>
""")


def format_digest(items: list[dict], cost: float | None = None) -> str:
    """Render the Tuner digest as an HTML email body."""
    today = date.today()
    week_start = today - timedelta(days=6)
    date_range = f"{week_start.strftime('%b %d')}–{today.strftime('%b %d, %Y')}"

    def _group_by_source(items_list):
        """Sort and group items by source label."""
        sorted_items = sorted(
            items_list,
            key=lambda e: (e.get("source_label", ""), e.get("published") or date.min),
        )
        grouped = []
        for name, group in groupby(sorted_items, key=lambda e: e.get("source_label", "Unknown")):
            show_items = sorted(
                list(group),
                key=lambda e: e.get("published") or date.min,
                reverse=True,
            )
            grouped.append((name, show_items))
        grouped.sort(key=lambda x: x[0])
        return grouped

    podcasts = [i for i in items if i.get("kind") == "podcast"]
    newsletters = [i for i in items if i.get("kind") == "newsletter"]
    must_reads = [i for i in items if i.get("must_read")]

    return _DIGEST_TEMPLATE.render(
        date_range=date_range,
        podcast_groups=_group_by_source(podcasts),
        newsletter_groups=_group_by_source(newsletters),
        must_reads=must_reads,
        cost=cost,
    )
