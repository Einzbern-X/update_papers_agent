from typing import Callable

from crawlers.base import html_hash
from planner.script_generator import extract_html_structure_sample
from planner.url_searcher import analyze_page_structure, build_page_crawl_plan, search_release_url


class ReleaseDiscoveryAgent:
    """Phase 1/2 for variable sources: find the release URL, then plan extraction."""

    def __init__(
        self,
        llm_client_web,
        llm_cfg: dict,
        fetch_html: Callable[[str, int, str], tuple[str, int]],
        timeout: int,
        user_agent: str,
        logger,
    ):
        self.llm_client_web = llm_client_web
        self.llm_cfg = llm_cfg
        self.fetch_html = fetch_html
        self.timeout = timeout
        self.user_agent = user_agent
        self.logger = logger

    def discover(self, source: dict, html: str, status_code: int = 200) -> dict | None:
        if not self.llm_client_web.available():
            self.logger.info("LLMClientWeb not available, skip discovery for: %s", source.get("name"))
            return None

        venue = source.get("venue", "")
        year = source.get("year", "")
        search_query = source.get("search_query", f"{venue} {year} accepted papers list official")
        name = source.get("name", "")

        self.logger.info("[Phase1] Searching release URL for %s ...", name)
        search_result = self._search(source, venue, year, search_query)
        if search_result is None:
            return None

        if not search_result.get("found"):
            self.logger.info(
                "[Phase1] %s not released yet: %s",
                name,
                search_result.get("not_released_reason", ""),
            )
            return self._not_found_plan(source, search_result)

        current_html, current_url, current_status = self._fetch_discovered_page(
            source, html, status_code, search_result
        )
        analysis = self._analyze(source, current_url, current_html)

        plan = build_page_crawl_plan(search_result, analysis)
        plan["_discovered_url"] = current_url
        plan["_discovered_html"] = current_html
        plan["_discovered_status"] = current_status
        plan["_discovered_hash"] = html_hash(current_html)

        self.logger.info(
            "[Phase2] Plan for %s: has_titles=%s, has_authors=%s, has_pdf=%s, needs_detail=%s",
            name,
            plan.get("has_titles"),
            plan.get("has_authors"),
            plan.get("has_pdf_links"),
            plan.get("needs_detail_page"),
        )
        return plan

    def _search(self, source: dict, venue: str, year: int, search_query: str) -> dict | None:
        if source.get("skip_url_search", False):
            self.logger.info("[Phase1] skip_url_search=true, using config URL directly: %s", source.get("url"))
            return {
                "found": True,
                "url": source.get("url", ""),
                "not_released_reason": "",
                "confidence": 1.0,
                "reason": "skip_url_search: using config url directly",
            }

        try:
            return search_release_url(
                self.llm_client_web,
                venue,
                year,
                search_query,
                configured_url=source.get("url", ""),
            )
        except Exception as e:
            self.logger.warning("[Phase1] Search failed for %s: %s", source.get("name", ""), e)
            return None

    def _fetch_discovered_page(
        self,
        source: dict,
        html: str,
        status_code: int,
        search_result: dict,
    ) -> tuple[str, str, int]:
        current_html = html
        current_url = source.get("url", "")
        current_status = status_code
        discovered_url = search_result.get("url", "").strip()
        confidence = float(search_result.get("confidence", 0.0))
        self.logger.info("[Phase1] Found URL: %s (confidence=%.2f)", discovered_url, confidence)

        if not discovered_url or discovered_url == current_url or confidence < 0.5:
            return current_html, current_url, current_status

        self.logger.info("[Phase1] Fetching discovered URL: %s", discovered_url)
        try:
            new_html, new_status = self.fetch_html(discovered_url, self.timeout, self.user_agent)
            if new_status < 400:
                return new_html, discovered_url, new_status
            self.logger.warning("[Phase1] Fetch returned %d for %s", new_status, discovered_url)
        except Exception as e:
            self.logger.warning("[Phase1] Fetch failed for %s: %s", discovered_url, e)

        return current_html, current_url, current_status

    def _analyze(self, source: dict, url: str, html: str) -> dict:
        max_html_chars = int(self.llm_cfg.get("max_html_chars", 14000))
        html_sample = extract_html_structure_sample(html, max_chars=max_html_chars)
        self.logger.info("[Phase2] Analyzing page structure for %s ...", source.get("name", ""))
        try:
            return analyze_page_structure(
                self.llm_client_web,
                url,
                html_sample,
                source.get("venue", ""),
                source.get("year", ""),
            )
        except Exception as e:
            self.logger.warning("[Phase2] Analysis failed for %s: %s", source.get("name", ""), e)
            return {}

    def _not_found_plan(self, source: dict, search_result: dict) -> dict:
        return {
            "found": False,
            "url": source.get("url", ""),
            "not_released_reason": search_result.get("not_released_reason", "not_found"),
            "has_titles": False,
            "has_authors": False,
            "has_pdf_links": False,
            "needs_detail_page": False,
            "detail_page_pattern": "",
            "detail_page_has_pdf": False,
            "page_structure_notes": "",
            "confidence": search_result.get("confidence", 0.0),
            "reason": search_result.get("reason", ""),
        }
