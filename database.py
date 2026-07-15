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
            story_key TEXT
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
        # Existing Railway databases may predate topic/story_key.
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(articles)")
        }
        if "topic" not in columns:
            conn.execute("ALTER TABLE articles ADD COLUMN topic TEXT")
        if "story_key" not in columns:
            conn.execute("ALTER TABLE articles ADD COLUMN story_key TEXT")

        cur = conn.execute("""
        INSERT OR IGNORE INTO articles
        (url, title, summary, source, section, published_at, fetched_at,
         importance, topic, story_key)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        ))
        return cur.rowcount > 0


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
