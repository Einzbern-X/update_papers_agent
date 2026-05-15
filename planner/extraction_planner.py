import json
import yaml
from pathlib import Path
from planner.extraction_schema import sanitize_rule

SYSTEM_PROMPT = """
你是论文列表页面解析规划 Agent。
你不能写 Python 代码，只能输出 JSON 解析规则。
程序会根据 JSON 规则执行抓取。

支持 css_selector：
{
  "released": true,
  "page_type": "accepted_papers",
  "rule_type": "css_selector",
  "paper_container": "每篇论文容器 selector",
  "title_selector": "容器内标题 selector",
  "authors_selector": "容器内作者 selector，可为空",
  "pdf_selector": "容器内 PDF 链接 selector，可为空",
  "pdf_attr": "href",
  "confidence": 0.0到1.0,
  "reason": "简短原因"
}

支持 block_regex：
{
  "released": true,
  "page_type": "accepted_papers",
  "rule_type": "block_regex",
  "container_selector": "body",
  "block_regex": "带命名组的正则，至少 (?P<title>...)，可选 (?P<authors>...) (?P<pdf_url>...)",
  "confidence": 0.0到1.0,
  "reason": "简短原因"
}

如果页面未放榜、只有 paper id、或你无法可靠生成规则，返回：
{
  "released": false,
  "page_type": "not_released_or_unknown",
  "rule_type": "",
  "confidence": 0.0,
  "reason": "原因"
}
"""


def source_rule_key(source: dict) -> str:
    venue = str(source.get("venue", "")).replace(" ", "_")
    year = str(source.get("year", ""))
    name = str(source.get("name", "")).replace(" ", "_").replace("/", "_")
    return f"{venue}_{year}_{name}"


def generate_extraction_rule(llm_client, page_info: dict, html: str, max_html_chars: int = 14000) -> dict:
    payload = {
        "source_name": page_info.get("source_name"),
        "venue": page_info.get("venue"),
        "year": page_info.get("year"),
        "url": page_info.get("url"),
        "page_title": page_info.get("page_title"),
        "headings": page_info.get("headings", [])[:40],
        "links": page_info.get("links", [])[:100],
        "text_blocks": page_info.get("text_blocks", [])[:80],
        "body_sample": page_info.get("body_sample", ""),
        "html_sample": html[:max_html_chars],
    }
    rule = llm_client.chat_json(SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False, indent=2))
    return sanitize_rule(rule)


def load_generated_rules(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def get_generated_rule(source: dict, path: str) -> dict | None:
    return load_generated_rules(path).get(source_rule_key(source))


def save_generated_rule(source: dict, rule: dict, path: str) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = load_generated_rules(path)
    key = source_rule_key(source)
    data[key] = rule
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return key
