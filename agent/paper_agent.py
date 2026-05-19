import time
import yaml
from crawlers.base import fetch_html, html_hash
from agent.contracts import RELEASE_JUDGE_NOT_READY_STATUSES, RELEASE_JUDGE_READY_STATUSES
from agent.detail_enricher import DetailPageEnricher
from agent.extraction_pipeline import ExtractionPipeline
from agent.release_discovery import ReleaseDiscoveryAgent
from database.db import init_db
from database.paper_repo import save_paper, export_papers_to_csv
from database.source_repo import is_source_done, update_source_status
from inspector.page_inspector import inspect_page
from planner.llm_client import LLMClient, LLMClientWeb
from planner.release_judge import judge_release_status
from utils.normalize import clean_text, normalize_pdf_url
from utils.logger import get_logger


class PaperCrawlerAgent:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self._load_config(config_path)
        self.logger = get_logger()

        self.db_path = self.config.get("database", {}).get("path", "data/papers.db")
        self.export_path = self.config.get("export", {}).get("path", "exports/all_papers.csv")
        req = self.config.get("request", {})
        self.timeout = int(req.get("timeout", 30))
        self.sleep_seconds = float(req.get("sleep_seconds", 0.2))
        self.user_agent = req.get("user_agent", "")

        self.agent_cfg = self.config.get("agent", {})
        self.llm_judge_release_for_variable = bool(self.agent_cfg.get("llm_judge_release_for_variable", True))
        # 已成功爬取的 source 默认跳过，除非配置 skip_done_sources: false
        self.skip_done_sources = bool(self.agent_cfg.get("skip_done_sources", True))

        self.llm_cfg = self.config.get("llm", {})
        self.llm_client = LLMClient(self.llm_cfg)
        self.llm_client_web = LLMClientWeb(self.llm_cfg)
        self.detail_enricher = DetailPageEnricher(
            fetch_html=fetch_html,
            timeout=self.timeout,
            user_agent=self.user_agent,
            logger=self.logger,
        )
        self.extraction_pipeline = ExtractionPipeline(
            llm_client=self.llm_client,
            llm_cfg=self.llm_cfg,
            agent_cfg=self.agent_cfg,
            detail_enricher=self.detail_enricher,
            logger=self.logger,
        )
        self.release_discovery = ReleaseDiscoveryAgent(
            llm_client_web=self.llm_client_web,
            llm_cfg=self.llm_cfg,
            fetch_html=fetch_html,
            timeout=self.timeout,
            user_agent=self.user_agent,
            logger=self.logger,
        )
        init_db(self.db_path)

    def _load_config(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _paper_row(self, paper: dict, source: dict) -> dict:
        return {
            "venue": clean_text(source.get("venue", "")),
            "year": int(source.get("year") or 0),
            "title": clean_text(paper.get("title", "")),
            "authors": clean_text(paper.get("authors", "")),
            "pdf_url": normalize_pdf_url(paper.get("pdf_url", "")),
            "source_url": clean_text(source.get("url", "")),
        }

    def _save_papers(self, papers: list[dict], source: dict) -> tuple[int, int, int]:
        inserted = updated = skipped = 0
        for p in papers:
            result = save_paper(self._paper_row(p, source), self.db_path)
            if result == "inserted":
                inserted += 1
            elif result == "updated":
                updated += 1
            else:
                skipped += 1
        return inserted, updated, skipped

    def _record_success(self, source: dict, attempt, last_hash: str, release_status: str = "released"):
        inserted, updated, skipped = self._save_papers(attempt.papers, source)
        update_source_status(
            source,
            attempt.status,
            self.db_path,
            release_status=release_status,
            last_hash=last_hash,
            paper_count=len(attempt.papers),
            generated_rule_key=attempt.generated_rule_key,
        )
        self.logger.info(
            "%s %s ok. papers=%d inserted=%d updated=%d skipped=%d",
            source.get("name", ""),
            attempt.status,
            len(attempt.papers),
            inserted,
            updated,
            skipped,
        )

    def _record_failure(self, source: dict, status: str, last_hash: str, reason: str,
                        paper_count: int = 0, release_status: str = "released",
                        generated_rule_key: str = ""):
        update_source_status(
            source,
            status,
            self.db_path,
            release_status=release_status,
            last_hash=last_hash,
            last_error=reason,
            paper_count=paper_count,
            generated_rule_key=generated_rule_key,
        )

    def _fetch_source(self, source: dict) -> tuple[str, int, str] | None:
        name = source.get("name", "")
        try:
            html, status_code = fetch_html(source.get("url", ""), self.timeout, self.user_agent)
        except Exception as e:
            update_source_status(source, "fetch_failed", self.db_path, last_error=str(e))
            self.logger.exception("Fetch failed: %s", name)
            return None

        last_hash = html_hash(html)
        if status_code >= 400:
            update_source_status(source, "not_found", self.db_path,
                                 last_hash=last_hash, release_status="not_found")
            self.logger.info("%s not found: %s", name, status_code)
            return None

        return html, status_code, last_hash

    def _llm_release_judge(self, source: dict, page_info: dict, html: str):
        if not self.llm_client.available():
            return {"status": "unknown", "reason": "llm_not_available", "confidence": 0.0}
        max_html_chars = int(self.llm_cfg.get("max_html_chars", 14000))
        return judge_release_status(self.llm_client, page_info, html, max_html_chars=max_html_chars)

    def _is_variable_source(self, source: dict) -> bool:
        return source.get("structure_type", "stable") == "variable" and bool(source.get("use_llm", False))

    def _should_skip_done_source(self, source: dict) -> bool:
        if not self.skip_done_sources:
            return False
        done, reason = is_source_done(source, self.db_path)
        if done:
            self.logger.info("✓ Skip already-done source: %s (%s)", source.get("name", ""), reason)
        return done

    def _run_stable_source(self, source: dict):
        fetched = self._fetch_source(source)
        if fetched is None:
            return
        html, _status_code, last_hash = fetched

        attempt = self.extraction_pipeline.extract_stable(source, html)
        if attempt.valid:
            self._record_success(source, attempt, last_hash, release_status="released_by_parser")
            return

        self._record_failure(
            source,
            "not_released_or_parser_failed",
            last_hash,
            attempt.reason,
            paper_count=len(attempt.papers),
            release_status="unknown",
        )
        self.logger.info("%s stable parser invalid: %s", source.get("name", ""), attempt.reason)

    def _run_variable_source(self, source: dict):
        fetched = self._fetch_source(source)
        if fetched is None:
            return
        html, status_code, last_hash = fetched

        crawl_plan = self.release_discovery.discover(source, html, status_code=status_code)
        if crawl_plan is not None and not crawl_plan.get("found", True):
            reason = crawl_plan.get("not_released_reason") or crawl_plan.get("reason", "not_found")
            self._record_failure(source, "not_released", last_hash, reason,
                                 release_status="not_released")
            self.logger.info("%s variable source not released: %s", source.get("name", ""), reason)
            return

        source, html, status_code, last_hash = self._apply_discovered_page(
            source, html, status_code, last_hash, crawl_plan
        )
        page_info = inspect_page(source, html, status_code)

        if not self._release_judge_allows_extraction(source, page_info, html, last_hash, crawl_plan):
            return

        attempt = self.extraction_pipeline.extract_variable(source, html, page_info, crawl_plan=crawl_plan)
        if attempt.valid:
            self._record_success(source, attempt, last_hash)
            return

        self._record_failure(
            source,
            attempt.status or "parser_failed",
            last_hash,
            attempt.reason,
            paper_count=len(attempt.papers),
            generated_rule_key=attempt.generated_rule_key,
        )
        self.logger.warning("%s all strategies failed. last error: %s", source.get("name", ""), attempt.reason)

    def _apply_discovered_page(
        self,
        source: dict,
        html: str,
        status_code: int,
        last_hash: str,
        crawl_plan: dict | None,
    ) -> tuple[dict, str, int, str]:
        if not crawl_plan or not crawl_plan.get("_discovered_url"):
            return source, html, status_code, last_hash

        discovered_url = crawl_plan["_discovered_url"]
        if discovered_url == source.get("url", ""):
            return source, html, status_code, last_hash

        self.logger.info("%s: using discovered URL: %s", source.get("name", ""), discovered_url)
        discovered_source = dict(source)
        discovered_source["url"] = discovered_url
        return (
            discovered_source,
            crawl_plan.get("_discovered_html", html),
            int(crawl_plan.get("_discovered_status", status_code)),
            crawl_plan.get("_discovered_hash", html_hash(crawl_plan.get("_discovered_html", html))),
        )

    def _release_judge_allows_extraction(
        self,
        source: dict,
        page_info: dict,
        html: str,
        last_hash: str,
        crawl_plan: dict | None,
    ) -> bool:
        if crawl_plan is not None or not self.llm_judge_release_for_variable:
            return True

        try:
            release_judge = self._llm_release_judge(source, page_info, html)
        except Exception as e:
            self._record_failure(source, "llm_release_judge_failed", last_hash, str(e),
                                 release_status="")
            self.logger.exception("LLM release judge failed: %s", source.get("name", ""))
            return False

        status = release_judge.get("status", "unknown")
        if status in RELEASE_JUDGE_NOT_READY_STATUSES:
            self._record_failure(source, status, last_hash, release_judge.get("reason", ""),
                                 release_status=status)
            self.logger.info("%s release status: %s", source.get("name", ""), status)
            return False

        if status not in RELEASE_JUDGE_READY_STATUSES:
            self._record_failure(source, "unknown_release_status", last_hash,
                                 release_judge.get("reason", ""), release_status=status)
            self.logger.info("%s release status unknown: %s", source.get("name", ""), release_judge)
            return False

        return True

    # ──────────────────────────────────────────────────────────────────────────
    # 主流程
    # ──────────────────────────────────────────────────────────────────────────

    def run_source(self, source: dict):
        name = source.get("name", "")
        self.logger.info("Checking source: %s", name)

        if self._should_skip_done_source(source):
            return

        if self._is_variable_source(source):
            self._run_variable_source(source)
        else:
            self._run_stable_source(source)

    def run(self):
        sources = self.config.get("sources", [])
        self.logger.info("Loaded %d sources", len(sources))
        for source in sources:
            if source.get("enabled", True) is False:
                self.logger.info("Skip disabled source: %s", source.get("name", ""))
                continue
            self.run_source(source)
            time.sleep(self.sleep_seconds)
        self.logger.info("Run finished")

    def export_csv(self) -> str:
        return export_papers_to_csv(self.export_path, self.db_path)
