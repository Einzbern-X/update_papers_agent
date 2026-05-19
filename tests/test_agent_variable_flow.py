import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import yaml  # noqa: F401
    from agent.paper_agent import PaperCrawlerAgent
    from database.source_repo import get_source_status
except ModuleNotFoundError as exc:
    PaperCrawlerAgent = None
    get_source_status = None
    MISSING_DEPENDENCY = exc.name
else:
    MISSING_DEPENDENCY = ""


@unittest.skipIf(PaperCrawlerAgent is None, f"missing dependency: {MISSING_DEPENDENCY}")
class VariableSourceFlowTest(unittest.TestCase):
    def test_variable_source_stops_when_phase1_does_not_find_release_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.yaml"
            db_path = tmp_path / "papers.db"
            config_path.write_text(
                f"""
request:
  timeout: 1
database:
  path: "{db_path}"
export:
  path: "{tmp_path / 'papers.csv'}"
llm:
  enabled: false
agent:
  auto_generate_rules: true
  skip_done_sources: false
  min_valid_paper_count: 5
  min_title_ratio: 0.9
sources: []
""",
                encoding="utf-8",
            )
            source = {
                "name": "Changing Conf 2026",
                "venue": "Changing Conf",
                "year": 2026,
                "url": "https://conf.example/cfp",
                "parser": "generic",
                "structure_type": "variable",
                "use_llm": True,
            }
            agent = PaperCrawlerAgent(str(config_path))

            with patch("agent.paper_agent.fetch_html", return_value=("<html>Call for Papers</html>", 200)), \
                 patch.object(agent.release_discovery, "discover", return_value={
                     "found": False,
                     "not_released_reason": "only CFP page found",
                 }), \
                 patch.object(agent.extraction_pipeline, "extract_variable",
                              side_effect=AssertionError("should not crawl")):
                agent.run_source(source)

            status = get_source_status(source, str(db_path))
            self.assertEqual(status["status"], "not_released")
            self.assertEqual(status["paper_count"], 0)
            self.assertEqual(status["last_error"], "only CFP page found")


if __name__ == "__main__":
    unittest.main()
