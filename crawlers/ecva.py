import re
from bs4 import Tag, NavigableString

from crawlers.base import make_soup, dedup_papers
from utils.normalize import clean_text, abs_url


YEAR_HEADING_RE = re.compile(r"\bECCV\s+(\d{4})\s+Papers\b", re.I)


def _is_ptitle_dt(node) -> bool:
    return (
        isinstance(node, Tag)
        and node.name == "dt"
        and "ptitle" in (node.get("class") or [])
    )


def _is_year_heading_text(text: str) -> int | None:
    """
    判断文本是否是年份标题，例如：
        ECCV 2024 Papers
        ECCV 2022 Papers
    """
    text = clean_text(text)
    m = YEAR_HEADING_RE.search(text)
    if not m:
        return None
    return int(m.group(1))


def _find_target_year_dts(soup, year: int) -> list[Tag]:
    """
    ECVA papers.php 是多年份混在一个页面里。

    正确逻辑：
        1. 先找到 "ECCV {year} Papers"
        2. 从这个标题后面开始找 dt.ptitle
        3. 遇到下一个 "ECCV xxxx Papers" 就停止

    这样可以避免 2024、2022、2020 等年份混在一起。
    """
    target_re = re.compile(rf"\bECCV\s+{year}\s+Papers\b", re.I)

    marker_text = soup.find(
        string=lambda s: s and target_re.search(clean_text(str(s)))
    )

    if not marker_text:
        return []

    dts = []
    seen = set()

    for node in marker_text.next_elements:
        # 1. 遇到下一个年份标题，停止
        if isinstance(node, NavigableString):
            found_year = _is_year_heading_text(str(node))
            if found_year and found_year != year:
                break

        # 2. 有些年份标题可能包在 h2/h3/div/button 里，也要识别
        if isinstance(node, Tag):
            node_text = clean_text(node.get_text(" ", strip=True))

            # 避免 body/main 这种大容器误判，只判断短文本标签
            if len(node_text) <= 80:
                found_year = _is_year_heading_text(node_text)
                if found_year and found_year != year:
                    break

            # 3. 收集目标年份区间内的论文 dt
            if _is_ptitle_dt(node):
                node_id = id(node)
                if node_id not in seen:
                    dts.append(node)
                    seen.add(node_id)

    return dts


def _parse_one_paper(dt: Tag, base_url: str) -> dict | None:
    """
    解析单篇论文结构：

        <dt class="ptitle">
            <a href="...">Paper Title</a>
        </dt>
        <dd>Author1, Author2, ...</dd>
        <dd>
            [<a href="...pdf">pdf</a>]
            [<a href="...">supplementary material</a>]
            [<a href="...">DOI</a>]
        </dd>
    """
    title_tag = dt.find("a")
    if not title_tag:
        return None

    title = clean_text(title_tag.get_text(" "))
    if not title:
        return None

    detail_url = ""
    if title_tag.get("href"):
        detail_url = abs_url(base_url, title_tag.get("href", ""))

    authors = ""
    pdf_url = ""

    dd_blocks = []

    sibling = dt.next_sibling
    while sibling is not None:
        if isinstance(sibling, Tag):
            # 下一篇论文开始
            if _is_ptitle_dt(sibling):
                break

            # 遇到其他年份标题，也停止
            sibling_text = clean_text(sibling.get_text(" ", strip=True))
            if len(sibling_text) <= 80:
                if _is_year_heading_text(sibling_text):
                    break

            if sibling.name == "dd":
                dd_blocks.append(sibling)

        sibling = sibling.next_sibling

    # 第一个 dd 通常是作者
    if dd_blocks:
        authors = clean_text(dd_blocks[0].get_text(" "))

    # 后续 dd 里找 pdf 链接
    for dd in dd_blocks[1:]:
        for a in dd.find_all("a"):
            label = clean_text(a.get_text(" ")).lower()
            href = a.get("href", "")

            if label == "pdf" or href.lower().endswith(".pdf"):
                pdf_url = abs_url(base_url, href)
                break

        if pdf_url:
            break

    return {
        "title": title,
        "authors": authors,
        "pdf_url": pdf_url,
        "detail_url": detail_url,
    }


def crawl_ecva(source: dict, html: str) -> list[dict]:
    """
    解析 ECVA papers.php 页面。

    注意：
    ECVA 是多年份共用一个页面，所以必须根据 source["year"]
    先截取对应年份区间，否则会把 2024、2022、2020 等论文混在一起。
    """
    base_url = source["url"]
    year = source.get("year")

    if not year:
        raise ValueError("ECVA parser requires source['year'], e.g. 2024")

    year = int(year)

    soup = make_soup(html)
    dts = _find_target_year_dts(soup, year)

    papers = []

    for dt in dts:
        paper = _parse_one_paper(dt, base_url)
        if paper:
            papers.append(paper)

    return dedup_papers(papers)