import time

from crawlers.base import fetch_html, make_soup, absolute_url, find_first_pdf_link, dedup_papers
from utils.normalize import clean_text


def _looks_like_ijcai_detail_link(href: str, text: str) -> bool:
    href_lower = (href or "").lower()
    text_lower = (text or "").lower()

    if not href:
        return False

    if text_lower in {"pdf", "details", "bibtex", "abstract"}:
        return False

    # IJCAI proceedings 通常有 /proceedings/year/xxx 或 .html 详情。
    return "proceedings" in href_lower or href_lower.endswith(".html")


def _parse_ijcai_detail(detail_url: str, sleep_seconds: float = 0.2) -> tuple[str, str]:
    authors = ""
    pdf_url = ""

    try:
        if sleep_seconds:
            time.sleep(sleep_seconds)

        html = fetch_html(detail_url)
        soup = make_soup(html)

        pdf_url = find_first_pdf_link(soup, detail_url)

        # 详情页结构可能变化，这里做宽松抽取。
        for tag in soup.find_all(["h3", "h4", "p", "div"]):
            text = clean_text(tag.get_text(" "))
            lower = text.lower()

            if lower.startswith("authors:"):
                authors = clean_text(text.split(":", 1)[-1])
                break

            if lower.startswith("author:"):
                authors = clean_text(text.split(":", 1)[-1])
                break

    except Exception:
        pass

    return authors, pdf_url


def crawl_ijcai(source: dict) -> list[dict]:
    url = source["url"]
    sleep_seconds = float(source.get("sleep_seconds", 0.2))

    html = fetch_html(url)
    soup = make_soup(html)

    papers = []

    for a in soup.find_all("a"):
        title = clean_text(a.get_text(" "))
        href = a.get("href", "")

        if len(title) < 15:
            continue

        if not _looks_like_ijcai_detail_link(href, title):
            continue

        detail_url = absolute_url(url, href)
        authors, pdf_url = _parse_ijcai_detail(detail_url, sleep_seconds=sleep_seconds)

        papers.append({
            "title": title,
            "authors": authors,
            "pdf_url": pdf_url,
        })

    return dedup_papers(papers)
