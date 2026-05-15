import sqlite3
from pathlib import Path


def get_conn(db_path: str = "data/papers.db"):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = "data/papers.db"):
    conn = get_conn(db_path)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS papers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venue TEXT NOT NULL,
        year INTEGER NOT NULL,
        title TEXT NOT NULL,
        normalized_title TEXT NOT NULL,
        authors TEXT,
        pdf_url TEXT,
        source_url TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(venue, year, normalized_title)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        venue TEXT,
        year INTEGER,
        url TEXT NOT NULL,
        parser TEXT,
        structure_type TEXT,
        status TEXT,
        release_status TEXT,
        last_hash TEXT,
        last_checked_at TEXT,
        last_success_at TEXT,
        last_error TEXT,
        paper_count INTEGER DEFAULT 0,
        generated_rule_key TEXT,
        UNIQUE(name, year, url)
    )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_papers_venue_year ON papers(venue, year)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status)")

    conn.commit()
    conn.close()
