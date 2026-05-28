from crawlers.base import make_soup, dedup_papers
from utils.normalize import clean_text, abs_url


def is_ptitle(node) -> bool:
    return (
        node is not None
        and node.name == "dt"
        and "ptitle" in (node.get("class") or [])
    )


def is_main_paper_pdf(href: str, label: str) -> bool:
    """
    只判断正文 PDF，不要 supplemental。
    CVF 正文一般是：
    /content/CVPR2026/papers/..._paper.pdf

    补充材料一般是：
    /content/CVPR2026/supplemental/..._supplemental.pdf
    /content/CVPR2026/supplemental/..._supplemental.zip
    """
    if not href:
        return False

    href_low = href.lower()
    label_low = clean_text(label).lower()

    # 明确排除 supplement
    if "/supplemental/" in href_low:
        return False
    if "supp" in label_low:
        return False
    if "supplement" in label_low:
        return False

    # 最稳：CVF 正文 PDF
    if "/papers/" in href_low and href_low.endswith("_paper.pdf"):
        return True

    # 兜底：label 就叫 pdf，且链接在 /papers/ 下
    if label_low == "pdf" and "/papers/" in href_low and href_low.endswith(".pdf"):
        return True

    return False


def extract_authors_from_author_dd(dd) -> str:
    """
    CVF 作者在：
    <form class="authsearch">
      <input type="hidden" name="query_author" value="Jie Xiao">
    </form>

    用 input 的 value 最干净，不会混入 pdf/supp/bibtex。
    """
    authors = []

    for inp in dd.select('form.authsearch input[name="query_author"]'):
        name = clean_text(inp.get("value", ""))
        if name:
            authors.append(name)

    if authors:
        return ", ".join(authors)

    # 兜底：如果页面结构变了，再从 a 文本里取
    link_texts = []
    for a in dd.find_all("a"):
        text = clean_text(a.get_text(" "))
        href = a.get("href", "")
        low = text.lower()

        if low in {"pdf", "supp", "bibtex", "arxiv"}:
            continue
        if href.lower().endswith(".pdf"):
            continue

        if text:
            link_texts.append(text)

    if link_texts:
        return ", ".join(link_texts)

    text = clean_text(dd.get_text(" "))
    low = text.lower()
    if "pdf" in low or "supp" in low or "bibtex" in low or "arxiv" in low:
        return ""

    return text


def extract_pdf_from_links_dd(dd, base_url: str) -> str:
    """
    从当前论文的链接 dd 中提取正文 PDF。
    只取 [pdf]，不取 [supp]。
    """
    for a in dd.find_all("a", href=True):
        label = clean_text(a.get_text(" "))
        href = a.get("href", "")

        if is_main_paper_pdf(href, label):
            return abs_url(base_url, href)

    return ""


def crawl_cvf(source: dict, html: str) -> list[dict]:
    url = source["url"]
    soup = make_soup(html)
    papers = []

    for dt in soup.find_all("dt", class_="ptitle"):
        title_a = dt.find("a", href=True)
        if not title_a:
            continue

        title = clean_text(title_a.get_text(" "))
        detail_url = abs_url(url, title_a.get("href", ""))

        authors = ""
        pdf_url = ""

        # 关键：只扫描当前 dt.ptitle 到下一个 dt.ptitle 之间的节点
        cur = dt.find_next_sibling()

        while cur is not None and not is_ptitle(cur):
            if cur.name == "dd":
                # 作者 dd：一般是第一个 dd，里面有 form.authsearch
                if not authors and cur.select('form.authsearch input[name="query_author"]'):
                    authors = extract_authors_from_author_dd(cur)

                # 链接 dd：里面有 [pdf] [supp] [arXiv] [bibtex]
                if not pdf_url:
                    candidate_pdf = extract_pdf_from_links_dd(cur, url)
                    if candidate_pdf:
                        pdf_url = candidate_pdf

            cur = cur.find_next_sibling()

        # 没有正文 PDF 的不要保存，避免后面用空链接或 supp 链接错判
        if not pdf_url:
            continue

        papers.append({
            "title": title,
            "authors": authors,
            "pdf_url": pdf_url,
            "source_url": detail_url,
        })

    return dedup_papers(papers)