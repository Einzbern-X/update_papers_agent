import hashlib
import re
import requests
from bs4 import BeautifulSoup
from utils.normalize import clean_text, abs_url


def fetch_html(url: str, timeout: int = 30, user_agent: str = "") -> tuple[str, int]:
    headers = {"User-Agent": user_agent or "Mozilla/5.0 PaperCrawlerAgent/1.0"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    return resp.text, resp.status_code


def make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "lxml")


def html_hash(html: str) -> str:
    return hashlib.md5((html or "").encode("utf-8", errors="ignore")).hexdigest()


def extract_doi(text: str) -> str:
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", str(text or ""), re.I)
    if not match:
        return ""
    return match.group(0).rstrip(".,);]")


def acm_pdf_from_doi(doi: str) -> str:
    doi = clean_text(doi)
    if not doi:
        return ""
    return f"https://dl.acm.org/doi/pdf/{doi}"


def find_first_pdf_link(soup: BeautifulSoup, base_url: str) -> str:
    for a in soup.find_all("a"):
        label = clean_text(a.get_text(" ")).lower()
        href = a.get("href", "")
        h = href.lower()
        if "pdf" in label or h.endswith(".pdf") or "/pdf/" in h or "arxiv.org/pdf" in h:
            return abs_url(base_url, href)
    return ""


def dedup_papers(papers: list[dict]) -> list[dict]:
    unique = {}
    for p in papers:
        title = clean_text(p.get("title", ""))
        if not title:
            continue
        key = title.lower()
        old = unique.get(key)
        if old is None:
            unique[key] = p
            continue
        old_score = int(bool(old.get("pdf_url"))) + int(bool(old.get("authors")))
        new_score = int(bool(p.get("pdf_url"))) + int(bool(p.get("authors")))
        if new_score > old_score:
            unique[key] = p
    return list(unique.values())
