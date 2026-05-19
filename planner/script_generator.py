"""
script_generator.py
让大模型根据目标页面的 HTML 内容和 PageCrawlPlan，生成一段专用的 Python 爬取脚本。
生成的脚本将通过 dynamic_crawler.py 在沙箱中执行，返回论文列表。

脚本约定：
- 脚本中必须定义函数 `def extract_papers(html: str, base_url: str) -> list[dict]:`
- 返回值是 list of dict，每个 dict 至少有 "title" 键，可选 "authors"、"pdf_url"
- 最终保存和导出的公开字段固定只有 venue/year/title/authors/pdf_url/source_url
- 脚本只能 import: re, bs4（BeautifulSoup）, urllib.parse
- 脚本不能做网络请求
"""

import json
import logging
import yaml
from pathlib import Path
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def extract_html_structure_sample(html: str, max_chars: int = 14000) -> str:
    """
    从原始 HTML 中提炼结构化摘要，供大模型分析使用：
    1. 去掉 <script>/<style>/<nav>/<footer>/<head> 等噪音标签
    2. 提取 <body> 的核心内容，保留 prettify 后的格式
    3. 控制总长度在 max_chars 以内

    这样大模型看到的是干净的内容 HTML，而不是被 JS/CSS 淹没的原始源码。
    """
    try:
        soup = BeautifulSoup(html, "lxml")
        # 去除噪音标签
        for tag in soup(["script", "style", "nav", "footer", "header",
                         "noscript", "iframe", "svg", "meta", "link"]):
            tag.decompose()

        body = soup.find("body") or soup
        cleaned = body.prettify()
        return cleaned[:max_chars]
    except Exception:
        # 降级：直接截断原始 HTML
        return html[:max_chars]


def pre_analyze_html(html: str) -> dict:
    """
    用程序主动探索 HTML 结构，生成一份结构分析报告。
    这模拟了人类工程师 "先跑代码看结构" 的思维过程。

    返回的报告会附在 prompt 里，让大模型不需要自己猜结构，
    而是直接基于已经探索好的结论来写脚本。
    """
    try:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript", "iframe"]):
            tag.decompose()

        report = {}

        # 1. 统计各容器类型数量
        tag_counts = {}
        for tag in ["table", "ul", "ol", "dl", "div", "section", "article"]:
            count = len(soup.find_all(tag))
            if count > 0:
                tag_counts[tag] = count
        report["container_counts"] = tag_counts

        # 2. 分析最可能的论文容器（取数量最多的几种）
        # 对 table 做深入分析
        tables = soup.find_all("table")
        if tables:
            table_analysis = []
            for i, t in enumerate(tables[:3]):
                rows = t.find_all("tr")
                # 取前2行展示结构
                row_samples = []
                for row in rows[:4]:
                    tds = row.find_all("td")
                    td_info = []
                    for td in tds:
                        children_tags = [c.name for c in td.children if hasattr(c, "name") and c.name]
                        text_preview = " ".join(td.get_text(" ").split())[:120]
                        td_info.append({
                            "children_tags": children_tags,
                            "text_preview": text_preview,
                        })
                    row_samples.append(td_info)
                table_analysis.append({
                    "table_index": i,
                    "total_rows": len(rows),
                    "row_samples": row_samples,
                })
            report["table_analysis"] = table_analysis

        # 3. 检查是否有 <strong>/<h2>/<h3> 包含论文标题的迹象
        strong_tags = soup.find_all("strong")
        report["strong_count"] = len(strong_tags)
        report["strong_samples"] = [
            " ".join(s.get_text(" ").split())[:100]
            for s in strong_tags[:5]
        ]

        # 4. 检查 DOI / PDF 链接
        doi_links = [a["href"] for a in soup.find_all("a", href=True)
                     if "doi.org" in a.get("href", "")]
        pdf_links = [a["href"] for a in soup.find_all("a", href=True)
                     if a.get("href", "").lower().endswith(".pdf")]
        report["doi_link_count"] = len(doi_links)
        report["doi_link_samples"] = doi_links[:3]
        report["pdf_link_count"] = len(pdf_links)
        report["pdf_link_samples"] = pdf_links[:3]

        # 5. 检查 DOI 文本（有时 DOI 不是 <a> 而是纯文本）
        import re
        doi_texts = re.findall(r"https://doi\.org/\S+", soup.get_text())
        report["doi_text_count"] = len(doi_texts)
        report["doi_text_samples"] = doi_texts[:3]

        return report

    except Exception as e:
        return {"error": str(e)}

SCRIPT_SYSTEM_PROMPT = """
你是论文列表页面爬取脚本生成 Agent。

你会收到：
- 会议名称、年份、URL
- 页面结构分析报告（PageCrawlPlan）：包含列表页是否有标题/作者/PDF、是否需要子页面、HTML 结构说明
- 页面 HTML 内容（已去除 script/style/nav 等噪音）

你的任务：
**先仔细阅读 HTML，识别每篇论文的完整容器结构，再生成 Python 爬取函数。**

## 分析步骤（必须执行）

**第一步：先阅读 `pre_analysis_report` 字段**（这是程序自动运行结构探索代码得出的报告）
- `table_analysis`：每个 table 的行数和前几行的内容预览，直接告诉你论文在哪里
- `strong_samples`：`<strong>` 标签内容，通常就是论文标题
- `doi_text_count` / `doi_text_samples`：DOI 出现在纯文本里（不是链接），要用正则提取
- `pdf_link_count`：PDF 直链数量

**第二步：基于报告结论，对照 html_sample 验证**，确认 selector 路径

## 函数签名（必须严格遵守）

```python
def extract_papers(html: str, base_url: str) -> list[dict]:
```

返回值是 list，每个元素是 dict，包含：
- "title": str（必须，论文标题，**只含标题文本，不含 DOI 或其他信息**）
- "authors": str（可选，作者列表）
- "pdf_url": str（可选，PDF 链接或 DOI URL）
- "detail_url": str（可选，论文详情页 URL，当列表页没有 PDF 时提供；这是内部临时字段，只用于补全 pdf_url，不会保存或导出）

最终保存/导出的公开字段固定只有：
venue, year, title, authors, pdf_url, source_url

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
  "reason": "简短说明脚本提取逻辑（包括你识别到的 HTML 结构）"
}

如果页面未放榜、没有论文列表、或无法可靠生成：
{
  "generated": false,
  "script": "",
  "confidence": 0.0,
  "reason": "原因"
}

## 关键注意事项
- 若标题在 `<strong>` 等子标签里，**只取该子标签的文本**，不取父元素 get_text()
- 若 DOI/PDF URL 和标题在同一个容器里，用正则 `re.search(r'https?://\\S+', text)` 单独提取 URL
- 不要用标题长度判断是否是论文，依赖 selector 的精确度
- 用 urllib.parse.urljoin(base_url, href) 补全相对 URL
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
        # 程序自动探索的结构报告（相当于工程师先跑代码看结构的结论）
        "pre_analysis_report": pre_analyze_html(html),
        # 去噪后的结构化 HTML，大模型能看到清晰的论文容器结构
        "html_sample": extract_html_structure_sample(html, max_chars=max_html_chars),
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


# ──────────────────────────────────────────────
# Reflection：基于执行错误修复脚本
# ──────────────────────────────────────────────

_FIX_SYSTEM_PROMPT = """
你是论文爬取脚本的自动修复 Agent。

上一版脚本执行后出现了问题，你需要分析错误并输出修复后的完整脚本。

你会收到：
- 原始脚本代码
- 执行后提取到的样本论文（前5条）
- 发现的具体问题列表
- 页面 HTML 片段（去噪后）

## 常见问题及修复策略

1. **标题混入了 DOI/URL 文本**
   - 原因：用了父元素 get_text()，把标题和 DOI 一起抓了
   - 修复：只取 `<strong>` 或标题专属子标签的文本；DOI 用正则单独提取

2. **作者字段为空**
   - 原因：作者在相邻 <tr>/<dd> 里，selector 没找到
   - 修复：检查 HTML 中作者所在的相对位置，用 next_sibling 或 find_next 定位

3. **提取数量为 0 或极少**
   - 原因：selector 写错，或页面结构与假设不符
   - 修复：重新分析 HTML，找到真正重复的论文容器

4. **标题包含多余空白或换行**
   - 修复：对 title 做 `' '.join(title.split())`

## 输出格式（必须是 JSON）

{
  "generated": true,
  "script": "修复后的完整 Python 函数代码",
  "confidence": 0.0到1.0,
  "reason": "说明修复了什么问题，使用了什么新策略"
}

## 约束（同生成时）
- 只能 import: re, bs4（BeautifulSoup）, urllib.parse
- 不能做网络请求
- 必须定义 `def extract_papers(html: str, base_url: str) -> list[dict]:`
"""


def _diagnose_papers(papers: list[dict]) -> list[str]:
    """
    检查提取结果，返回发现的问题列表。
    问题描述会作为 Reflection 的输入反馈给大模型。
    """
    issues = []
    if not papers:
        issues.append("提取结果为空，完全没有论文")
        return issues

    # 检查标题混入 URL
    doi_in_title = sum(1 for p in papers if "doi.org" in p.get("title", "").lower()
                       or "http" in p.get("title", "").lower())
    if doi_in_title > 0:
        issues.append(
            f"{doi_in_title}/{len(papers)} 篇论文的 title 字段混入了 DOI URL 或 http 链接，"
            "应只取标题文本，DOI 放入 pdf_url 字段"
        )

    # 检查作者为空
    empty_authors = sum(1 for p in papers if not p.get("authors", "").strip())
    if empty_authors > len(papers) * 0.5:
        issues.append(
            f"{empty_authors}/{len(papers)} 篇论文的 authors 字段为空，"
            "请检查作者在 HTML 中的位置并重新提取"
        )

    # 检查标题过短或明显不是论文标题
    bad_titles = [p["title"] for p in papers
                  if len(p.get("title", "")) < 5 or p.get("title", "").startswith("http")]
    if bad_titles:
        issues.append(f"发现 {len(bad_titles)} 个可疑标题（过短或以http开头）：{bad_titles[:3]}")

    return issues


def fix_crawl_script(llm_client, original_script: str, papers: list[dict],
                     html: str, max_html_chars: int = 14000) -> dict:
    """
    Reflection：把执行结果的问题反馈给大模型，让它修复脚本。

    Args:
        llm_client: LLMClient 实例
        original_script: 上一轮生成的脚本代码
        papers: 上一轮执行得到的论文列表（用于诊断问题）
        html: 页面原始 HTML
        max_html_chars: HTML 截断长度

    Returns:
        dict: 同 generate_crawl_script 的返回格式
    """
    issues = _diagnose_papers(papers)
    if not issues:
        # 没有发现问题，不需要修复
        return {"generated": False, "script": "", "confidence": 0.0, "reason": "no_issues_found"}

    sample_papers = papers[:5]

    payload = {
        "original_script": original_script,
        "issues_found": issues,
        "sample_papers_extracted": sample_papers,
        "html_sample": extract_html_structure_sample(html, max_chars=max_html_chars),
    }

    logger.info("Reflection: found %d issues, asking LLM to fix script", len(issues))
    for issue in issues:
        logger.info("  - %s", issue)

    result = llm_client.chat_json(
        _FIX_SYSTEM_PROMPT,
        json.dumps(payload, ensure_ascii=False, indent=2)
    )

    generated = bool(result.get("generated", False))
    script = str(result.get("script", "")).strip()
    confidence = float(result.get("confidence", 0.0))
    reason = str(result.get("reason", ""))

    if generated and "def extract_papers" not in script:
        return {
            "generated": False,
            "script": "",
            "confidence": 0.0,
            "reason": f"fix_missing_extract_papers: {reason}",
        }

    return {
        "generated": generated,
        "script": script,
        "confidence": confidence,
        "reason": f"[reflection_fix] {reason}",
    }
