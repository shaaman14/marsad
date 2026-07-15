import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).with_name("data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "marsad.db"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialise():
    with connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS subscribers (
            chat_id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS watchlist (
            term TEXT NOT NULL COLLATE NOCASE,
            kind TEXT NOT NULL CHECK(kind IN ('company','theme')),
            created_at TEXT NOT NULL,
            PRIMARY KEY(term, kind)
        );

        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            summary TEXT,
            source TEXT,
            section TEXT NOT NULL,
            published_at TEXT,
            fetched_at TEXT NOT NULL,
            importance INTEGER DEFAULT 0,
            topic TEXT,
            story_key TEXT,
            region TEXT
        );

        CREATE TABLE IF NOT EXISTS source_health (
            source TEXT PRIMARY KEY,
            section TEXT NOT NULL,
            status TEXT NOT NULL,
            item_count INTEGER NOT NULL DEFAULT 0,
            error_text TEXT,
            checked_at TEXT NOT NULL
        );
        """)


def add_subscriber(chat_id):
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO subscribers(chat_id, created_at) VALUES (?, ?)",
            (chat_id, now_iso()),
        )


def subscribers():
    with connect() as conn:
        return [row["chat_id"] for row in conn.execute("SELECT chat_id FROM subscribers")]


def add_watch(term, kind):
    term = term.strip()
    if not term:
        return False
    with connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO watchlist(term, kind, created_at) VALUES (?, ?, ?)",
            (term, kind, now_iso()),
        )
        return cur.rowcount > 0


def remove_watch(term):
    with connect() as conn:
        cur = conn.execute("DELETE FROM watchlist WHERE term = ?", (term.strip(),))
        return cur.rowcount > 0


def watchlist(kind):
    with connect() as conn:
        return [
            row["term"]
            for row in conn.execute(
                "SELECT term FROM watchlist WHERE kind = ? ORDER BY term",
                (kind,),
            )
        ]


def save_article(article):
    with connect() as conn:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(articles)")
        }
        for column, sql_type in {
            "topic": "TEXT",
            "story_key": "TEXT",
            "region": "TEXT",
        }.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE articles ADD COLUMN {column} {sql_type}")

        cur = conn.execute("""
        INSERT OR IGNORE INTO articles
        (url, title, summary, source, section, published_at, fetched_at,
         importance, topic, story_key, region)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            article["url"],
            article["title"],
            article.get("summary", ""),
            article.get("source", ""),
            article["section"],
            article.get("published_at"),
            article["fetched_at"],
            article.get("importance", 0),
            article.get("topic"),
            article.get("story_key"),
            article.get("region"),
        ))
        return cur.rowcount > 0


def save_source_health(items):
    with connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS source_health (
            source TEXT PRIMARY KEY,
            section TEXT NOT NULL,
            status TEXT NOT NULL,
            item_count INTEGER NOT NULL DEFAULT 0,
            error_text TEXT,
            checked_at TEXT NOT NULL
        )
        """)
        for item in items:
            conn.execute("""
            INSERT INTO source_health
            (source, section, status, item_count, error_text, checked_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
                section=excluded.section,
                status=excluded.status,
                item_count=excluded.item_count,
                error_text=excluded.error_text,
                checked_at=excluded.checked_at
            """, (
                item["source"],
                item["section"],
                item["status"],
                item.get("items", 0),
                item.get("error"),
                now_iso(),
            ))


def get_source_health():
    with connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS source_health (
            source TEXT PRIMARY KEY,
            section TEXT NOT NULL,
            status TEXT NOT NULL,
            item_count INTEGER NOT NULL DEFAULT 0,
            error_text TEXT,
            checked_at TEXT NOT NULL
        )
        """)
        return [
            dict(row)
            for row in conn.execute("""
            SELECT * FROM source_health
            ORDER BY section, status DESC, source
            """)
        ]


def recent_articles(section, limit=20, hours=72, require_published=True):
    published_clause = "AND published_at IS NOT NULL" if require_published else ""
    with connect() as conn:
        return [
            dict(row)
            for row in conn.execute(f"""
            SELECT * FROM articles
            WHERE section = ?
              {published_clause}
              AND datetime(COALESCE(published_at, fetched_at)) >= datetime('now', ?)
            ORDER BY importance DESC,
                     datetime(COALESCE(published_at, fetched_at)) DESC,
                     id DESC
            LIMIT ?
            """, (section, f"-{hours} hours", limit))
        ]
