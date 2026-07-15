import hashlib
import html
import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup

from database import now_iso, save_article, watchlist

BASE = Path(__file__).parent


def clean(value, limit=500):
    if not value:
        return ""
    text = BeautifulSoup(html.unescape(value), "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)[:limit]


def domain(url):
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def allowed(url, section, config):
    host = domain(url)
    if any(host == d or host.endswith("." + d) for d in config.get("blocked_domains", [])):
        return False
    approved = config.get("allowed_domains", {}).get(section, [])
    return not approved or any(host == d or host.endswith("." + d) for d in approved)


def importance(title, summary, section):
    text = f"{title} {summary}".lower()
    score = 0
    strong = [
        "default", "downgrade", "upgrade", "merger", "acquisition",
        "rate cut", "rate hike", "war", "ceasefire", "earnings",
        "guidance", "tariff", "inflation", "bankruptcy"
    ]
    score += sum(2 for word in strong if word in text)

    for company in watchlist("company"):
        if company.lower() in title.lower():
            score += 8
        elif company.lower() in text:
            score += 5

    for theme in watchlist("theme"):
        if theme.lower() in title.lower():
            score += 5
        elif theme.lower() in text:
            score += 3

    if section == "markets":
        score += 1
    return score


def parse_date(entry):
    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        if raw:
            try:
                return parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat()
            except Exception:
                pass
    return None


async def fetch_rss(section, spec, client):
    response = await client.get(spec["url"], follow_redirects=True)
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    output = []

    for entry in parsed.entries[:40]:
        title = clean(entry.get("title"), 280)
        url = entry.get("link")
        if not title or not url:
            continue
        summary = clean(entry.get("summary") or entry.get("description"))
        output.append({
            "url": url,
            "title": title,
            "summary": summary,
            "source": spec["name"],
            "section": section,
            "published_at": parse_date(entry),
        })
    return output


async def fetch_gdelt(section, query, client, config):
    params = {
        "query": query,
        "mode": "ArtList",
        "maxrecords": 40,
        "format": "json",
        "sort": "HybridRel",
    }
    response = await client.get(
        "https://api.gdeltproject.org/api/v2/doc/doc?" + urlencode(params),
        follow_redirects=True,
    )
    response.raise_for_status()
    output = []

    for item in response.json().get("articles", []):
        title = clean(item.get("title"), 280)
        url = item.get("url")
        if not title or not url or not allowed(url, section, config):
            continue

        published = None
        raw_date = item.get("seendate")
        if raw_date:
            try:
                published = datetime.strptime(
                    raw_date[:14], "%Y%m%d%H%M%S"
                ).replace(tzinfo=timezone.utc).isoformat()
            except Exception:
                pass

        output.append({
            "url": url,
            "title": title,
            "summary": "",
            "source": domain(url),
            "section": section,
            "published_at": published,
        })
    return output


async def refresh(user_agent):
    config = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    added = 0
    errors = []

    async with httpx.AsyncClient(
        timeout=25,
        headers={"User-Agent": user_agent},
    ) as client:
        for section, feeds in config.get("rss_feeds", {}).items():
            for spec in feeds:
                try:
                    items = await fetch_rss(section, spec, client)
                    for item in items:
                        item["fetched_at"] = now_iso()
                        item["importance"] = importance(
                            item["title"], item["summary"], section
                        )
                        added += int(save_article(item))
                except Exception as exc:
                    errors.append(f'{spec["name"]}: {exc}')

        for section, queries in config.get("gdelt_queries", {}).items():
            for query in queries:
                try:
                    items = await fetch_gdelt(section, query, client, config)
                    for item in items:
                        item["fetched_at"] = now_iso()
                        item["importance"] = importance(
                            item["title"], item["summary"], section
                        )
                        added += int(save_article(item))
                except Exception as exc:
                    errors.append(f"GDELT {section}: {exc}")

        for company in watchlist("company")[:20]:
            try:
                items = await fetch_gdelt("companies", company, client, config)
                for item in items:
                    item["fetched_at"] = now_iso()
                    item["importance"] = importance(
                        item["title"], item["summary"], "companies"
                    )
                    added += int(save_article(item))
            except Exception as exc:
                errors.append(f"GDELT {company}: {exc}")

    return {"added": added, "errors": errors}
