# 电商 SingleFile 页面 AI 相关评论提取工具

本工具用于批量处理 Chrome SingleFile 保存的电商商品页，提取普通商品评价和淘宝/天猫“问大家”，再用本地关键词规则筛选可能与 AI 信息来源有关的内容。

当前版本还可以调用已配置的 LLM，对本次提取到的评论做高速情感快判，并只对少量高价值评论做简短详析。HTML 解析、关键词规则判断和复核台都在本机运行；只有开启情感 LLM 时，才会把待分析文本提交给配置的模型服务。

## 安装

需要 Python 3.10 或更高版本。

```powershell
python -m pip install -r requirements.txt
```

开发/测试环境额外安装：
```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## 基本运行

将待处理的 `.html` / `.htm` 文件放入项目同级的 `input_html` 目录，然后运行：

```powershell
python main.py
```

默认流程会：

1. 解析 `input_html` 中的 SingleFile HTML。
2. 提取评论、问大家问题、问大家回答，并写入 `content_all`。
3. 用本地关键词和规则生成 AI 相关候选。
4. 默认对评论运行“本地规则快判 + LLM JSONL 快判 + 少量高价值详析”的情感管线。
5. 写出带时间戳的 Excel 工作簿。

如果只想离线抽取、不调用情感模型：

```powershell
python main.py --no-enable-sentiment
```

每次运行都会生成新文件，不会覆盖旧结果。默认输出文件名使用第一个输入文件的商品标题和运行时间，例如：

```text
output/明基 ScreenBar Halo 2 屏幕挂灯_20260614_183025.xlsx
```

## 常用参数

- `--input PATH`：输入 HTML 目录，默认 `./input_html`。
- `--output PATH`：输出目录，默认 `./output`；也兼容传入 `.xlsx` 路径。
- `--run-name NAME`：本次运行名称；默认取第一个输入文件的商品标题。
- `--keywords PATH`：AI 关键词 YAML 文件，默认 `./config/ai_keywords.yaml`。
- `--recursive`：递归读取输入目录下的子目录。
- `--debug` / `--no-debug`：是否输出低置信度 debug 样本，默认开启。
- `--max-files N`：最多处理前 N 个文件，便于调试。

## LLM 配置

Provider 配置示例见 `config/llm_providers.example.json`。建议复制为：

```text
config/llm_providers.local.json
```

并把真实 key 放在：

```text
config/secrets/deepseek_api_key.txt
```

`config/llm_providers.local.json` 和 `config/secrets/*` 默认不会提交到 Git。

Provider 配置中的容量字段：

- `default_batch_size`：该 provider/model 的默认请求窗口，即每次请求提交给 LLM 的内容条数。
- `timeout_seconds`：该 provider/model 的单次请求超时上限。它不是总任务目标，而是防止单个请求无限等待的保护值。
- `target_content_count`：容量校准目标的内容条数，当前目标是 `500`。
- `target_total_seconds`：容量校准目标的端到端完成时间，当前目标是 `120` 秒。
- `capacity_note`：记录这个窗口的来源、假设和适用范围，便于以后接入其他 LLM 时复核。

这些字段是按 LLM 能力配置的。DeepSeek、OpenAI-compatible 服务、本地模型网关、其他厂商模型都可以有不同窗口。

## 情感参数

- `--enable-sentiment` / `--no-enable-sentiment`：是否运行高速情感管线，默认开启。
- `--sentiment-limit N|all`：本次最多处理多少条评论，默认 `all`，即快判层覆盖全部评论。
- `--detail-limit N|all`：本次最多对多少条高价值评论做详析，默认 `50`。如需把所有高价值候选都提交详析，可使用 `--detail-limit all`。
- `--sentiment-batch-size N`：快判层每次提交给 LLM 的评论数，默认 `50`。
- `--detail-batch-size N`：详析层每次提交给 LLM 的评论数，默认 `10`。
- `--dry-run`：只跑 HTML 抽取和本地规则快判，不调用情感 LLM。
- `--sentiment-only` / `--force-reprocess-sentiment`：为未来数据库工作流保留；当前离线 Excel 工作流只处理本次运行的内容。
- `--llm-provider NAME`：provider 配置名，默认 `deepseek`。
- `--llm-config PATH`：本地 provider 配置文件，默认 `./config/llm_providers.local.json`。
- `--llm-api-key-file PATH`：API key 文件路径；会覆盖 provider 配置里的 key 文件。
- `--llm-model NAME`：模型名；为空时使用 provider 配置里的 `default_model`。
- `--llm-timeout N`：临时覆盖单次 LLM 请求超时时间。

### 旧版结构化详析参数

旧版 `llm_review_analysis` / `llm_praise_items` / `llm_complaint_items` 仍可显式运行，但不再默认开启：

- `--llm-analyze`：运行旧版重型结构化详析。
- `--prompt-version VERSION`：prompt 版本，默认 `v1`。
- `--llm-limit N|all`：最多分析前 N 条目标内容；用于小批量试跑和调试，默认 `all`。
- `--llm-batch-size N`：临时覆盖“每次请求提交给 LLM 的内容条数”。不传时使用当前 provider/model 在 `config/llm_providers.local.json` 中配置的容量窗口。
- `--llm-retry-delays "1,3"`：请求失败后的重试等待秒数，默认 `1,3`，表示初次尝试后最多再重试两次。
- `--llm-dry-run`：只统计 LLM 目标内容数，不实际调用 API。
- `--llm-skip-existing` / `--no-llm-skip-existing`：是否跳过本次运行内重复的输入 hash，默认跳过。

### 每次请求提交给 LLM 的内容条数从哪里来

这个数不是从 Excel 自动推断出来的，也不是所有 LLM 共用的固定值。它是针对具体 provider/model 的容量窗口配置，目标是满足同一条使用体验要求：

- 目标体验：端到端约 `120` 秒内完成 `500` 条内容的旧版结构化详析。新情感快判应显著更快，因为输出 token 被限制为极简 JSONL。
- 端到端时间包括：把内容传给 LLM、LLM 生成、回传、脚本解析 JSON、校验、错误处理、整理结果和写入 Excel。
- 不同 LLM 的上下文窗口、输出速度、JSON 稳定性、限流和网络表现不同，所以窗口容量必须按 provider/model 单独校准。
- 当前 DeepSeek 的容量窗口写在 `config/llm_providers.local.json` 的 `providers.deepseek.default_batch_size` 中；同一 provider/model 的单次请求保护超时写在 `providers.deepseek.timeout_seconds` 中。

命令行参数 `--llm-batch-size` 只用于临时覆盖这个容量配置，例如单条调试、降低失败率或做新模型试验；它不是默认窗口来源。

当前代码路径是：

1. `main.py` 先从 `content_all` 中选择有 `content_text_clean` 正文的目标内容。
2. `--llm-limit` 如果存在，会先截断目标内容总数。
3. `main.py` 读取 `--llm-provider` 指向的 provider/model 配置。
4. 默认窗口来自该 provider 配置的 `default_batch_size`，这个值应当是围绕“500 条 / 120 秒端到端完成”目标校准出来的。
5. 如果显式传入 `--llm-batch-size N`，则用命令行参数临时覆盖 provider 配置。
6. 显式传入 `--llm-analyze` 时，`main.py` 调用 `LLMCommentAnalysisService.analyze_comments(..., batch_size=解析后的窗口容量)`。
7. service 内部按这个 batch size 累积内容；满一批就发一次 LLM 请求，最后不足一批的剩余内容会单独发一请求。

因此，实际每次请求条数通常是 provider/model 配置的 `default_batch_size`，或你显式传入的 `--llm-batch-size`，最后一批可能更少。比如目标内容 `563` 条、DeepSeek 当前窗口 `50` 时，会发约 `12` 次请求：前面每次 50 条，最后一次 13 条。

调参建议：

- 调试问题时用 `--llm-batch-size 1`，失败定位最清楚。
- 日常运行不传 `--llm-batch-size`，让程序使用 provider/model 已校准窗口。
- 新接入其他 LLM 时，先用小窗口试跑，再根据“500 条 / 120 秒端到端完成”的目标调整该 provider 的 `default_batch_size` 和 `timeout_seconds`。
- 如果模型输出 JSON 很稳定、评论较短，可以调大该 provider 的窗口；如果出现 `batch result item count mismatch`、JSON 不完整、超时或失败率升高，调小窗口或提高该 provider 的 `timeout_seconds`。

## 情感分类的缘由与说明

原来的关键词规则主要回答“这条内容是否可能体现 AI 对购前决策的影响”。它不擅长回答另一个问题：消费者到底在夸什么、怎么夸，或者在吐槽什么、怎么吐槽。

因此新增高速情感管线，目标不是让模型为每条评论写长解释，而是把全量评论先压缩成可统计的短标签，再只对少量高价值评论补充证据和 GEO 内容价值：

- `sentiment_fast`：全量快判结果，包含情感标签、情感分数、主要夸法 code、主要骂法 code 和置信度。
- `sentiment_detail`：少量高价值评论详析，包含证据句、判断原因和 GEO 内容价值。
- `sentiment_summary`：情感分布、规则命中量、LLM 快判量、详析量和失败量。
- `sentiment_failures`：JSONL 解析失败、缺失结果或 API 错误。

这样设计的原因：

- 许多评论是混合情绪，例如“光线柔和，但底座占地方”，需要稳定标成 `M`。
- 客服、物流、安装体验常常会混入好评，但不一定代表商品本身好。
- “不错、满意”这类泛泛表达情绪明确，但业务证据弱。
- “孩子写作业两小时不刺眼”这类表达可能语气平淡，但对购前决策很有价值。
- 极简 code 输出可以把 50 条评论的输出控制在约 2500 tokens，而不是旧方案的约 20000 tokens。

证据强度不是情绪强度。比如“垃圾，千万别买”情绪很强，但如果没有具体原因，证据可能较弱；“透明桌垫会反光”语气平，但证据更具体。

### 高速情感新规则

情感处理分两层：

- 快判层：优先用本地规则处理低信息短评；规则不放心的评论进入 LLM 快判。LLM 每条评论只输出一行 JSONL：`i/s/sc/p/n/c`。
- 详析层：只有负向、混合、低置信、AI 相关、长评论或含决策关键词的高价值评论进入详析。详析每条评论只输出 `i/e/r/g`。

快判 code：

- 情感：`P` 正向，`N` 负向，`M` 混合，`Z` 中性。
- 夸法：`F` 功能效果，`S` 使用场景，`E` 体验舒适，`O` 外观质感，`I` 安装使用，`V` 服务物流，`C` 对比胜出，`P$` 性价比接受，`B` 品牌信任，`D` 决策安心，`-` 无。
- 骂法：`F` 核心功能不满，`S` 场景不适配，`E` 体验不适，`O` 外观做工问题，`I` 安装使用麻烦，`V` 服务物流问题，`Q` 品控故障，`P$` 价格不值，`G` 宣传落差，`R` 后悔退换，`-` 无。

快判层禁止输出中文解释、证据句、Markdown 或 pretty JSON；如果 JSONL 解析失败或缺失评论，会重试一次，仍失败则写入 `sentiment_failures`，不污染结果表。

## 常用示例

```powershell
# 纯本地离线抽取，不调用大模型
python main.py --no-enable-sentiment

# 只跑本地规则快判，不调用情感 LLM
python main.py --sentiment-limit 100 --dry-run

# 正式小批量情感快判，最多 100 条评论、10 条详析
python main.py --sentiment-limit 100 --detail-limit 10

# 调整快判和详析批量
python main.py --sentiment-batch-size 100 --detail-batch-size 20

# 显式运行旧版重型结构化详析
python main.py --llm-analyze --llm-limit 20 --llm-batch-size 1
```

## 输出表格

运行后检查：

- `output/运行名_YYYYMMDD_HHMMSS.xlsx`
- `output/run.log`

优先查看以下 Sheet：

- `ai_candidates`：AI 相关候选及判定理由。
- `content_all`：全部提取内容，包括评论、问题和回答。
- `qa_pairs_raw`：问大家原始配对。
- `reviews_raw`：评论原始结构。
- `summary_by_month`：按评论月份统计 AI 相关变化趋势。
- `sentiment_run_summary`：高速情感管线运行状态、规则命中量、LLM 快判量、详析量和失败量。
- `sentiment_fast`：全量评论快判标签、分数、主要夸法、主要骂法和置信度。
- `sentiment_detail`：少量高价值评论的证据句、判断原因和 GEO 内容价值。
- `sentiment_summary`：情感分布和处理量汇总。
- `sentiment_failures`：情感 JSONL 解析失败、缺失结果或 API 错误。
- `sentiment_timings`：快判和详析请求耗时、token、批量大小。
- `llm_*`：旧版重型结构化详析输出，仅显式传入 `--llm-analyze` 时有内容。
- `errors`：单文件错误，不会中断整个批次。
- `debug_samples`：无法稳定配对的问答样本。

## 本地 AI 影响识别规则

- 豆包、DeepSeek、ChatGPT、Kimi、通义千问等为明确 AI 来源词。
- 支持词内空格写法，例如 `Deep Seek`、`Chat GPT`。
- `AI` / `ai` 使用英文边界与上下文规则，`air`、`chair`、`pair`、`rain` 不会被误判。
- `推荐`、`比较`、`选择`、`值不值` 等普通购前决策词不会单独触发 A/B；只有高强度调研行为才会进入 C。
- `比较满意`、`比较适合`、`光比较柔和`、`推荐给大家`、`问客服比较细` 等普通消费表达会判为 D 或非 AI 候选。
- A/B/C/D 是“AI 影响可能性等级”：A 为明确具体 AI，B 为泛 AI / 算法入口，C 为高强度购前调研下的 AI 介入可能，D 为普通购前决策分母。
- 不要把 A+B+C 统一表述为“已确认 AI 影响”；A/B 是明确入口证据，C 需要人工复核。
- v1.4 起，买后体验、价格赔付争议、商家回复、买后体验对比不进入 A-D，也不会被标成 D。

## 注意事项

SingleFile 只能保存当时页面已经加载到 DOM 中的内容。运行前应在页面中打开评论或“问大家”区域，并滚动或展开需要保存的内容。

复核台的“调试与错误 → 平台质量提示”会自动标出“评论极少、问大家很多”的页面。这通常说明评论区只保存了少量预览卡片；应重新打开评论区、滚动加载后再次保存，而不是把当前提取量当作完整评论池。

## 启动前端

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

运行：

```powershell
.\start_ui.ps1
```

如需给大陆客户机或同一局域网内其他电脑访问，请使用中文访问入口：

```powershell
.\install_deps_cn.ps1
.\start_ui_cn.ps1
```

打开浏览器后，上传脚本输出的 Excel 文件，或直接选择 `output` 目录中的历史 `.xlsx` 文件，即可浏览分析结果。

注意：

- 前端只读取 Excel，不重新解析 HTML。
- 前端不联网，不调用大模型。
- 人工复核结果保存在 `output/review_feedback.csv`。
