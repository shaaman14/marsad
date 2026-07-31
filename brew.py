from event_engine import cluster
import asyncio
import json
import os
import re
from collections import defaultdict
from functools import lru_cache

import httpx

from sources import enrich_lead
from datetime import datetime, timezone as dt_timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from database import get_company_snapshot, get_market_snapshot, recent_articles, watchlist

DIVIDER = "━━━━━━━━━━━━━━━━━━"

COFFEE_BREAK_ITEMS = [
    ("🧠 Trivia", "Which commodity gave its name to the word “salary”?", "Salt. Roman soldiers were sometimes associated with a salt allowance, giving rise to the Latin root behind “salary.”"),
    ("🏛 Financial History", "What was the first modern stock index?", "The Dow Jones Transportation Average, created in 1884, predates the Dow Jones Industrial Average."),
    ("🌍 Did You Know?", "Which country has the most islands?", "Sweden, with more than 260,000 islands."),
    ("🧠 Trivia", "What was the first company to reach a US$1 trillion market value?", "Apple, in August 2018."),
    ("🏛 Financial History", "Why do markets use bulls and bears?", "A bull attacks upward with its horns; a bear swipes downward with its paws."),
    ("🌍 Did You Know?", "Which desert is the largest in the world?", "Antarctica. A desert is defined by low precipitation, not heat."),
    ("🧠 Trivia", "What does the S in S&P stand for?", "Standard. Standard Statistics merged with Poor’s Publishing in 1941."),
    ("🏛 Financial History", "What was the Buttonwood Agreement?", "A 1792 pact among 24 brokers that helped form the institution that became the New York Stock Exchange."),
]


@lru_cache(maxsize=1)
def _cached_config_text():
    return (Path(__file__).parent / "config.json").read_text(encoding="utf-8")


def load_config():
    return json.loads(_cached_config_text())


def age_label(published_at):
    if not published_at:
        return "time unavailable"
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        hours = max(0, int((datetime.now(dt_timezone.utc) - dt.astimezone(dt_timezone.utc)).total_seconds() // 3600))
        if hours < 1:
            return "<1h ago"
        if hours < 24:
            return f"{hours}h ago"
        return f"{hours // 24}d ago"
    except Exception:
        return "time unavailable"


def freshness_score(published_at):
    """Return a small freshness bonus without parsing display labels."""
    if not published_at:
        return 0

    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)

        hours = max(
            0,
            int(
                (
                    datetime.now(dt_timezone.utc)
                    - dt.astimezone(dt_timezone.utc)
                ).total_seconds()
                // 3600
            ),
        )
        return max(0, 8 - min(hours, 8))
    except Exception:
        return 0


WIRE_BOILERPLATE_PATTERNS = [
    r"\baccording to [^,.]+[,]?\s*",
    r"\bthe company said in a statement[,]?\s*",
    r"\bin a statement (released )?(on \w+ )?",
    r"\bsources (familiar with the matter |close to the matter |with knowledge of the matter )?(said|told reuters|told cnbc)[,]?\s*",
    r"\bon (monday|tuesday|wednesday|thursday|friday|saturday|sunday)[,]?\s*",
    r"\b(reuters|cnbc|bloomberg) (reported|reports)( that)?\s*",
]


def strip_boilerplate(text):
    for pattern in WIRE_BOILERPLATE_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    # Attribution clauses ("sources said", "said in a statement") are almost
    # always followed by "that ..."; once the attribution itself is
    # stripped, a leading "that" left dangling at the start reads as broken
    # grammar, so drop it too.
    text = re.sub(r"^that\s+", "", text.strip(), flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def clean_summary(item_or_cluster, include_title=True):
    """Build a lead sentence without quoting wire copy verbatim.

    Previously this lifted the first sentence of the raw feed summary
    unchanged, which is why the brief read like a copy-paste of the source
    article rather than an editor's take. Instead: lead with the title
    (typically the cleanest, most declarative part of any feed item), strip
    common wire-service boilerplate ("according to...", "sources said",
    weekday datelines) from the summary, and only append it as a second
    clause when it's genuinely distinct new information rather than a
    reworded echo of the title. When called with a cluster (not a bare
    item), also note how many other outlets are covering the same story --
    that cross-source signal is itself editorial context a single-source
    clip can't give you.
    """
    if "items" in item_or_cluster:
        cluster = item_or_cluster
        item = cluster["lead"]
        other_sources = len({a.get("source") for a in cluster["items"]}) - 1
    else:
        item = item_or_cluster
        other_sources = 0

    title = item["title"].strip().rstrip(".")
    summary = strip_boilerplate(re.sub(r"\s+", " ", (item.get("summary") or "").strip()))

    detail = ""
    if summary:
        first = summary.split(". ")[0].strip().rstrip(".")
        vague = ("while ", "weak demand", "this ", "it ", "they ", "the country", "the company")
        distinct = 40 <= len(first) <= 220 and not first.lower().startswith(vague) and not similar(first, title)
        if distinct:
            detail = first

    if include_title:
        body = title + (", " + detail[0].lower() + detail[1:] if detail else "")
    else:
        # Caller (e.g. world_section) already shows the title in a heading,
        # so don't repeat it here -- but never return an empty body.
        body = detail if detail else title

    coverage = f" ({other_sources} other outlets are also on this)" if other_sources >= 2 else ""
    return body + coverage + "."


def sentence_join(prefix, sentence):
    """Join prose without corrupting acronyms such as US, UK or AI."""
    sentence = sentence.strip()
    if not sentence:
        return prefix
    return prefix + sentence



def source_quality(item, config):
    source = item.get("source") or ""
    quality = config.get("source_quality", {})
    return int(quality.get(source, 0))


def full_story_text(item):
    return (
        item.get("title", "") + " "
        + (item.get("summary") or "") + " "
        + (item.get("source") or "")
    ).lower()


def dynamic_market_topic(item):
    text = full_story_text(item)
    rules = [
        ("M&A", [
            "acquisition", "acquire", "takeover", "merger", "offer price",
            "stake talks", "majority stake", "buyout", "bid for", "sell stake"
        ]),
        ("Rates & Central Banks", [
            "federal reserve", " fed ", "ecb", "boj", "bank of japan",
            "pboc", "rate hike", "rate cut", "interest rate",
            "bond-buying", "bond buying", "treasury yield", "bond yield"
        ]),
        ("Commodities", [
            "oil", "gold", "copper", "uranium", "commodity", "commodities"
        ]),
        ("Economy", [
            "gdp", "inflation", "jobs report", "employment data", "pmi",
            "retail sales", "household expectations", "consumer prices"
        ]),
        ("FX", [
            "dollar rises", "dollar falls", "yen rises", "yen falls",
            "yuan rises", "yuan falls", "euro rises", "euro falls",
            "currency market", "foreign exchange", " fx "
        ]),
        ("Equities", [
            "stocks", "shares", "equities", "nasdaq", "s&p", "stock"
        ]),
    ]
    for label, terms in rules:
        if any(term in text for term in terms):
            return label
    return "Corporate News" if item.get("section") == "markets" else (item.get("topic") or "General")


def dynamic_region(item):
    text = full_story_text(item)

    # More specific geopolitical regions first.
    rules = [
        ("Europe", [
            "ukraine", "kyiv", "russia", "moscow", "european union",
            "europe", "france", "germany", "italy", "spain", "britain",
            "united kingdom"
        ]),
        ("Middle East", [
            "iran", "israel", "gaza", "bahrain", "kuwait", "qatar",
            "saudi", "uae", "united arab emirates", "hormuz",
            "hezbollah", "middle east"
        ]),
        ("Asia", [
            "china", "japan", "korea", "india", "singapore", "malaysia",
            "indonesia", "thailand", "philippines", "taiwan", "hong kong",
            "asia", "anwar", "takaichi"
        ]),
        ("Africa", [
            "africa", "nigeria", "kenya", "ethiopia", "south africa",
            "egypt", "morocco", "algeria", "tunisia"
        ]),
        ("Americas", [
            "united states", "u.s.", "us ", "american", "washington",
            "pentagon", "trump", "biden", "canada", "mexico", "brazil",
            "argentina", "latin america"
        ]),
    ]
    for region, terms in rules:
        if any(term in text for term in terms):
            return region

    stored = item.get("region")
    return stored if stored and stored != "Global" else "Global"


def story_allowed(item, config):
    text = full_story_text(item)
    normalized_text = re.sub(r"[^\w]", "", text)
    blocked = {
        re.sub(r"[^\w]", "", value.lower())
        for value in (
            config.get("blocked_source_names")
            or config.get("company_source_blocklist", [])
        )
    }

    # Google News can label the source Yahoo while the actual publisher
    # appears in the headline, so check the entire story text. Compared in
    # normalized (punctuation/space-stripped) form since Google News
    # sometimes labels the source as a raw domain (e.g. "bitcoinworld.co.in")
    # instead of the outlet's display name ("Bitcoin World").
    if any(source and source in normalized_text for source in blocked):
        return False

    for pattern in config.get("company_junk_patterns", []):
        if re.search(pattern, text, flags=re.IGNORECASE):
            return False

    return True


def world_story_score(item, config):
    text = full_story_text(item)
    score = int(item.get("importance", 0))
    score += source_quality(item, config)
    score += source_quality(item, config)

    for term, weight in config.get("world_high_value_terms", {}).items():
        if term in text:
            score += int(weight)

    for term in config.get("world_low_value_terms", []):
        if term in text:
            score -= 30

    return score



def market_story_score(item, config):
    """Rank market news by investor impact, source quality and freshness."""
    text = full_story_text(item)
    score = int(item.get("importance", 0))
    score += source_quality(item, config) * 2
    score += freshness_score(item.get("published_at"))

    for rule in config.get("macro_priority_rules", []):
        terms = [str(term).lower() for term in rule.get("terms", [])]
        if terms and any(term in text for term in terms):
            score += int(rule.get("weight", 0))

    for term in config.get("market_low_value_terms", []):
        if str(term).lower() in text:
            score -= 35

    return score


def token_set(text):
    stop = {
        "the","a","an","to","of","in","on","for","and","with","as","at","by","from",
        "after","says","new","live","latest","amid","over","into","its","is","are"
    }
    return {
        t for t in re.findall(r"[a-z0-9]+", text.lower())
        if t not in stop and len(t) > 2
    }


def similar(a, b):
    ta, tb = token_set(a), token_set(b)
    if not ta or not tb:
        return False
    overlap = len(ta & tb)
    return overlap >= 3 and overlap / min(len(ta), len(tb)) >= 0.45


def cluster_events(items, limit=12):
    clusters = []
    for item in items:
        placed = False
        for cluster in clusters:
            if similar(item["title"], cluster["lead"]["title"]):
                cluster["items"].append(item)
                # Best lead: higher importance, then better summary length.
                current = cluster["lead"]
                if (
                    item.get("importance", 0),
                    len(item.get("summary") or "")
                ) > (
                    current.get("importance", 0),
                    len(current.get("summary") or "")
                ):
                    cluster["lead"] = item
                placed = True
                break
        if not placed:
            clusters.append({"lead": item, "items": [item]})

    for cluster in clusters:
        cluster["score"] = (
            cluster["lead"].get("importance", 0)
            + min(len({x.get("source") for x in cluster["items"]}), 4) * 2
            + freshness_score(cluster["lead"].get("published_at"))
        )
    clusters.sort(key=lambda c: c["score"], reverse=True)
    return clusters[:limit]


async def enrich_clusters(clusters, client):
    """Concurrently top up any cluster leads whose stored summary is too
    thin to synthesize from. Only called on the small number of clusters
    actually about to be rendered, not the full candidate pool, so this
    adds a handful of concurrent requests per brief rather than hundreds.
    """
    if not clusters:
        return clusters
    enriched_leads = await asyncio.gather(
        *(enrich_lead(cluster["lead"], client) for cluster in clusters)
    )
    for cluster, lead in zip(clusters, enriched_leads):
        cluster["lead"] = lead
    return clusters


def source_line(cluster):
    sources = []
    for item in cluster["items"]:
        src = item.get("source") or "Source"
        if src not in sources:
            sources.append(src)
    lead = cluster["lead"]
    linked = f'<a href="{escape(lead["url"], quote=True)}">{escape(sources[0])}</a>'
    others = " • ".join(escape(s) for s in sources[1:3])
    suffix = f" • {others}" if others else ""
    return f"{linked}{suffix} · {escape(age_label(lead.get('published_at')))}"


def why_it_matters(item):
    topic = item.get("topic") or "General"
    mapping = {
        "Rates & Central Banks": "This can shift bond yields, currencies and equity valuations.",
        "FX": "Currency moves affect imported inflation, earnings translation and cross-border returns.",
        "Commodities": "Commodity prices feed into inflation, trade balances and producer earnings.",
        "Equities": "This signals where risk appetite and sector leadership are moving.",
        "Economy": "The data can change growth expectations and the likely path of monetary policy.",
        "Geopolitics": "Escalation can affect energy, shipping, inflation and broad risk sentiment.",
    }
    return mapping.get(topic, "")



def market_snapshot_section():
    rows = get_market_snapshot()
    if not rows:
        return "<b>📊 Market Snapshot</b>\n\nMarket data unavailable."

    lines = ["<b>📊 Market Snapshot</b>"]
    for row in rows:
        value = row.get("value")
        change = row.get("change_pct")
        if value is None:
            continue

        if row["name"] == "UST 10Y":
            if value < 1:
                value *= 10
            elif value > 20:
                value /= 10
            value_text = f"{value:.2f}%"
        elif row["name"] in {"USD/JPY", "USD/CNH"}:
            value_text = f"{value:.3f}"
        elif value >= 1000:
            value_text = f"{value:,.0f}"
        else:
            value_text = f"{value:,.2f}"

        move = ""
        if change is not None:
            if change > 0:
                move = f" 🟢 ▲ {abs(change):.2f}%"
            elif change < 0:
                move = f" 🔴 ▼ {abs(change):.2f}%"
            else:
                move = " ⚪ 0.00%"

        lines.append(f"<b>{escape(row['name'])}</b>  {value_text}{move}")
    return "\n".join(lines)

async def world_section(items, client):
    cfg = load_config()
    display = cfg.get("brew_display", {})
    limit = int(display.get("world_items", 6))
    max_per_region = int(display.get("world_max_per_region", 2))
    ranked_items = []

    for item in items:
        copy = dict(item)
        copy["importance"] = world_story_score(copy, cfg)
        # Breadth mode: keep almost all credible fresh stories and use
        # scoring only to order them, rather than excluding lower-ranked news.
        if copy["importance"] < -10:
            continue
        ranked_items.append(copy)

    clusters = cluster_events(ranked_items, 40)
    selected = []
    region_counts = defaultdict(int)

    for cluster in clusters:
        region = dynamic_region(cluster["lead"])
        if region_counts[region] >= max_per_region:
            continue
        selected.append(cluster)
        region_counts[region] += 1
        if len(selected) >= limit:
            break

    # Fill any remaining slots regardless of region so useful stories are not
    # omitted simply because several developments occurred in one geography.
    if len(selected) < limit:
        for cluster in clusters:
            if cluster not in selected:
                selected.append(cluster)
            if len(selected) >= limit:
                break

    if not selected:
        return "<b>🌍 Around the World</b>\n\nNo material fresh developments."

    selected = await enrich_clusters(selected, client)
    blocks = ["<b>🌍 Around the World</b>"]
    for cluster in selected:
        lead = cluster["lead"]
        blocks.append(
            f'<b>{escape(dynamic_region(lead))}: '
            f'{escape(lead["title"])}</b>\n'
            f'{escape(clean_summary(cluster, include_title=False))}\n'
            f'<i>{source_line(cluster)}</i>'
        )

    return "\n\n".join(blocks)


async def markets_section(items, client):
    cfg = load_config()
    display = cfg.get("brew_display", {})
    limit = int(display.get("market_items", 8))
    max_per_topic = int(display.get("market_max_per_topic", 2))
    ranked_items = []
    for item in items:
        copy = dict(item)
        copy["importance"] = market_story_score(copy, cfg)
        ranked_items.append(copy)

    clusters = cluster_events(ranked_items, 40)
    chosen = []
    topic_counts = defaultdict(int)

    # Breadth mode: permit more than one story per category. Ranking decides
    # order, but does not force one headline per topic or discard useful items.
    for cluster in clusters:
        topic = dynamic_market_topic(cluster["lead"])
        if topic_counts[topic] >= max_per_topic:
            continue
        chosen.append(cluster)
        topic_counts[topic] += 1
        if len(chosen) >= limit:
            break

    if len(chosen) < limit:
        for cluster in clusters:
            if cluster not in chosen:
                chosen.append(cluster)
            if len(chosen) >= limit:
                break

    if not chosen:
        return "<b>📈 Markets</b>\n\nNo material fresh market developments."

    chosen = await enrich_clusters(chosen, client)
    blocks = ["<b>📈 Markets</b>"]
    for cluster in chosen:
        lead = cluster["lead"]
        topic = dynamic_market_topic(lead)
        block = f'<b>{escape(topic)}</b>\n{escape(clean_summary(cluster))}'
        why = why_it_matters({**lead, "topic": topic})
        if why:
            block += f"\n<i>Why it matters: {escape(why)}</i>"
        block += f"\n<i>{source_line(cluster)}</i>"
        blocks.append(block)
    return "\n\n".join(blocks)



def company_event_score(item, config):
    text = (item["title"] + " " + (item.get("summary") or "")).lower()
    score = int(item.get("importance", 0)) + source_quality(item, config)

    for term, weight in config.get("company_event_weights", {}).items():
        if term in text:
            score += int(weight)

    for term in config.get("company_junk_terms", []):
        if term in text:
            score -= 25

    return score


def company_price_line(company):
    row = get_company_snapshot(company)
    if not row or row.get("value") is None:
        return "<i>Verified price unavailable.</i>"
    if row.get("validation_status") != "verified":
        return "<i>Verified price unavailable.</i>"

    currency = (row.get("currency") or "").upper()
    symbol = row.get("symbol") or ""
    exchange = row.get("exchange") or ""
    value = float(row["value"])
    price = f"{value:,.2f}"
    prefix = "$" if currency == "USD" else (currency + " " if currency else "")
    change = row.get("change_pct")
    if change is None:
        move = ""
    elif change > 0:
        move = f"  🟢 <b>▲ {abs(change):.2f}%</b>"
    elif change < 0:
        move = f"  🔴 <b>▼ {abs(change):.2f}%</b>"
    else:
        move = "  ⚪ <b>0.00%</b>"

    as_of = row.get("as_of") or ""
    try:
        dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        stamp = dt.astimezone(ZoneInfo("Asia/Singapore")).strftime("%d %b, %H:%M SGT")
    except Exception:
        stamp = "time unavailable"

    exchange_text = f" · {escape(exchange)}" if exchange else ""
    return (
        f'<code>{escape(symbol)}</code>{exchange_text}  '
        f'<b>{escape(prefix + price)}</b>{move}\n'
        f'<i>Verified · as of {escape(stamp)}</i>'
    )


def alias_matches(name, text, exclude_terms=()):
    """True if `name` (a company alias) genuinely refers to the tracked
    company in `text`, and not to an unrelated company sharing the same
    ticker/name -- e.g. Brookfield's ticker "BAM" is also just the literal
    word "BAM" in the completely unrelated Dutch construction firm
    "Koninklijke BAM Groep". A generic "does this look financial" check
    doesn't help here, since the unrelated firm's own earnings report is
    just as financial as Brookfield's. Instead, `exclude_terms` (config-
    driven, per company) names the specific unrelated entity so it can be
    ruled out directly once discovered, without risking false negatives on
    short tickers that aren't actually ambiguous (KKR, NVDA, etc).
    """
    if name.lower() not in text:
        return False
    if any(term in text for term in exclude_terms):
        return False
    return True


async def company_section(client, used_story_keys=None):
    if used_story_keys is None:
        used_story_keys = set()
    cfg = load_config()
    aliases = cfg.get("company_search_terms", cfg.get("company_aliases", {}))
    items = recent_articles("companies", 500, 72, True)
    blocks = ["<b>🏢 My Companies</b>"]

    for company in watchlist("company")[:12]:
        names = aliases.get(company, [company])
        exclude_terms = [
            t.lower()
            for t in cfg.get("company_alias_exclusions", {}).get(company, [])
        ]
        matched = []

        for item in items:
            text = (item["title"] + " " + (item.get("summary") or "")).lower()
            if not any(alias_matches(name, text, exclude_terms) for name in names):
                continue

            if not story_allowed(item, cfg):
                continue

            score = company_event_score(item, cfg)
            if score < 10:
                continue

            copy = dict(item)
            copy["importance"] = score
            matched.append(copy)

        clusters = cluster_events(matched, 4)
        price_line = company_price_line(company)
        heading = f"<b>{escape(company)}</b>"
        if price_line:
            heading += f"\n{price_line}"

        if not clusters:
            blocks.append(heading + "\nNo material fresh developments.")
            continue

        cluster = clusters[0]
        cluster["lead"] = await enrich_lead(cluster["lead"], client)
        used_story_keys.add(cluster["lead"].get("story_key"))
        blocks.append(
            heading + "\n\n"
            f'{escape(clean_summary(cluster))}\n'
            f'<i>{source_line(cluster)}</i>'
        )

    return "\n\n".join(blocks)


async def theme_section(client, used_story_keys=None):
    cfg = load_config()
    if used_story_keys is None:
        used_story_keys = set()
    rules = cfg.get("theme_rules", {})
    display = cfg.get("brew_display", {})
    per_theme = int(display.get("theme_items_per_theme", 2))
    all_items = (
        recent_articles("themes", 500, 36, True)
        + recent_articles("companies", 500, 36, True)
    )
    blocks = ["<b>🧠 Themes</b>"]

    for theme in watchlist("theme")[:10]:
        rule = rules.get(theme, {})
        include = [term.lower() for term in rule.get("include", [theme])]
        exclude = [term.lower() for term in rule.get("exclude", [])]
        matched = []

        for item in all_items:
            # Don't re-print the exact same headline that already led a
            # company's block above -- themes intentionally also draw from
            # the companies feed (so Uranium can surface Cameco stories),
            # but that shouldn't mean literally duplicating the same lead.
            if item.get("story_key") and item["story_key"] in used_story_keys:
                continue

            if not story_allowed(item, cfg):
                continue

            text = (
                item["title"] + " "
                + (item.get("summary") or "") + " "
                + (item.get("topic") or "")
            ).lower()

            if not any(term in text for term in include):
                continue
            if any(term in text for term in exclude):
                continue

            copy = dict(item)
            copy["importance"] = (
                int(item.get("importance", 0))
                + source_quality(item, cfg)
                + 4
            )
            matched.append(copy)

        clusters = cluster_events(matched, max(per_theme, 1))
        if not clusters:
            blocks.append(
                f"<b>{escape(theme)}</b>\nNo material fresh developments."
            )
            continue

        shown = await enrich_clusters(clusters[:per_theme], client)
        lines = [f"<b>{escape(theme)}</b>"]
        for cluster in shown:
            used_story_keys.add(cluster["lead"].get("story_key"))
            lines.append(
                f'{escape(clean_summary(cluster))}\n'
                f'<i>{source_line(cluster)}</i>'
            )
        blocks.append("\n\n".join(lines))

    return "\n\n".join(blocks)


def coffee_break(now):
    fresh = recent_articles("coffee", 8, 24 * 7, True)
    if fresh:
        item = fresh[0]
        return (
            "<b>☕ Coffee Break</b>\n\n"
            f'<b>{escape(item["title"])}</b>\n'
            f'{escape(clean_summary(item))}\n'
            f'<i><a href="{escape(item["url"], quote=True)}">{escape(item.get("source") or "Source")}</a> · {escape(age_label(item.get("published_at")))}</i>'
        )
    kind, q, a = COFFEE_BREAK_ITEMS[now.toordinal() % len(COFFEE_BREAK_ITEMS)]
    return f"<b>☕ Coffee Break</b>\n\n<b>{kind}</b>\n{escape(q)}\n\n<b>Answer:</b> {escape(a)}"


async def editors_take(world_items, market_items, client):
    cfg = load_config()
    ranked_markets = []
    for item in market_items:
        copy = dict(item)
        copy["importance"] = market_story_score(copy, cfg)
        ranked_markets.append(copy)
    markets = cluster_events(ranked_markets, 8)

    ranked_world = []
    for item in world_items:
        copy = dict(item)
        copy["importance"] = world_story_score(copy, cfg)
        if copy["importance"] >= 5:
            ranked_world.append(copy)
    world = cluster_events(ranked_world, 8)

    top_markets = await enrich_clusters(markets[:2], client)
    top_world = await enrich_clusters(world[:1], client)

    market_leads = [
        clean_summary(cluster).rstrip(".")
        for cluster in top_markets
    ]
    world_lead = (
        clean_summary(top_world[0]).rstrip(".")
        if top_world else ""
    )

    if not market_leads and not world_lead:
        return "Good morning. No major fresh developments were identified."

    sentences = []
    if market_leads:
        sentences.append("; ".join(market_leads))
    if world_lead:
        sentences.append("Beyond markets, " + world_lead)

    return "Good morning. " + ". ".join(sentences) + "."


async def build(timezone_name):
    now = datetime.now(ZoneInfo(timezone_name))
    world_items = recent_articles("world", 80, 36, True)
    market_items = recent_articles("markets", 80, 36, True)
    used_story_keys = set()

    timeout = httpx.Timeout(connect=5.0, read=6.0, write=6.0, pool=5.0)
    headers = {"User-Agent": os.environ.get("USER_AGENT", "Marsad/0.1")}
    async with httpx.AsyncClient(
        timeout=timeout,
        headers=headers,
        limits=httpx.Limits(max_connections=15, max_keepalive_connections=8),
    ) as client:
        parts = [
            f"<b>☕ MARSAD BREW</b>\n<i>{now.strftime('%A, %d %B %Y')}</i>\n\n"
            f"{escape(await editors_take(world_items, market_items, client))}",
            market_snapshot_section(),
            await world_section(world_items, client),
            await markets_section(market_items, client),
            await company_section(client, used_story_keys),
            await theme_section(client, used_story_keys),
            coffee_break(now),
        ]

    chunks, current = [], ""
    for part in parts:
        candidate = part if not current else current + f"\n\n{DIVIDER}\n\n" + part
        if len(candidate) <= 3900:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = part
    if current:
        chunks.append(current)
    return chunks
