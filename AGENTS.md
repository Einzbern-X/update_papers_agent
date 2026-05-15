# Paper Crawler Agent — 开发规则

本文件定义了 AI 编码助手在此项目中必须遵守的开发规范。
参考思想来源：[mattpocock/skills TDD](https://github.com/mattpocock/skills/tree/main/skills/engineering/tdd)

---

## 项目领域词汇（Domain Glossary）

| 术语 | 含义 |
|---|---|
| `source` | 配置中的一个会议来源，含 venue / year / url / parser / structure_type |
| `stable source` | 页面结构固定的来源，使用固定 parser（cvf / ecva / ijcai / neurips） |
| `variable source` | 页面结构每年可能变化的来源，需要大模型辅助 |
| `crawl_plan` / `PageCrawlPlan` | Phase 2 分析页面后生成的结构描述，含 has_titles / needs_detail_page 等 |
| `release URL` | 会议已录用论文列表的官方页面 URL（可能和配置中不同） |
| `detail_url` | 论文详情子页面 URL（当列表页没有 PDF 时，需要进入此页获取） |
| `generated_script` | 大模型为特定页面生成的 Python 爬取函数，保存在 runtime_rules/ |
| `generated_rule` | 大模型生成的 CSS/regex 解析规则（旧策略，兜底用） |
| `enrich` | 访问 detail_url，从子页面补全 pdf_url 的过程 |
| `validate_papers` | 验证提取的论文列表是否满足最低数量和标题合法率 |

---

## 核心开发原则

### 1. 测试行为，不测实现（Behavior, Not Implementation）

> 参考 mattpocock/tdd：*"Tests should verify behavior through public interfaces, not implementation details."*

- **禁止**：测试内部实现细节（如 `soup.find_all` 的调用次数、私有方法的返回值）
- **要求**：测试公共接口的行为，例如：
  - `crawl_ecva(source, html)` → 返回 ≥ N 篇论文，且每篇有 title
  - `run_generated_script(script, html, url)` → 返回合法 papers list
  - `validate_papers(papers, 5, 0.9)` → 对空列表返回 `(False, reason)`

- **好的测试描述行为**：`test_ecva_parser_extracts_titles_and_authors`
- **坏的测试描述实现**：`test_soup_finds_dt_ptitle_elements`

### 2. 垂直切片 / Tracer Bullet（一次只做一件事）

> 参考 mattpocock/tdd：*"One test → one implementation → repeat"*

- **每次修改一个 parser 或模块，同步写或更新对应的行为测试**
- **不要一次性写 5 个测试再一次性实现**
- 正确节奏：
  ```
  修改 ecva.py → 写 test_ecva.py 的一个 case → 验证通过 → 下一个
  修改 neurips.py → 写 test_neurips.py 的一个 case → 验证通过 → 下一个
  ```

### 3. 使用真实 HTML Fixture，不 Mock 网络

- 测试 parser 时，**直接使用真实页面的 HTML 片段作为 fixture 字符串**，不需要 mock requests
- fixture 文件放在 `tests/fixtures/` 目录，以 `{venue}_{year}.html` 命名
- 这样测试在离线状态下也能运行，且反映真实页面结构

### 4. parser 修改的标准流程

当你需要修改或新增一个 parser（如 ecva.py / neurips.py / ijcai.py）时：

```
Step 1: 阅读目标页面的真实 HTML 结构（用户通常会粘贴）
Step 2: 确认要提取的字段：title / authors / pdf_url
Step 3: 修改 parser，用精确 CSS selector（而非猜测文本长度）
Step 4: 写或更新对应测试，验证：
         - len(papers) >= min_count（至少能提取几篇）
         - 每篇有非空 title
         - authors 字段存在（如果页面有）
         - pdf_url 格式正确（如果页面有）
Step 5: 确认测试通过
```

### 5. variable source 的 Agent 流程不得跳步

`variable source` 的完整处理顺序：

```
Phase 1: 大模型联网搜索放榜 URL
  → 找不到或未放榜：记录 not_released，直接返回，不继续

Phase 2: 大模型分析页面结构 → 生成 PageCrawlPlan
  → crawl_plan 必须传递给后续的脚本生成

爬取策略（按优先级，不得跳过前面直接用后面）：
  1. 历史保存的脚本（generated_scripts.yaml）
  2. 历史保存的 rule（generated_rules.yaml）
  3. 固定 parser（generic 等）
  4. 大模型生成定制脚本（携带 crawl_plan）
     → 如果 crawl_plan.needs_detail_page=true，脚本需提取 detail_url
     → enrich 流程补全 pdf_url
  5. 兜底：大模型生成 rule
```

### 6. 生成脚本的安全约束（沙箱规则）

`dynamic_crawler.py` 的沙箱只允许以下 import：
- `re`
- `bs4` / `BeautifulSoup`
- `urllib.parse`

**禁止**：`requests`、`os`、`sys`、`subprocess`、文件 IO、任何网络操作。

大模型生成脚本时，prompt 必须明确说明这个约束。

### 7. config.yaml 的 variable source 必须有 search_query

每个 `structure_type: variable` 的来源都必须配置：
```yaml
search_query: "具体的英文搜索词，用于大模型联网搜索放榜 URL"
```

否则大模型会用默认的通用搜索词，准确率下降。

---

## 测试文件约定

```
tests/
  fixtures/           # HTML 片段文件（真实页面截取）
    ecva_2024.html
    neurips_2025.html
    ijcai_2025.html
  test_crawlers.py    # 测试各个固定 parser 的行为
  test_dynamic.py     # 测试沙箱执行和脚本安全性
  test_validate.py    # 测试 validate_papers 的边界行为
  test_integration.py # 端到端测试（使用 fixture HTML）
```

测试函数命名规则：`test_{模块}_{行为描述}`，例如：
- `test_ecva_extracts_title_authors_pdf`
- `test_neurips_pdf_url_points_to_proceedings`
- `test_sandbox_blocks_import_os`
- `test_validate_rejects_empty_list`

---

## 禁止事项

- ❌ 不得在 parser 里用文本长度猜测是否是论文标题（如旧的 `len(text) > 20`）
- ❌ 不得跳过 Phase 1/2，直接用配置中的 URL 当作放榜页（variable source）
- ❌ 不得在生成的脚本里允许网络请求
- ❌ 不得修改 config.yaml 里 stable source 的 enabled 状态（除非用户明确要求）
- ❌ 不得一次性重写所有文件，每次只改最小范围
