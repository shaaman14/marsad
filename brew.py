from datetime import datetime, timezone as dt_timezone
from html import escape
from zoneinfo import ZoneInfo

from database import recent_articles, watchlist

DIVIDER = "━━━━━━━━━━━━━━━━━━"


def article_age(published_at, timezone_name):
    if not published_at:
        return "Undated"

    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=dt_timezone.utc)

        now = datetime.now(dt_timezone.utc)
        hours = max(
            0,
            int(
                (
                    now - published.astimezone(dt_timezone.utc)
                ).total_seconds()
                // 3600
            ),
        )

        if hours < 1:
            return "Published less than 1h ago"
        if hours < 24:
            return f"Published {hours}h ago"

        days = hours // 24
        if days <= 3:
            return f"Published {days}d ago"

        local_time = published.astimezone(ZoneInfo(timezone_name))
        return "Published " + local_time.strftime("%d %b %Y")
    except Exception:
        return "Publication time unavailable"


def article(item, timezone_name):
    return (
        f'<a href="{escape(item["url"], quote=True)}">'
        f'<b>{escape(item["title"])}</b></a>\n'
        f'<i>{escape(item.get("source") or "Source")} · '
        f'{escape(article_age(item.get("published_at"), timezone_name))}</i>'
    )


def section(title, items, timezone_name, limit=3, empty="No fresh stories found."):
    selected = items[:limit]
    if not selected:
        return f"<b>{title}</b>\n\n{empty}"

    return (
        f"<b>{title}</b>\n\n"
        + "\n\n".join(article(item, timezone_name) for item in selected)
    )


def company_section(timezone_name):
    companies = watchlist("company")
    items = recent_articles(
        "companies",
        limit=60,
        hours=72,
        require_published=True,
    )
    lines = ["<b>🏢 My Companies</b>"]
    found = 0

    for company in companies:
        match = next(
            (
                item
                for item in items
                if company.lower()
                in (item["title"] + " " + (item.get("summary") or "")).lower()
            ),
            None,
        )
        if match:
            lines.append(
                f"<b>{escape(company)}</b>\n{article(match, timezone_name)}"
            )
            found += 1

        if found >= 5:
            break

    if found == 0:
        lines.append("No fresh material watchlist updates found.")

    return "\n\n".join(lines)


def coffee_break(timezone_name):
    # Coffee Break may use older, timeless material.
    items = recent_articles(
        "coffee",
        limit=5,
        hours=24 * 30,
        require_published=False,
    )
    if items:
        return (
            "<b>☕ Coffee Break</b>\n\n"
            + article(items[0], timezone_name)
            + "\n\nOne interesting thing before you start the day."
        )

    return (
        "<b>☕ Coffee Break</b>\n\n"
        "<b>Today in financial history</b>\n"
        "The Amsterdam Stock Exchange, founded in the early 1600s, "
        "is commonly regarded as the world's first modern stock exchange."
    )


def build(timezone_name):
    now = datetime.now(ZoneInfo(timezone_name))
    header = (
        "<b>☕ MARSAD BREW</b>\n"
        f"<i>{now.strftime('%A, %d %B %Y')}</i>\n\n"
        "Good morning. Here is the latest across the world, markets, "
        "and your watchlist."
    )

    parts = [
        header,
        section(
            "🌍 Around the World",
            recent_articles(
                "world",
                limit=12,
                hours=36,
                require_published=True,
            ),
            timezone_name,
            limit=3,
        ),
        section(
            "📈 Markets",
            recent_articles(
                "markets",
                limit=12,
                hours=36,
                require_published=True,
            ),
            timezone_name,
            limit=4,
        ),
        company_section(timezone_name),
        section(
            "🧠 Themes",
            recent_articles(
                "themes",
                limit=12,
                hours=72,
                require_published=True,
            ),
            timezone_name,
            limit=3,
        ),
        coffee_break(timezone_name),
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
