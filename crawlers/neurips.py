import time

from crawlers.base import fetch_html, make_soup, absolute_url, find_first_pdf_link, dedup_papers
from utils.normalize import clean_text


def _parse_detail_page(detail_url: str, sleep_seconds: float = 0.2) -> str:
    try:
        if sleep_seconds:
            time.sleep(sleep_seconds)

        html = fetch_html(detail_url)
        soup = make_soup(html)
        return find_first_pdf_link(soup, detail_url)
    except Exception:
        return ""


def crawl_neurips(source: dict) -> list[dict]:
    url = source["url"]
    sleep_seconds = float(source.get("sleep_seconds", 0.2))

    html = fetch_html(url)
    soup = make_soup(html)

    papers = []

    for li in soup.find_all("li"):
        a = li.find("a")
        if not a:
            continue

        title = clean_text(a.get_text(" "))
        href = a.get("href", "")

        if len(title) < 10 or not href:
            continue

        paper_url = absolute_url(url, href)

        authors = ""
        i_tag = li.find("i")
        if i_tag:
            authors = clean_text(i_tag.get_text(" "))

        pdf_url = _parse_detail_page(paper_url, sleep_seconds=sleep_seconds)

        papers.append({
            "title": title,
            "authors": authors,
            "pdf_url": pdf_url,
        })

    return dedup_papers(papers)
