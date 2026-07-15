from datetime import datetime, timezone as dt_timezone
from html import escape
from zoneinfo import ZoneInfo

from database import recent_articles, watchlist

DIVIDER = "━━━━━━━━━━━━━━━━━━"

COFFEE_BREAK_ITEMS = [
    {
        "kind": "🧠 Today’s Trivia",
        "question": "Which city hosted the first widely recognised modern securities exchange?",
        "answer": "Amsterdam. Earlier merchant and commodity exchanges existed, but Amsterdam developed organised trading in transferable company shares in the early 1600s."
    },
    {
        "kind": "🏛 Financial History",
        "question": "Why is the ticker tape called a ticker?",
        "answer": "Early machines printed stock prices on paper while making a ticking sound as the tape advanced."
    },
    {
        "kind": "🌍 Did You Know?",
        "question": "Africa is the only continent in all four hemispheres.",
        "answer": "The Equator and prime meridian both cross the continent."
    },
    {
        "kind": "🧠 Today’s Trivia",
        "question": "What was the first company commonly associated with publicly traded shares?",
        "answer": "The Dutch East India Company, founded in 1602."
    },
]


def article_age(published_at, timezone_name):
    if not published_at:
        return "Time unavailable"
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=dt_timezone.utc)
        now = datetime.now(dt_timezone.utc)
        hours = max(
            0,
            int((now - published.astimezone(dt_timezone.utc)).total_seconds() // 3600),
        )
        if hours < 1:
            return "<1h ago"
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"
    except Exception:
        return "Time unavailable"


def source_link(item, timezone_name):
    return (
        f'<a href="{escape(item["url"], quote=True)}">'
        f'{escape(item.get("source") or "Source")}</a>'
        f' · {escape(article_age(item.get("published_at"), timezone_name))}'
    )


def usable_summary(item):
    summary = (item.get("summary") or "").strip()
    if summary and len(summary) >= 60:
        first = summary.split(". ")[0].strip()
        if len(first) < 260:
            return first.rstrip(".") + "."
    title = item["title"].strip()
    return title.rstrip(".") + "."


def unique_stories(items, limit):
    seen = set()
    selected = []
    for item in items:
        key = item.get("story_key") or item["title"].lower()
        if key in seen:
            continue
        seen.add(key)
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def opening(world, markets):
    leads = []
    if markets:
        leads.append(usable_summary(markets[0]))
    if world:
        leads.append(usable_summary(world[0]))
    if len(leads) == 2:
        return (
            "Good morning. "
            + leads[0]
            + " Meanwhile, "
            + leads[1][0].lower()
            + leads[1][1:]
        )
    if leads:
        return "Good morning. " + leads[0]
    return "Good morning. The latest source refresh did not identify enough current material for a full opening note."


def narrative_section(title, items, timezone_name, limit=3):
    selected = unique_stories(items, limit)
    if not selected:
        return f"<b>{title}</b>\n\nNo material fresh developments."

    blocks = [f"<b>{title}</b>"]
    for item in selected:
        blocks.append(
            f'<b>{escape(item["title"])}</b>\n'
            f'{escape(usable_summary(item))}\n'
            f'<i>{source_link(item, timezone_name)}</i>'
        )
    return "\n\n".join(blocks)


def markets_section(items, timezone_name):
    selected = unique_stories(items, 4)
    if not selected:
        return "<b>📈 Markets</b>\n\nNo material fresh market developments."

    grouped = {}
    for item in selected:
        grouped.setdefault(item.get("topic") or "General", []).append(item)

    blocks = ["<b>📈 Markets</b>"]
    for topic, topic_items in grouped.items():
        item = topic_items[0]
        blocks.append(
            f'<b>{escape(topic)}</b>\n'
            f'{escape(usable_summary(item))}\n'
            f'<i>{source_link(item, timezone_name)}</i>'
        )
    return "\n\n".join(blocks)


def companies_section(timezone_name):
    companies = watchlist("company")
    items = recent_articles("companies", limit=100, hours=72, require_published=True)
    blocks = ["<b>🏢 My Companies</b>"]

    for company in companies[:10]:
        match = next(
            (
                item for item in items
                if company.lower() in (
                    item["title"] + " " + (item.get("summary") or "")
                ).lower()
            ),
            None,
        )
        if match:
            blocks.append(
                f'<b>{escape(company)}</b>\n'
                f'{escape(usable_summary(match))}\n'
                f'<i>{source_link(match, timezone_name)}</i>'
            )
        else:
            blocks.append(
                f'<b>{escape(company)}</b>\n'
                "No material fresh developments."
            )
    return "\n\n".join(blocks)


def themes_section(timezone_name):
    themes = watchlist("theme")
    items = recent_articles("themes", limit=80, hours=72, require_published=True)
    blocks = ["<b>🧠 Themes</b>"]

    for theme in themes[:8]:
        match = next(
            (
                item for item in items
                if theme.lower() in (
                    item["title"] + " " + (item.get("summary") or "")
                ).lower()
            ),
            None,
        )
        if match:
            blocks.append(
                f'<b>{escape(theme)}</b>\n'
                f'{escape(usable_summary(match))}\n'
                f'<i>{source_link(match, timezone_name)}</i>'
            )
        else:
            blocks.append(
                f'<b>{escape(theme)}</b>\n'
                "No material fresh developments."
            )
    return "\n\n".join(blocks)


def coffee_break(now):
    item = COFFEE_BREAK_ITEMS[now.toordinal() % len(COFFEE_BREAK_ITEMS)]
    return (
        "<b>☕ Coffee Break</b>\n\n"
        f'<b>{item["kind"]}</b>\n'
        f'{escape(item["question"])}\n\n'
        f'<b>Answer:</b> {escape(item["answer"])}'
    )


def build(timezone_name):
    now = datetime.now(ZoneInfo(timezone_name))
    world = recent_articles("world", limit=20, hours=36, require_published=True)
    markets = recent_articles("markets", limit=20, hours=36, require_published=True)

    parts = [
        (
            "<b>☕ MARSAD BREW</b>\n"
            f"<i>{now.strftime('%A, %d %B %Y')}</i>\n\n"
            f"{escape(opening(world, markets))}"
        ),
        narrative_section("🌍 Around the World", world, timezone_name, limit=3),
        markets_section(markets, timezone_name),
        companies_section(timezone_name),
        themes_section(timezone_name),
        coffee_break(now),
    ]

    chunks = []
    current = ""
    for part in parts:
        proposed = part if not current else current + f"\n\n{DIVIDER}\n\n" + part
        if len(proposed) <= 3900:
            current = proposed
        else:
            if current:
                chunks.append(current)
            current = part

    if current:
        chunks.append(current)
    return chunks
