import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from utils.normalize import clean_text


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PaperCrawlerAgent/1.0; "
        "+https://example.com/paper-crawler)"
    )
}


def fetch_html(url: str, timeout: int = 30) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def absolute_url(base_url: str, href: str) -> str:
    if not href:
        return ""
    return urljoin(base_url, href)


def extract_doi(text: str) -> str:
    text = str(text or "")
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, re.I)
    if not match:
        return ""
    return match.group(0).rstrip(".,);]")


def acm_pdf_from_doi(doi: str) -> str:
    doi = clean_text(doi)
    if not doi:
        return ""

    # 仅构造 ACM PDF 地址，不下载 PDF。
    return f"https://dl.acm.org/doi/pdf/{doi}"


def find_first_pdf_link(soup: BeautifulSoup, base_url: str) -> str:
    for a in soup.find_all("a"):
        label = clean_text(a.get_text(" ")).lower()
        href = a.get("href", "")

        if not href:
            continue

        href_lower = href.lower()

        if (
            "pdf" in label
            or href_lower.endswith(".pdf")
            or "/pdf/" in href_lower
            or "paper" == label
        ):
            return absolute_url(base_url, href)

    return ""


def extract_pdf_from_page(page_url: str, timeout: int = 30, sleep_seconds: float = 0.0) -> str:
    if not page_url:
        return ""

    try:
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

        html = fetch_html(page_url, timeout=timeout)
        soup = make_soup(html)
        return find_first_pdf_link(soup, page_url)
    except Exception:
        return ""


def dedup_papers(papers: list[dict]) -> list[dict]:
    unique = {}

    for paper in papers:
        title = clean_text(paper.get("title", ""))
        if not title:
            continue

        key = title.lower()
        old = unique.get(key)

        if old is None:
            unique[key] = paper
            continue

        # 重复标题时，优先保留有 PDF / 作者更多的记录。
        old_score = int(bool(old.get("pdf_url"))) + int(bool(old.get("authors")))
        new_score = int(bool(paper.get("pdf_url"))) + int(bool(paper.get("authors")))

        if new_score > old_score:
            unique[key] = paper

    return list(unique.values())
