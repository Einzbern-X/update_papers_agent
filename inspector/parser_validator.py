from utils.normalize import clean_text

BAD_TITLE_EXACT = {
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
    "accepted papers",
    "papers",
}

BAD_TITLE_PREFIXES = (
    "click here",
    "read more",
    "download",
    "back to",
    "view all",
)


def validate_papers(papers: list[dict], min_count: int = 5, min_title_ratio: float = 0.9) -> tuple[bool, str]:
    if not papers:
        return False, "no_papers"
    if len(papers) < min_count:
        return False, f"too_few_papers:{len(papers)}"
    title_count = sum(1 for p in papers if clean_text(p.get("title", "")))
    title_ratio = title_count / max(len(papers), 1)
    if title_ratio < min_title_ratio:
        return False, f"low_title_ratio:{title_ratio:.2f}"
    too_long = sum(1 for p in papers if len(clean_text(p.get("title", ""))) > 320)
    if too_long / max(len(papers), 1) > 0.25:
        return False, "too_many_long_titles"
    url_in_title = sum(1 for p in papers if "http://" in clean_text(p.get("title", "")).lower()
                       or "https://" in clean_text(p.get("title", "")).lower()
                       or "doi.org" in clean_text(p.get("title", "")).lower())
    if url_in_title / max(len(papers), 1) > 0.1:
        return False, "too_many_urls_in_titles"
    bad_navigation_titles = 0
    normalized_titles = []
    for p in papers:
        title = clean_text(p.get("title", ""))
        low = title.lower()
        normalized_titles.append(low)
        if low in BAD_TITLE_EXACT or low.startswith(BAD_TITLE_PREFIXES):
            bad_navigation_titles += 1
    if bad_navigation_titles / max(len(papers), 1) > 0.1:
        return False, "too_many_navigation_titles"
    unique_title_ratio = len(set(normalized_titles)) / max(len(normalized_titles), 1)
    if unique_title_ratio < 0.75:
        return False, f"too_many_duplicate_titles:{unique_title_ratio:.2f}"
    return True, "ok"
