from utils.normalize import clean_text


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
    return True, "ok"
