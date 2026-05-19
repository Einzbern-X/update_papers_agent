"""
行为测试：验证各 parser 公共接口的提取行为。
遵循 AGENTS.md 规范：测试行为，不测实现细节。
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from crawlers.ecva import crawl_ecva

# ─── ECVA Fixture HTML ────────────────────────────────────────────────────────
# 模拟 ecva.net/papers.php 的 accordion 结构，含 2024 和 2022 两个年份

ECVA_FIXTURE_HTML = """
<html><body>
<div class="py-6 container">
  <h2>ECCV Conference Papers</h2>

  <button class="accordion">ECCV 2024 Papers</button>
  <div class="accordion-content">
    <div id="content">
      <dl>
        The DOI links will be inaccessible until released by Springer.
        <dt class="ptitle"><br>
          <a href="papers/eccv_2024/papers_ECCV/html/4_ECCV_2024_paper.php">
            Paper Alpha 2024
          </a>
        </dt>
        <dd>Alice Smith, Bob Jones</dd>
        <dd>[<a href="papers/eccv_2024/papers_ECCV/papers/00004.pdf">pdf</a>]</dd>

        <dt class="ptitle"><br>
          <a href="papers/eccv_2024/papers_ECCV/html/6_ECCV_2024_paper.php">
            Paper Beta 2024
          </a>
        </dt>
        <dd>Charlie Brown, Diana Prince</dd>
        <dd>[<a href="papers/eccv_2024/papers_ECCV/papers/00006.pdf">pdf</a>]</dd>
      </dl>
    </div>
  </div>

  <button class="accordion">ECCV 2022 Papers</button>
  <div class="accordion-content">
    <div id="content">
      <dl>
        <dt class="ptitle"><br>
          <a href="papers/eccv_2022/papers_ECCV/html/10_ECCV_2022_paper.php">
            Paper Gamma 2022
          </a>
        </dt>
        <dd>Eve White, Frank Black</dd>
        <dd>[<a href="papers/eccv_2022/papers_ECCV/papers/00010.pdf">pdf</a>]</dd>
      </dl>
    </div>
  </div>

  <button class="accordion">ECCV 2020 Papers</button>
  <div class="accordion-content">
    <div id="content">
      <dl>
        <dt class="ptitle"><br>
          <a href="papers/eccv_2020/papers_ECCV/html/5_ECCV_2020_paper.php">
            Paper Delta 2020
          </a>
        </dt>
        <dd>George Green</dd>
        <dd>[<a href="papers/eccv_2020/papers_ECCV/papers/00005.pdf">pdf</a>]</dd>
      </dl>
    </div>
  </div>
</div>
</body></html>
"""


class TestEcvaParser:
    """测试 crawl_ecva 的行为：按年份提取且不混入其他年份论文"""

    def _make_source(self, year):
        return {"url": "https://www.ecva.net/papers.php", "year": year}

    # ── 正常提取 ──────────────────────────────────────────────────────────────

    def test_ecva_extracts_only_2024_papers(self):
        """当 source.year=2024 时，只返回 2024 年的论文"""
        papers = crawl_ecva(self._make_source(2024), ECVA_FIXTURE_HTML)
        titles = [p["title"] for p in papers]
        assert len(papers) == 2, f"期望 2 篇，实际 {len(papers)}: {titles}"
        assert any("Alpha 2024" in t for t in titles)
        assert any("Beta 2024" in t for t in titles)
        # 不含其他年份
        assert not any("2022" in t for t in titles)
        assert not any("2020" in t for t in titles)

    def test_ecva_extracts_only_2022_papers(self):
        """当 source.year=2022 时，只返回 2022 年的论文"""
        papers = crawl_ecva(self._make_source(2022), ECVA_FIXTURE_HTML)
        titles = [p["title"] for p in papers]
        assert len(papers) == 1, f"期望 1 篇，实际 {len(papers)}: {titles}"
        assert "Gamma 2022" in titles[0]
        # 不含其他年份
        assert not any("2024" in t for t in titles)

    def test_ecva_extracts_only_2020_papers(self):
        """当 source.year=2020 时，只返回 2020 年的论文"""
        papers = crawl_ecva(self._make_source(2020), ECVA_FIXTURE_HTML)
        titles = [p["title"] for p in papers]
        assert len(papers) == 1
        assert "Delta 2020" in titles[0]

    # ── 字段完整性 ────────────────────────────────────────────────────────────

    def test_ecva_papers_have_title_and_authors(self):
        """每篇论文都有非空的 title 和 authors"""
        papers = crawl_ecva(self._make_source(2024), ECVA_FIXTURE_HTML)
        for p in papers:
            assert p.get("title"), "title 不能为空"
            assert p.get("authors"), f"论文 '{p['title']}' 的 authors 为空"

    def test_ecva_pdf_url_is_absolute(self):
        """pdf_url 应为绝对 URL"""
        papers = crawl_ecva(self._make_source(2024), ECVA_FIXTURE_HTML)
        for p in papers:
            if p.get("pdf_url"):
                assert p["pdf_url"].startswith("http"), (
                    f"pdf_url 应以 http 开头: {p['pdf_url']}"
                )

    # ── 边界情况 ──────────────────────────────────────────────────────────────

    def test_ecva_returns_empty_for_nonexistent_year(self):
        """请求的年份在页面中不存在时，应返回空列表而非报错"""
        papers = crawl_ecva(self._make_source(2026), ECVA_FIXTURE_HTML)
        assert papers == [], f"不存在的年份应返回 [], 实际: {papers}"

    def test_ecva_returns_empty_for_blank_html(self):
        """空 HTML 时应返回空列表"""
        papers = crawl_ecva(self._make_source(2024), "")
        assert papers == []

    def test_ecva_no_cross_year_contamination(self):
        """2024 和 2022 的结果集互不包含对方的论文（交集为空）"""
        papers_2024 = crawl_ecva(self._make_source(2024), ECVA_FIXTURE_HTML)
        papers_2022 = crawl_ecva(self._make_source(2022), ECVA_FIXTURE_HTML)
        titles_2024 = {p["title"] for p in papers_2024}
        titles_2022 = {p["title"] for p in papers_2022}
        overlap = titles_2024 & titles_2022
        assert not overlap, f"2024 和 2022 结果集存在重叠: {overlap}"
