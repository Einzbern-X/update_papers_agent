from crawlers.base import fetch_html, make_soup, absolute_url, extract_doi, acm_pdf_from_doi, dedup_papers
from utils.normalize import clean_text


def _split_title_authors_from_block(text: str) -> tuple[str, str]:
    text = clean_text(text)

    # 常见格式可能是：Title Authors... 或 Authors: ...
    for sep in [" Authors: ", " Author: ", "\nAuthors:"]:
        if sep in text:
            left, right = text.split(sep, 1)
            return clean_text(left), clean_text(right)

    return text, ""


def crawl_acmmm(source: dict) -> list[dict]:
    url = source["url"]
    html = fetch_html(url)
    soup = make_soup(html)

    papers = []

    # ACM MM 官网 accepted list 通常在页面正文列表/表格里。
    for tag in soup.find_all(["li", "tr", "p", "div"]):
        text = clean_text(tag.get_text(" "))
        if len(text) < 25:
            continue

        lower = text.lower()
        if any(x in lower for x in ["registration", "important dates", "call for", "committee"]):
            continue

        doi = extract_doi(text)
        pdf_url = acm_pdf_from_doi(doi) if doi else ""

        for a in tag.find_all("a"):
            label = clean_text(a.get_text(" ")).lower()
            href = a.get("href", "")

            if "pdf" in label or href.lower().endswith(".pdf"):
                pdf_url = absolute_url(url, href)

        title, authors = _split_title_authors_from_block(text)

        # 过滤太像整段说明文字的内容
        if len(title) > 350:
            continue

        papers.append({
            "title": title,
            "authors": authors,
            "pdf_url": pdf_url,
        })

    # 再从链接中找可能的论文标题
    for a in soup.find_all("a"):
        title = clean_text(a.get_text(" "))
        href = a.get("href", "")

        if len(title) < 20 or len(title) > 250:
            continue

        lower = title.lower()
        if lower in {"home", "program", "schedule", "accepted papers"}:
            continue

        doi = extract_doi(href)
        pdf_url = acm_pdf_from_doi(doi) if doi else ""

        if href.lower().endswith(".pdf"):
            pdf_url = absolute_url(url, href)

        papers.append({
            "title": title,
            "authors": "",
            "pdf_url": pdf_url,
        })

    return dedup_papers(papers)
