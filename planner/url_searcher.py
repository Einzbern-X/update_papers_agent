"""
url_searcher.py

对于 structure_type=variable 的会议来源，让大模型通过联网搜索完成以下完整分析：

Phase 1 - 搜索放榜 URL
  - 联网搜索会议的已录用论文列表页面
  - 判断是否已放榜（有可能压根还没有）

Phase 2 - 深度分析页面结构（仅在找到 URL 后执行）
  - 访问页面，分析页面 HTML 内容
  - 判断列表页本身是否包含标题、作者、PDF 链接
  - 如果需要点进子页面才能拿到 PDF，记录这个模式
  - 输出结构化的「爬取方案」

最终返回 PageCrawlPlan，包含：
  - found: bool                      是否找到放榜页面
  - url: str                         放榜页面 URL（可能和配置中不同）
  - not_released_reason: str         未放榜时的说明
  - has_titles: bool                 列表页是否有标题
  - has_authors: bool                列表页是否有作者
  - has_pdf_links: bool              列表页是否有 PDF 直链
  - needs_detail_page: bool          是否需要点进子页面才能拿到完整信息
  - detail_page_pattern: str         子页面链接的规律描述（如果需要）
  - detail_page_has_pdf: bool        子页面是否有 PDF 直链
  - page_structure_notes: str        页面结构的补充描述（给脚本生成用）
  - confidence: float
  - reason: str
"""

import json
import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Phase 1: 搜索放榜 URL
# ─────────────────────────────────────────────────────────────────────────────

_SEARCH_SYSTEM_PROMPT = """
你是一个学术会议论文放榜侦察 Agent。

你的任务是：通过联网搜索，找到指定会议「已录用论文完整列表」的官方页面 URL。

## 严格规则
- 必须使用 $web_search 工具实际搜索，不能凭记忆猜测 URL。
- 可以多次搜索直到确定。
- 优先找官方会议网站（不是 arxiv、semantic scholar、paperswithcode 等第三方）。
- 区分「Call for Papers」「Important Dates」页面和真正的「放榜页面」：
  - CFP/Important Dates = 未放榜，不算找到
  - Accepted Papers / Proceedings / Paper List = 放榜页面
- 有的会议会有多个 track，找包含所有论文或主要 track 的那个页面。

## 输出 JSON（必须严格遵守）
{
  "found": true 或 false,
  "url": "放榜页面完整 URL（未找到则为空字符串）",
  "not_released_reason": "如果未放榜，说明原因；找到则留空",
  "confidence": 0.0到1.0,
  "reason": "简短说明"
}

## 注意
- 如果搜索结果显示会议尚未公布录用名单，found=false，并在 not_released_reason 中说明。
- 如果不确定是否是完整论文列表，confidence 设为 0.4 以下。
"""


def search_release_url(llm_client_web, venue: str, year: int, search_query: str) -> dict:
    """
    Phase 1: 用大模型 web_search 工具搜索会议论文放榜页面 URL。

    Returns:
        dict: {
            "found": bool,
            "url": str,
            "not_released_reason": str,
            "confidence": float,
            "reason": str,
        }
    """
    user_msg = (
        f"请联网搜索 **{venue} {year}** 会议的「已录用论文完整列表」页面（accepted papers page）。\n\n"
        f"推荐搜索词：{search_query}\n\n"
        f"注意：\n"
        f"- 必须使用 $web_search 工具，不要凭记忆。\n"
        f"- 找到后验证这是真正的论文列表页，而不是 Call for Papers 页面。\n"
        f"- 如果还没放榜，请在 not_released_reason 中说明。\n"
        f"- 最终返回 JSON 格式结果。"
    )

    result = llm_client_web.chat_with_web_search(
        system_prompt=_SEARCH_SYSTEM_PROMPT,
        user_message=user_msg,
    )

    if isinstance(result, dict) and "found" in result:
        return result

    logger.warning("url_searcher Phase1: unexpected result: %s", str(result)[:200])
    return {
        "found": False,
        "url": "",
        "not_released_reason": "search_failed",
        "confidence": 0.0,
        "reason": f"unexpected_format: {str(result)[:200]}",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: 深度分析页面结构
# ─────────────────────────────────────────────────────────────────────────────

_ANALYZE_SYSTEM_PROMPT = """
你是一个网页结构分析 Agent，专门分析学术会议论文列表页面的结构。

你会收到一个页面的 HTML 片段。你需要仔细分析：

## 分析任务

1. **列表页直接包含哪些信息？**
   - 是否有论文标题（title）
   - 是否有作者（authors）
   - 是否有 PDF 直链（href 指向 .pdf 文件）

2. **是否需要点进子页面？**
   - 有的会议列表页只有标题，点击标题跳转到论文详情页才有作者/PDF
   - 有的列表页已经包含完整信息

3. **如果需要子页面，分析子页面模式：**
   - 子页面链接是什么格式的
   - 子页面里有没有 PDF 链接，有没有 `<meta name="citation_pdf_url">` 等

4. **页面 HTML 结构关键特征：**
   - 每篇论文用什么容器包裹（class/id）
   - 标题在哪个元素里
   - 作者在哪个元素里
   - PDF 链接在哪个元素里

## 输出 JSON（严格遵守）
{
  "has_titles": true/false,
  "has_authors": true/false,
  "has_pdf_links": true/false,
  "needs_detail_page": true/false,
  "detail_page_pattern": "如果需要子页面，描述链接的格式规律；不需要则为空字符串",
  "detail_page_has_pdf": true/false,
  "page_structure_notes": "关键的 HTML 结构说明，帮助后续生成爬取脚本。例如：每篇论文在 <div class='paper_wrapper'> 中，标题在 <div class='title'>，作者在 <div class='authors'>，PDF 在 <a href='xxx.pdf'>",
  "confidence": 0.0到1.0,
  "reason": "简短说明"
}

## 重要提示
- 只分析结构，不要编写爬取代码。
- page_structure_notes 要具体，包含 CSS class/selector 信息，供后续脚本生成使用。
- 如果页面还没有论文内容（未放榜），has_titles=false，confidence 设低。
"""


def analyze_page_structure(llm_client_web, url: str, html_sample: str, venue: str, year: int) -> dict:
    """
    Phase 2: 让大模型分析页面 HTML 结构，判断是否需要子页面，输出爬取方案。

    Args:
        llm_client_web: LLMClientWeb 实例（用联网模型，上下文更强）
        url: 页面 URL
        html_sample: 页面 HTML 前 N 个字符
        venue: 会议名
        year: 年份

    Returns:
        dict: {
            "has_titles": bool,
            "has_authors": bool,
            "has_pdf_links": bool,
            "needs_detail_page": bool,
            "detail_page_pattern": str,
            "detail_page_has_pdf": bool,
            "page_structure_notes": str,
            "confidence": float,
            "reason": str,
        }
    """
    user_msg = (
        f"请分析以下 {venue} {year} 论文列表页面的 HTML 结构。\n"
        f"页面 URL：{url}\n\n"
        f"HTML 内容（前段）：\n```html\n{html_sample}\n```\n\n"
        f"请仔细查看：\n"
        f"1. 列表页本身是否包含标题、作者、PDF 链接？\n"
        f"2. 是否需要点击论文标题跳转到子页面才能获取完整信息？\n"
        f"3. 每篇论文的 HTML 容器结构是什么？\n"
        f"输出 JSON 格式结果。"
    )

    result = llm_client_web.chat_with_web_search(
        system_prompt=_ANALYZE_SYSTEM_PROMPT,
        user_message=user_msg,
    )

    if isinstance(result, dict) and "has_titles" in result:
        return result

    logger.warning("url_searcher Phase2: unexpected result: %s", str(result)[:200])
    return {
        "has_titles": False,
        "has_authors": False,
        "has_pdf_links": False,
        "needs_detail_page": False,
        "detail_page_pattern": "",
        "detail_page_has_pdf": False,
        "page_structure_notes": "",
        "confidence": 0.0,
        "reason": f"analysis_failed: {str(result)[:200]}",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 组合结果：PageCrawlPlan
# ─────────────────────────────────────────────────────────────────────────────

def build_page_crawl_plan(search_result: dict, analysis_result: dict) -> dict:
    """
    将 Phase 1 和 Phase 2 的结果合并成完整的 PageCrawlPlan。
    """
    plan = {
        # Phase 1 信息
        "found": search_result.get("found", False),
        "url": search_result.get("url", ""),
        "not_released_reason": search_result.get("not_released_reason", ""),
        # Phase 2 信息
        "has_titles": analysis_result.get("has_titles", False),
        "has_authors": analysis_result.get("has_authors", False),
        "has_pdf_links": analysis_result.get("has_pdf_links", False),
        "needs_detail_page": analysis_result.get("needs_detail_page", False),
        "detail_page_pattern": analysis_result.get("detail_page_pattern", ""),
        "detail_page_has_pdf": analysis_result.get("detail_page_has_pdf", False),
        "page_structure_notes": analysis_result.get("page_structure_notes", ""),
        # 综合置信度取两者最低值
        "confidence": min(
            float(search_result.get("confidence", 0.0)),
            float(analysis_result.get("confidence", 1.0)),
        ),
        "reason": f"search: {search_result.get('reason','')} | analysis: {analysis_result.get('reason','')}",
    }
    return plan
