from datetime import datetime
from agent.contracts import RELEASED_STATUSES
from database.db import get_conn
from utils.normalize import clean_text

# 这些 status 代表已成功爬取过论文，下次可以跳过
DONE_STATUSES = RELEASED_STATUSES


def get_source_status(source: dict, db_path: str = "data/papers.db") -> dict | None:
    """
    查询数据库里某个 source 的当前状态记录。
    返回 dict（含 status / paper_count / last_success_at 等），找不到则返回 None。
    """
    name = clean_text(source.get("name", ""))
    year = int(source.get("year") or 0)
    url = clean_text(source.get("url", ""))
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM sources WHERE name=? AND year=? AND url=?",
        (name, year, url),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return dict(row)


def is_source_done(source: dict, db_path: str = "data/papers.db") -> tuple[bool, str]:
    """
    判断某个 source 是否已经成功爬取过。
    返回 (is_done, reason_string)。
    """
    record = get_source_status(source, db_path)
    if record is None:
        return False, "no_record"
    status = record.get("status", "")
    if status in DONE_STATUSES:
        paper_count = record.get("paper_count", 0)
        last_success_at = record.get("last_success_at", "")
        return True, f"status={status}, papers={paper_count}, last_success={last_success_at}"
    return False, f"status={status}"


def update_source_status(
    source: dict,
    status: str,
    db_path: str = "data/papers.db",
    release_status: str = "",
    last_hash: str = "",
    paper_count: int = 0,
    last_error: str = "",
    generated_rule_key: str = "",
):
    name = clean_text(source.get("name", ""))
    venue = clean_text(source.get("venue", ""))
    year = int(source.get("year") or 0)
    url = clean_text(source.get("url", ""))
    parser = clean_text(source.get("parser", ""))
    structure_type = clean_text(source.get("structure_type", ""))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    success_at = now if status.startswith("released") else ""

    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id FROM sources WHERE name=? AND year=? AND url=?", (name, year, url))
    row = cur.fetchone()

    if row is None:
        cur.execute(
            """
            INSERT INTO sources (name, venue, year, url, parser, structure_type, status, release_status,
                last_hash, last_checked_at, last_success_at, last_error, paper_count, generated_rule_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, venue, year, url, parser, structure_type, status, release_status, last_hash, now, success_at, last_error, paper_count, generated_rule_key),
        )
    else:
        cur.execute(
            """
            UPDATE sources
            SET parser=?, structure_type=?, status=?, release_status=?, last_hash=?, last_checked_at=?,
                last_success_at=CASE WHEN ? != '' THEN ? ELSE last_success_at END,
                last_error=?, paper_count=?, generated_rule_key=?
            WHERE id=?
            """,
            (parser, structure_type, status, release_status, last_hash, now, success_at, success_at,
             last_error, paper_count, generated_rule_key, row["id"]),
        )

    conn.commit()
    conn.close()
