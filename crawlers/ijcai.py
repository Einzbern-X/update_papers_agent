from crawlers.base import make_soup, dedup_papers
from utils.normalize import clean_text, abs_url


def crawl_ijcai(source: dict, html: str) -> list[dict]:
    """
    解析 IJCAI proceedings 页面。

    页面结构（每篇论文）：
        <div id="paperN" class="paper_wrapper">
            <div class="title">Paper Title</div>
            <div class="authors">Author1, Author2, ...</div>
            <div class="details">
                (<a href="0001.pdf">PDF</a> | <a href="/proceedings/2025/1">Details</a>)
            </div>
        </div>
    """
    base_url = source["url"]
    soup = make_soup(html)
    papers = []

    for wrapper in soup.find_all("div", class_="paper_wrapper"):
        # 标题
        title_tag = wrapper.find("div", class_="title")
        if not title_tag:
            continue
        title = clean_text(title_tag.get_text(" "))
        if len(title) < 10:
            continue

        # 作者
        authors_tag = wrapper.find("div", class_="authors")
        authors = clean_text(authors_tag.get_text(" ")) if authors_tag else ""

        # PDF 链接
        pdf_url = ""
        details_tag = wrapper.find("div", class_="details")
        if details_tag:
            for a in details_tag.find_all("a"):
                label = clean_text(a.get_text(" ")).lower()
                href = a.get("href", "")
                if label == "pdf" or href.lower().endswith(".pdf"):
                    pdf_url = abs_url(base_url, href)
                    break

        papers.append({"title": title, "authors": authors, "pdf_url": pdf_url})

    return dedup_papers(papers)
