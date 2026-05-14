from crawlers.base import fetch_html, make_soup, absolute_url, extract_doi, acm_pdf_from_doi, dedup_papers
from utils.normalize import clean_text


def _looks_like_paper_title(text: str) -> bool:
    text = clean_text(text)
    lower = text.lower()

    if len(text) < 15 or len(text) > 250:
        return False

    bad = [
        "siggraph", "table of contents", "papers on the web",
        "back to", "copyright", "home", "author index"
    ]

    if any(lower == x for x in bad):
        return False

    return True


def crawl_siggraph(source: dict) -> list[dict]:
    url = source["url"]
    html = fetch_html(url)
    soup = make_soup(html)

    papers = []

    # Ke-Sen 页面通常按标题链接/文本 + 作者/机构 + DOI/PDF 链接排列。
    # 这个 parser 保守抽取标题和 PDF，不强行推断机构。
    for block in soup.find_all(["p", "li", "tr", "div"]):
        text = clean_text(block.get_text(" "))
        if len(text) < 20:
            continue

        doi = extract_doi(text)
        pdf_url = acm_pdf_from_doi(doi) if doi else ""

        for a in block.find_all("a"):
            label = clean_text(a.get_text(" ")).lower()
            href = a.get("href", "")

            if (
                "pdf" in label
                or "paper" in label
                or href.lower().endswith(".pdf")
                or "arxiv.org/pdf" in href.lower()
            ):
                pdf_url = absolute_url(url, href)

            if not doi:
                doi = extract_doi(href)
                if doi and not pdf_url:
                    pdf_url = acm_pdf_from_doi(doi)

        # 标题优先取块中的第一个较长链接文本
        title = ""
        for a in block.find_all("a"):
            candidate = clean_text(a.get_text(" "))
            if _looks_like_paper_title(candidate):
                title = candidate
                break

        if not title:
            # 退而求其次，用块首句作为标题
            title = text.split(". ")[0]
            title = clean_text(title)

        if not _looks_like_paper_title(title):
            continue

        papers.append({
            "title": title,
            "authors": "",
            "pdf_url": pdf_url,
        })

    return dedup_papers(papers)
