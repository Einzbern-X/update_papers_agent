from crawlers.base import fetch_html, make_soup, absolute_url, extract_doi, acm_pdf_from_doi, dedup_papers
from utils.normalize import clean_text


BAD_WORDS = {
    "home",
    "program",
    "schedule",
    "registration",
    "sponsors",
    "committee",
    "contact",
    "important dates",
    "call for papers",
    "submission",
    "venue",
}


def looks_like_title(text: str) -> bool:
    text = clean_text(text)
    lower = text.lower()

    if len(text) < 20 or len(text) > 250:
        return False

    if lower in BAD_WORDS:
        return False

    if any(lower.startswith(x) for x in ["click here", "read more", "download"]):
        return False

    return True


def crawl_generic(source: dict) -> list[dict]:
    url = source["url"]
    html = fetch_html(url)
    soup = make_soup(html)

    papers = []

    for a in soup.find_all("a"):
        title = clean_text(a.get_text(" "))
        href = a.get("href", "")

        if not looks_like_title(title):
            continue

        doi = extract_doi(href) or extract_doi(title)
        pdf_url = ""

        if href.lower().endswith(".pdf"):
            pdf_url = absolute_url(url, href)
        elif doi and "10.1145" in doi:
            pdf_url = acm_pdf_from_doi(doi)

        papers.append({
            "title": title,
            "authors": "",
            "pdf_url": pdf_url,
        })

    for block in soup.find_all(["li", "p", "tr"]):
        text = clean_text(block.get_text(" "))
        if not looks_like_title(text):
            continue

        doi = extract_doi(text)
        pdf_url = acm_pdf_from_doi(doi) if doi and "10.1145" in doi else ""

        for a in block.find_all("a"):
            label = clean_text(a.get_text(" ")).lower()
            href = a.get("href", "")

            if "pdf" in label or href.lower().endswith(".pdf"):
                pdf_url = absolute_url(url, href)

        papers.append({
            "title": text,
            "authors": "",
            "pdf_url": pdf_url,
        })

    return dedup_papers(papers)
