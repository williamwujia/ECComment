# 电商评论 AI 影响力浏览与复核台

## 前端开发指南 - Codex 版

版本：v0.1  
用途：直接交给 Codex，为现有 `ecommerce_ai_comment_extractor` 项目增加本地前端。  
核心目标：把现有 Excel 输出变成可浏览、可筛选、可复核、可截图的工作台。  
当前边界：只做前端浏览与人工复核，不扩展“购买决策来源归因”。

---

## 1. 项目背景

现有项目已经完成：

```text
本地 SingleFile HTML
→ 平台识别
→ 商品信息提取
→ 评论 / 问大家 / 大家评提取
→ 文本清洗
→ 去重
→ 购前决策标注
→ AI 候选规则筛选
→ 证据等级 A/B/C/D
→ 多 Sheet Excel 输出
```

现在的问题是：

```text
Excel 可以保存结果，但不方便浏览、筛选、复核、截图和迭代规则。
```

因此，本次开发不是重做分析逻辑，而是在现有 Excel 输出之上增加一个本地前端。

---

## 2. 核心方法口径

前端必须始终围绕两级分类展示结果：

```text
全部评论 / 问答
├─ 使用体验型内容
│  └─ 不作为 AI 影响判断的主要分母
│
└─ 前置购买决策型内容
   ├─ AI 相关候选：A/B/C
   └─ 非 AI 相关：D，但仍保留在购前决策母集
```

关键原则：

```text
pre_purchase_decision ≠ ai_candidate
```

解释：

- `pre_purchase_decision` 表示这条内容是否在解释购买前决策，例如怎么选、值不值、怕踩坑、做攻略、买前问客服、比较几款。
- `ai_candidate` 表示这条内容是否可能出现 AI 信息入口，例如豆包、DeepSeek、ChatGPT、AI 助手、AI 搜索、智能问答、算法推荐、系统推荐。
- 一条内容可以属于购前决策母集，但不是 AI 候选。
- D 级内容不进入 AI 候选，但可以进入购前决策母集。

前端展示时必须同时展示两个比例：

```text
AI 候选 / 全部内容
AI 候选 / 购前决策内容
```

第二个比例更重要，因为普通评论主要是使用体验，不是购买理由。

---

## 3. 本次开发目标

新增一个本地前端工具，暂定名：

```text
电商评论 AI 影响力浏览与复核台 v0.1
```

目标：

1. 读取现有脚本输出的 Excel 文件。
2. 展示核心统计口径。
3. 浏览购前决策评论。
4. 浏览 AI 候选强案例。
5. 查看全部内容，方便追溯和排查。
6. 查看商品汇总、关键词汇总、debug 与 errors。
7. 支持人工复核，但不覆盖原始 Excel。
8. 人工复核结果另存为 CSV。

---

## 4. 明确不做什么

第一版不要扩展功能边界。

不要做：

```text
1. 不做购买决策来源全分类。
2. 不区分朋友、家人、客服、达人、小红书、抖音、搜索等影响来源。
3. 不调用大模型。
4. 不重新解析 HTML。
5. 不联网。
6. 不访问淘宝、京东或任何外部网站。
7. 不做账号系统。
8. 不做云端部署。
9. 不做数据库。
10. 不做复杂权限。
11. 不自动生成正式客户报告。
12. 不直接修改原始 Excel。
```

原因：

```text
当前重点是把“评论 → 购前决策母集 → AI 候选 → A/B/C 证据”这条链路看清楚。
```

---

## 5. 技术路线

第一版使用 Streamlit。

理由：

```text
1. 现有项目是 Python 体系。
2. 现有输出是 Excel。
3. Streamlit 适合快速做本地数据浏览工具。
4. 不需要后端服务、不需要数据库、不需要登录。
5. 后续如果要产品化，再升级 React + FastAPI。
```

运行方式建议：

```bash
streamlit run app.py
```

用户在前端上传或选择 Excel 文件。

---

## 6. 新增目录结构

请在现有项目中增加以下文件：

```text
ecommerce_ai_comment_extractor/
  app.py
  ui/
    __init__.py
    data_loader.py
    filters.py
    cards.py
    charts.py
    feedback.py
    tables.py
    export.py
    styles.py
  output/
    review_feedback.csv
```

如果现有项目没有 `ui/` 文件夹，请新建。

---

## 7. 依赖更新

在 `requirements.txt` 增加：

```text
streamlit
plotly
```

优先使用：

- `streamlit`：页面与交互。
- `pandas`：读取 Excel 与筛选。
- `plotly`：漏斗图、横向柱状图。
- `openpyxl`：读取 xlsx。

不要引入过重依赖。

---

## 8. 数据输入

前端只读取现有 Excel 文件。

必须支持以下 Sheet：

```text
content_all
ai_candidates
pre_purchase_details
summary_by_product
summary_by_keyword
errors
debug_samples
```

可以支持但第一版不强依赖：

```text
reviews_raw
qa_pairs_raw
jd_review_tags
```

如果某个 Sheet 不存在：

```text
1. 不要报错中断。
2. 页面显示提示：该 Sheet 不存在。
3. 继续展示其他 Sheet。
```

---

## 9. 数据加载要求

实现：

```python
load_excel(path_or_file) -> dict[str, pd.DataFrame]
```

要求：

1. 返回一个字典，key 为 sheet 名，value 为 DataFrame。
2. 自动检查核心 Sheet 是否存在。
3. 自动补齐缺失字段，防止页面崩溃。
4. 所有文本字段填充为空字符串。
5. 布尔字段兼容 True/False、TRUE/FALSE、1/0、是/否。
6. evidence_level 统一转为大写 A/B/C/D。
7. 如果 Excel 为空或格式错误，前端显示清晰错误提示。

建议核心字段：

```text
content_id
record_type
source_file
platform
product_title
shop_name
product_url
product_id
content_role
content_text_raw
content_text_clean
parent_text_clean
sku
user_name_masked
user_status
content_order
content_hash
pre_purchase_decision
pre_purchase_terms
pre_purchase_reason
ai_candidate
ai_candidate_gate_reason
ai_source_terms
ai_action_terms
purchase_context_terms
decision_context_terms
matched_keywords
matched_sentence
match_score
evidence_level
evidence_reason
excluded_by_rule
exclude_reason
extract_confidence
```

---

## 10. 全局界面风格

界面气质：

```text
Notion + 轻量 BI + 审核后台
```

不要做成炫酷数据大屏。

整体要求：

```text
白底 / 浅灰底
黑灰文字
少量强调色
卡片式内容
表格 + 详情
图表小而清楚
高密度但不拥挤
```

颜色建议：

```text
主色：深蓝 / 靛蓝，用于 AI 候选、主按钮
辅助色：灰色，用于普通信息
提醒色：橙色，用于 C 级、debug、低置信度
风险色：红色，用于 errors、明显误判
成功色：绿色，用于人工复核确认
```

证据等级显示：

```text
A：深色强调，强案例
B：中度强调，中等证据
C：橙色或弱强调，需要复核
D：灰色，非 AI 相关
```

---

## 11. 全局布局

使用 Streamlit 左侧栏作为导航与文件选择区。

页面结构：

```text
左侧栏：
- 上传 / 选择 Excel
- 页面导航
- 全局筛选器

主内容区：
- 页面标题
- 核心说明
- 指标卡
- 图表
- 表格 / 卡片
- 复核区域
```

推荐页面：

```text
1. Dashboard 总览
2. 购前决策评论
3. AI 候选证据库
4. 全部内容
5. 商品汇总
6. 关键词汇总
7. Debug / Errors
8. 复核记录
```

---

## 12. Dashboard 总览页

### 12.1 页面目标

回答一个问题：

```text
这批内容里，多少是购前决策？其中多少出现 AI 影响痕迹？
```

### 12.2 第一行核心指标卡

只放 4 个主指标：

```text
全部内容数
购前决策内容数
AI 候选数
AI 候选 / 购前决策内容
```

可在指标卡下方用小字显示：

```text
AI 候选 / 全部内容
A/B/C 数量
D 数量
商品数量
平台数量
```

### 12.3 漏斗图

图表类型：Plotly Funnel。

漏斗顺序：

```text
全部内容
购前决策内容
AI 候选
A 级强证据
```

如果 A 级数量为 0，也正常显示。

图表尺寸：

```text
高度：320px 左右
宽度：主区域 60% 或整行
```

### 12.4 证据等级分布

图表类型：横向柱状图。

展示：

```text
A
B
C
D
```

尺寸：

```text
高度：260–320px
```

### 12.5 商品排行

展示 Top 10 商品：

```text
按 AI 候选数排序
按 AI 候选 / 购前决策内容占比排序
```

第一版可以只做一个 Top 10 横向柱状图。

---

## 13. 购前决策评论页

### 13.1 页面目标

帮助人工确认：

```text
哪些内容真的在解释“为什么买 / 怎么选 / 值不值 / 怕不怕踩坑”。
```

默认数据源：

```text
pre_purchase_details
```

如果该 Sheet 不存在，则从 `content_all` 中筛选：

```python
pre_purchase_decision == True
```

### 13.2 筛选器

顶部或侧边提供：

```text
平台
商品
店铺
内容类型：review / question / answer
是否 AI 候选
证据等级：A/B/C/D
购前决策词
关键词
SKU
来源文件
文本搜索
extract_confidence 范围
```

### 13.3 卡片展示

不要只用表格。默认用卡片。

每条卡片字段：

```text
商品名｜平台｜SKU｜评论时间/顺序
原文内容
命中句子
购前决策理由
AI 候选判断
证据等级
命中关键词
来源文件
```

卡片要求：

```text
1. 原文必须醒目。
2. 原文默认显示 4–6 行，支持展开。
3. 命中词可以高亮，但不要破坏原文。
4. 每张卡片提供复核按钮。
5. 支持复制原文。
```

### 13.4 卡片中的判断标签

展示为小标签：

```text
购前决策：是
AI候选：是/否
证据等级：A/B/C/D
来源：平台 / 文件
```

---

## 14. AI 候选证据库页

### 14.1 页面目标

帮助人工查看可以进入报告的 AI 影响案例。

默认数据源：

```text
ai_candidates
```

只展示：

```text
A/B/C
```

不要展示 D。

### 14.2 排序

默认排序：

```text
A → B → C
同等级按 match_score 降序
```

### 14.3 卡片结构

每张 AI 候选卡片展示：

```text
证据等级
match_score
消费者原文
命中句子
AI 来源词
AI 行为词
购买动作词
证据理由
商品名
平台
SKU
来源文件
```

A 级卡片可以更醒目。

### 14.4 复制为报告案例

为每条 AI 候选增加按钮：

```text
复制为报告案例
```

复制文本模板：

```text
【{evidence_level} 级案例】用户原文提到“{matched_sentence}”。该内容命中 AI 来源词 {ai_source_terms}，并出现 {ai_action_terms} / {purchase_context_terms} 等决策动作，可作为 AI 介入购买决策链路的候选证据。商品：{product_title}，平台：{platform}。
```

如果字段为空，自动略过。

---

## 15. 全部内容页

### 15.1 页面目标

提供完整追溯与排查能力。

默认数据源：

```text
content_all
```

### 15.2 展示方式

用高密度表格，不用卡片。

默认字段：

```text
content_id
platform
product_title
record_type
content_text_clean
pre_purchase_decision
ai_candidate
evidence_level
matched_keywords
exclude_reason
source_file
```

### 15.3 交互

要求：

```text
1. 支持全文搜索。
2. 支持多条件筛选。
3. 支持下载筛选后的 CSV。
4. 点击或选择某一行后，下方展示详情。
```

Streamlit 第一版可以用 `st.dataframe` + 选择行的方式；如选择行复杂，则先用表格展示，再提供 content_id 搜索详情。

---

## 16. 商品汇总页

### 16.1 页面目标

比较不同商品的评论结构与 AI 候选情况。

默认数据源：

```text
summary_by_product
```

如果没有该 Sheet，则从 `content_all` 聚合生成。

### 16.2 指标

每个商品展示：

```text
商品名
平台
全部内容数
购前决策内容数
AI 候选数
AI 候选 / 全部内容
AI 候选 / 购前决策内容
A 数量
B 数量
C 数量
D 数量
来源文件数量
```

### 16.3 图表

使用横向柱状图：

```text
Top 10 商品：AI 候选数
Top 10 商品：AI 候选 / 购前决策内容
```

不要用饼图。

---

## 17. 关键词汇总页

### 17.1 页面目标

帮助迭代关键词、排除词和误判规则。

默认数据源：

```text
summary_by_keyword
```

如果没有该 Sheet，则从 `content_all.matched_keywords` 简单拆分聚合。

### 17.2 指标

展示：

```text
关键词
关键词类型
命中次数
进入购前决策次数
进入 AI 候选次数
对应证据等级分布
典型原文
误判反馈次数
```

### 17.3 图表

使用横向柱状图：

```text
关键词命中 Top 20
AI 候选关键词 Top 20
误判反馈关键词 Top 20，如已有 feedback
```

不要做词云。

---

## 18. Debug / Errors 页

### 18.1 页面目标

帮助开发继续迭代 parser 与规则。

默认数据源：

```text
errors
debug_samples
```

### 18.2 展示模块

分成三个区：

```text
解析错误
低置信度样本
平台质量提示
```

### 18.3 京东质量提示

如果字段存在：

```text
declared_review_count
saved_comment_card_count
```

并且：

```text
declared_review_count 明显大于 saved_comment_card_count
```

则展示提醒：

```text
该 JD 页面只保存了当前可见/已渲染评价，不能代表完整评论池。
```

---

## 19. 人工复核功能

### 19.1 原则

人工复核结果不得覆盖原始 Excel。

另存为：

```text
output/review_feedback.csv
```

### 19.2 每条内容的复核选项

提供：

```text
判断正确
购前决策误判
AI 候选误判
证据等级需调整
需要加入排除词
需要加入关键词
备注
```

### 19.3 复核字段

CSV 字段：

```text
feedback_id
content_id
source_file
product_title
platform
content_text_clean
original_pre_purchase_decision
manual_pre_purchase_decision
original_ai_candidate
manual_ai_candidate
original_evidence_level
manual_evidence_level
feedback_type
suggested_keyword
suggested_exclude_pattern
note
reviewed_at
reviewed_by
```

### 19.4 保存规则

实现：

```python
save_feedback(row: dict) -> None
load_feedback() -> pd.DataFrame
```

要求：

```text
1. 如果 review_feedback.csv 不存在，自动创建。
2. 如果同一 content_id 多次复核，保留多条记录，不覆盖。
3. feedback_id 使用时间戳 + content_id 或 uuid。
4. reviewed_at 使用本地时间字符串。
```

---

## 20. 导出功能

每个主要页面支持导出当前筛选结果：

```text
下载当前筛选 CSV
下载 AI 候选案例 CSV
下载复核记录 CSV
```

AI 候选页额外提供：

```text
下载报告案例 Markdown
```

Markdown 格式：

```markdown
# AI 影响候选案例

## A 级案例

- 商品：...
- 平台：...
- 原文：...
- 判断理由：...

## B 级案例
...

## C 级案例
...
```

---

## 21. 图表类型规范

使用图表要克制。

### 必做图表

```text
漏斗图：全部内容 → 购前决策 → AI 候选 → A 级强证据
横向柱状图：证据等级分布
横向柱状图：商品 AI 候选 Top 10
横向柱状图：关键词命中 Top 20
```

### 暂不做图表

```text
饼图：不用，容易误导
折线图：不用，除非未来加入日期趋势
散点图：不用
词云：不用
```

### 图表大小

```text
Dashboard 漏斗图：高度 320px
证据等级柱状图：高度 280px
商品排行图：高度 360–500px
关键词排行图：高度 500–700px
```

---

## 22. 组件建议

### 22.1 `ui/data_loader.py`

负责：

```text
读取 Excel
检查 Sheet
补齐字段
标准化布尔值
标准化 evidence_level
```

### 22.2 `ui/filters.py`

负责：

```text
平台筛选
商品筛选
证据等级筛选
AI候选筛选
购前决策筛选
关键词搜索
全文搜索
```

### 22.3 `ui/cards.py`

负责：

```text
购前决策卡片
AI候选证据卡片
详情卡片
```

### 22.4 `ui/charts.py`

负责：

```text
漏斗图
证据等级柱状图
商品排行图
关键词排行图
```

### 22.5 `ui/feedback.py`

负责：

```text
复核表单
保存 feedback csv
读取 feedback csv
生成复核统计
```

### 22.6 `ui/tables.py`

负责：

```text
通用表格显示
字段选择
CSV 下载
```

### 22.7 `ui/styles.py`

负责：

```text
统一 CSS
证据等级颜色
卡片样式
指标卡样式
```

---

## 23. 样式实现建议

可以使用 `st.markdown(..., unsafe_allow_html=True)` 加少量 CSS。

卡片 CSS 示例：

```css
.review-card {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 12px;
  background: #ffffff;
}

.review-text {
  font-size: 15px;
  line-height: 1.7;
  color: #111827;
}

.meta-text {
  font-size: 12px;
  color: #6b7280;
}

.badge-a {
  background: #1e3a8a;
  color: white;
  padding: 2px 8px;
  border-radius: 999px;
}

.badge-b {
  background: #2563eb;
  color: white;
  padding: 2px 8px;
  border-radius: 999px;
}

.badge-c {
  background: #f59e0b;
  color: white;
  padding: 2px 8px;
  border-radius: 999px;
}

.badge-d {
  background: #9ca3af;
  color: white;
  padding: 2px 8px;
  border-radius: 999px;
}
```

---

## 24. Dashboard 统计逻辑

从 `content_all` 计算：

```python
total_count = len(content_all)
pre_purchase_count = content_all[content_all["pre_purchase_decision"] == True].shape[0]
ai_candidate_count = content_all[content_all["ai_candidate"] == True].shape[0]

ai_rate_total = ai_candidate_count / total_count if total_count else 0
ai_rate_pre_purchase = ai_candidate_count / pre_purchase_count if pre_purchase_count else 0
```

证据等级：

```python
evidence_counts = content_all["evidence_level"].value_counts()
```

AI 候选页数据优先使用 `ai_candidates`，如果不存在则从 `content_all` 中筛选：

```python
content_all[
  (content_all["ai_candidate"] == True) &
  (content_all["evidence_level"].isin(["A", "B", "C"]))
]
```

---

## 25. 验收标准

### 25.1 基础验收

```text
1. 可以通过 streamlit run app.py 启动。
2. 可以上传或读取现有 Excel。
3. Sheet 缺失时不崩溃。
4. Dashboard 可以显示核心指标。
5. 可以看到漏斗图。
6. 可以浏览购前决策内容。
7. 可以浏览 AI 候选 A/B/C。
8. 可以查看 content_all 全表。
9. 可以查看 errors 与 debug_samples。
10. 可以保存人工复核结果到 review_feedback.csv。
```

### 25.2 口径验收

```text
1. Dashboard 必须同时显示 AI 候选 / 全部内容 与 AI 候选 / 购前决策内容。
2. AI 候选页不得展示 D 级。
3. D 级可以出现在购前决策页和 Dashboard 证据分布里。
4. 前端不得把“购前决策”直接等同于“AI 影响”。
5. 前端不得新增朋友、客服、达人、小红书等决策来源归因功能。
```

### 25.3 追溯验收

任意一条内容必须能看到：

```text
原文
命中句子
命中关键词
商品名
平台
来源文件
判断理由
证据等级
```

### 25.4 复核验收

```text
1. 人工复核不修改原始 Excel。
2. review_feedback.csv 可以持续追加。
3. 复核记录可以在前端查看。
4. 可以下载复核记录。
```

---

## 26. 推荐实现顺序

按以下顺序开发：

```text
第一步：app.py 基础导航 + Excel 上传
第二步：data_loader.py 读取 Excel 与字段标准化
第三步：Dashboard 指标卡 + 漏斗图 + 证据等级图
第四步：购前决策评论页卡片
第五步：AI 候选证据库页卡片
第六步：全部内容页表格与筛选
第七步：商品汇总页与关键词汇总页
第八步：Debug / Errors 页
第九步：人工复核保存 review_feedback.csv
第十步：导出 CSV / Markdown
```

不要先做复杂样式。先保证数据能正确展示。

---

## 27. 质量要求

代码要求：

```text
1. 函数拆分清楚。
2. 不要把所有逻辑都堆在 app.py。
3. 对缺失字段、空表、空 Excel 做保护。
4. 所有筛选函数要能处理空 DataFrame。
5. 所有下载文件名包含日期时间。
6. 页面上避免英文技术错误直接暴露给普通用户。
```

界面要求：

```text
1. 原文可读优先。
2. 筛选方便。
3. 判断可追溯。
4. 证据等级醒目。
5. 图表不要过多。
6. 不要做成 BI 大屏。
```

---

## 28. README 补充

请更新 README，增加：

```markdown
## 启动前端

安装依赖：

```bash
pip install -r requirements.txt
```

运行：

```bash
streamlit run app.py
```

打开浏览器后，上传脚本输出的 Excel 文件，即可浏览分析结果。

注意：

- 前端只读取 Excel，不重新解析 HTML。
- 前端不联网，不调用大模型。
- 人工复核结果保存在 `output/review_feedback.csv`。
```

---

## 29. 最终一句话

这个前端不是新的分析引擎，而是现有规则输出的浏览、复核、追溯工作台。

请优先保证：

```text
看得清楚
筛得方便
追得回原文
复核结果能沉淀
口径不跑偏
```
