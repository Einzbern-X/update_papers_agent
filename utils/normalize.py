import re
from urllib.parse import urljoin


def clean_text(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def normalize_title(title) -> str:
    title = clean_text(title).lower()
    title = re.sub(r"[^\w\s\u4e00-\u9fff]", "", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()


def abs_url(base_url: str, href: str) -> str:
    if not href:
        return ""
    return urljoin(base_url, href)


def truncate(text: str, max_chars: int) -> str:
    text = str(text or "")
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def normalize_pdf_url(url: str) -> str:
    """
    规范化 pdf_url：
    - https://doi.org/<suffix>            → https://dl.acm.org/doi/epdf/<suffix>
    - https://dl.acm.org/doi/pdf/<suffix> → https://dl.acm.org/doi/epdf/<suffix>
    - 其他 URL 原样返回
    """
    url = clean_text(url)
    if not url:
        return ""
    # doi.org 直链 → epdf
    m = re.match(r"https://doi\.org/(.+)", url)
    if m:
        return f"https://dl.acm.org/doi/epdf/{m.group(1)}"
    # dl.acm.org/doi/pdf/ → epdf
    m = re.match(r"https://dl\.acm\.org/doi/pdf/(.+)", url)
    if m:
        return f"https://dl.acm.org/doi/epdf/{m.group(1)}"
    return url
