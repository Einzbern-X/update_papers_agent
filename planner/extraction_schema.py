CSS_FIELDS = {"released", "page_type", "rule_type", "paper_container", "title_selector", "authors_selector", "pdf_selector", "pdf_attr", "confidence", "reason"}
REGEX_FIELDS = {"released", "page_type", "rule_type", "container_selector", "block_regex", "confidence", "reason"}


def sanitize_rule(rule: dict) -> dict:
    rt = rule.get("rule_type", "")
    if rt == "css_selector":
        out = {k: v for k, v in rule.items() if k in CSS_FIELDS}
        out.setdefault("pdf_attr", "href")
        return out
    if rt in {"regex", "block_regex"}:
        return {k: v for k, v in rule.items() if k in REGEX_FIELDS}
    return {"released": False, "rule_type": "", "confidence": 0.0, "reason": "invalid rule_type"}
