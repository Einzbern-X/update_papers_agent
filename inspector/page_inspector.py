from crawlers.base import make_soup
from utils.normalize import clean_text, truncate


def inspect_page(source: dict, html: str, status_code: int) -> dict:
    soup = make_soup(html)
    page_title = clean_text(soup.title.get_text(" ")) if soup.title else ""

    headings = []
    for tag in soup.find_all(["h1", "h2", "h3"])[:40]:
        t = clean_text(tag.get_text(" "))
        if t:
            headings.append(t)

    links = []
    for a in soup.find_all("a")[:100]:
        text = clean_text(a.get_text(" "))
        href = a.get("href", "")
        if text or href:
            links.append({"text": text[:180], "href": href[:260]})

    text_blocks = []
    for tag in soup.find_all(["li", "tr", "p", "div"])[:160]:
        t = clean_text(tag.get_text(" "))
        if len(t) > 20:
            text_blocks.append(truncate(t, 320))

    body_sample = truncate(clean_text(soup.get_text(" ")), 4500)

    return {
        "source_name": source.get("name", ""),
        "venue": source.get("venue", ""),
        "year": source.get("year", ""),
        "url": source.get("url", ""),
        "status_code": status_code,
        "page_title": page_title,
        "headings": headings,
        "links": links,
        "text_blocks": text_blocks[:80],
        "body_sample": body_sample,
        "html_length": len(html or ""),
    }
