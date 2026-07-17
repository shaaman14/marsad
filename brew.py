import json
import re
from collections import defaultdict
from datetime import datetime, timezone as dt_timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from database import get_market_snapshot, recent_articles, watchlist

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


def load_config():
    return json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))


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


def clean_summary(item):
    title = item["title"].strip().rstrip(".")
    summary = re.sub(r"\s+", " ", (item.get("summary") or "").strip())
    if summary:
        first = summary.split(". ")[0].strip().rstrip(".")
        vague = ("while ", "weak demand", "this ", "it ", "they ", "the country", "the company")
        if 55 <= len(first) <= 300 and not first.lower().startswith(vague):
            return first + "."
    return title + "."


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
        ("Rates & Central Banks", [
            "federal reserve", " fed ", "ecb", "boj", "bank of japan",
            "pboc", "pbo", "rate hike", "rate cut", "interest rate",
            "bond-buying", "bond buying", "yield", "yields"
        ]),
        ("FX", [
            "dollar", "yen", "yuan", "euro", "currency", "currencies", "fx"
        ]),
        ("Commodities", [
            "oil", "gold", "copper", "uranium", "commodity", "commodities"
        ]),
        ("Equities", [
            "stocks", "shares", "equities", "nasdaq", "s&p"
        ]),
        ("Economy", [
            "gdp", "inflation", "jobs", "employment", "pmi",
            "retail sales", "household expectations"
        ]),
    ]
    for label, terms in rules:
        if any(term in text for term in terms):
            return label
    return item.get("topic") or "General"


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


def company_story_allowed(item, config):
    text = full_story_text(item)
    blocked = {
        value.lower()
        for value in config.get("company_source_blocklist", [])
    }

    # Google News can label the source Yahoo while the actual publisher
    # appears in the headline, so check the entire story text.
    if any(source in text for source in blocked):
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
            arrow = "▲" if change >= 0 else "▼"
            move = f" {arrow} {abs(change):.2f}%"

        lines.append(f"<b>{escape(row['name'])}</b>  {value_text}{move}")
    return "\n".join(lines)

def world_section(items):
    cfg = load_config()
    ranked_items = []

    for item in items:
        copy = dict(item)
        copy["importance"] = world_story_score(copy, cfg)
        if copy["importance"] < 5:
            continue
        ranked_items.append(copy)

    clusters = cluster_events(ranked_items, 25)
    selected = []
    used_regions = set()

    for cluster in clusters:
        region = dynamic_region(cluster["lead"])
        if region in used_regions:
            continue
        selected.append(cluster)
        used_regions.add(region)
        if len(selected) == 3:
            break

    if len(selected) < 3:
        for cluster in clusters:
            if cluster not in selected:
                selected.append(cluster)
            if len(selected) == 3:
                break

    if not selected:
        return "<b>🌍 Around the World</b>\n\nNo material fresh developments."

    blocks = ["<b>🌍 Around the World</b>"]
    for cluster in selected:
        lead = cluster["lead"]
        blocks.append(
            f'<b>{escape(dynamic_region(lead))}: '
            f'{escape(lead["title"])}</b>\n'
            f'{escape(clean_summary(lead))}\n'
            f'<i>{source_line(cluster)}</i>'
        )

    return "\n\n".join(blocks)


def markets_section(items):
    clusters = cluster_events(items, 20)
    chosen = []
    seen_topics = set()
    for c in clusters:
        topic = dynamic_market_topic(c["lead"])
        if topic in seen_topics:
            continue
        chosen.append(c)
        seen_topics.add(topic)
        if len(chosen) == 4:
            break

    if not chosen:
        return "<b>📈 Markets</b>\n\nNo material fresh market developments."

    blocks = ["<b>📈 Markets</b>"]
    for c in chosen:
        lead = c["lead"]
        topic = dynamic_market_topic(lead)
        block = f'<b>{escape(topic)}</b>\n{escape(clean_summary(lead))}'
        why = why_it_matters(lead)
        if why:
            block += f"\n<i>Why it matters: {escape(why)}</i>"
        block += f"\n<i>{source_line(c)}</i>"
        blocks.append(block)
    return "\n\n".join(blocks)



def company_event_score(item, config):
    text = (item["title"] + " " + (item.get("summary") or "")).lower()
    score = int(item.get("importance", 0))

    for term, weight in config.get("company_event_weights", {}).items():
        if term in text:
            score += int(weight)

    for term in config.get("company_junk_terms", []):
        if term in text:
            score -= 25

    return score


def company_section():
    cfg = load_config()
    aliases = cfg.get("company_search_terms", cfg.get("company_aliases", {}))
    items = recent_articles("companies", 500, 72, True)
    blocks = ["<b>🏢 My Companies</b>"]

    for company in watchlist("company")[:12]:
        names = aliases.get(company, [company])
        matched = []

        for item in items:
            text = (item["title"] + " " + (item.get("summary") or "")).lower()
            if not any(name.lower() in text for name in names):
                continue

            if not company_story_allowed(item, cfg):
                continue

            score = company_event_score(item, cfg)
            if score < 10:
                continue

            copy = dict(item)
            copy["importance"] = score
            matched.append(copy)

        clusters = cluster_events(matched, 4)
        if not clusters:
            blocks.append(
                f"<b>{escape(company)}</b>\nNo material fresh developments."
            )
            continue

        cluster = clusters[0]
        lead = cluster["lead"]
        blocks.append(
            f'<b>{escape(company)}</b>\n'
            f'{escape(clean_summary(lead))}\n'
            f'<i>{source_line(cluster)}</i>'
        )

    return "\n\n".join(blocks)


def theme_section():
    cfg = load_config()
    rules = cfg.get("theme_rules", {})
    all_items = (
        recent_articles("themes", 500, 72, True)
        + recent_articles("companies", 500, 72, True)
    )
    blocks = ["<b>🧠 Themes</b>"]

    for theme in watchlist("theme")[:10]:
        rule = rules.get(theme, {})
        include = [term.lower() for term in rule.get("include", [theme])]
        exclude = [term.lower() for term in rule.get("exclude", [])]
        matched = []

        for item in all_items:
            text = (
                item["title"] + " "
                + (item.get("summary") or "") + " "
                + (item.get("topic") or "")
            ).lower()

            if not any(term in text for term in include):
                continue
            if any(term in text for term in exclude):
                continue
            if not company_story_allowed(item, cfg):
                continue

            copy = dict(item)
            copy["importance"] = (
                int(item.get("importance", 0))
                + source_quality(item, cfg)
                + 4
            )
            matched.append(copy)

        clusters = cluster_events(matched, 4)
        if not clusters:
            blocks.append(
                f"<b>{escape(theme)}</b>\nNo material fresh developments."
            )
            continue

        cluster = clusters[0]
        lead = cluster["lead"]
        blocks.append(
            f'<b>{escape(theme)}</b>\n'
            f'{escape(clean_summary(lead))}\n'
            f'<i>{source_line(cluster)}</i>'
        )

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


def opening(world_items, market_items):
    world = cluster_events(world_items, 5)
    markets = cluster_events(market_items, 5)
    leads = []
    if markets:
        leads.append(clean_summary(markets[0]["lead"]))
    if world:
        leads.append(clean_summary(world[0]["lead"]))
    if not leads:
        return "Good morning. No major fresh developments were identified."
    if len(leads) == 1:
        return "Good morning. " + leads[0]
    return "Good morning. " + leads[0] + " Meanwhile, " + leads[1][0].lower() + leads[1][1:]



def editors_take(world_items, market_items):
    markets = cluster_events(market_items, 8)
    cfg = load_config()

    ranked_world = []
    for item in world_items:
        copy = dict(item)
        copy["importance"] = world_story_score(copy, cfg)
        if copy["importance"] >= 5:
            ranked_world.append(copy)
    world = cluster_events(ranked_world, 8)

    market_leads = [
        clean_summary(cluster["lead"]).rstrip(".")
        for cluster in markets[:2]
    ]
    world_lead = (
        clean_summary(world[0]["lead"]).rstrip(".")
        if world else ""
    )

    if not market_leads and not world_lead:
        return "Good morning. No major fresh developments were identified."

    sentences = []
    if market_leads:
        sentences.append("; ".join(market_leads))
    if world_lead:
        sentences.append("Beyond markets, " + world_lead)

    return "Good morning. " + ". ".join(sentences) + "."


def build(timezone_name):
    now = datetime.now(ZoneInfo(timezone_name))
    world_items = recent_articles("world", 80, 36, True)
    market_items = recent_articles("markets", 80, 36, True)

    parts = [
        f"<b>☕ MARSAD BREW</b>\n<i>{now.strftime('%A, %d %B %Y')}</i>\n\n{escape(editors_take(world_items, market_items))}",
        market_snapshot_section(),
        world_section(world_items),
        markets_section(market_items),
        company_section(),
        theme_section(),
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
