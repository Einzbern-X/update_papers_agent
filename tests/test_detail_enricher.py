import unittest

from agent.detail_enricher import DetailPageEnricher


class _Logger:
    def warning(self, *_args):
        pass


class DetailPageEnricherBehaviorTest(unittest.TestCase):
    def test_enrich_uses_citation_pdf_meta(self):
        def fetch_html(_url, _timeout, _user_agent):
            return (
                '<html><head><meta name="citation_pdf_url" '
                'content="https://conf.example/papers/1.pdf"></head></html>',
                200,
            )

        enricher = DetailPageEnricher(fetch_html, timeout=1, user_agent="", logger=_Logger(), sleep_seconds=0)
        papers = [{"title": "A Reliable Parser", "detail_url": "https://conf.example/papers/1"}]

        enriched = enricher.enrich(papers)

        self.assertEqual(enriched[0]["pdf_url"], "https://conf.example/papers/1.pdf")

    def test_enrich_resolves_relative_pdf_links(self):
        def fetch_html(_url, _timeout, _user_agent):
            return ('<html><body><a href="../paper.pdf">PDF</a></body></html>', 200)

        enricher = DetailPageEnricher(fetch_html, timeout=1, user_agent="", logger=_Logger(), sleep_seconds=0)
        papers = [{"title": "A Reliable Parser", "detail_url": "https://conf.example/session/papers/1"}]

        enriched = enricher.enrich(papers)

        self.assertEqual(enriched[0]["pdf_url"], "https://conf.example/session/paper.pdf")


if __name__ == "__main__":
    unittest.main()
