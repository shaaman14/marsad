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

from database import now_iso, recent_articles, save_article, watchlist

BASE = Path(__file__).parent


def clean(value, limit=700):
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


def parse_date(entry):
    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        if raw:
            try:
                return parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat()
            except Exception:
                pass

    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
    return None


def importance(title, summary, section, source_priority=0):
    text = f"{title} {summary}".lower()
    score = source_priority

    strong = [
        "default", "downgrade", "upgrade", "merger", "acquisition",
        "rate cut", "rate hike", "war", "ceasefire", "earnings",
        "guidance", "tariff", "inflation", "bankruptcy", "election",
        "sanction", "central bank"
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


async def fetch_direct_feed(section, spec, client):
    response = await client.get(spec["url"], follow_redirects=True)
    response.raise_for_status()
    parsed = feedparser.parse(response.content)

    if parsed.bozo and not parsed.entries:
        raise RuntimeError(str(parsed.bozo_exception))

    output = []
    for entry in parsed.entries[:60]:
        title = clean(entry.get("title"), 300)
        url = entry.get("link")
        if not title or not url:
            continue

        output.append({
            "url": url,
            "title": title,
            "summary": clean(entry.get("summary") or entry.get("description")),
            "source": spec["name"],
            "section": section,
            "published_at": parse_date(entry),
            "source_priority": int(spec.get("priority", 0)),
        })
    return output


async def fetch_gdelt(section, query, client, config):
    params = {
        "query": query,
        "mode": "ArtList",
        "maxrecords": 25,
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
        title = clean(item.get("title"), 300)
        url = item.get("url")
        if not title or not url or not allowed(url, section, config):
            continue

        published = None
        raw = item.get("seendate")
        if raw:
            try:
                published = datetime.strptime(
                    raw[:14], "%Y%m%d%H%M%S"
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
            "source_priority": 2,
        })
    return output


def store(items):
    added = 0
    for item in items:
        item["fetched_at"] = now_iso()
        item["importance"] = importance(
            item["title"],
            item.get("summary", ""),
            item["section"],
            item.pop("source_priority", 0),
        )
        added += int(save_article(item))
    return added


async def refresh(user_agent):
    config = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    added = 0
    errors = []
    source_health = []

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        headers={"User-Agent": user_agent},
    ) as client:
        # Trusted direct feeds are always fetched first.
        for section, specs in config.get("direct_feeds", {}).items():
            for spec in specs:
                try:
                    items = await fetch_direct_feed(section, spec, client)
                    added += store(items)
                    source_health.append({
                        "source": spec["name"],
                        "section": section,
                        "status": "ok",
                        "items": len(items),
                    })
                except Exception as exc:
                    errors.append(f'{spec["name"]}: {exc}')
                    source_health.append({
                        "source": spec["name"],
                        "section": section,
                        "status": "error",
                        "items": 0,
                    })

        fallback = config.get("fallback", {})
        if fallback.get("enabled", True):
            minimums = fallback.get("minimum_fresh_stories", {})
            queries = fallback.get("queries", {})

            # Only use GDELT when direct feeds did not leave enough fresh material.
            for section, section_queries in queries.items():
                current_count = len(
                    recent_articles(
                        section,
                        limit=100,
                        hours=48 if section in {"world", "markets"} else 72,
                        require_published=True,
                    )
                )
                required = int(minimums.get(section, 0))
                if current_count >= required:
                    continue

                for query in section_queries:
                    try:
                        items = await fetch_gdelt(section, query, client, config)
                        added += store(items)
                    except Exception as exc:
                        errors.append(f"GDELT fallback {section}: {exc}")

                    current_count = len(
                        recent_articles(
                            section,
                            limit=100,
                            hours=48 if section in {"world", "markets"} else 72,
                            require_published=True,
                        )
                    )
                    if current_count >= required:
                        break

        # Company discovery remains query-based until direct IR/entity feeds are added.
        for company in watchlist("company")[:20]:
            try:
                items = await fetch_gdelt("companies", company, client, config)
                added += store(items)
            except Exception as exc:
                errors.append(f"Company discovery {company}: {exc}")

    return {
        "added": added,
        "errors": errors,
        "source_health": source_health,
    }
