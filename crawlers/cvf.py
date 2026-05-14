from crawlers.base import fetch_html, make_soup, absolute_url, extract_doi, dedup_papers
from utils.normalize import clean_text


def crawl_cvf(source: dict) -> list[dict]:
    url = source["url"]
    html = fetch_html(url)
    soup = make_soup(html)

    papers = []

    for dt in soup.find_all("dt", class_="ptitle"):
        title_tag = dt.find("a")
        if not title_tag:
            continue

        title = clean_text(title_tag.get_text(" "))
        authors = ""
        pdf_url = ""

        siblings = []
        cur = dt

        # CVF 通常结构：dt.ptitle + 若干 dd
        for _ in range(8):
            cur = cur.find_next_sibling()
            if cur is None:
                break
            siblings.append(cur)

        for sib in siblings:
            text = clean_text(sib.get_text(" "))

            if sib.name == "dd" and not authors:
                lower = text.lower()
                if "pdf" not in lower and "abstract" not in lower and "supp" not in lower:
                    authors = text

            for a in sib.find_all("a"):
                label = clean_text(a.get_text(" ")).lower()
                href = a.get("href", "")

                if "pdf" in label or href.lower().endswith(".pdf"):
                    pdf_url = absolute_url(url, href)

        papers.append({
            "title": title,
            "authors": authors,
            "pdf_url": pdf_url,
        })

    return dedup_papers(papers)
