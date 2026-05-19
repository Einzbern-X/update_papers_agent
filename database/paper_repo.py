from pathlib import Path
from datetime import datetime
import pandas as pd
from agent.contracts import PUBLIC_PAPER_FIELDS
from database.db import get_conn
from utils.normalize import clean_text, normalize_title

PUBLIC_COLUMNS = list(PUBLIC_PAPER_FIELDS)


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

    cur.execute(
        "SELECT * FROM papers WHERE venue=? AND year=? AND normalized_title=?",
        (venue, year, normalized_title),
    )
    row = cur.fetchone()

    if row is None:
        cur.execute(
            """
            INSERT INTO papers (venue, year, title, normalized_title, authors, pdf_url, source_url, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (venue, year, title, normalized_title, authors, pdf_url, source_url, now, now),
        )
        conn.commit()
        conn.close()
        return "inserted"

    new_authors = row["authors"] or ""
    new_pdf_url = row["pdf_url"] or ""
    new_source_url = row["source_url"] or ""
    changed = False

    if authors and authors != new_authors:
        new_authors = authors
        changed = True
    if pdf_url and pdf_url != new_pdf_url:
        new_pdf_url = pdf_url
        changed = True
    if source_url and source_url != new_source_url:
        new_source_url = source_url
        changed = True

    if changed:
        cur.execute(
            """
            UPDATE papers SET authors=?, pdf_url=?, source_url=?, updated_at=? WHERE id=?
            """,
            (new_authors, new_pdf_url, new_source_url, now, row["id"]),
        )
        conn.commit()
        conn.close()
        return "updated"

    conn.close()
    return "unchanged"


def fetch_all_papers(db_path: str = "data/papers.db") -> list[dict]:
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute(f"SELECT {', '.join(PUBLIC_COLUMNS)} FROM papers ORDER BY year DESC, venue ASC, title ASC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def export_papers_to_csv(csv_path: str, db_path: str = "data/papers.db") -> str:
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    rows = fetch_all_papers(db_path)
    pd.DataFrame(rows, columns=PUBLIC_COLUMNS).to_csv(csv_path, index=False, encoding="utf-8-sig")
    return csv_path
