from crawlers.base import make_soup, dedup_papers
from utils.normalize import clean_text, abs_url


_BASE = "https://papers.nips.cc"


def _abstract_href_to_pdf(href: str) -> str:
    """
    将列表页的 abstract 链接转成 PDF 直链。

    列表页 href 示例：
        /paper_files/paper/2025/hash/0010031a1b4910aa67edbda26a705518-Abstract-Conference.html
        /paper_files/paper/2025/hash/xxx-Abstract-Datasets_and_Benchmarks_Track.html
        /paper_files/paper/2025/hash/xxx-Abstract-Position_Paper_Track.html

    目标 PDF 链接（详情页 Paper 按钮）：
        https://proceedings.neurips.cc/paper_files/paper/2025/file/0010031a1b4910aa67edbda26a705518-Paper-Conference.pdf
        https://proceedings.neurips.cc/paper_files/paper/2025/file/xxx-Paper-Datasets_and_Benchmarks_Track.pdf
        https://proceedings.neurips.cc/paper_files/paper/2025/file/xxx-Paper-Position_Paper_Track.pdf

    转换规则：
      1. hash/ -> file/
      2. -Abstract- -> -Paper-
      3. .html -> .pdf
      4. 域名改为 proceedings.neurips.cc
    """
    if not href:
        return ""
    path = href
    # 换 hash -> file
    path = path.replace("/hash/", "/file/")
    # 换 -Abstract- -> -Paper-
    path = path.replace("-Abstract-", "-Paper-")
    # 换后缀
    if path.endswith(".html"):
        path = path[:-5] + ".pdf"
    return f"https://proceedings.neurips.cc{path}"


def crawl_neurips(source: dict, html: str) -> list[dict]:
    """
    解析 papers.nips.cc 列表页。

    页面结构（每篇论文）：
        <li class="conference" data-track="conference">
            <div class="paper-content">
                <a title="paper title" href="/paper_files/paper/2025/hash/xxx-Abstract-Conference.html">
                    Paper Title
                </a>
                <span class="paper-authors">Author1, Author2, ...</span>
            </div>
            <span class="paper-track-badge">Main Conference Track</span>
        </li>
    """
    soup = make_soup(html)
    papers = []

    paper_list = soup.find("ul", class_="paper-list")
    if paper_list is None:
        # 兼容：没有 paper-list 时退化到全部 li
        items = soup.find_all("li")
    else:
        items = paper_list.find_all("li")

    for li in items:
        content_div = li.find("div", class_="paper-content")
        if content_div:
            a_tag = content_div.find("a", title="paper title") or content_div.find("a")
            authors_span = content_div.find("span", class_="paper-authors")
        else:
            a_tag = li.find("a")
            authors_span = None

        if not a_tag:
            continue

        title = clean_text(a_tag.get_text(" "))
        if len(title) < 10:
            continue

        authors = clean_text(authors_span.get_text(" ")) if authors_span else ""

        href = a_tag.get("href", "")
        pdf_url = _abstract_href_to_pdf(href)

        papers.append({"title": title, "authors": authors, "pdf_url": pdf_url})

    return dedup_papers(papers)
