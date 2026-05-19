from dataclasses import dataclass

from agent.contracts import INTERNAL_DETAIL_URL_FIELD
from agent.parser_registry import get_crawler
from crawlers.dynamic_crawler import crawl_by_script
from crawlers.rule_based import crawl_by_rule
from inspector.parser_validator import validate_papers
from planner.extraction_planner import (
    generate_extraction_rule,
    get_generated_rule,
    save_generated_rule,
    source_rule_key,
)
from planner.script_generator import (
    fix_crawl_script,
    generate_crawl_script,
    get_generated_script,
    save_generated_script,
)


@dataclass
class ExtractionAttempt:
    papers: list[dict]
    valid: bool
    reason: str
    status: str = ""
    generated_rule_key: str = ""


class ExtractionPipeline:
    """Runs the ordered extraction strategies for a source."""

    def __init__(
        self,
        llm_client,
        llm_cfg: dict,
        agent_cfg: dict,
        detail_enricher,
        logger,
    ):
        self.llm_client = llm_client
        self.llm_cfg = llm_cfg
        self.detail_enricher = detail_enricher
        self.logger = logger

        self.auto_generate_rules = bool(agent_cfg.get("auto_generate_rules", True))
        self.save_generated_rules = bool(agent_cfg.get("save_generated_rules", True))
        self.generated_rules_path = agent_cfg.get("generated_rules_path", "runtime_rules/generated_rules.yaml")
        self.generated_scripts_path = agent_cfg.get("generated_scripts_path", "runtime_rules/generated_scripts.yaml")
        self.min_valid_paper_count = int(agent_cfg.get("min_valid_paper_count", 5))
        self.min_title_ratio = float(agent_cfg.get("min_title_ratio", 0.9))
        self.max_reflection_rounds = int(agent_cfg.get("max_reflection_rounds", 2))

    def extract_stable(self, source: dict, html: str) -> ExtractionAttempt:
        return self.try_fixed_parser(source, html)

    def extract_variable(
        self,
        source: dict,
        html: str,
        page_info: dict,
        crawl_plan: dict | None = None,
    ) -> ExtractionAttempt:
        last_attempt = ExtractionAttempt([], False, "not_attempted")
        for strategy in (
            self.try_saved_script,
            self.try_saved_rule,
            self.try_fixed_parser,
        ):
            attempt = strategy(source, html)
            if attempt.valid:
                return attempt
            last_attempt = attempt

        if not self.auto_generate_rules:
            return ExtractionAttempt(
                papers=last_attempt.papers,
                valid=False,
                reason=last_attempt.reason,
                status="parser_failed",
            )

        script_attempt = self.generate_script_and_parse(source, html, page_info, crawl_plan=crawl_plan)
        if script_attempt.valid:
            return script_attempt

        self.logger.warning(
            "%s generated script failed: %s. Falling back to rule.",
            source.get("name", ""),
            script_attempt.reason,
        )

        rule_attempt = self.generate_rule_and_parse(source, html, page_info)
        if rule_attempt.valid:
            return rule_attempt

        return ExtractionAttempt(
            papers=rule_attempt.papers,
            valid=False,
            reason=rule_attempt.reason,
            status="llm_rule_failed",
            generated_rule_key=rule_attempt.generated_rule_key,
        )

    def try_fixed_parser(self, source: dict, html: str) -> ExtractionAttempt:
        parser_name = source.get("parser", "")
        crawler = get_crawler(parser_name)
        if crawler is None:
            return ExtractionAttempt([], False, f"unknown_parser:{parser_name}")
        papers = crawler(source, html)
        return self._validated(papers, "released_fixed_parser")

    def try_saved_rule(self, source: dict, html: str) -> ExtractionAttempt:
        rule = get_generated_rule(source, self.generated_rules_path)
        if not rule:
            return ExtractionAttempt([], False, "no_saved_rule")
        papers = crawl_by_rule(source, html, rule)
        return self._validated(
            papers,
            "released_saved_rule",
            generated_rule_key=source_rule_key(source),
        )

    def try_saved_script(self, source: dict, html: str) -> ExtractionAttempt:
        script_info = get_generated_script(source, self.generated_scripts_path)
        if not script_info:
            return ExtractionAttempt([], False, "no_saved_script")
        papers = crawl_by_script(source, html, script_info)
        papers = self._enrich_if_needed(papers)
        return self._validated(papers, "released_saved_script")

    def generate_rule_and_parse(self, source: dict, html: str, page_info: dict) -> ExtractionAttempt:
        if not self.llm_client.available():
            return ExtractionAttempt([], False, "llm_not_available")

        max_html_chars = int(self.llm_cfg.get("max_html_chars", 14000))
        rule = generate_extraction_rule(self.llm_client, page_info, html, max_html_chars=max_html_chars)
        if not rule.get("released") or not rule.get("rule_type"):
            return ExtractionAttempt([], False, f"llm_no_rule:{rule.get('reason', '')}")

        papers = crawl_by_rule(source, html, rule)
        attempt = self._validated(papers, "released_generated_rule")
        if attempt.valid and self.save_generated_rules:
            attempt.generated_rule_key = save_generated_rule(source, rule, self.generated_rules_path)
        return attempt

    def generate_script_and_parse(
        self,
        source: dict,
        html: str,
        page_info: dict,
        crawl_plan: dict | None = None,
    ) -> ExtractionAttempt:
        if not self.llm_client.available():
            return ExtractionAttempt([], False, "llm_not_available")

        max_html_chars = int(self.llm_cfg.get("max_html_chars", 14000))
        script_info = generate_crawl_script(
            self.llm_client,
            page_info,
            html,
            max_html_chars=max_html_chars,
            crawl_plan=crawl_plan,
        )
        if not script_info.get("generated") or not script_info.get("script"):
            return ExtractionAttempt([], False, f"llm_no_script:{script_info.get('reason', '')}")

        papers = crawl_by_script(source, html, script_info)
        valid, reason = self._validate(papers)
        self.logger.info("Script round 0: papers=%d valid=%s reason=%s", len(papers), valid, reason)

        for round_idx in range(1, self.max_reflection_rounds + 1):
            if valid:
                break

            self.logger.info("Reflection round %d: attempting to fix script...", round_idx)
            fixed_info = fix_crawl_script(
                self.llm_client,
                original_script=script_info["script"],
                papers=papers,
                html=html,
                max_html_chars=max_html_chars,
            )
            if not fixed_info.get("generated") or not fixed_info.get("script"):
                self.logger.info(
                    "Reflection round %d: no fix generated (%s)",
                    round_idx,
                    fixed_info.get("reason", ""),
                )
                break

            script_info = fixed_info
            papers = crawl_by_script(source, html, script_info)
            valid, reason = self._validate(papers)
            self.logger.info(
                "Reflection round %d: papers=%d valid=%s reason=%s",
                round_idx,
                len(papers),
                valid,
                reason,
            )

        needs_detail = crawl_plan.get("needs_detail_page", False) if crawl_plan else False
        if (needs_detail or self._has_detail_urls(papers)) and papers:
            self.logger.info("Enriching %d papers with detail pages...", len(papers))
            papers = self.detail_enricher.enrich(papers)

        attempt = self._validated(papers, "released_generated_script")
        if attempt.valid and self.save_generated_rules:
            attempt.generated_rule_key = save_generated_script(source, script_info, self.generated_scripts_path)
        return attempt

    def _validated(
        self,
        papers: list[dict],
        status: str,
        generated_rule_key: str = "",
    ) -> ExtractionAttempt:
        valid, reason = self._validate(papers)
        return ExtractionAttempt(papers, valid, reason, status, generated_rule_key)

    def _validate(self, papers: list[dict]) -> tuple[bool, str]:
        return validate_papers(papers, self.min_valid_paper_count, self.min_title_ratio)

    def _enrich_if_needed(self, papers: list[dict]) -> list[dict]:
        if any(p.get(INTERNAL_DETAIL_URL_FIELD) and not p.get("pdf_url") for p in papers):
            return self.detail_enricher.enrich(papers)
        return papers

    def _has_detail_urls(self, papers: list[dict]) -> bool:
        return any(p.get(INTERNAL_DETAIL_URL_FIELD) for p in papers)
