import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = "data/papers.db"


def get_conn(db_path: str = DEFAULT_DB_PATH):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH):
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
    CREATE INDEX IF NOT EXISTS idx_papers_venue_year
    ON papers (venue, year)
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_papers_normalized_title
    ON papers (normalized_title)
    """)

    conn.commit()
    conn.close()
