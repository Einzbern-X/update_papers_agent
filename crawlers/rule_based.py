import re
from crawlers.base import make_soup, dedup_papers
from utils.normalize import clean_text, abs_url


def _text(container, selector):
    if not selector:
        return ""
    node = container.select_one(selector)
    return clean_text(node.get_text(" ")) if node else ""


def _attr(container, selector, attr, base_url):
    if not selector:
        return ""
    node = container.select_one(selector)
    if not node:
        return ""
    val = node.get(attr, "")
    return abs_url(base_url, val) if attr in {"href", "src"} else clean_text(val)


def _css_rule(soup, base_url, rule):
    papers = []
    for c in soup.select(rule.get("paper_container", "")):
        title = _text(c, rule.get("title_selector", ""))
        authors = _text(c, rule.get("authors_selector", ""))
        pdf_url = _attr(c, rule.get("pdf_selector", ""), rule.get("pdf_attr", "href"), base_url)
        if title:
            papers.append({"title": title, "authors": authors, "pdf_url": pdf_url})
    return papers


def _regex_rule(soup, base_url, rule):
    container_selector = rule.get("container_selector", "body")
    pattern = rule.get("block_regex", "")
    if not pattern:
        return []
    text = "\n".join(clean_text(n.get_text("\n")) for n in soup.select(container_selector))
    papers = []
    for m in re.compile(pattern, re.S | re.I).finditer(text):
        gd = m.groupdict()
        title = clean_text(gd.get("title", ""))
        authors = clean_text(gd.get("authors", ""))
        pdf_url = clean_text(gd.get("pdf_url", ""))
        if title:
            papers.append({"title": title, "authors": authors, "pdf_url": abs_url(base_url, pdf_url) if pdf_url else ""})
    return papers


def crawl_by_rule(source: dict, html: str, rule: dict) -> list[dict]:
    soup = make_soup(html)
    base_url = source.get("url", "")
    if rule.get("rule_type") == "css_selector":
        papers = _css_rule(soup, base_url, rule)
    elif rule.get("rule_type") in {"regex", "block_regex"}:
        papers = _regex_rule(soup, base_url, rule)
    else:
        papers = []
    return dedup_papers(papers)
