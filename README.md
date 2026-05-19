# Paper Crawler Agent

这是一个论文放榜监测 Agent：

- **稳定网站**：CVF / ECVA / IJCAI / NeurIPS 等，每年结构基本不变，直接用已有脚本。
- **变化网站**：KDD / ACM MM / SIGGRAPH 等，每年页面结构可能变化，Agent 会先搜索并核验放榜页，再分析页面结构，最后按策略链提取论文。

## 输出字段

SQLite 和 CSV 对外字段固定为： 

```csv
venue,year,title,authors,pdf_url,source_url
```

`detail_url` 只在内部用于补全 PDF，不会保存或导出。

## 项目结构

核心代码按 Agent 职责拆分：

```text
agent/
  paper_agent.py          # 主编排：读取 source、记录状态、保存论文
  release_discovery.py    # variable source 的 Phase 1/2：找放榜 URL + 分析页面结构
  extraction_pipeline.py  # 解析策略链：历史脚本/rule、固定 parser、生成脚本/rule
  detail_enricher.py      # 从 detail_url 补全 pdf_url
  contracts.py            # 公开字段、内部字段、状态常量
  parser_registry.py      # 固定 parser 注册表
crawlers/                 # 固定 parser、rule parser、动态脚本沙箱
planner/                  # LLM prompt、页面结构规划、脚本/rule 生成
inspector/                # 页面摘要和提取结果校验
database/                 # SQLite 保存、source 状态、CSV 导出
tests/                    # 离线行为测试
```

## Agent 流程

stable source：

```text
fetch URL -> fixed parser -> validate -> save/export public fields
```

variable source：

```text
fetch configured URL
-> ReleaseDiscoveryAgent 搜索并核验放榜页
-> 分析页面结构生成 crawl_plan
-> ExtractionPipeline 按顺序尝试：
   1. 历史 generated_script
   2. 历史 generated_rule
   3. 固定 parser
   4. LLM 生成沙箱脚本
   5. LLM 生成 rule 兜底
-> 如果有 detail_url，DetailPageEnricher 补 pdf_url
-> validate -> save/export public fields
```

## 安装

```bash
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
released_generated_script
released_saved_rule
released_saved_script
not_released_or_parser_failed
llm_release_judge_failed
llm_rule_failed
fetch_failed
```

## 大模型做什么

对 variable 来源，大模型负责三类任务：

- 搜索并核验官方放榜页面，不把 CFP / Important Dates 当成论文列表。
- 分析页面结构，生成 `PageCrawlPlan`，告诉后续脚本是否需要 `detail_url`。
- 在固定 parser 失败时生成受限 Python 脚本；脚本在沙箱中执行，只允许 `re`、`bs4`、`urllib.parse`，不能联网或读写文件。

如果脚本策略失败，Agent 会再退回到 JSON rule 策略作为兜底。
