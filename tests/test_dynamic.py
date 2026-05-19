import unittest

from crawlers.dynamic_crawler import run_generated_script


class DynamicCrawlerBehaviorTest(unittest.TestCase):
    def test_dynamic_script_preserves_detail_url(self):
        script = """
from bs4 import BeautifulSoup
from urllib.parse import urljoin

def extract_papers(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    papers = []
    for item in soup.select(".paper"):
        papers.append({
            "title": item.select_one(".title").get_text(" "),
            "authors": item.select_one(".authors").get_text(" "),
            "detail_url": urljoin(base_url, item.select_one("a")["href"]),
        })
    return papers
"""
        html = """
<section>
  <div class="paper"><a class="title" href="/papers/1">A Reliable Parser for Changing Conference Websites</a><span class="authors">Ada Lovelace</span></div>
  <div class="paper"><a class="title" href="/papers/2">Robust Paper Discovery with Release Page Verification</a><span class="authors">Grace Hopper</span></div>
</section>
"""

        papers = run_generated_script(script, html, "https://conf.example/accepted")

        self.assertEqual(papers[0]["detail_url"], "https://conf.example/papers/1")
        self.assertEqual(papers[1]["detail_url"], "https://conf.example/papers/2")


    def test_sandbox_blocks_import_os(self):
        script = """
import os

def extract_papers(html: str, base_url: str) -> list[dict]:
    return [{"title": os.getcwd()}]
"""

        self.assertEqual(run_generated_script(script, "<html></html>", "https://conf.example"), [])


if __name__ == "__main__":
    unittest.main()
