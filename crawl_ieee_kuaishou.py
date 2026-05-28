#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Use IEEE Xplore official Python SDK file xploreapi.py to search papers by affiliation.

Usage:
  python crawl_ieee_kuaishou_debug_fixed.py --api-key YOUR_KEY --output ieee_kuaishou_papers.csv

Or put key in env:
  export IEEE_API_KEY="YOUR_KEY"
  python crawl_ieee_kuaishou_debug_fixed.py --output ieee_kuaishou_papers.csv

Put xploreapi.py in the same directory as this script, or use --sdk-path.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


AFFILIATION_QUERIES = [
    "Kuaishou",
    "Kuaishou Technology",
    "Beijing Kuaishou Technology",
    "Kwai",
]

KUAISHOU_KEYWORDS = [
    "kuaishou",
    "kuaishou technology",
    "beijing kuaishou",
    "kwai",
]

FIELDNAMES = [
    "matched_query",
    "article_number",
    "title",
    "authors",
    "affiliations",
    "abstract",
    "publication_title",
    "publication_year",
    "publication_date",
    "content_type",
    "doi",
    "pdf_url",
    "html_url",
    "abstract_url",
    "publisher",
    "insert_date",
]


def load_xplore_class(sdk_path: str | None = None):
    """Load XPLORE from xploreapi.py in same directory or user-specified path."""
    candidates: list[Path] = []

    if sdk_path:
        candidates.append(Path(sdk_path).expanduser().resolve())

    candidates.append(Path(__file__).resolve().parent / "xploreapi.py")
    candidates.append(Path.cwd() / "xploreapi.py")

    for path in candidates:
        if path.exists():
            spec = importlib.util.spec_from_file_location("xploreapi", str(path))
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules["xploreapi"] = module
            spec.loader.exec_module(module)
            if not hasattr(module, "XPLORE"):
                raise RuntimeError(f"{path} exists, but it has no XPLORE class")
            print(f"[INFO] loaded xploreapi.py from: {path}")
            return module.XPLORE

    raise ModuleNotFoundError(
        "Cannot find xploreapi.py. Put xploreapi.py in the same directory as this script, "
        "or pass --sdk-path /path/to/xploreapi.py"
    )


def mask_api_key_in_url(url: str) -> str:
    parts = urlsplit(url)
    pairs = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        if k.lower() == "apikey" and v:
            v = v[:4] + "***" + v[-4:] if len(v) > 8 else "***"
        pairs.append((k, v))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(safe_text(v) for v in value if v is not None)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {safe_text(v)}" for k, v in value.items())
    return str(value).replace("\n", " ").replace("\r", " ").strip()


def normalize_title(title: str) -> str:
    return " ".join(title.lower().strip().split())


def extract_authors(article: dict) -> str:
    authors = article.get("authors", "")

    if isinstance(authors, dict):
        author_list = authors.get("authors", [])
    elif isinstance(authors, list):
        author_list = authors
    else:
        return safe_text(authors)

    names = []
    for author in author_list:
        if isinstance(author, dict):
            name = author.get("full_name") or author.get("name") or author.get("preferred_name") or ""
            if name:
                names.append(name)
        else:
            names.append(str(author))

    return "; ".join(names)


def extract_affiliations(article: dict) -> str:
    affs = []

    for key in ["affiliation", "affiliations"]:
        if article.get(key):
            affs.append(article.get(key))

    authors = article.get("authors", "")
    if isinstance(authors, dict):
        author_list = authors.get("authors", [])
    elif isinstance(authors, list):
        author_list = authors
    else:
        author_list = []

    for author in author_list:
        if not isinstance(author, dict):
            continue
        for key in ["affiliation", "affiliations", "authorAffiliation"]:
            if author.get(key):
                affs.append(author.get(key))

    return safe_text(affs)


def is_kuaishou_paper(article: dict) -> bool:
    text = " ".join(
        [
            safe_text(article.get("title")),
            safe_text(article.get("abstract")),
            safe_text(article.get("publication_title")),
            extract_affiliations(article),
        ]
    ).lower()
    return any(keyword in text for keyword in KUAISHOU_KEYWORDS)


def get_total_count(data: dict, articles: list[dict]) -> int:
    for key in ["total_records", "totalfound", "totalFound", "total"]:
        if key in data:
            try:
                return int(data[key])
            except Exception:
                pass
    return len(articles)


def looks_like_json(text: str) -> bool:
    s = text.lstrip()
    return s.startswith("{") or s.startswith("[")


def save_bad_response(raw: str, affiliation: str, start_record: int) -> str:
    safe_aff = re.sub(r"[^A-Za-z0-9_.-]+", "_", affiliation).strip("_") or "unknown"
    path = Path(f"ieee_bad_response_{safe_aff}_{start_record}.txt")
    path.write_text(raw or "", encoding="utf-8")
    return str(path.resolve())


def build_query(XPLORE, api_key: str, affiliation: str, start_record: int, max_records: int):
    query = XPLORE(api_key)
    query.affiliationText(affiliation)
    query.startingResult(start_record)
    query.maximumResults(max_records)
    query.resultsSorting("article_title", "asc")
    query.dataType("json")

    # Important: use raw here. If the API returns empty string / HTML / error text,
    # the official SDK's dataFormat("object") will crash inside json.loads before
    # we can see the real response.
    query.dataFormat("raw")
    return query


def call_ieee_sdk(
    XPLORE,
    api_key: str,
    affiliation: str,
    start_record: int,
    max_records: int = 200,
    debug: bool = False,
    debug_url_only: bool = False,
) -> dict:
    query = build_query(XPLORE, api_key, affiliation, start_record, max_records)
    url = query.callAPI(False)

    if debug or debug_url_only:
        print("[DEBUG]", mask_api_key_in_url(url))

    if debug_url_only:
        return {"articles": [], "total_records": 0, "_debug_url_only": True}

    try:
        raw = query.callAPI()
    except Exception as e:
        raise RuntimeError(
            f"IEEE SDK request failed for affiliation={affiliation!r}, start_record={start_record}. "
            f"Query={mask_api_key_in_url(url)}. Error={e}"
        ) from e

    if raw is None:
        raw = ""

    if not isinstance(raw, str):
        # In case someone changes dataFormat back to object.
        if isinstance(raw, dict):
            return raw
        raise RuntimeError(f"Unexpected SDK return type: {type(raw)}")

    if not raw.strip():
        bad_path = save_bad_response(raw, affiliation, start_record)
        raise RuntimeError(
            "IEEE API returned an empty response. "
            "Most likely reasons: API key is not approved/activated, network/proxy/TLS issue, "
            "or the endpoint rejected the request. "
            f"Query={mask_api_key_in_url(url)}. Saved raw response: {bad_path}"
        )

    if not looks_like_json(raw):
        bad_path = save_bad_response(raw, affiliation, start_record)
        preview = raw[:300].replace("\n", " ").replace("\r", " ")
        raise RuntimeError(
            "IEEE API returned non-JSON content, so it cannot be parsed as JSON. "
            "This usually means an error page or access denial was returned. "
            f"Query={mask_api_key_in_url(url)}. Preview={preview!r}. Saved raw response: {bad_path}"
        )

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        bad_path = save_bad_response(raw, affiliation, start_record)
        preview = raw[:300].replace("\n", " ").replace("\r", " ")
        raise RuntimeError(
            f"IEEE API response looked like JSON but failed to parse: {e}. "
            f"Preview={preview!r}. Saved raw response: {bad_path}"
        ) from e


def crawl_by_affiliation(
    XPLORE,
    api_key: str,
    affiliation: str,
    max_records: int = 200,
    sleep_seconds: float = 1.0,
    debug: bool = False,
    debug_url_only: bool = False,
) -> list[dict]:
    print(f"\n[INFO] Searching IEEE affiliation: {affiliation}")

    start_record = 1
    all_articles = []

    while True:
        data = call_ieee_sdk(
            XPLORE=XPLORE,
            api_key=api_key,
            affiliation=affiliation,
            start_record=start_record,
            max_records=max_records,
            debug=debug,
            debug_url_only=debug_url_only,
        )

        if debug_url_only:
            break

        if data.get("error"):
            raise RuntimeError(f"IEEE API error: {data.get('error')}")

        articles = data.get("articles", [])
        if not articles:
            print(f"[INFO] no more articles, stop. start_record={start_record}")
            break

        total = get_total_count(data, articles)
        print(
            f"[INFO] affiliation={affiliation}, "
            f"start_record={start_record}, got={len(articles)}, total={total}"
        )

        all_articles.extend(articles)
        start_record += len(articles)

        if start_record > total:
            break

        time.sleep(sleep_seconds)

    return all_articles


def dedup_articles(items: list[tuple[dict, str]]) -> list[tuple[dict, str]]:
    seen = set()
    result = []

    for article, query_text in items:
        article_number = safe_text(article.get("article_number"))
        doi = safe_text(article.get("doi")).lower()
        title = normalize_title(safe_text(article.get("title")))
        key = article_number or doi or title

        if not key or key in seen:
            continue

        seen.add(key)
        result.append((article, query_text))

    return result


def article_to_row(article: dict, matched_query: str) -> dict:
    return {
        "matched_query": matched_query,
        "article_number": safe_text(article.get("article_number")),
        "title": safe_text(article.get("title")),
        "authors": extract_authors(article),
        "affiliations": extract_affiliations(article),
        "abstract": safe_text(article.get("abstract")),
        "publication_title": safe_text(article.get("publication_title")),
        "publication_year": safe_text(article.get("publication_year")),
        "publication_date": safe_text(article.get("publication_date")),
        "content_type": safe_text(article.get("content_type")),
        "doi": safe_text(article.get("doi")),
        "pdf_url": safe_text(article.get("pdf_url")),
        "html_url": safe_text(article.get("html_url")),
        "abstract_url": safe_text(article.get("abstract_url")),
        "publisher": safe_text(article.get("publisher")),
        "insert_date": safe_text(article.get("insert_date")),
    }


def save_csv(rows: list[dict], output_path: str):
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[DONE] saved CSV: {output_path}")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", default=os.getenv("IEEE_API_KEY", ""), help="IEEE Xplore API key")
    parser.add_argument("--sdk-path", default="", help="Path to xploreapi.py. Optional if it is in the same directory.")
    parser.add_argument("--output", default="ieee_kuaishou_papers.csv", help="Output CSV path")
    parser.add_argument("--sleep", type=float, default=1.0, help="Sleep seconds between pages")
    parser.add_argument("--max-records", type=int, default=200, help="Max records per request, capped by SDK at 200")
    parser.add_argument("--no-filter", action="store_true", help="Keep raw API results without Kuaishou/Kwai second-pass filter")
    parser.add_argument("--debug", action="store_true", help="Print masked query URL before each request")
    parser.add_argument("--debug-url-only", action="store_true", help="Only print masked query URLs; do not call API")
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.api_key:
        raise ValueError(
            "Missing IEEE API key. Set env IEEE_API_KEY or pass --api-key.\n"
            "Example: export IEEE_API_KEY='YOUR_KEY'"
        )

    XPLORE = load_xplore_class(args.sdk_path or None)

    collected: list[tuple[dict, str]] = []

    for affiliation in AFFILIATION_QUERIES:
        articles = crawl_by_affiliation(
            XPLORE=XPLORE,
            api_key=args.api_key,
            affiliation=affiliation,
            max_records=args.max_records,
            sleep_seconds=args.sleep,
            debug=args.debug,
            debug_url_only=args.debug_url_only,
        )

        for article in articles:
            collected.append((article, affiliation))

    if args.debug_url_only:
        print("[DONE] debug-url-only finished; no CSV generated.")
        return

    print(f"\n[INFO] raw collected articles: {len(collected)}")

    deduped = dedup_articles(collected)
    print(f"[INFO] after dedup: {len(deduped)}")

    if args.no_filter:
        filtered = deduped
    else:
        filtered = [
            (article, query_text)
            for article, query_text in deduped
            if is_kuaishou_paper(article)
        ]

    print(f"[INFO] after Kuaishou/Kwai filter: {len(filtered)}")

    rows = [article_to_row(article, query_text) for article, query_text in filtered]
    rows.sort(
        key=lambda x: (
            x.get("publication_year", ""),
            x.get("publication_date", ""),
            x.get("title", ""),
        ),
        reverse=True,
    )

    save_csv(rows, args.output)


if __name__ == "__main__":
    main()
