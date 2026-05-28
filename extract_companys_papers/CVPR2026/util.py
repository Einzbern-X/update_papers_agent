import os
import re
import csv
import json
import time
import argparse
import sqlite3
import traceback
import threading
from typing import Dict, Any, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pymupdf as fitz
from tqdm import tqdm
from openai import OpenAI


COMPANIES = {
    "Alibaba": [
        "Alibaba",
        "Alibaba Group",
        "Alibaba Cloud",
        "Alibaba DAMO Academy",
        "DAMO Academy",
        "Tongyi Lab",
        "Qwen",
        "Taobao",
        "Tmall",
        "AliExpress",
        "Lazada",
        "Cainiao",
        "DingTalk",
        "Youku",
        "alibaba-inc.com",
        "alibaba.com",
        "aliyun.com",
    ],
    "ByteDance": [
        "ByteDance",
        "Bytedance",
        "ByteDance Research",
        "ByteDance Seed",
        "Seed Team",
        "TikTok",
        "TikTok AI Lab",
        "TikTok Research",
        "CapCut",
        "PICO",
        "bytedance.com",
        "tiktok.com",
    ],
    "Google": [
        "Google",
        "Google Research",
        "Google DeepMind",
        "DeepMind",
        "Google Cloud",
        "Google Brain",
        "YouTube",
        "google.com",
        "deepmind.com",
    ],
    "Meta": [
        "Meta",
        "Meta AI",
        "Facebook",
        "Facebook AI Research",
        "FAIR",
        "Reality Labs",
        "Instagram",
        "WhatsApp",
        "meta.com",
        "fb.com",
        "facebook.com",
    ],
    "Tencent": [
        "Tencent",
        "Tencent AI Lab",
        "Tencent YouTu Lab",
        "Tencent Youtu Lab",
        "Tencent ARC Lab",
        "Tencent Robotics X",
        "Tencent Games",
        "WeChat",
        "tencent.com",
    ],
    "OpenAI": [
        "OpenAI",
        "openai.com",
    ],
}


ALL_ALIASES = sorted(
    set(alias for aliases in COMPANIES.values() for alias in aliases),
    key=len,
    reverse=True,
)


_thread_local = threading.local()


def build_client() -> OpenAI:
    api_key = os.getenv("MOONSHOT_API_KEY")
    if not api_key:
        raise RuntimeError("请先设置环境变量：export MOONSHOT_API_KEY='你的kimi_api_key'")

    return OpenAI(
        api_key=api_key,
        base_url="https://api.moonshot.cn/v1",
    )


def get_thread_client() -> OpenAI:
    """
    每个线程一个 OpenAI client，避免多个线程共享同一个 client 引发不稳定问题。
    """
    client = getattr(_thread_local, "client", None)
    if client is None:
        client = build_client()
        _thread_local.client = client
    return client


def get_thread_session() -> requests.Session:
    """
    每个线程一个 requests.Session，提高 PDF 下载效率。
    """
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            )
        })
        _thread_local.session = session
    return session


def connect_db(db_path: str) -> sqlite3.Connection:
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"数据库文件不存在：{db_path}")
    return sqlite3.connect(db_path)


def load_papers(conn: sqlite3.Connection, venue: str, year: int, limit: Optional[int] = None):
    sql = """
    select venue, year, title, authors, pdf_url, source_url
    from papers
    where venue = ?
      and year = ?
    """
    params = [venue, year]

    if limit:
        sql += " limit ?"
        params.append(limit)

    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()

    papers = []
    for row in rows:
        papers.append({
            "venue": row[0],
            "year": row[1],
            "title": row[2] or "",
            "authors": row[3] or "",
            "pdf_url": row[4] or "",
            "source_url": row[5] or "",
        })

    return papers


def request_bytes(url: str, timeout: int = 60) -> bytes:
    if not url:
        return b""

    try:
        session = get_thread_session()
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    except Exception:
        return b""


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\x00", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def make_paper_key(title: str, pdf_url: str) -> str:
    """
    用 title + pdf_url 作为唯一键。
    兼容断点续跑和避免重复写 CSV。
    """
    title = clean_text(title).lower()
    pdf_url = clean_text(pdf_url).lower()
    return f"{title}|||{pdf_url}"


def extract_pdf_first_two_pages_text(pdf_url: str) -> Dict[str, str]:
    """
    提取 PDF 第 1 页和第 2 页文字。

    page1_text:
        只用于判断公司机构归属。

    first_two_pages_text:
        用于提取摘要，避免摘要跨页。
    """
    data = request_bytes(pdf_url)
    if not data:
        return {
            "page1_text": "",
            "page2_text": "",
            "first_two_pages_text": "",
        }

    try:
        doc = fitz.open(stream=data, filetype="pdf")

        if len(doc) == 0:
            doc.close()
            return {
                "page1_text": "",
                "page2_text": "",
                "first_two_pages_text": "",
            }

        page1_text = doc[0].get_text() if len(doc) >= 1 else ""
        page2_text = doc[1].get_text() if len(doc) >= 2 else ""

        doc.close()

        page1_text = clean_text(page1_text)
        page2_text = clean_text(page2_text)

        first_two_pages_text = clean_text(
            f"""
            [PAGE 1]
            {page1_text}

            [PAGE 2]
            {page2_text}
            """
        )

        return {
            "page1_text": page1_text,
            "page2_text": page2_text,
            "first_two_pages_text": first_two_pages_text,
        }

    except Exception:
        return {
            "page1_text": "",
            "page2_text": "",
            "first_two_pages_text": "",
        }


def extract_abstract_from_text(text: str) -> str:
    """
    从 PDF 前 2 页文本中尝试截取摘要。
    如果正则提取失败，后面会使用 Kimi 返回的 abstract 兜底。
    """
    if not text:
        return ""

    text = clean_text(text)

    patterns = [
        r"Abstract\s*(.*?)(?:1\.?\s*Introduction|I\.?\s*Introduction|Introduction|Keywords|Index Terms)",
        r"ABSTRACT\s*(.*?)(?:1\.?\s*INTRODUCTION|INTRODUCTION|KEYWORDS|INDEX TERMS)",
    ]

    for p in patterns:
        m = re.search(p, text, flags=re.I | re.S)
        if m:
            abstract = clean_text(m.group(1))
            if 50 <= len(abstract) <= 5000:
                return abstract

    return ""


def parse_json_from_model(text: str) -> Dict[str, Any]:
    if not text:
        return {}

    text = text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    m = re.search(r"\{.*\}", text, flags=re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}

    return {}


def normalize_company_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    保证 Kimi 返回结构稳定。
    """
    companies = result.get("companies", {})
    if not isinstance(companies, dict):
        companies = {}

    normalized = {}

    for company in COMPANIES.keys():
        item = companies.get(company, {})
        if not isinstance(item, dict):
            item = {}

        normalized[company] = {
            "is_related": bool(item.get("is_related", False)),
            "confidence": float(item.get("confidence", 0) or 0),
            "matched_affiliations": item.get("matched_affiliations", [])
            if isinstance(item.get("matched_affiliations", []), list)
            else [],
            "reason": str(item.get("reason", "") or ""),
        }

    return {
        "companies": normalized,
        "abstract": str(result.get("abstract", "") or ""),
    }


def judge_by_kimi(
    model: str,
    paper: Dict[str, str],
    pdf_page1_text: str,
    pdf_first_two_pages_text: str,
    max_input_chars: int = 18000,
    retry: int = 3,
) -> Dict[str, Any]:

    client = get_thread_client()
    company_alias_text = json.dumps(COMPANIES, ensure_ascii=False, indent=2)

    system_prompt = f"""
你是论文机构归属判断助手。你的任务是判断一篇论文是否属于以下公司相关论文：

- Alibaba
- ByteDance
- Google
- Meta
- Tencent
- OpenAI

判断规则非常重要：
- 公司机构归属只能根据 PDF 第 1 页内容判断。
- PDF 第 2 页只能用于补全摘要，不能用于判断作者机构。
- 如果第 1 页没有明确公司机构证据，即使第 2 页或摘要中出现公司名、模型名、数据集名，也不能判定为该公司论文。
- 不能根据论文题目、数据库作者字段、参考文献、相关工作、模型名称、实验对比或常识猜测机构归属。
- 一篇论文可能同时属于多家公司，例如企业合作论文。此时多个公司都可以标记为 true。
- 论文中机构不会出现中文，所以只根据英文机构、英文邮箱域名和英文单位名称判断。

公司别名参考如下，但不要机械匹配，要判断它是否是作者当前机构或首页机构证据：
{company_alias_text}

计入范围：
- PDF 第 1 页中的作者当前机构、论文单位、通讯单位、脚注、邮箱域名或首页机构信息明确属于上述公司。
- 例如 Google Research、Google DeepMind、Meta AI、FAIR、ByteDance、Tencent AI Lab、Alibaba DAMO Academy、OpenAI 等。
- 如果第 1 页出现明确公司邮箱域名，也可以作为证据，例如 google.com、deepmind.com、meta.com、bytedance.com、tencent.com、alibaba.com、openai.com 等。

不计入范围：
- 只是使用了某公司的模型、API、云服务、数据集或代码。
- 只是引用了某公司的论文。
- 只是参考文献、相关工作、实验对比中出现公司名。
- 作者过去曾在某公司工作，但当前论文首页机构不是该公司。
- PDF 第 2 页只允许用于补全摘要，不允许作为机构归属证据。
- 第 1 页没有明确机构证据时，对该公司判定为 false。

输出必须是严格 JSON，不要输出 Markdown，不要解释 JSON 之外的内容。
JSON 格式如下：
{{
  "companies": {{
    "Alibaba": {{
      "is_related": true 或 false,
      "confidence": 0 到 1 的数字,
      "matched_affiliations": ["只能填写 PDF 第 1 页中命中的机构或邮箱证据"],
      "reason": "一句话说明判断依据"
    }},
    "ByteDance": {{
      "is_related": true 或 false,
      "confidence": 0 到 1 的数字,
      "matched_affiliations": [],
      "reason": ""
    }},
    "Google": {{
      "is_related": true 或 false,
      "confidence": 0 到 1 的数字,
      "matched_affiliations": [],
      "reason": ""
    }},
    "Meta": {{
      "is_related": true 或 false,
      "confidence": 0 到 1 的数字,
      "matched_affiliations": [],
      "reason": ""
    }},
    "Tencent": {{
      "is_related": true 或 false,
      "confidence": 0 到 1 的数字,
      "matched_affiliations": [],
      "reason": ""
    }},
    "OpenAI": {{
      "is_related": true 或 false,
      "confidence": 0 到 1 的数字,
      "matched_affiliations": [],
      "reason": ""
    }}
  }},
  "abstract": "论文摘要。可以根据 PDF 第 1-2 页提取；如果没有摘要，返回空字符串"
}}
""".strip()

    content = f"""
请完成两个任务：

1. 只根据 [PDF PAGE 1] 判断作者机构是否属于 Alibaba、ByteDance、Google、Meta、Tencent、OpenAI。
2. 根据 [PDF PAGE 1-2] 尽量提取完整摘要。

注意：
- 判断机构时只能看 [PDF PAGE 1]。
- [PDF PAGE 2] 只能用于补全摘要，不能作为机构判断依据。
- 数据库中的作者字段不能作为机构证据。

PDF 地址：
{paper.get("pdf_url", "")}

数据库标题，仅供输出核对，不得作为机构判断依据：
{paper.get("title", "")}

数据库作者字段，仅供输出核对，不得作为机构判断依据：
{paper.get("authors", "")}

[PDF PAGE 1]
{pdf_page1_text}

[PDF PAGE 1-2]
{pdf_first_two_pages_text}
""".strip()

    if len(content) > max_input_chars:
        content = content[:max_input_chars]

    last_err = None

    for attempt in range(1, retry + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
            )

            raw = resp.choices[0].message.content
            result = parse_json_from_model(raw)

            if not result:
                raise ValueError(f"模型未返回合法 JSON：{raw[:500]}")

            return normalize_company_result(result)

        except Exception as e:
            last_err = e
            time.sleep(2 * attempt)

    empty_companies = {}
    for company in COMPANIES.keys():
        empty_companies[company] = {
            "is_related": False,
            "confidence": 0,
            "matched_affiliations": [],
            "reason": f"Kimi 判断失败：{last_err}",
        }

    return {
        "companies": empty_companies,
        "abstract": "",
    }


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def company_csv_path(out_dir: str, company: str, venue: str, year: int) -> str:
    safe_company = company.lower().replace(" ", "_")
    safe_venue = venue.lower()
    return os.path.join(out_dir, f"{safe_company}_{safe_venue}{year}.csv")


def ensure_company_csvs(out_dir: str, venue: str, year: int):
    ensure_dir(out_dir)

    for company in COMPANIES.keys():
        path = company_csv_path(out_dir, company, venue, year)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            continue

        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["题目", "作者", "摘要", "pdf地址"])
            writer.writeheader()


def load_written_keys_by_company(out_dir: str, venue: str, year: int) -> Dict[str, set]:
    """
    读取已有 CSV，避免续跑时重复写入同一篇论文。
    """
    result = {company: set() for company in COMPANIES.keys()}

    for company in COMPANIES.keys():
        path = company_csv_path(out_dir, company, venue, year)
        if not os.path.exists(path):
            continue

        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    title = row.get("题目", "")
                    pdf_url = row.get("pdf地址", "")
                    if title or pdf_url:
                        result[company].add(make_paper_key(title, pdf_url))
        except Exception:
            continue

    return result


def append_company_row(
    out_dir: str,
    company: str,
    venue: str,
    year: int,
    paper: Dict[str, str],
    abstract: str,
):
    path = company_csv_path(out_dir, company, venue, year)

    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["题目", "作者", "摘要", "pdf地址"])
        writer.writerow({
            "题目": paper.get("title", ""),
            "作者": paper.get("authors", ""),
            "摘要": abstract or "",
            "pdf地址": paper.get("pdf_url", ""),
        })


def append_log(log_path: str, item: Dict[str, Any]):
    with open(log_path, "a", encoding="utf-8", newline="") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def get_processed_from_log(log_path: str, retry_errors: bool = False) -> Tuple[set, set]:
    """
    读取已有 log，用于断点续跑。

    返回：
    - processed_keys: 新版 key，title + pdf_url
    - processed_titles: 兼容旧日志，只按 title 跳过

    默认所有写入 log 的论文都视为已处理。
    如果加 --retry-errors，则遇到 error/error_type 的记录不会跳过，会重新处理。
    """
    processed_keys = set()
    processed_titles = set()

    if not os.path.exists(log_path):
        return processed_keys, processed_titles

    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                item = json.loads(line)
            except Exception:
                continue

            if retry_errors and (item.get("error") or item.get("error_type")):
                continue

            title = item.get("title", "")
            pdf_url = item.get("pdf_url", "")

            if title:
                processed_titles.add(clean_text(title).lower())

            if title or pdf_url:
                processed_keys.add(make_paper_key(title, pdf_url))

    return processed_keys, processed_titles


def quick_alias_hit(text: str) -> bool:
    text_low = text.lower()
    for alias in ALL_ALIASES:
        if alias.lower() in text_low:
            return True
    return False


def count_company_csv_rows(out_dir: str, venue: str, year: int) -> Dict[str, int]:
    counts = {company: 0 for company in COMPANIES.keys()}

    for company in COMPANIES.keys():
        path = company_csv_path(out_dir, company, venue, year)
        if not os.path.exists(path):
            continue

        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                counts[company] = sum(1 for _ in reader)
        except Exception:
            counts[company] = 0

    return counts


def write_summary_csv(
    summary_path: str,
    counts: Dict[str, int],
    total_papers: int,
    newly_judged_count: int,
    skipped_by_resume_count: int,
    workers: int,
):
    with open(summary_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "company",
                "count",
                "total_papers",
                "newly_judged_papers",
                "skipped_by_resume",
                "workers",
            ]
        )
        writer.writeheader()

        for company, count in counts.items():
            writer.writerow({
                "company": company,
                "count": count,
                "total_papers": total_papers,
                "newly_judged_papers": newly_judged_count,
                "skipped_by_resume": skipped_by_resume_count,
                "workers": workers,
            })


def process_one_paper(
    paper: Dict[str, str],
    model: str,
    only_alias_candidates: bool,
    sleep_seconds: float,
) -> Dict[str, Any]:
    """
    线程 worker。
    不在这里写 CSV / log，避免多线程写文件冲突。
    """
    title = paper.get("title", "").strip()
    pdf_url = paper.get("pdf_url", "")

    try:
        pdf_pages = extract_pdf_first_two_pages_text(pdf_url)

        pdf_page1_text = pdf_pages["page1_text"]
        pdf_first_two_pages_text = pdf_pages["first_two_pages_text"]

        if not pdf_page1_text:
            log_item = {
                "title": title,
                "authors": paper.get("authors", ""),
                "pdf_url": pdf_url,
                "source_url": paper.get("source_url", ""),
                "companies": {
                    company: {
                        "is_related": False,
                        "confidence": 0,
                        "matched_affiliations": [],
                        "reason": "PDF 第 1 页文本提取失败或为空，未进行 Kimi 判断",
                    }
                    for company in COMPANIES.keys()
                },
                "abstract_found": False,
                "error_type": "empty_pdf_page1",
            }

            return {
                "status": "pdf_empty",
                "paper": paper,
                "log_item": log_item,
                "related_companies": [],
                "abstract": "",
            }

        regex_abstract = extract_abstract_from_text(pdf_first_two_pages_text)

        # 机构判断只看第 1 页，所以关键词预筛选也只看第 1 页
        evidence_text = " ".join([
            pdf_url,
            pdf_page1_text[:6000],
        ])

        if only_alias_candidates and not quick_alias_hit(evidence_text):
            log_item = {
                "title": title,
                "authors": paper.get("authors", ""),
                "pdf_url": pdf_url,
                "source_url": paper.get("source_url", ""),
                "companies": {
                    company: {
                        "is_related": False,
                        "confidence": 0,
                        "matched_affiliations": [],
                        "reason": "PDF 第 1 页未命中目标公司关键词，跳过 Kimi 调用",
                    }
                    for company in COMPANIES.keys()
                },
                "abstract_found": bool(regex_abstract),
                "skipped_by_alias_prefilter": True,
            }

            return {
                "status": "skipped_by_alias",
                "paper": paper,
                "log_item": log_item,
                "related_companies": [],
                "abstract": regex_abstract,
            }

        result = judge_by_kimi(
            model=model,
            paper=paper,
            pdf_page1_text=pdf_page1_text,
            pdf_first_two_pages_text=pdf_first_two_pages_text,
        )

        final_abstract = result.get("abstract") or regex_abstract
        company_results = result.get("companies", {})

        related_companies: List[str] = []

        for company in COMPANIES.keys():
            item = company_results.get(company, {})
            if item.get("is_related", False):
                related_companies.append(company)

        log_item = {
            "title": title,
            "authors": paper.get("authors", ""),
            "pdf_url": pdf_url,
            "source_url": paper.get("source_url", ""),
            "related_companies": related_companies,
            "companies": company_results,
            "abstract_found": bool(final_abstract),
        }

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

        return {
            "status": "judged",
            "paper": paper,
            "log_item": log_item,
            "related_companies": related_companies,
            "abstract": final_abstract,
        }

    except Exception as e:
        log_item = {
            "title": title,
            "authors": paper.get("authors", ""),
            "pdf_url": paper.get("pdf_url", ""),
            "source_url": paper.get("source_url", ""),
            "companies": {},
            "error": str(e),
            "traceback": traceback.format_exc(),
        }

        return {
            "status": "error",
            "paper": paper,
            "log_item": log_item,
            "related_companies": [],
            "abstract": "",
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="SQLite 数据库路径")
    parser.add_argument("--out-dir", default="company_cvpr2026_csv", help="输出 CSV 文件夹")
    parser.add_argument("--log", default="company_cvpr2026_judge_log.jsonl", help="判断日志 JSONL")
    parser.add_argument("--summary", default="company_cvpr2026_summary.csv", help="统计汇总 CSV")
    parser.add_argument("--venue", default="CVPR")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--model", default="kimi-k2.6")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4, help="并发线程数，建议 3-5")
    parser.add_argument("--sleep", type=float, default=0.1, help="每个线程每篇 Kimi 调用后的暂停秒数")
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="不使用 log 断点续跑，强制重新处理",
    )
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="断点续跑时，重新处理之前 log 中带 error/error_type 的论文",
    )
    parser.add_argument(
        "--only-alias-candidates",
        action="store_true",
        help="只对 PDF 第 1 页中出现目标公司关键词的论文调用 Kimi，可省钱更快，但可能漏掉机构写法特殊的论文",
    )
    parser.set_defaults(resume=True)

    args = parser.parse_args()

    if args.workers < 1:
        args.workers = 1
    if args.workers > 8:
        print("[WARN] workers 太高可能触发限流，已自动限制为 8")
        args.workers = 8

    # 提前检查 API Key
    _ = os.getenv("MOONSHOT_API_KEY")
    if not _:
        raise RuntimeError("请先设置环境变量：export MOONSHOT_API_KEY='你的kimi_api_key'")

    conn = connect_db(args.db)
    papers = load_papers(conn, args.venue, args.year, args.limit)
    conn.close()

    print(f"[INFO] 从数据库读取到 {len(papers)} 篇 {args.venue} {args.year} 论文")

    ensure_company_csvs(args.out_dir, args.venue, args.year)

    written_keys_by_company = load_written_keys_by_company(
        args.out_dir,
        args.venue,
        args.year,
    )

    processed_keys = set()
    processed_titles = set()

    if args.resume:
        processed_keys, processed_titles = get_processed_from_log(
            args.log,
            retry_errors=args.retry_errors,
        )
        print(f"[INFO] 已从日志读取已处理记录：{len(processed_keys)} 条")

    todo_papers = []
    skipped_by_resume = 0

    for paper in papers:
        title = paper.get("title", "")
        pdf_url = paper.get("pdf_url", "")
        key = make_paper_key(title, pdf_url)
        title_key = clean_text(title).lower()

        if args.resume and (key in processed_keys or title_key in processed_titles):
            skipped_by_resume += 1
            continue

        todo_papers.append(paper)

    print(f"[INFO] 本次需要处理：{len(todo_papers)} 篇")
    print(f"[INFO] 断点跳过：{skipped_by_resume} 篇")
    print(f"[INFO] 使用线程数：{args.workers}")

    newly_judged_count = 0
    skipped_by_alias_count = 0
    pdf_empty_count = 0
    error_count = 0

    executor = ThreadPoolExecutor(max_workers=args.workers)
    futures = []

    try:
        for paper in todo_papers:
            future = executor.submit(
                process_one_paper,
                paper,
                args.model,
                args.only_alias_candidates,
                args.sleep,
            )
            futures.append(future)

        for future in tqdm(as_completed(futures), total=len(futures), desc="Judging papers"):
            result = future.result()

            status = result.get("status")
            paper = result.get("paper", {})
            log_item = result.get("log_item", {})
            related_companies = result.get("related_companies", [])
            abstract = result.get("abstract", "")

            # 主线程写 log，避免多线程乱写
            append_log(args.log, log_item)

            if status == "judged":
                newly_judged_count += 1
            elif status == "skipped_by_alias":
                skipped_by_alias_count += 1
            elif status == "pdf_empty":
                pdf_empty_count += 1
            elif status == "error":
                error_count += 1

            # 主线程写 CSV，避免多线程乱写
            if related_companies:
                title = paper.get("title", "")
                pdf_url = paper.get("pdf_url", "")
                paper_key = make_paper_key(title, pdf_url)

                for company in related_companies:
                    if paper_key in written_keys_by_company[company]:
                        continue

                    append_company_row(
                        out_dir=args.out_dir,
                        company=company,
                        venue=args.venue,
                        year=args.year,
                        paper=paper,
                        abstract=abstract,
                    )
                    written_keys_by_company[company].add(paper_key)

                print(f"\n[HIT] {title}")
                print(f"      Companies: {', '.join(related_companies)}")

    except KeyboardInterrupt:
        print("\n[STOP] 用户中断，已保留当前 CSV 和日志。下次直接重新运行即可自动续跑。")
        executor.shutdown(wait=False, cancel_futures=True)
        return

    finally:
        executor.shutdown(wait=True)

    final_counts = count_company_csv_rows(args.out_dir, args.venue, args.year)

    write_summary_csv(
        summary_path=args.summary,
        counts=final_counts,
        total_papers=len(papers),
        newly_judged_count=newly_judged_count,
        skipped_by_resume_count=skipped_by_resume,
        workers=args.workers,
    )

    print("\n[DONE]")
    print(f"本次实际调用 Kimi 判断：{newly_judged_count}")
    print(f"断点续跑跳过：{skipped_by_resume}")
    print(f"关键词预筛跳过：{skipped_by_alias_count}")
    print(f"PDF 第 1 页提取失败或为空：{pdf_empty_count}")
    print(f"异常错误：{error_count}")

    print("\n[COUNTS]")
    for company, count in final_counts.items():
        print(f"{company}: {count}")

    print(f"\n输出文件夹：{args.out_dir}")
    print(f"判断日志：{args.log}")
    print(f"统计汇总：{args.summary}")


if __name__ == "__main__":
    main()