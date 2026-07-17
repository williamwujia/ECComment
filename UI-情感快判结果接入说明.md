# UI 情感快判结果接入说明

## 当前状态

项目已经把默认情感处理从“全量长文本结构化详析”切换为“高速快判 + 少量详析”。

默认运行 `python main.py` 时：

1. 解析 `input_html` 中的电商 SingleFile HTML。
2. 输出原有 `content_all`、`ai_candidates`、`reviews_raw` 等 sheet。
3. 默认运行新情感管线 `--enable-sentiment`。
4. 对评论做本地规则快判。
5. 对规则不放心的评论调用 LLM JSONL 快判。
6. 对少量高价值评论调用 LLM 详析。
7. 写入新增 sentiment 系列 sheet。

旧版重型 LLM 结构化详析仍保留，但默认关闭。只有显式传入 `--llm-analyze` 时，`llm_review_analysis`、`llm_praise_items`、`llm_complaint_items` 等旧 sheet 才会有内容。

## 推荐 UI 优先接入的 Sheet

### 1. sentiment_fast

这是 UI 最应该优先使用的全量情感结果表，一条评论一行。

字段：

| 字段 | 含义 | UI 建议 |
|---|---|---|
| `content_id` | 评论在本次工作簿里的 ID | 用来和 `content_all.content_id` join |
| `content_hash` | 评论内容 hash | 可用于去重/稳定匹配 |
| `source_file` | 来源 HTML 文件 | 可作为筛选项 |
| `platform` | 平台 | 可作为筛选项 |
| `product_title` | 商品标题 | 商品维度展示 |
| `sku` | SKU | 可作为筛选项 |
| `content_text_clean` | 评论正文 | 评论列表主文本 |
| `sentiment_label` | 情感标签 code：`P/N/M/Z` | 用于筛选和统计 |
| `sentiment_label_cn` | 中文情感：正向/负向/混合/中性 | UI 展示优先用这个 |
| `sentiment_score` | 情感分数，1-10 | 可做均分、色阶、排序 |
| `praise_code` | 主要夸法 code | 用于统计 |
| `praise_cn` | 主要夸法中文 | UI 展示优先用这个 |
| `complaint_code` | 主要骂法 code | 用于统计 |
| `complaint_cn` | 主要骂法中文 | UI 展示优先用这个 |
| `sentiment_confidence` | 置信度：1低/2中/3高 | 低置信建议打标或进入复核 |
| `sentiment_source` | `rule` 或 `llm_fast` | 可展示处理来源 |

情感标签：

| code | 中文 |
|---|---|
| `P` | 正向 |
| `N` | 负向 |
| `M` | 混合 |
| `Z` | 中性 |

UI 展示建议：

- 列表默认显示：`sentiment_label_cn`、`sentiment_score`、`praise_cn`、`complaint_cn`、`sentiment_confidence`。
- 情感筛选：正向、负向、混合、中性。
- 重点复核筛选：`sentiment_label in ["N", "M"]` 或 `sentiment_confidence == 1`。
- AI 相关情感视图：用 `content_id` join `ai_candidates` 或 `content_all`，筛选 `ai_candidate = True` 后看情感分布、夸法/骂法分布。

### 2. sentiment_detail

这是少量高价值评论的短详析表，不是全量表。

字段：

| 字段 | 含义 | UI 建议 |
|---|---|---|
| `content_id` | 评论 ID | 和 `sentiment_fast` / `content_all` join |
| `content_hash` | 评论 hash | 辅助匹配 |
| `content_text_clean` | 评论正文 | 展示上下文 |
| `sentiment_evidence` | 关键证据句 | 详情区高亮展示 |
| `sentiment_reason` | 判断原因，短文本 | 详情区展示 |
| `geo_value` | GEO 内容价值 | 可作为内容机会提示 |

进入详析的条件包括：负向、混合、低置信、AI 相关、长评论、含买前决策关键词等。因此 UI 不应假设每条评论都有详析。

UI 展示建议：

- 在评论详情面板中，如果能按 `content_id` 找到 `sentiment_detail`，展示“证据句 / 判断原因 / GEO 内容价值”。
- 可新增“高价值评论”视图，只展示 `sentiment_detail` 中出现的评论。

### 3. sentiment_summary

情感统计汇总表。

字段：

| 字段 | 含义 |
|---|---|
| `metric` | 指标名 |
| `label` | 可选中文标签 |
| `value` | 指标值 |

当前典型指标：

- `total_count`
- `rule_count`
- `llm_fast_count`
- `detail_count`
- `failed_count`
- `elapsed_seconds`
- `sentiment_P`
- `sentiment_N`
- `sentiment_M`
- `sentiment_Z`

UI 展示建议：

- 顶部 KPI：总处理评论数、规则处理数、LLM 快判数、详析数、失败数。
- 情感占比图：`sentiment_P/N/M/Z`。
- 平均情感分建议直接从 `sentiment_fast.sentiment_score` 计算。

### 4. sentiment_run_summary

本次情感管线运行状态。

字段：

| 字段 | 含义 |
|---|---|
| `enabled` | 是否启用新情感管线 |
| `status` | `success` / `partial` / `failed_to_start` / `disabled` |
| `message` | 运行摘要 |
| `target_review_count` | 目标评论数 |
| `rule_count` | 本地规则处理数 |
| `llm_fast_count` | LLM 快判成功数 |
| `detail_count` | 详析成功数 |
| `failed_count` | 失败数 |
| `sentiment_limit` | 本次快判上限 |
| `detail_limit` | 本次详析上限 |
| `sentiment_batch_size` | 快判批量大小 |
| `detail_batch_size` | 详析批量大小 |
| `dry_run` | 是否 dry run |
| `elapsed_seconds` | 情感管线耗时 |

UI 展示建议：

- 在数据健康/运行信息区域展示。
- 如果 `status != success`，提示用户查看 `sentiment_failures`。

### 5. sentiment_failures

情感处理失败表。

字段：

| 字段 | 含义 |
|---|---|
| `stage` | `sentiment_fast` 或 `sentiment_detail` |
| `content_id` | 评论 ID |
| `content_hash` | 评论 hash |
| `content_text_clean` | 评论正文 |
| `error_type` | 错误类型 |
| `error_message` | 错误信息 |
| `raw_response` | 原始模型响应 |

UI 展示建议：

- 可做一个“处理失败”折叠区。
- 默认不影响主情感列表。

### 6. sentiment_timings

情感 LLM 请求耗时表。

字段包括：

- `scope`：`sentiment_fast` 或 `sentiment_detail`
- `batch_size`
- `attempt`
- `status`
- `total_seconds`
- `response_read_seconds`
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `max_tokens`
- `finish_reason`
- `content_ids`

UI 展示建议：

- 用于调试和性能面板。
- 不是普通用户主视图必需字段。

## 和旧 LLM Sheet 的关系

旧 sheet：

- `llm_run_summary`
- `llm_review_analysis`
- `llm_praise_items`
- `llm_complaint_items`
- `llm_failures`
- `llm_request_timings`

这些是旧版“全量结构化详析”输出，默认不再生产内容。

UI 处理建议：

1. 新 UI 优先使用 `sentiment_*`。
2. 如果旧 `llm_*` sheet 有内容，可以作为“旧版详析/兼容数据”展示。
3. 不要再把 `llm_review_analysis` 作为默认情感数据源。

## 推荐 UI 信息架构

### 概览页

- 总评论数：`sentiment_summary.total_count`
- 正向/负向/混合/中性占比：`sentiment_summary.sentiment_P/N/M/Z`
- 平均情感分：从 `sentiment_fast.sentiment_score` 计算
- 规则处理占比：`rule_count / total_count`
- LLM 快判占比：`llm_fast_count / total_count`
- 详析评论数：`detail_count`
- 失败数：`failed_count`

### 评论列表

数据源：`sentiment_fast` join `content_all`。

推荐列：

- 评论正文
- 情感
- 情感分数
- 主要夸法
- 主要骂法
- 置信度
- 处理来源
- AI 候选等级（从 `content_all` 或 `ai_candidates` join）

推荐筛选：

- 情感：正向/负向/混合/中性
- 夸法
- 骂法
- 低置信
- AI 候选
- 高价值详析存在

### 高价值评论页

数据源：`sentiment_detail` join `sentiment_fast`。

推荐展示：

- 评论正文
- 情感标签与分数
- 证据句
- 判断原因
- GEO 内容价值
- AI 候选信息

### AI 相关情感页

数据源：`sentiment_fast` join `content_all` 或 `ai_candidates`。

推荐指标：

- AI 相关评论中的情感分布
- AI 相关评论中的夸法分布
- AI 相关评论中的骂法分布
- AI 相关高价值评论列表

## 重要实现注意

1. `sentiment_detail` 不是全量表，不能用它代表整体情感分布。
2. `sentiment_fast.content_id` 是当前工作簿内的行级 ID，可和 `content_all.content_id` join。
3. `sentiment_label_cn`、`praise_cn`、`complaint_cn` 已经给出中文展示，UI 不需要重复维护字典，除非要做本地化。
4. `sentiment_source=rule` 表示没有调用 LLM，属于正常快判结果。
5. `dry_run=True` 时只会有本地规则结果，`llm_fast_count` 和 `detail_count` 通常为 0。
6. 旧 `llm_*` sheet 可能为空，这是新默认行为，不是错误。

## 当前验证结果

当前测试状态：

```text
42 passed, 19 subtests passed
```

当前 input 目录样例 dry run：

```text
Sentiment target review rows: 50
rule=10; llm_fast=0; detail=0; failed=0
```

正式运行 50 条情感快判示例：

```powershell
.\.venv\Scripts\python.exe main.py --sentiment-limit 50 --detail-limit 10 --no-llm-analyze
```

只跑本地规则、不调用模型：

```powershell
.\.venv\Scripts\python.exe main.py --sentiment-limit 50 --dry-run --no-llm-analyze
```
