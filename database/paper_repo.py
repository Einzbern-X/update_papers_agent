from pathlib import Path
from datetime import datetime
import pandas as pd

from database.db import get_conn
from utils.normalize import normalize_title, clean_text


PUBLIC_COLUMNS = [
    "venue",
    "year",
    "title",
    "authors",
    "pdf_url",
    "source_url",
]


def _get_existing(cur, venue: str, year: int, normalized_title: str):
    cur.execute("""
    SELECT id, authors, pdf_url, source_url
    FROM papers
    WHERE venue = ? AND year = ? AND normalized_title = ?
    """, (venue, year, normalized_title))

    return cur.fetchone()


def save_paper(paper: dict, db_path: str = "data/papers.db") -> str:
    venue = clean_text(paper.get("venue", ""))
    year = int(paper.get("year") or 0)
    title = clean_text(paper.get("title", ""))
    authors = clean_text(paper.get("authors", ""))
    pdf_url = clean_text(paper.get("pdf_url", ""))
    source_url = clean_text(paper.get("source_url", ""))

    if not venue or not year or not title:
        return "skipped"

    normalized_title = normalize_title(title)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_conn(db_path)
    cur = conn.cursor()

    existing = _get_existing(cur, venue, year, normalized_title)

    if existing is None:
        cur.execute("""
        INSERT INTO papers (
            venue, year, title, normalized_title, authors, pdf_url, source_url,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            venue,
            year,
            title,
            normalized_title,
            authors,
            pdf_url,
            source_url,
            now,
            now,
        ))

        conn.commit()
        conn.close()
        return "inserted"

    need_update = False

    new_authors = existing["authors"] or ""
    new_pdf_url = existing["pdf_url"] or ""
    new_source_url = existing["source_url"] or ""

    if authors and authors != new_authors:
        new_authors = authors
        need_update = True

    if pdf_url and pdf_url != new_pdf_url:
        new_pdf_url = pdf_url
        need_update = True

    if source_url and source_url != new_source_url:
        new_source_url = source_url
        need_update = True

    if need_update:
        cur.execute("""
        UPDATE papers
        SET authors = ?, pdf_url = ?, source_url = ?, updated_at = ?
        WHERE id = ?
        """, (
            new_authors,
            new_pdf_url,
            new_source_url,
            now,
            existing["id"],
        ))

        conn.commit()
        conn.close()
        return "updated"

    conn.close()
    return "unchanged"


def fetch_all_papers(db_path: str = "data/papers.db") -> list[dict]:
    conn = get_conn(db_path)
    cur = conn.cursor()

    cur.execute(f"""
    SELECT {", ".join(PUBLIC_COLUMNS)}
    FROM papers
    ORDER BY year DESC, venue ASC, title ASC
    """)

    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def export_papers_to_csv(csv_path: str = "exports/all_papers.csv", db_path: str = "data/papers.db") -> str:
    rows = fetch_all_papers(db_path)
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(rows, columns=PUBLIC_COLUMNS)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return csv_path


def query_by_venue_year(venue: str, year: int, db_path: str = "data/papers.db") -> list[dict]:
    conn = get_conn(db_path)
    cur = conn.cursor()

    cur.execute(f"""
    SELECT {", ".join(PUBLIC_COLUMNS)}
    FROM papers
    WHERE venue = ? AND year = ?
    ORDER BY title ASC
    """, (venue, year))

    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows
