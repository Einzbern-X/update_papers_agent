# paper_crawler_agent_llm_release

这是一个论文放榜监测 Agent：

- **稳定网站**：CVF / ECVA / IJCAI / NeurIPS 等，每年结构基本不变，直接用已有脚本。
- **变化网站**：KDD / ACM MM / SIGGRAPH 等，每年页面结构可能变化，Agent 会先让大模型判断是否放榜；如果已放榜但固定 parser 失效，再让大模型生成当前页面的临时解析规则。

## 输出字段

SQLite 和 CSV 对外字段固定为：

```csv
venue,year,title,authors,pdf_url,source_url
```

## 安装

```bash
cd paper_crawler_agent_llm_release
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 配置大模型

使用 OpenAI-compatible `/v1/chat/completions` 接口。

```bash
export LLM_API_KEY="你的key"
export LLM_BASE_URL="https://api.openai.com/v1"
```

如果是内部模型，把 `LLM_BASE_URL` 改成内部兼容接口地址即可。

## 运行

```bash
python main.py
```

导出 CSV：

```bash
python main.py --export
```

只导出不爬取：

```bash
python main.py --export-only
```

## 数据库

默认保存到：

```text
data/papers.db
```

包含两张主要表：

- `papers`：论文数据。
- `sources`：每个页面的监测状态。

`sources.status` 常见状态：

```text
not_released
id_only
released_fixed_parser
released_generated_rule
released_saved_rule
not_released_or_parser_failed
llm_release_judge_failed
llm_rule_failed
fetch_failed
```

## 大模型做什么

对 variable 来源，大模型先输出页面状态：

```json
{"status":"released_with_papers","has_titles":true,"has_authors":true,"has_pdf_links":false}
```

如果固定 parser 失败，大模型再输出解析规则：

```json
{
  "released": true,
  "rule_type": "css_selector",
  "paper_container": "div.paper-item",
  "title_selector": "h3",
  "authors_selector": ".authors",
  "pdf_selector": "a[href$='.pdf']",
  "pdf_attr": "href"
}
```

程序只执行解析规则，不自动执行大模型生成的 Python 代码。
