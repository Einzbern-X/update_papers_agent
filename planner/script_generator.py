"""
script_generator.py
让大模型根据目标页面的 HTML 内容和 PageCrawlPlan，生成一段专用的 Python 爬取脚本。
生成的脚本将通过 dynamic_crawler.py 在沙箱中执行，返回论文列表。

脚本约定：
- 脚本中必须定义函数 `def extract_papers(html: str, base_url: str) -> list[dict]:`
- 返回值是 list of dict，每个 dict 至少有 "title" 键，可选 "authors"、"pdf_url"
- 脚本只能 import: re, bs4（BeautifulSoup）, urllib.parse
- 脚本不能做网络请求
"""

import json
import logging
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)

SCRIPT_SYSTEM_PROMPT = """
你是论文列表页面爬取脚本生成 Agent。

你会收到：
- 会议名称、年份、URL
- 页面结构分析报告（PageCrawlPlan）：包含列表页是否有标题/作者/PDF、是否需要子页面、HTML 结构说明
- 页面 HTML 片段

你的任务：
根据上述信息，生成一段 Python 函数代码，从列表页 HTML 中提取论文信息。

## 函数签名（必须严格遵守）

```python
def extract_papers(html: str, base_url: str) -> list[dict]:
```

返回值是 list，每个元素是 dict，包含：
- "title": str（必须，论文标题，不能为空）
- "authors": str（可选，作者列表，逗号分隔）
- "pdf_url": str（可选，PDF 链接）
- "detail_url": str（可选，论文详情页 URL，当列表页没有 PDF 时提供，用于后续抓取）

## 处理子页面的情况

如果 PageCrawlPlan 中 needs_detail_page=true，说明需要进入子页面获取 PDF：
- 在 dict 中填写 "detail_url"（论文详情页的完整 URL）
- "pdf_url" 可以留空，后续流程会访问 detail_url 获取 PDF

## 允许 import 的库
- re
- bs4（BeautifulSoup）
- urllib.parse（urljoin 等）

## 禁止
- 不能发起网络请求（requests, urllib.request 等）
- 不能读写文件
- 不能 import 其他库

## 输出格式（必须是 JSON）

{
  "generated": true,
  "script": "完整的 Python 函数代码字符串，包括 import 和函数定义",
  "confidence": 0.0到1.0,
  "reason": "简短说明脚本提取逻辑"
}

如果页面未放榜、没有论文列表、或无法可靠生成：
{
  "generated": false,
  "script": "",
  "confidence": 0.0,
  "reason": "原因"
}

## 注意
- 根据 page_structure_notes 中描述的 HTML 结构来写 selector，要精确
- 用 urllib.parse.urljoin(base_url, href) 补全相对 URL
- 过滤掉非论文内容（导航、菜单、标题过短的元素）
- 标题至少 10 个字符
- 如果列表页已经有 PDF 直链，直接提取；不需要 detail_url
"""


def generate_crawl_script(llm_client, page_info: dict, html: str,
                           max_html_chars: int = 14000,
                           crawl_plan: dict | None = None) -> dict:
    """
    让大模型根据页面 HTML 和 PageCrawlPlan 生成定制爬取脚本。

    Args:
        llm_client: LLMClient 实例（普通 JSON 模式即可）
        page_info: inspect_page 返回的页面信息
        html: 页面 HTML 原文
        max_html_chars: 发给大模型的 HTML 截断长度
        crawl_plan: 可选的 PageCrawlPlan（来自 url_searcher.analyze_page_structure）

    Returns:
        dict: {
            "generated": bool,
            "script": str,
            "confidence": float,
            "reason": str,
        }
    """
    payload = {
        "source_name": page_info.get("source_name"),
        "venue": page_info.get("venue"),
        "year": page_info.get("year"),
        "url": page_info.get("url"),
        "page_title": page_info.get("page_title"),
        "headings": page_info.get("headings", [])[:30],
        "links": page_info.get("links", [])[:60],
        "text_blocks": page_info.get("text_blocks", [])[:40],
        "body_sample": page_info.get("body_sample", ""),
        "html_sample": html[:max_html_chars],
    }

    # 如果有 PageCrawlPlan，附加进去，帮助大模型理解结构
    if crawl_plan:
        payload["page_crawl_plan"] = {
            "has_titles": crawl_plan.get("has_titles"),
            "has_authors": crawl_plan.get("has_authors"),
            "has_pdf_links": crawl_plan.get("has_pdf_links"),
            "needs_detail_page": crawl_plan.get("needs_detail_page"),
            "detail_page_pattern": crawl_plan.get("detail_page_pattern", ""),
            "detail_page_has_pdf": crawl_plan.get("detail_page_has_pdf"),
            "page_structure_notes": crawl_plan.get("page_structure_notes", ""),
        }

    result = llm_client.chat_json(SCRIPT_SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False, indent=2))

    generated = bool(result.get("generated", False))
    script = str(result.get("script", "")).strip()
    confidence = float(result.get("confidence", 0.0))
    reason = str(result.get("reason", ""))

    if generated and "def extract_papers" not in script:
        logger.warning("script_generator: missing 'extract_papers' function")
        return {
            "generated": False,
            "script": "",
            "confidence": 0.0,
            "reason": f"missing_extract_papers_function: {reason}",
        }

    return {
        "generated": generated,
        "script": script,
        "confidence": confidence,
        "reason": reason,
    }


# ──────────────────────────────────────────────
# 脚本持久化
# ──────────────────────────────────────────────

def _script_key(source: dict) -> str:
    venue = str(source.get("venue", "")).replace(" ", "_")
    year = str(source.get("year", ""))
    name = str(source.get("name", "")).replace(" ", "_").replace("/", "_")
    return f"{venue}_{year}_{name}"


def load_generated_scripts(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def get_generated_script(source: dict, path: str) -> dict | None:
    return load_generated_scripts(path).get(_script_key(source))


def save_generated_script(source: dict, script_info: dict, path: str) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = load_generated_scripts(path)
    key = _script_key(source)
    data[key] = script_info
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return key
