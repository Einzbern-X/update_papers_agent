from crawlers.base import make_soup, dedup_papers
from utils.normalize import clean_text, abs_url


def crawl_ecva(source: dict, html: str) -> list[dict]:
    """
    解析 ECVA papers.php 页面。

    页面结构：
        页面使用 accordion 组件，每个年份对应一对：
            <button class="accordion">ECCV {year} Papers</button>
            <div class="accordion-content">
              <div id="content">
                <dl>
                  <dt class="ptitle"><a href="...">Paper Title</a></dt>
                  <dd>Author1, Author2, ...</dd>
                  <dd>[<a href="...pdf">pdf</a>] ...</dd>
                  ...
                </dl>
              </div>
            </div>

    本函数通过 source["year"] 找到对应年份的 accordion-content，
    再解析其中的 dt.ptitle 条目，避免混入其他年份的论文。
    """
    base_url = source["url"]
    year = source.get("year")
    soup = make_soup(html)
    papers = []

    # 找到目标年份的 accordion-content
    target_content = None

    # 遍历所有 button.accordion，找年份匹配的那个
    for btn in soup.find_all("button", class_="accordion"):
        btn_text = clean_text(btn.get_text(" "))
        # 按钮文本形如 "ECCV 2024 Papers"，检查年份是否匹配
        if year and str(year) in btn_text:
            # 紧随 button 之后的 div.accordion-content 即为该年份内容
            sibling = btn.next_sibling
            while sibling is not None:
                if hasattr(sibling, "name"):
                    if sibling.name == "div" and "accordion-content" in (sibling.get("class") or []):
                        target_content = sibling
                        break
                    elif sibling.name in ("button", "div"):
                        # 遇到其他有意义标签，停止
                        break
                sibling = sibling.next_sibling
            break

    if target_content is None:
        # 如果没有找到对应年份的 accordion（可能该年份尚未公布），返回空列表
        return []

    # 在目标年份的内容块中解析论文
    for dt in target_content.find_all("dt", class_="ptitle"):
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
