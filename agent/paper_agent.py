import time
import yaml
from crawlers.base import fetch_html, html_hash
from crawlers.cvf import crawl_cvf
from crawlers.ecva import crawl_ecva
from crawlers.ijcai import crawl_ijcai
from crawlers.neurips import crawl_neurips
from crawlers.generic import crawl_generic
from crawlers.rule_based import crawl_by_rule
from crawlers.dynamic_crawler import crawl_by_script
from database.db import init_db
from database.paper_repo import save_paper, export_papers_to_csv
from database.source_repo import update_source_status
from inspector.page_inspector import inspect_page
from inspector.parser_validator import validate_papers
from planner.llm_client import LLMClient, LLMClientWeb
from planner.release_judge import judge_release_status
from planner.extraction_planner import generate_extraction_rule, get_generated_rule, save_generated_rule, source_rule_key
from planner.url_searcher import search_release_url, analyze_page_structure, build_page_crawl_plan
from planner.script_generator import (
    generate_crawl_script,
    get_generated_script,
    save_generated_script,
)
from utils.normalize import clean_text, abs_url
from utils.logger import get_logger
from database.source_repo import is_source_done

CRAWLER_MAP = {
    "cvf": crawl_cvf,
    "ecva": crawl_ecva,
    "ijcai": crawl_ijcai,
    "neurips": crawl_neurips,
    "generic": crawl_generic,
}


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

        agent_cfg = self.config.get("agent", {})
        self.llm_judge_release_for_variable = bool(agent_cfg.get("llm_judge_release_for_variable", True))
        self.auto_generate_rules = bool(agent_cfg.get("auto_generate_rules", True))
        self.save_generated_rules = bool(agent_cfg.get("save_generated_rules", True))
        self.generated_rules_path = agent_cfg.get("generated_rules_path", "runtime_rules/generated_rules.yaml")
        self.generated_scripts_path = agent_cfg.get("generated_scripts_path", "runtime_rules/generated_scripts.yaml")
        self.min_valid_paper_count = int(agent_cfg.get("min_valid_paper_count", 5))
        self.min_title_ratio = float(agent_cfg.get("min_title_ratio", 0.9))
        # 已成功爬取的 source 默认跳过，除非配置 skip_done_sources: false
        self.skip_done_sources = bool(agent_cfg.get("skip_done_sources", True))

        self.llm_cfg = self.config.get("llm", {})
        self.llm_client = LLMClient(self.llm_cfg)
        self.llm_client_web = LLMClientWeb(self.llm_cfg)
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
            "pdf_url": clean_text(paper.get("pdf_url", "")),
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

    # ──────────────────────────────────────────────────────────────────────────
    # 子页面 PDF 补全：当列表页没有 PDF，需要访问 detail_url 获取
    # ──────────────────────────────────────────────────────────────────────────

    def _enrich_papers_with_detail_pages(self, papers: list[dict]) -> list[dict]:
        """
        对 papers 中有 detail_url 但没有 pdf_url 的论文，
        访问 detail_url，从 <meta name="citation_pdf_url"> 或 PDF 链接里提取 pdf_url。
        最多处理 20 篇（避免请求过多）。
        """
        from crawlers.base import make_soup
        enriched_count = 0
        max_enrich = 20

        for paper in papers:
            if paper.get("pdf_url") or not paper.get("detail_url"):
                continue
            if enriched_count >= max_enrich:
                break
            detail_url = paper["detail_url"]
            try:
                detail_html, status = fetch_html(detail_url, self.timeout, self.user_agent)
                if status >= 400:
                    continue
                soup = make_soup(detail_html)

                # 优先：<meta name="citation_pdf_url">
                meta = soup.find("meta", attrs={"name": "citation_pdf_url"})
                if meta and meta.get("content"):
                    paper["pdf_url"] = clean_text(meta["content"])
                    enriched_count += 1
                    time.sleep(0.1)
                    continue

                # 备选：找 href 以 .pdf 结尾的链接，或 label 含 pdf/paper 的链接
                for a in soup.find_all("a"):
                    label = clean_text(a.get_text(" ")).lower()
                    href = a.get("href", "")
                    if href.lower().endswith(".pdf") or label in ("pdf", "paper"):
                        paper["pdf_url"] = abs_url(detail_url, href)
                        break

                enriched_count += 1
                time.sleep(0.1)

            except Exception as e:
                self.logger.warning("enrich detail page failed: %s — %s", detail_url, e)

        return papers

    # ──────────────────────────────────────────────────────────────────────────
    # 固定 parsers / 历史规则 / 历史脚本
    # ──────────────────────────────────────────────────────────────────────────

    def _try_fixed_parser(self, source: dict, html: str):
        parser_name = source.get("parser", "")
        crawler = CRAWLER_MAP.get(parser_name)
        if crawler is None:
            return [], False, f"unknown_parser:{parser_name}"
        papers = crawler(source, html)
        valid, reason = validate_papers(papers, self.min_valid_paper_count, self.min_title_ratio)
        return papers, valid, reason

    def _try_saved_rule(self, source: dict, html: str):
        rule = get_generated_rule(source, self.generated_rules_path)
        if not rule:
            return [], False, "no_saved_rule", ""
        papers = crawl_by_rule(source, html, rule)
        valid, reason = validate_papers(papers, self.min_valid_paper_count, self.min_title_ratio)
        return papers, valid, reason, source_rule_key(source)

    def _try_saved_script(self, source: dict, html: str):
        script_info = get_generated_script(source, self.generated_scripts_path)
        if not script_info:
            return [], False, "no_saved_script", ""
        papers = crawl_by_script(source, html, script_info)
        valid, reason = validate_papers(papers, self.min_valid_paper_count, self.min_title_ratio)
        key = f"{source.get('venue', '')}_{source.get('year', '')}_{source.get('name', '')}"
        return papers, valid, reason, key

    def _generate_rule_and_parse(self, source: dict, html: str, page_info: dict):
        if not self.llm_client.available():
            return [], False, "llm_not_available", ""
        max_html_chars = int(self.llm_cfg.get("max_html_chars", 14000))
        rule = generate_extraction_rule(self.llm_client, page_info, html, max_html_chars=max_html_chars)
        if not rule.get("released") or not rule.get("rule_type"):
            return [], False, f"llm_no_rule:{rule.get('reason', '')}", ""
        papers = crawl_by_rule(source, html, rule)
        valid, reason = validate_papers(papers, self.min_valid_paper_count, self.min_title_ratio)
        key = ""
        if valid and self.save_generated_rules:
            key = save_generated_rule(source, rule, self.generated_rules_path)
        return papers, valid, reason, key

    def _generate_script_and_parse(self, source: dict, html: str, page_info: dict,
                                    crawl_plan: dict | None = None):
        """生成定制爬取脚本并执行。crawl_plan 由 Phase 2 分析提供，可为 None。"""
        if not self.llm_client.available():
            return [], False, "llm_not_available", ""
        max_html_chars = int(self.llm_cfg.get("max_html_chars", 14000))
        script_info = generate_crawl_script(
            self.llm_client, page_info, html,
            max_html_chars=max_html_chars,
            crawl_plan=crawl_plan,
        )
        if not script_info.get("generated") or not script_info.get("script"):
            return [], False, f"llm_no_script:{script_info.get('reason', '')}", ""
        papers = crawl_by_script(source, html, script_info)

        # 如果脚本提取出 detail_url，自动补全 pdf_url
        needs_detail = crawl_plan.get("needs_detail_page", False) if crawl_plan else False
        has_detail_urls = any(p.get("detail_url") for p in papers)
        if (needs_detail or has_detail_urls) and papers:
            self.logger.info("Enriching %d papers with detail pages...", len(papers))
            papers = self._enrich_papers_with_detail_pages(papers)

        valid, reason = validate_papers(papers, self.min_valid_paper_count, self.min_title_ratio)
        key = ""
        if valid and self.save_generated_rules:
            key = save_generated_script(source, script_info, self.generated_scripts_path)
        return papers, valid, reason, key

    def _llm_release_judge(self, source: dict, page_info: dict, html: str):
        if not self.llm_client.available():
            return {"status": "unknown", "reason": "llm_not_available", "confidence": 0.0}
        max_html_chars = int(self.llm_cfg.get("max_html_chars", 14000))
        return judge_release_status(self.llm_client, page_info, html, max_html_chars=max_html_chars)

    # ──────────────────────────────────────────────────────────────────────────
    # Phase 1+2: 搜索放榜 URL & 分析页面结构
    # ──────────────────────────────────────────────────────────────────────────

    def _discover_page_crawl_plan(self, source: dict, html: str) -> dict | None:
        """
        用大模型进行两阶段分析：
          Phase 1: 联网搜索放榜 URL（如果搜索到不同 URL，则重新下载页面）
          Phase 2: 分析已下载页面的 HTML 结构，生成 PageCrawlPlan

        返回 (new_url_or_None, crawl_plan_or_None)
        """
        if not self.llm_client_web.available():
            self.logger.info("LLMClientWeb not available, skip discovery for: %s", source.get("name"))
            return None

        venue = source.get("venue", "")
        year = source.get("year", "")
        search_query = source.get("search_query", f"{venue} {year} accepted papers list official")
        name = source.get("name", "")

        # Phase 1: 搜索
        self.logger.info("[Phase1] Searching release URL for %s ...", name)

        # 如果 source 配置了 skip_url_search: true，跳过联网搜索，直接用配置中的 URL
        if source.get("skip_url_search", False):
            self.logger.info("[Phase1] skip_url_search=true, using config URL directly: %s", source.get("url"))
            search_result = {
                "found": True,
                "url": source.get("url", ""),
                "not_released_reason": "",
                "confidence": 1.0,
                "reason": "skip_url_search: using config url directly",
            }
        else:
            try:
                search_result = search_release_url(self.llm_client_web, venue, year, search_query)
            except Exception as e:
                self.logger.warning("[Phase1] Search failed for %s: %s", name, e)
                return None

        if not search_result.get("found"):
            self.logger.info("[Phase1] %s not released yet: %s", name,
                             search_result.get("not_released_reason", ""))
            # 返回一个标记"未放榜"的 plan
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

        discovered_url = search_result.get("url", "").strip()
        confidence_p1 = float(search_result.get("confidence", 0.0))
        self.logger.info("[Phase1] Found URL: %s (confidence=%.2f)", discovered_url, confidence_p1)

        # 如果搜索到的 URL 和配置中不同，重新下载页面
        current_html = html
        current_url = source.get("url", "")
        if discovered_url and discovered_url != current_url and confidence_p1 >= 0.5:
            self.logger.info("[Phase1] Fetching discovered URL: %s", discovered_url)
            try:
                new_html, new_status = fetch_html(discovered_url, self.timeout, self.user_agent)
                if new_status < 400:
                    current_html = new_html
                    current_url = discovered_url
                else:
                    self.logger.warning("[Phase1] Fetch returned %d for %s", new_status, discovered_url)
            except Exception as e:
                self.logger.warning("[Phase1] Fetch failed for %s: %s", discovered_url, e)

        # Phase 2: 分析页面结构
        max_html_chars = int(self.llm_cfg.get("max_html_chars", 14000))
        html_sample = current_html[:max_html_chars]
        self.logger.info("[Phase2] Analyzing page structure for %s ...", name)
        try:
            analysis = analyze_page_structure(
                self.llm_client_web, current_url, html_sample, venue, year
            )
        except Exception as e:
            self.logger.warning("[Phase2] Analysis failed for %s: %s", name, e)
            analysis = {}

        plan = build_page_crawl_plan(search_result, analysis)
        # 记录搜索发现的 URL，供 run_source 使用
        plan["_discovered_url"] = current_url
        plan["_discovered_html"] = current_html
        self.logger.info(
            "[Phase2] Plan for %s: has_titles=%s, has_authors=%s, has_pdf=%s, needs_detail=%s",
            name,
            plan.get("has_titles"), plan.get("has_authors"),
            plan.get("has_pdf_links"), plan.get("needs_detail_page"),
        )
        return plan

    # ──────────────────────────────────────────────────────────────────────────
    # 主流程
    # ──────────────────────────────────────────────────────────────────────────

    def run_source(self, source: dict):
        name = source.get("name", "")
        url = source.get("url", "")
        structure_type = source.get("structure_type", "stable")
        use_llm = bool(source.get("use_llm", False))
        self.logger.info("Checking source: %s", name)

        # ──────────────────────────────────────────────────────────
        # 已成功爬取过的 source，直接跳过（除非配置 skip_done_sources: false）
        # ──────────────────────────────────────────────────────────
        if self.skip_done_sources:
            done, reason = is_source_done(source, self.db_path)
            if done:
                self.logger.info("✓ Skip already-done source: %s (%s)", name, reason)
                return

        # ──────────────────────────────────────────────────────────
        # stable 来源：直接 fetch + 固定 parser，不调用大模型
        # ──────────────────────────────────────────────────────────
        if structure_type != "variable" or not use_llm:
            try:
                html, status_code = fetch_html(url, self.timeout, self.user_agent)
            except Exception as e:
                update_source_status(source, "fetch_failed", self.db_path, last_error=str(e))
                self.logger.exception("Fetch failed: %s", name)
                return
            h = html_hash(html)
            page_info = inspect_page(source, html, status_code)
            if status_code >= 400:
                update_source_status(source, "not_found", self.db_path, last_hash=h, release_status="not_found")
                return
            papers, valid, reason = self._try_fixed_parser(source, html)
            if valid:
                inserted, updated, skipped = self._save_papers(papers, source)
                update_source_status(source, "released_fixed_parser", self.db_path,
                                     release_status="released_by_parser", last_hash=h, paper_count=len(papers))
                self.logger.info("%s stable ok. papers=%d inserted=%d updated=%d skipped=%d",
                                 name, len(papers), inserted, updated, skipped)
            else:
                update_source_status(source, "not_released_or_parser_failed", self.db_path,
                                     release_status="unknown", last_hash=h, last_error=reason, paper_count=len(papers))
                self.logger.info("%s stable parser invalid: %s", name, reason)
            return

        # ──────────────────────────────────────────────────────────
        # variable 来源：先下载配置中的 URL（用于 Phase 2 分析）
        # ──────────────────────────────────────────────────────────
        try:
            html, status_code = fetch_html(url, self.timeout, self.user_agent)
        except Exception as e:
            update_source_status(source, "fetch_failed", self.db_path, last_error=str(e))
            self.logger.exception("Fetch failed: %s", name)
            return

        h = html_hash(html)
        if status_code >= 400:
            update_source_status(source, "not_found", self.db_path, last_hash=h, release_status="not_found")
            self.logger.info("%s not found: %s", name, status_code)
            return

        # ──────────────────────────────────────────────────────────
        # Phase 1+2: 大模型搜索放榜 URL + 深度分析页面结构
        # ──────────────────────────────────────────────────────────
        crawl_plan = self._discover_page_crawl_plan(source, html)

        if crawl_plan is not None and not crawl_plan.get("found", True):
            # 大模型 Phase1 搜索未找到放榜页，但配置 URL 本身 fetch 已成功（status < 400）
            # → 降级 fallback：跳过 Phase1 判断，直接用配置 URL 继续 Phase2 分析 + 脚本生成
            self.logger.warning(
                "%s: Phase1 returned not-found (reason: %s), but config URL returned %d. "
                "Falling back to config URL for Phase2 analysis.",
                name, crawl_plan.get("not_released_reason", ""), status_code
            )
            crawl_plan["found"] = True
            crawl_plan["url"] = url
            crawl_plan["_discovered_url"] = url
            crawl_plan["_discovered_html"] = html

        # 如果 Phase 1 发现了新的 URL+HTML，使用它们
        if crawl_plan and crawl_plan.get("_discovered_url"):
            discovered_url = crawl_plan["_discovered_url"]
            discovered_html = crawl_plan.get("_discovered_html", html)
            if discovered_url != url:
                self.logger.info("%s: using discovered URL: %s", name, discovered_url)
                source = dict(source)
                source["url"] = discovered_url
                url = discovered_url
                html = discovered_html
                h = html_hash(html)

        page_info = inspect_page(source, html, status_code)

        # ──────────────────────────────────────────────────────────
        # 如果没有 crawl_plan（web client 不可用），退化到旧的 release judge
        # ──────────────────────────────────────────────────────────
        release_judge = {"status": "unknown", "reason": "not_judged"}
        if crawl_plan is None and self.llm_judge_release_for_variable:
            try:
                release_judge = self._llm_release_judge(source, page_info, html)
            except Exception as e:
                update_source_status(source, "llm_release_judge_failed", self.db_path,
                                     last_hash=h, last_error=str(e))
                self.logger.exception("LLM release judge failed: %s", name)
                return
            status = release_judge.get("status", "unknown")
            if status in {"not_released", "id_only"}:
                update_source_status(source, status, self.db_path, release_status=status,
                                     last_hash=h, last_error=release_judge.get("reason", ""))
                self.logger.info("%s release status: %s", name, status)
                return
            if status not in {"released_with_papers", "released_without_pdf"}:
                update_source_status(source, "unknown_release_status", self.db_path,
                                     release_status=status, last_hash=h,
                                     last_error=release_judge.get("reason", ""))
                self.logger.info("%s release status unknown: %s", name, release_judge)
                return

        # ──────────────────────────────────────────────────────────
        # 爬取策略优先级：
        # 1. 历史保存的脚本
        # 2. 历史保存的 rule
        # 3. 固定 parser（generic 等）
        # 4. 大模型生成定制脚本（携带 crawl_plan 信息）
        # 5. 兜底：大模型生成 rule
        # ──────────────────────────────────────────────────────────

        # 1. 历史脚本
        papers, valid, reason, script_key = self._try_saved_script(source, html)
        if valid:
            inserted, updated, skipped = self._save_papers(papers, source)
            update_source_status(source, "released_saved_script", self.db_path,
                                 release_status="released", last_hash=h, paper_count=len(papers))
            self.logger.info("%s saved script ok. papers=%d inserted=%d updated=%d skipped=%d",
                             name, len(papers), inserted, updated, skipped)
            return

        # 2. 历史 rule
        papers, valid, reason, rule_key = self._try_saved_rule(source, html)
        if valid:
            inserted, updated, skipped = self._save_papers(papers, source)
            update_source_status(source, "released_saved_rule", self.db_path,
                                 release_status="released", last_hash=h, paper_count=len(papers),
                                 generated_rule_key=rule_key)
            self.logger.info("%s saved rule ok. papers=%d inserted=%d updated=%d skipped=%d",
                             name, len(papers), inserted, updated, skipped)
            return

        # 3. 固定 parser
        papers, valid, reason = self._try_fixed_parser(source, html)
        if valid:
            inserted, updated, skipped = self._save_papers(papers, source)
            update_source_status(source, "released_fixed_parser", self.db_path,
                                 release_status="released", last_hash=h, paper_count=len(papers))
            self.logger.info("%s fixed parser ok. papers=%d inserted=%d updated=%d skipped=%d",
                             name, len(papers), inserted, updated, skipped)
            return

        if self.auto_generate_rules:
            # 4. 大模型生成定制脚本（携带 crawl_plan，包含页面结构和子页面信息）
            papers, valid, script_reason, script_key = self._generate_script_and_parse(
                source, html, page_info, crawl_plan=crawl_plan
            )
            if valid:
                inserted, updated, skipped = self._save_papers(papers, source)
                update_source_status(source, "released_generated_script", self.db_path,
                                     release_status="released", last_hash=h, paper_count=len(papers))
                self.logger.info("%s generated script ok. papers=%d inserted=%d updated=%d skipped=%d",
                                 name, len(papers), inserted, updated, skipped)
                return

            self.logger.warning("%s generated script failed: %s. Falling back to rule.", name, script_reason)

            # 5. 兜底：大模型生成 rule
            papers, valid, rule_reason, rule_key = self._generate_rule_and_parse(source, html, page_info)
            if valid:
                inserted, updated, skipped = self._save_papers(papers, source)
                update_source_status(source, "released_generated_rule", self.db_path,
                                     release_status="released", last_hash=h, paper_count=len(papers),
                                     generated_rule_key=rule_key)
                self.logger.info("%s generated rule ok. papers=%d inserted=%d updated=%d skipped=%d",
                                 name, len(papers), inserted, updated, skipped)
                return

            update_source_status(source, "llm_rule_failed", self.db_path,
                                 release_status="released", last_hash=h,
                                 last_error=rule_reason, paper_count=len(papers))
            self.logger.warning("%s all strategies failed. last error: %s", name, rule_reason)
            return

        update_source_status(source, "parser_failed", self.db_path,
                             release_status="released", last_hash=h,
                             last_error=reason, paper_count=len(papers))

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
