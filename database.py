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

        CREATE TABLE IF NOT EXISTS market_snapshot (
            name TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            value REAL,
            change_pct REAL,
            as_of TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS company_snapshot (
            company TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            currency TEXT,
            exchange TEXT,
            value REAL,
            previous_close REAL,
            change_pct REAL,
            as_of TEXT,
            data_source TEXT,
            validation_status TEXT,
            updated_at TEXT NOT NULL
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
        CREATE TABLE IF NOT EXISTS company_snapshot (
            company TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            currency TEXT,
            exchange TEXT,
            value REAL,
            previous_close REAL,
            change_pct REAL,
            as_of TEXT,
            data_source TEXT,
            validation_status TEXT,
            updated_at TEXT NOT NULL
        );

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
        CREATE TABLE IF NOT EXISTS company_snapshot (
            company TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            currency TEXT,
            exchange TEXT,
            value REAL,
            previous_close REAL,
            change_pct REAL,
            as_of TEXT,
            data_source TEXT,
            validation_status TEXT,
            updated_at TEXT NOT NULL
        );

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


def save_market_snapshot(rows):
    with connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS market_snapshot (
            name TEXT PRIMARY KEY, symbol TEXT NOT NULL, value REAL,
            change_pct REAL, as_of TEXT, updated_at TEXT NOT NULL
        )
        """)
        for row in rows:
            conn.execute("""
            INSERT INTO market_snapshot (name,symbol,value,change_pct,as_of,updated_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET symbol=excluded.symbol,value=excluded.value,
            change_pct=excluded.change_pct,as_of=excluded.as_of,updated_at=excluded.updated_at
            """, (row['name'],row['symbol'],row.get('value'),row.get('change_pct'),row.get('as_of'),now_iso()))

def get_market_snapshot():
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS market_snapshot (name TEXT PRIMARY KEY,symbol TEXT NOT NULL,value REAL,change_pct REAL,as_of TEXT,updated_at TEXT NOT NULL)""")
        return [dict(r) for r in conn.execute("""SELECT * FROM market_snapshot ORDER BY CASE name WHEN 'S&P 500' THEN 1 WHEN 'Nasdaq' THEN 2 WHEN 'UST 10Y' THEN 3 WHEN 'DXY' THEN 4 WHEN 'USD/JPY' THEN 5 WHEN 'USD/CNH' THEN 6 WHEN 'Oil' THEN 7 WHEN 'Gold' THEN 8 WHEN 'Copper' THEN 9 WHEN 'Bitcoin' THEN 10 ELSE 99 END""")]


def _ensure_company_snapshot_schema(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS company_snapshot (
        company TEXT PRIMARY KEY, symbol TEXT NOT NULL, currency TEXT,
        exchange TEXT, value REAL, previous_close REAL, change_pct REAL,
        as_of TEXT, data_source TEXT, validation_status TEXT,
        updated_at TEXT NOT NULL
    )
    """)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(company_snapshot)")}
    for column, sql_type in {
        "exchange": "TEXT",
        "previous_close": "REAL",
        "data_source": "TEXT",
        "validation_status": "TEXT",
    }.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE company_snapshot ADD COLUMN {column} {sql_type}")


def save_company_snapshot(rows):
    with connect() as conn:
        _ensure_company_snapshot_schema(conn)
        for row in rows:
            conn.execute("""
            INSERT INTO company_snapshot
            (company,symbol,currency,exchange,value,previous_close,change_pct,
             as_of,data_source,validation_status,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(company) DO UPDATE SET
                symbol=excluded.symbol,currency=excluded.currency,
                exchange=excluded.exchange,value=excluded.value,
                previous_close=excluded.previous_close,
                change_pct=excluded.change_pct,as_of=excluded.as_of,
                data_source=excluded.data_source,
                validation_status=excluded.validation_status,
                updated_at=excluded.updated_at
            """, (
                row['company'], row['symbol'], row.get('currency'),
                row.get('exchange'), row.get('value'), row.get('previous_close'),
                row.get('change_pct'), row.get('as_of'), row.get('data_source'),
                row.get('validation_status'), now_iso()
            ))


def get_company_snapshot(company=None):
    with connect() as conn:
        _ensure_company_snapshot_schema(conn)
        if company is not None:
            row = conn.execute(
                "SELECT * FROM company_snapshot WHERE company = ? COLLATE NOCASE",
                (company,),
            ).fetchone()
            return dict(row) if row else None
        return [dict(row) for row in conn.execute(
            "SELECT * FROM company_snapshot ORDER BY company"
        )]

