from crawlers.base import fetch_html, make_soup, absolute_url, extract_doi, acm_pdf_from_doi, dedup_papers
from utils.normalize import clean_text


def _extract_authors_from_text(text: str) -> str:
    text = clean_text(text)

    markers = ["Authors:", "Author:", "Presented by:"]
    for marker in markers:
        if marker in text:
            return clean_text(text.split(marker, 1)[-1])

    return ""


def crawl_kdd(source: dict) -> list[dict]:
    url = source["url"]
    html = fetch_html(url)
    soup = make_soup(html)

    papers = []

    # KDD 官网页面通常包含标题、作者、机构、DOI，可能在卡片或表格里。
    for block in soup.find_all(["article", "li", "tr", "div", "p"]):
        text = clean_text(block.get_text(" "))

        if len(text) < 25:
            continue

        lower = text.lower()
        if any(x in lower for x in [
            "registration", "committee", "sponsor", "keynote",
            "call for", "important dates", "venue information"
        ]):
            continue

        doi = extract_doi(text)
        pdf_url = acm_pdf_from_doi(doi) if doi else ""

        for a in block.find_all("a"):
            label = clean_text(a.get_text(" ")).lower()
            href = a.get("href", "")

            if "pdf" in label or href.lower().endswith(".pdf"):
                pdf_url = absolute_url(url, href)

            if not doi:
                doi = extract_doi(href)
                if doi and not pdf_url:
                    pdf_url = acm_pdf_from_doi(doi)

        authors = _extract_authors_from_text(text)

        # 尝试把 DOI 后面的内容去掉，避免标题带 DOI 一起入库
        title = text
        if doi:
            title = clean_text(text.split(doi, 1)[0])

        # 避免把很大的页面容器作为标题
        if len(title) > 350:
            continue

        papers.append({
            "title": title,
            "authors": authors,
            "pdf_url": pdf_url,
        })

    return dedup_papers(papers)
