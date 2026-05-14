import re
from urllib.parse import urljoin


def clean_text(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def normalize_title(title) -> str:
    title = clean_text(title).lower()

    # 去掉常见标点，保留字母数字中文和空格
    title = re.sub(r"[^\w\s\u4e00-\u9fff]", "", title)
    title = re.sub(r"\s+", " ", title)

    return title.strip()


def clean_url(url) -> str:
    return clean_text(url)


def make_absolute_url(base_url: str, href: str) -> str:
    if not href:
        return ""
    return urljoin(base_url, href)
