from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from database import recent_articles, watchlist

DIVIDER = "━━━━━━━━━━━━━━━━━━"


def article(article):
    return (
        f'<a href="{escape(article["url"], quote=True)}">'
        f'<b>{escape(article["title"])}</b></a>\n'
        f'<i>{escape(article.get("source") or "Source")}</i>'
    )


def section(title, items, limit=3, empty="Nothing material found."):
    selected = items[:limit]
    if not selected:
        return f"<b>{title}</b>\n\n{empty}"
    return f"<b>{title}</b>\n\n" + "\n\n".join(article(item) for item in selected)


def company_section():
    companies = watchlist("company")
    items = recent_articles("companies", 50, 72)
    lines = ["<b>🏢 My Companies</b>"]
    found = 0

    for company in companies:
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
            lines.append(f"<b>{escape(company)}</b>\n{article(match)}")
            found += 1
        if found >= 5:
            break

    if found == 0:
        lines.append("No material watchlist updates found.")
    return "\n\n".join(lines)


def coffee_break():
    items = recent_articles("coffee", 5, 168)
    if items:
        return (
            "<b>☕ Coffee Break</b>\n\n"
            + article(items[0])
            + "\n\nOne interesting thing before you start the day."
        )
    return (
        "<b>☕ Coffee Break</b>\n\n"
        "<b>Today in financial history</b>\n"
        "The Amsterdam Stock Exchange, founded in the early 1600s, "
        "is commonly regarded as the world's first modern stock exchange."
    )


def build(timezone):
    now = datetime.now(ZoneInfo(timezone))
    header = (
        "<b>☕ MARSAD BREW</b>\n"
        f"<i>{now.strftime('%A, %d %B %Y')}</i>\n\n"
        "Good morning. Here is what matters across the world, markets, "
        "and your watchlist."
    )

    sections = [
        header,
        section("🌍 Around the World", recent_articles("world", 10, 36), 3),
        section("📈 Markets", recent_articles("markets", 10, 36), 4),
        company_section(),
        section("🧠 Themes", recent_articles("themes", 10, 72), 3),
        coffee_break(),
    ]

    chunks = []
    current = ""
    for part in sections:
        proposed = part if not current else current + f"\n\n{DIVIDER}\n\n" + part
        if len(proposed) <= 3900:
            current = proposed
        else:
            chunks.append(current)
            current = part
    if current:
        chunks.append(current)
    return chunks
