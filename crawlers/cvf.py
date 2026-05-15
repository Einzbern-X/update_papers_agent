from crawlers.base import make_soup, dedup_papers
from utils.normalize import clean_text, abs_url


def crawl_cvf(source: dict, html: str) -> list[dict]:
    url = source["url"]
    soup = make_soup(html)
    papers = []

    for dt in soup.find_all("dt", class_="ptitle"):
        a = dt.find("a")
        if not a:
            continue
        title = clean_text(a.get_text(" "))
        authors = ""
        pdf_url = ""
        cur = dt
        for _ in range(8):
            cur = cur.find_next_sibling()
            if cur is None:
                break
            text = clean_text(cur.get_text(" "))
            if cur.name == "dd" and not authors:
                low = text.lower()
                if "pdf" not in low and "abstract" not in low and "supp" not in low:
                    authors = text
            for link in cur.find_all("a"):
                label = clean_text(link.get_text(" ")).lower()
                href = link.get("href", "")
                if "pdf" in label or href.lower().endswith(".pdf"):
                    pdf_url = abs_url(url, href)
        papers.append({"title": title, "authors": authors, "pdf_url": pdf_url})
    return dedup_papers(papers)
