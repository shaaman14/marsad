import asyncio
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


MARKET_TERMS = {
    "market", "markets", "stocks", "equities", "shares", "bond", "bonds",
    "yield", "yields", "treasury", "treasuries", "currency", "currencies",
    "dollar", "euro", "yen", "yuan", "oil", "gold", "copper", "commodity",
    "commodities", "inflation", "interest rate", "rates", "central bank",
    "federal reserve", "fed", "ecb", "boj", "pbo", "gdp", "jobs",
    "employment", "unemployment", "retail sales", "pmi"
}

BUSINESS_ONLY_TERMS = {
    "movie", "film", "streaming", "social media curfew", "lawsuit",
    "celebrity", "box office", "television", "entertainment"
}


def market_relevant(title, summary):
    text = f"{title} {summary}".lower()
    has_market_term = any(term in text for term in MARKET_TERMS)
    business_only = any(term in text for term in BUSINESS_ONLY_TERMS)
    return has_market_term and not business_only


def story_key(title):
    words = re.findall(r"[a-z0-9]+", title.lower())
    stop = {
        "the", "a", "an", "to", "of", "in", "on", "for", "and", "with",
        "as", "at", "by", "from", "after", "says", "new"
    }
    core = sorted({word for word in words if word not in stop and len(word) > 2})
    return "|".join(core[:10])


def infer_topic(title, summary):
    text = f"{title} {summary}".lower()
    rules = [
        ("Rates & Central Banks", ["fed", "federal reserve", "ecb", "rate cut", "rate hike", "interest rate"]),
        ("FX", ["dollar", "yen", "yuan", "euro", "currency", "fx"]),
        ("Commodities", ["oil", "gold", "copper", "uranium", "commodity"]),
        ("Equities", ["stocks", "shares", "equities", "nasdaq", "s&p"]),
        ("Economy", ["gdp", "inflation", "jobs", "employment", "pmi", "retail sales"]),
        ("Geopolitics", ["war", "ceasefire", "sanction", "election", "missile", "strike"]),
    ]
    for label, terms in rules:
        if any(term in text for term in terms):
            return label
    return "General"


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

        summary = clean(entry.get("summary") or entry.get("description"))
        if section == "markets" and not market_relevant(title, summary):
            continue

        output.append({
            "url": url,
            "title": title,
            "summary": summary,
            "source": spec["name"],
            "section": section,
            "published_at": parse_date(entry),
            "source_priority": int(spec.get("priority", 0)),
            "topic": infer_topic(title, summary),
            "story_key": story_key(title),
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

        summary = ""
        if section == "markets" and not market_relevant(title, summary):
            continue

        output.append({
            "url": url,
            "title": title,
            "summary": summary,
            "source": domain(url),
            "section": section,
            "published_at": published,
            "source_priority": 2,
            "topic": infer_topic(title, summary),
            "story_key": story_key(title),
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

    timeout = httpx.Timeout(
        connect=6.0,
        read=10.0,
        write=10.0,
        pool=6.0,
    )

    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": user_agent},
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    ) as client:

        async def run_direct(section, spec):
            try:
                items = await asyncio.wait_for(
                    fetch_direct_feed(section, spec, client),
                    timeout=12,
                )
                count = store(items)
                return count, {
                    "source": spec["name"],
                    "section": section,
                    "status": "ok",
                    "items": len(items),
                }, None
            except Exception as exc:
                return 0, {
                    "source": spec["name"],
                    "section": section,
                    "status": "error",
                    "items": 0,
                }, f'{spec["name"]}: {exc}'

        # Fetch all trusted feeds in parallel.
        direct_tasks = [
            run_direct(section, spec)
            for section, specs in config.get("direct_feeds", {}).items()
            for spec in specs
        ]
        if direct_tasks:
            direct_results = await asyncio.gather(*direct_tasks)
            for count, health, error in direct_results:
                added += count
                source_health.append(health)
                if error:
                    errors.append(error)

        fallback = config.get("fallback", {})
        if fallback.get("enabled", True):
            minimums = fallback.get("minimum_fresh_stories", {})
            queries = fallback.get("queries", {})

            async def run_fallback(section, query):
                try:
                    items = await asyncio.wait_for(
                        fetch_gdelt(section, query, client, config),
                        timeout=10,
                    )
                    return store(items), None
                except Exception as exc:
                    return 0, f"GDELT fallback {section}: {exc}"

            # At most one fallback query per section, and only where needed.
            fallback_tasks = []
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
                if current_count < required and section_queries:
                    fallback_tasks.append(
                        run_fallback(section, section_queries[0])
                    )

            if fallback_tasks:
                fallback_results = await asyncio.gather(*fallback_tasks)
                for count, error in fallback_results:
                    added += count
                    if error:
                        errors.append(error)

        # Company discovery is the slowest layer.
        # Limit to five companies per refresh and run them in parallel.
        async def run_company(company):
            try:
                items = await asyncio.wait_for(
                    fetch_gdelt("companies", company, client, config),
                    timeout=8,
                )
                return store(items), None
            except Exception as exc:
                return 0, f"Company discovery {company}: {exc}"

        companies = watchlist("company")[:5]
        if companies:
            company_results = await asyncio.gather(
                *(run_company(company) for company in companies)
            )
            for count, error in company_results:
                added += count
                if error:
                    errors.append(error)

    return {
        "added": added,
        "errors": errors,
        "source_health": source_health,
    }
