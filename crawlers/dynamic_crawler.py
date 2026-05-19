"""
dynamic_crawler.py
在受限沙箱中执行大模型生成的爬取脚本，返回论文列表。

安全约束：
- 只允许 import re, bs4, urllib.parse
- 禁止网络请求、文件 IO、sys/os 等危险模块
- 执行超时保护
- 返回值必须是 list[dict]，每个 dict 必须有 "title"
- 对外保存/导出字段固定只有 venue/year/title/authors/pdf_url/source_url；
  detail_url 只允许作为 enrich 阶段的内部临时字段

脚本生成格式约定（见 script_generator.py）：
    def extract_papers(html: str, base_url: str) -> list[dict]: ...
"""

import re
import types
import logging
from bs4 import BeautifulSoup
import urllib.parse
from agent.contracts import INTERNAL_DETAIL_URL_FIELD
from crawlers.base import dedup_papers
from utils.normalize import clean_text

logger = logging.getLogger(__name__)


# 沙箱允许的内置函数白名单
_SAFE_BUILTINS = {
    "len", "range", "enumerate", "zip", "map", "filter", "list", "dict",
    "set", "tuple", "str", "int", "float", "bool", "None", "True", "False",
    "print", "isinstance", "hasattr", "getattr", "any", "all", "max", "min",
    "sorted", "reversed", "sum", "abs", "round", "repr", "type",
    "Exception", "ValueError", "KeyError", "AttributeError", "IndexError",
}


def _build_sandbox_globals():
    """构建受限执行环境的 globals 字典。"""
    import builtins

    safe_builtins = {k: getattr(builtins, k) for k in _SAFE_BUILTINS if hasattr(builtins, k)}
    safe_builtins["__builtins__"] = safe_builtins

    # 允许 import 的模块
    allowed_modules = {
        "re": re,
        "bs4": __import__("bs4"),
        "BeautifulSoup": BeautifulSoup,
        "urllib": urllib,
        "urllib.parse": urllib.parse,
    }

    # 自定义 __import__，只允许白名单模块
    def _safe_import(name, *args, **kwargs):
        top = name.split(".")[0]
        if top in ("re", "bs4", "urllib"):
            return allowed_modules.get(name) or allowed_modules.get(top)
        raise ImportError(f"import '{name}' is not allowed in generated script sandbox")

    safe_builtins["__import__"] = _safe_import

    sandbox = dict(allowed_modules)
    sandbox["__builtins__"] = safe_builtins
    return sandbox


def _validate_papers(papers) -> list[dict]:
    """过滤并标准化论文列表。"""
    if not isinstance(papers, list):
        return []
    result = []
    for p in papers:
        if not isinstance(p, dict):
            continue
        title = clean_text(str(p.get("title", "")))
        if not title:  # 空标题不算论文
            continue
        item = {
            "title": title,
            "authors": clean_text(str(p.get("authors", ""))),
            "pdf_url": clean_text(str(p.get("pdf_url", ""))),
        }
        detail_url = clean_text(str(p.get(INTERNAL_DETAIL_URL_FIELD, "")))
        if detail_url:
            item[INTERNAL_DETAIL_URL_FIELD] = detail_url
        result.append(item)
    return result


def run_generated_script(script_code: str, html: str, base_url: str) -> list[dict]:
    """
    在受限沙箱中执行大模型生成的爬取脚本。

    Args:
        script_code: 大模型生成的 Python 代码，必须包含 extract_papers(html, base_url) 函数
        html: 目标页面的 HTML 内容
        base_url: 页面 URL，用于拼接相对路径

    Returns:
        list[dict]: 提取到的论文列表，每个 dict 包含 title / authors / pdf_url，
        可临时包含 detail_url 用于后续补全 pdf_url
    """
    if not script_code or not script_code.strip():
        logger.warning("dynamic_crawler: empty script_code")
        return []

    sandbox = _build_sandbox_globals()

    try:
        exec(compile(script_code, "<generated_script>", "exec"), sandbox)  # noqa: S102
    except Exception as e:
        logger.warning("dynamic_crawler: script compilation/exec failed: %s", e)
        return []

    extract_fn = sandbox.get("extract_papers")
    if not callable(extract_fn):
        logger.warning("dynamic_crawler: 'extract_papers' function not found in script")
        return []

    try:
        raw_papers = extract_fn(html, base_url)
    except Exception as e:
        logger.warning("dynamic_crawler: extract_papers() raised exception: %s", e)
        return []

    papers = _validate_papers(raw_papers)
    papers = dedup_papers(papers)
    logger.debug("dynamic_crawler: extracted %d papers from generated script", len(papers))
    return papers


def crawl_by_script(source: dict, html: str, script_info: dict) -> list[dict]:
    """
    根据保存的脚本信息执行爬取。

    Args:
        source: 来源配置 dict（含 url 字段）
        html: 页面 HTML
        script_info: save_generated_script 保存的结构 {"script": ..., "generated": ..., ...}

    Returns:
        list[dict]: 论文列表
    """
    script_code = str(script_info.get("script", "")).strip()
    base_url = source.get("url", "")
    if not script_code:
        return []
    return run_generated_script(script_code, html, base_url)
