import json

SYSTEM_PROMPT = """
你是论文会议放榜状态判断 Agent。
你会看到一个会议网页的标题、URL、heading、链接文本、正文片段和部分 HTML。
你只输出 JSON，不要输出解释。

你需要判断页面状态：
- not_released: 还未公布论文列表，只是 CFP / Important Dates / Submission / Coming Soon 等。
- id_only: 只有 paper id / submission id / conditionally accepted id，没有论文标题和作者。
- released_with_papers: 已经有论文标题列表，可能有作者/PDF/DOI。
- released_without_pdf: 有论文标题和作者，但没有 PDF 链接。
- unknown: 无法可靠判断。

输出格式：
{
  "status": "not_released | id_only | released_with_papers | released_without_pdf | unknown",
  "has_titles": true/false,
  "has_authors": true/false,
  "has_pdf_links": true/false,
  "has_doi": true/false,
  "confidence": 0.0到1.0,
  "reason": "简短原因"
}

注意：
如果只是 Call for Papers、Submission Guidelines、Important Dates，必须判为 not_released。
如果只有 paper ID，没有标题和作者，判为 id_only。
如果页面列出大量论文标题，即使没有 PDF，也应判为 released_without_pdf 或 released_with_papers。
"""


def judge_release_status(llm_client, page_info: dict, html: str, max_html_chars: int = 12000) -> dict:
    payload = {
        "source_name": page_info.get("source_name"),
        "venue": page_info.get("venue"),
        "year": page_info.get("year"),
        "url": page_info.get("url"),
        "status_code": page_info.get("status_code"),
        "page_title": page_info.get("page_title"),
        "headings": page_info.get("headings", [])[:40],
        "links": page_info.get("links", [])[:100],
        "text_blocks": page_info.get("text_blocks", [])[:80],
        "body_sample": page_info.get("body_sample", ""),
        "html_sample": html[:max_html_chars],
    }
    result = llm_client.chat_json(SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False, indent=2))
    status = result.get("status", "unknown")
    if status not in {"not_released", "id_only", "released_with_papers", "released_without_pdf", "unknown"}:
        result["status"] = "unknown"
    return result
