import time
import yaml
from pathlib import Path

from crawlers.cvf import crawl_cvf
from crawlers.openreview import crawl_openreview
from crawlers.neurips import crawl_neurips
from crawlers.ijcai import crawl_ijcai
from crawlers.acmmm import crawl_acmmm
from crawlers.kdd import crawl_kdd
from crawlers.siggraph import crawl_siggraph
from crawlers.generic import crawl_generic

from database.db import init_db
from database.paper_repo import save_paper, export_papers_to_csv
from utils.normalize import clean_text
from utils.logger import get_logger


CRAWLER_MAP = {
    "cvf": crawl_cvf,
    "openreview": crawl_openreview,
    "neurips": crawl_neurips,
    "ijcai": crawl_ijcai,
    "acmmm": crawl_acmmm,
    "kdd": crawl_kdd,
    "siggraph": crawl_siggraph,
    "generic": crawl_generic,
}


class PaperCrawlerAgent:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self._load_config(config_path)
        self.logger = get_logger()

        self.db_path = self.config.get("database", {}).get("path", "data/papers.db")
        self.export_path = self.config.get("export", {}).get("path", "exports/all_papers.csv")
        self.sleep_seconds = float(self.config.get("request", {}).get("sleep_seconds", 0.2))

        init_db(self.db_path)

    def _load_config(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _normalize_row(self, paper: dict, source: dict) -> dict:
        source_url = source.get("source_url") or source.get("url") or ""

        return {
            "venue": clean_text(source.get("venue", "")),
            "year": source.get("year", ""),
            "title": clean_text(paper.get("title", "")),
            "authors": clean_text(paper.get("authors", "")),
            "pdf_url": clean_text(paper.get("pdf_url", "")),
            "source_url": clean_text(source_url),
        }

    def run(self):
        sources = self.config.get("sources", [])
        self.logger.info("Loaded %d sources from %s", len(sources), self.config_path)

        total_parsed = 0
        total_inserted = 0
        total_updated = 0
        total_skipped = 0

        for source in sources:
            if source.get("enabled", True) is False:
                self.logger.info("Skip disabled source: %s", source.get("name"))
                continue

            name = source.get("name", "")
            parser_name = source.get("parser", "")

            crawler = CRAWLER_MAP.get(parser_name)
            if crawler is None:
                self.logger.warning("Unknown parser '%s' for source: %s", parser_name, name)
                continue

            self.logger.info("Crawling source: %s", name)

            try:
                papers = crawler(source)
            except Exception as e:
                self.logger.exception("Failed to crawl source %s: %s", name, e)
                continue

            self.logger.info("Parsed %d papers from %s", len(papers), name)
            total_parsed += len(papers)

            for paper in papers:
                row = self._normalize_row(paper, source)

                if not row["title"]:
                    total_skipped += 1
                    continue

                result = save_paper(row, self.db_path)

                if result == "inserted":
                    total_inserted += 1
                elif result == "updated":
                    total_updated += 1
                else:
                    total_skipped += 1

            time.sleep(self.sleep_seconds)

        self.logger.info(
            "Finished. parsed=%d inserted=%d updated=%d skipped=%d",
            total_parsed,
            total_inserted,
            total_updated,
            total_skipped,
        )

    def export_csv(self) -> str:
        Path(self.export_path).parent.mkdir(parents=True, exist_ok=True)
        return export_papers_to_csv(self.export_path, self.db_path)
