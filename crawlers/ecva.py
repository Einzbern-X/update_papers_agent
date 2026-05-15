from crawlers.base import make_soup, dedup_papers
from utils.normalize import clean_text, abs_url


def crawl_ecva(source: dict, html: str) -> list[dict]:
    """
    解析 ECVA papers.php 页面。

    页面结构（每篇论文）：
        <dt class="ptitle">
            <a href="...">Paper Title</a>
        </dt>
        <dd>Author1, Author2, ...</dd>
        <dd>
            [<a href="...00004.pdf">pdf</a>]
            ...
        </dd>
    """
    base_url = source["url"]
    soup = make_soup(html)
    papers = []

    # 找所有 <dt class="ptitle">，每个代表一篇论文
    for dt in soup.find_all("dt", class_="ptitle"):
        # 1. 标题：dt 内第一个 <a> 的文本
        title_tag = dt.find("a")
        if not title_tag:
            continue
        title = clean_text(title_tag.get_text(" "))
        if not title:
            continue

        authors = ""
        pdf_url = ""

        # 2. 遍历紧跟在 dt 后面的所有 <dd> 兄弟节点
        sibling = dt.next_sibling
        dd_count = 0
        while sibling is not None:
            # 跳过纯文本/换行节点
            if hasattr(sibling, "name"):
                if sibling.name == "dt":
                    # 下一篇论文开始，停止
                    break
                if sibling.name == "dd":
                    dd_count += 1
                    if dd_count == 1:
                        # 第一个 dd：作者
                        authors = clean_text(sibling.get_text(" "))
                    else:
                        # 后续 dd：找 pdf 链接
                        for a in sibling.find_all("a"):
                            label = clean_text(a.get_text(" ")).lower()
                            href = a.get("href", "")
                            if label == "pdf" or href.lower().endswith(".pdf"):
                                pdf_url = abs_url(base_url, href)
                                break
            sibling = sibling.next_sibling

        papers.append({"title": title, "authors": authors, "pdf_url": pdf_url})

    return dedup_papers(papers)
