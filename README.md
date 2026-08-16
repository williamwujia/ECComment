# 电商消费者反馈洞察与持续追踪

这是一个面向淘宝、天猫和京东评论数据的本地分析工具。它可以从 SingleFile
网页或京东采集 CSV 中提取消费者反馈，按平台和商品隔离数据，持续增量去重，
并生成 AI 影响识别、情绪分析、质量检查和品牌看板。

项目提供三种工作方式：

- **持续追踪模式（推荐）**：每个项目使用独立 Excel 工作簿，可反复导入新快照、
  查看变化，并安全移除错误更新。
- **一次性分析模式**：批量解析 `input_html` 中的网页，生成带时间戳的独立
  Excel 结果。
- **评论图片剥离模式**：从 SingleFile 中保存买家原评图与追评图，累计维护
  SQLite、每商品图片索引 Excel，并生成现有跟踪器可导入的纯文字 CSV。

## 当前能力

- 解析淘宝、天猫等平台由 Chrome SingleFile 保存的商品页面。
- 通过本地 Chrome 扩展批量采集京东“全部评价 → 最新”评论。
- 导入包含多个商品的京东 CSV，并按 `platform + product_id` 自动拆分。
- 在 `project_id + item_key` 范围内增量去重，不让不同商品串库。
- 本地识别 AI 影响线索，并按 A–D 证据等级汇总。
- 对评论执行情绪快判及高价值评论详析。
- 提供品牌看板、商品对比、原文查看、质量日志和待复核队列。
- 更新前预览影响，写入时自动备份并采用原子方式保存工作簿。
- 从“最近快照”预览删除影响、明确确认并回退错误更新。
- 把 SingleFile 内嵌的评论图片按“平台 → 商品 → 评论 → 原评/追评”剥离，
  支持重复导入、增量追评/图片和整批撤销，不联网补抓缺图。

## 环境要求与安装

- Windows
- Python 3.10 或更高版本
- Chrome（京东采集需要）

```powershell
python -m pip install -r requirements.txt
```

如需运行测试：

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## 快速开始

启动本机界面：

```powershell
.\start_ui.ps1
```

脚本默认从端口 `8501` 开始查找可用端口。如果端口已被占用，会自动使用下一个
可用端口，并在终端显示实际访问地址。

只使用评论图片剥离工具时，双击 `启动_图片剥离.bat`，或运行：

```powershell
.\start_review_assets.ps1
```

该入口只监听本机 `127.0.0.1`，并为大型 SingleFile 将单次上传上限设为 500 MB。

需要让同一局域网内的其他电脑访问时：

```powershell
.\install_deps_cn.ps1
.\start_ui_cn.ps1
```

终端会分别显示本机地址和局域网访问地址。也可以指定起始端口：

```powershell
.\start_ui.ps1 -Port 8600
.\start_ui_cn.ps1 -Port 8600
```

## 界面结构

### 评论图片剥离

1. 启动 `start_review_assets.ps1`，设置长期使用的资产库根目录。
2. 一次选择多个淘宝、天猫或京东 SingleFile HTML。
3. 点击“解析并预览”，核对并可修改平台、商品 ID、评论数、图片数和状态。
4. 点击“确认入库”后才写入 SQLite、图片、商品 Excel 和纯文字 CSV。
5. 处理完成后点击“导出本次图片包”，选择导出目录，获得一份可独立移动的
   `图片目录.xlsx + images/`。
6. 在“批次与撤销”中可撤销本工具记录的批次；若同一商品存在更晚批次，必须
   先撤销较晚批次，避免破坏后续增量状态。

默认资产库是项目目录下的 `ReviewAssets`：

```text
ReviewAssets/
├─ review_assets.db
└─ products/<platform>_<product_id>/
   ├─ reviews/<local_review_id>/review_01.jpg
   ├─ <platform>_<product_id>.xlsx
   └─ downstream_reviews.csv
```

图片只从 SingleFile 已实际保存的数据中解码；远程 URL 不会被访问。缺图会保留
索引并产生警告。`downstream_reviews.csv` 不含图片字段，可在维护后台作为现有
评论 CSV 继续导入。

“本次图片包”按 `batch_id` 导出该批次识别到的原评图和追评图。即使图片此前已
入库、该批新增图片数为 0，导出包仍包含图片与评论目录；Excel 会单独标记哪些是
本批新增、哪些是历史图片。包内 Excel 固定包含 `summary`、`reviews`、`images`
三个 Sheet；`images` 的“查看图片”列使用指向包内 `images/` 的相对超链接，因此
整个文件夹移动或复制到其他电脑后仍可使用。撤销入库不会删除已经导出的外部图片包。

### 品牌看板

品牌看板是只读入口，用于查看：

- 淘宝/天猫商品评论、问大家问题和回答；
- 全部来源的内容总量及淘宝、天猫、京东来源分布；
- 情绪分类、AI 影响 A–D 分级和证据覆盖；
- 评论原文、商品对比和趋势汇总。

注意统计口径：前三项反馈规模只统计淘宝和天猫；“全部内容”包含所有已导入
来源，界面会同时展示各平台的内容数量。

### 维护后台

维护后台包含以下页面：

- **数据更新**：上传 SingleFile HTML 或京东评论 CSV，预览并确认写入。
- **项目状态**：查看商品、内容和最近快照，也可回退错误更新。
- **数据质量与日志**：查看 fallback、警告、失败、页面快照和更新日志。
- **待复核队列**：处理身份信息不足的疑似重复内容。
- **扩展分析**：检查情绪快判、详析、失败及 LLM 运行摘要。
- **使用说明**：在界面内查看日常操作提示。

在项目选择框中选择“＋ 新建项目”，填写项目名称和可选目标即可创建独立项目
工作簿，创建后系统会自动切换到新项目。

## 持续更新数据

1. 打开“维护后台 → 数据更新”。
2. 选择已有项目，或先新建项目。
3. 上传一个或多个 `.html`、`.htm` 或 `.csv` 文件。
4. 保持平台为“自动识别”，除非确实需要手动指定。
5. 检查预览中的商品 ID、提取量、预计新增量、重复量和边界状态。
6. 确认无误后执行写入。

预览不会调用 LLM，也不会修改工作簿。正式更新会先处理文件、分析新增内容，
再安全写回项目工作簿。

情绪详析覆盖率在维护后台固定显示为 **100%**。这不是仅修改界面文案：所有
符合详析条件的高价值评论都会进入详析流程，不再存在隐藏的条数上限。启用
LLM 时，请留意调用成本和处理时间。

## 回退错误更新

错误文件写入后无需手工修改 Excel：

1. 打开“维护后台 → 项目状态”。
2. 在“最近快照”表格中单击要移除的快照。
3. 查看该快照内容数、当时新增数、将彻底移除的内容数及删除后剩余快照数。
4. 勾选确认框。
5. 点击“移除所选快照”。

回退时系统会：

- 先备份项目工作簿；
- 删除目标快照及仅由它产生的内容和分析结果；
- 保留仍出现在其他快照中的内容；
- 重新计算首次/最后出现时间、活跃状态和商品当前信息；
- 重建看板兼容表和相关汇总。

如果剩余快照缺少必要的内容明细，系统会拒绝写入，避免在信息不完整时破坏项目
数据。删除商品唯一快照时，该商品记录也会从项目中移除。

## 京东评论采集

推荐使用 `chrome_extension` 中的本地 Chrome 扩展。它使用日常 Chrome 的现有
登录会话，不读取密码、验证码或支付信息。

### 安装扩展

1. 打开 `chrome://extensions`。
2. 开启“开发者模式”。
3. 点击“加载已解压的扩展程序”。
4. 选择本项目的 `chrome_extension` 文件夹。
5. 登录京东并固定“京东评论采集器”扩展。

扩展代码更新后，需要在扩展管理页点击一次“刷新”，并刷新已打开的京东商品页。

### 批量采集

在扩展中每行输入一个 `商品 URL,目标数量`：

```text
https://item.jd.com/13745188.html,20
https://item.jd.com/100244103673.html,50
```

扩展会逐个商品执行：

1. 打开商品页；
2. 进入“全部评价”；
3. 切换到“最新”；
4. 滚动评论弹层而不是商品主页面；
5. 采集昵称、星级、时间、商品名、SKU 和评论正文；
6. 达到目标后继续下一个商品；
7. 到底后连续多次没有新评论时，记录实际数量和未达标状态并继续队列。

队列和采集结果保存在 `chrome.storage.local`，扩展后台被 Chrome 暂停后仍可恢复。
全部完成后会下载 UTF-8 CSV，并逐商品报告目标数、实际数和短缺情况。

### 导入京东 CSV

CSV 至少需要以下列：

- `platform`
- `product_id`
- `review_text_raw`

扩展还会输出 `product_url`、`product_title`、`user_name_masked`、`rating`、
`review_time` 和 `sku`。一个 CSV 可以包含多个商品，导入器会按
`platform + product_id` 拆分为独立快照，并使用 `jd:<商品ID>` 作为商品键。

为避免页面组件污染商品资料，错误标题“最小单价计算器”不会覆盖项目中的商品名。

## 一次性分析

将 SingleFile `.html` 或 `.htm` 文件放入 `input_html`，然后运行：

```powershell
python main.py
```

仅做本地抽取、不调用情绪模型：

```powershell
python main.py --no-enable-sentiment
```

也可以一键执行抽取并启动旧版复核台：

```powershell
.\run_pipeline_and_ui.ps1
```

该脚本同样会从 `8501` 开始自动寻找可用端口。常用参数：

```powershell
python main.py `
  --input .\input_html `
  --output .\output `
  --run-name "本次分析" `
  --recursive
```

每次运行生成新的带时间戳工作簿，不覆盖旧结果。旧版一次性复核台也可单独启动：

```powershell
python -m streamlit run review_app.py
```

## LLM 配置

复制示例配置：

```powershell
Copy-Item `
  .\config\llm_providers.example.json `
  .\config\llm_providers.local.json
```

把 API Key 写入：

```text
config/secrets/deepseek_api_key.txt
```

本地 provider 配置和 `config/secrets/*` 默认不会提交到 Git。只有启用 LLM
情绪处理或旧版结构化分析时，待分析文本才会发送给配置的模型服务；HTML 解析、
规则判断、预览和看板读取均在本地完成。

一次性模式的情绪参数可通过以下命令查看：

```powershell
python main.py --help
```

## 命令行持续追踪

除界面外，也可以通过 `app.py` 管理项目：

```powershell
python app.py init-project --help
python app.py update --help
python app.py reanalyze --help
python app.py backfill-sentiment --help
```

典型的安全更新流程是先预览，再用相同参数正式执行：

```powershell
python app.py update `
  --workbook ".\projects\消费者反馈追踪.xlsx" `
  --project-id "consumer_feedback" `
  --file ".\input_html\product_20260726.html" `
  --dry-run
```

去掉 `--dry-run` 后才会正式写入。更完整的命令行示例见
[持续追踪使用说明](持续追踪使用说明.md)。

## 数据与安全

- `projects` 中的工作簿是持续追踪项目的核心数据，请纳入备份。
- 正式更新和快照回退会先创建备份，再原子写入。
- 不要把真实 API Key、用户隐私数据或包含敏感信息的原始页面提交到 Git。
- SingleFile 只能保存当时已加载进 DOM 的内容；采集前应展开并滚动需要保存的
  评论或问答区域。
- 京东页面结构变化时，应先验证评论弹层和滚动容器，再调整采集逻辑。

## 测试

运行全部测试：

```powershell
python -m pytest -q
```

与本次更新最相关的测试：

```powershell
python -m pytest -q tests/test_tracking.py tests/test_tracker_metrics.py
```
