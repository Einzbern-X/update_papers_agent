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
