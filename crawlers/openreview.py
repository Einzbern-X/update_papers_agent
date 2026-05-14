from utils.normalize import clean_text


def _content_value(content: dict, key: str):
    value = content.get(key, "")

    # OpenReview API v2 常见格式：{"value": "..."}
    if isinstance(value, dict) and "value" in value:
        return value["value"]

    return value


def _normalize_authors(authors) -> str:
    if isinstance(authors, list):
        return "; ".join(clean_text(x) for x in authors)
    return clean_text(authors)


def _normalize_pdf_url(pdf) -> str:
    if not isinstance(pdf, str) or not pdf:
        return ""

    if pdf.startswith("/"):
        return "https://openreview.net" + pdf

    return pdf


def crawl_openreview(source: dict) -> list[dict]:
    import openreview

    invitation = source.get("openreview_invitation")
    if not invitation:
        raise ValueError("openreview parser requires 'openreview_invitation' in config.yaml")

    # OpenReview 官方 Python client 支持 get_all_notes(invitation=...)。
    # API v2 优先，失败时再尝试 legacy API。
    try:
        client = openreview.api.OpenReviewClient(baseurl="https://api2.openreview.net")
        notes = client.get_all_notes(invitation=invitation)
    except Exception:
        legacy_client = openreview.Client(baseurl="https://api.openreview.net")
        notes = legacy_client.get_all_notes(invitation=invitation)

    papers = []

    for note in notes:
        content = getattr(note, "content", {}) or {}

        title = clean_text(_content_value(content, "title"))
        authors = _normalize_authors(_content_value(content, "authors"))
        pdf_url = _normalize_pdf_url(_content_value(content, "pdf"))

        if not title:
            continue

        papers.append({
            "title": title,
            "authors": authors,
            "pdf_url": pdf_url,
        })

    return papers
