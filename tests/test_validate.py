import unittest

from inspector.parser_validator import validate_papers


class ValidatePapersBehaviorTest(unittest.TestCase):
    def test_validate_accepts_reasonable_paper_list(self):
        papers = [
            {"title": "A Reliable Parser for Changing Conference Websites"},
            {"title": "Robust Paper Discovery with Release Page Verification"},
            {"title": "Learning Structured Extraction Plans from HTML"},
            {"title": "Detecting Accepted Paper Lists without Crawling Noise"},
            {"title": "Detail Page Enrichment for Scholarly Metadata"},
        ]

        self.assertEqual(validate_papers(papers, min_count=5, min_title_ratio=0.9), (True, "ok"))


    def test_validate_rejects_navigation_items(self):
        papers = [
            {"title": "Home"},
            {"title": "Program"},
            {"title": "Schedule"},
            {"title": "Registration"},
            {"title": "Call for Papers"},
        ]

        valid, reason = validate_papers(papers, min_count=5, min_title_ratio=0.9)

        self.assertFalse(valid)
        self.assertEqual(reason, "too_many_navigation_titles")


    def test_validate_rejects_urls_mixed_into_titles(self):
        papers = [
            {"title": "A Reliable Parser for Changing Conference Websites https://doi.org/10.1145/123"},
            {"title": "Robust Paper Discovery with Release Page Verification https://doi.org/10.1145/456"},
            {"title": "Learning Structured Extraction Plans from HTML https://doi.org/10.1145/789"},
            {"title": "Detecting Accepted Paper Lists without Crawling Noise https://doi.org/10.1145/101"},
            {"title": "Detail Page Enrichment for Scholarly Metadata https://doi.org/10.1145/112"},
        ]

        valid, reason = validate_papers(papers, min_count=5, min_title_ratio=0.9)

        self.assertFalse(valid)
        self.assertEqual(reason, "too_many_urls_in_titles")


    def test_validate_rejects_duplicate_titles(self):
        papers = [
            {"title": "A Reliable Parser for Changing Conference Websites"},
            {"title": "A Reliable Parser for Changing Conference Websites"},
            {"title": "A Reliable Parser for Changing Conference Websites"},
            {"title": "Robust Paper Discovery with Release Page Verification"},
            {"title": "Robust Paper Discovery with Release Page Verification"},
        ]

        valid, reason = validate_papers(papers, min_count=5, min_title_ratio=0.9)

        self.assertFalse(valid)
        self.assertTrue(reason.startswith("too_many_duplicate_titles"))


if __name__ == "__main__":
    unittest.main()
