import time
from typing import Callable

from agent.contracts import INTERNAL_DETAIL_URL_FIELD
from crawlers.base import make_soup
from utils.normalize import abs_url, clean_text


class DetailPageEnricher:
    """补全动态脚本提取出的 detail_url，把它转换成公开字段 pdf_url。"""

    def __init__(
        self,
        fetch_html: Callable[[str, int, str], tuple[str, int]],
        timeout: int,
        user_agent: str,
        logger,
        max_enrich: int = 20,
        sleep_seconds: float = 0.1,
    ):
        self.fetch_html = fetch_html
        self.timeout = timeout
        self.user_agent = user_agent
        self.logger = logger
        self.max_enrich = max_enrich
        self.sleep_seconds = sleep_seconds

    def enrich(self, papers: list[dict]) -> list[dict]:
        enriched_count = 0
        for paper in papers:
            if paper.get("pdf_url") or not paper.get(INTERNAL_DETAIL_URL_FIELD):
                continue
            if enriched_count >= self.max_enrich:
                break

            detail_url = paper[INTERNAL_DETAIL_URL_FIELD]
            try:
                detail_html, status = self.fetch_html(detail_url, self.timeout, self.user_agent)
                if status >= 400:
                    continue

                pdf_url = self._extract_pdf_url(detail_html, detail_url)
                if pdf_url:
                    paper["pdf_url"] = pdf_url

                enriched_count += 1
                time.sleep(self.sleep_seconds)
            except Exception as e:
                self.logger.warning("enrich detail page failed: %s — %s", detail_url, e)

        return papers

    def _extract_pdf_url(self, html: str, detail_url: str) -> str:
        soup = make_soup(html)

        meta = soup.find("meta", attrs={"name": "citation_pdf_url"})
        if meta and meta.get("content"):
            return clean_text(meta["content"])

        for a in soup.find_all("a"):
            label = clean_text(a.get_text(" ")).lower()
            href = a.get("href", "")
            if href.lower().endswith(".pdf") or label in ("pdf", "paper"):
                return abs_url(detail_url, href)

        return ""
