# 电商评论 AI 影响力提取工具
# C 级误判修正说明 v1.4

## 1. 本次要解决的问题

在 v1.3 规则中，C 级被定义为：

> 没有提到具体 AI，也没有泛 AI / 算法 / 智能推荐入口，但出现明显高强度购前调研、搜索、对比、科普、做功课、反复筛选。

这个方向是对的，但当前规则容易把以下内容误判为 C，且分数很高：

- 买后使用体验中的“和之前的灯对比”；
- 买后价格投诉中的“京东比价 / 第三方比价”；
- 商家回复中的“欢迎跟任何竞品比质量”；
- 普通客服服务中的“买之前问得比较细”；
- 程度副词里的“比较满意 / 比较适合 / 比较细”。

本次修改目标：

1. 不增加新字段；
2. 保留 v1.3 的 A/B/C/D 思路；
3. 收紧 C 级判断，避免“对比”一出现就高分；
4. 让非购前内容不进入 A-D，不把 D 变成垃圾桶。

---

## 2. 核心原则

### 2.1 A-D 只服务购前决策判断

A-D 不是所有评论的分类标签，只用于“购前决策相关内容”。

因此：

- 买后体验评论，不进入 A-D；
- 物流/安装/售后评论，不进入 A-D；
- 价格投诉/赔付争议，不进入 A-D；
- 商家回复/店铺承诺，不进入 A-D；
- 普通使用效果验证，不进入 A-D。

处理方式：

```text
pre_purchase_decision = False
ai_candidate = False
ai_influence_level = ""
evidence_level = ""
ai_evidence_type = "none"
exclude_reason = "not_pre_purchase_decision"
```

如果现有代码不允许 `ai_influence_level` 为空，可以用：

```text
ai_influence_level = "N/A"
```

但不要标成 D。

### 2.2 D 不是非 AI 评论垃圾桶

D 只表示：

> 这条评论确实聚焦购买前决策，但没有 AI 入口，也没有高强度调研。

例如：

```text
客服月夜很负责，买之前和之后，我问的比较细，客服都耐心地解答。
```

这条可以是 D。

但下面这种不是 D：

```text
收到货了，和之前家里用的灯对比下来，感觉色温不太习惯。
```

这是买后体验对比，不是购前决策。

---

## 3. 不新增字段的处理方案

不新增 `decision_scope` 等字段。

只调整现有字段逻辑：

```text
pre_purchase_decision
ai_candidate
ai_influence_level
evidence_level
ai_evidence_type
matched_keywords
matched_sentence
match_score
excluded_by_rule
exclude_reason
```

新增的是规则函数，不是数据字段。

建议在 `analysis/pre_purchase.py` 和 `analysis/evidence_rules.py` 中加入以下判断函数：

```python
is_merchant_reply_like(text)
is_after_purchase_context(text)
is_price_dispute_context(text)
is_post_purchase_comparison(text)
is_intensive_research_context(text)
```

这些函数只用于判断，不新增输出字段。

---

## 4. C 级新 Gate：必须先过 3 道门

C 级不能只靠“对比 / 比价 / 竞品 / 比较”触发。

C 级必须同时满足：

```text
1. 不是商家回复；
2. 不是买后语境；
3. 不是价格/赔付争议；
4. 是购前决策语境；
5. 出现高强度调研行为。
```

换成代码逻辑：

```python
if is_merchant_reply_like(text):
    return not_pre_purchase()

if is_price_dispute_context(text):
    return not_pre_purchase()

if is_after_purchase_context(text) and not has_strong_pre_purchase_anchor(text):
    return not_pre_purchase()

if is_post_purchase_comparison(text):
    return not_pre_purchase()

if has_specific_ai_source(text):
    return level_A()

if has_generic_ai_or_algorithm_entry(text):
    return level_B()

if is_intensive_research_context(text):
    return level_C()

if is_pre_purchase_decision_context(text):
    return level_D()

return not_pre_purchase()
```

---

## 5. 先排除商家回复

### 5.1 商家回复特征

以下内容高度像商家回复、店铺承诺、售后说明，不应进入消费者评论判断：

```text
接受任何不满意
包邮全额退
免费试用
不满意包邮退
欢迎且支持跟任何竞品比质量
灯身/光源十年质保
前3年免费
4-10年需按成本价
包修包换
买家0成本
无任何后顾之忧
注意记得保留原包装
```

### 5.2 商家回复判断规则

如果文本中出现多个商家承诺词，尤其是编号列表，应视为商家回复或商家话术。

建议规则：

```python
merchant_reply_terms = [
    "接受任何不满意",
    "包邮全额退",
    "免费试用",
    "不满意包邮退",
    "欢迎且支持跟任何竞品比质量",
    "十年质保",
    "包修包换",
    "买家0成本",
    "无任何后顾之忧",
    "保留原包装",
]

merchant_reply_patterns = [
    r"1[、.].*2[、.].*3[、.]",
    r"包邮.*退",
    r"质保.*包修.*包换",
]
```

如果命中：

```text
pre_purchase_decision = False
ai_candidate = False
ai_influence_level = ""
excluded_by_rule = True
exclude_reason = "merchant_reply_like_text"
```

### 5.3 注意

商家回复中的：

```text
欢迎且支持跟任何竞品比质量
```

不能触发 C。

因为这不是消费者的购前对比行为。

---

## 6. 排除买后语境

### 6.1 买后语境关键词

以下词出现时，优先判断为买后体验，而不是购前决策：

```text
收到了
到货了
昨天下单今天就到了
下单后没两天就收到了
物流很快
师傅上门安装
安装很及时
用了
用了一下午
用久了
目前没什么感觉
之前家里用的灯
原来那个
另外一个我用了半年
刚到
收到货
图片没有拍出
售后服务希望
```

### 6.2 买后语境处理

如果文本出现买后语境，且没有明确的购前锚点，则：

```text
pre_purchase_decision = False
ai_candidate = False
ai_influence_level = ""
excluded_by_rule = True
exclude_reason = "post_purchase_experience"
```

### 6.3 明确购前锚点例外

以下词可以把评论拉回购前决策：

```text
买之前
买前
购买前
下单前
入手前
选之前
决定之前
最后选
最终选择
终于确定
对比很多品牌后
做了很多功课后
```

但要注意：

```text
之前的灯
之前家里用的灯
之前没用过
原来那个
```

这些不是购前锚点，而是历史使用背景。

---

## 7. 排除买后体验对比

### 7.1 买后体验对比不是 C

以下表达不是购前调研：

```text
和之前的灯对比了一下
和原来的灯对比
和之前家里用的灯对比下来
比之前那个亮
比原来的灯舒服
显色度比之前更高
原来那个有点刺眼
另外一个我用了半年
```

这些是买后使用体验对比，不是“购买前对比很多品牌/型号”。

### 7.2 建议排除模式

```python
post_purchase_comparison_patterns = [
    r"和之前.*灯.*对比",
    r"和原来.*灯.*对比",
    r"和之前家里用的.*对比",
    r"比之前那个",
    r"比原来那个",
    r"原来那个",
    r"另外一个我用了",
    r"用了半年",
]
```

命中后，如果没有强购前锚点：

```text
pre_purchase_decision = False
ai_candidate = False
ai_influence_level = ""
excluded_by_rule = True
exclude_reason = "post_purchase_comparison"
```

---

## 8. 排除价格/赔付争议

### 8.1 价格争议不是 C

以下表达不是购前调研：

```text
价格比京东贵
淘宝百亿补贴
第三方比价
不给赔
完全不给赔
价保
保价
赔付
补差价
```

这种内容是买后价格争议、平台规则争议，不是购前决策。

### 8.2 价格争议处理

命中价格争议，且没有明确购前调研语境时：

```text
pre_purchase_decision = False
ai_candidate = False
ai_influence_level = ""
excluded_by_rule = True
exclude_reason = "after_purchase_price_dispute"
```

### 8.3 注意

“性价比高”可以是购前价值判断，也可以是买后评价。

只有当它和以下词同句或近邻出现时，才进入购前判断：

```text
对比了很多
选了很久
最终选择
买之前
做功课
网上搜索
```

单独出现：

```text
性价比高
价格还行
价格有点贵
```

不要触发 C。

---

## 9. 收紧“对比”触发 C 的条件

### 9.1 能触发 C 的对比

必须是购买前筛选候选商品的对比。

示例：

```text
对比了很多品牌，最后选了这款。
对比了很多型号，最终还是选择了这款。
对比好多家最终买的这个。
网上搜索对比了很多品牌型号。
小红书做了很多功课，对比了很多品牌。
```

这些可以触发 C。

### 9.2 不能触发 C 的对比

```text
和之前的灯对比了一下。
和之前家里用的灯对比下来不习惯。
价格比京东贵。
第三方比价不给赔。
欢迎跟任何竞品比质量。
比较满意。
比较适合。
比较细。
比较柔和。
```

这些不能触发 C。

### 9.3 C 级对比建议正则

```python
c_research_patterns = [
    r"对比了?(很多|好多|多家|多个|几家|几款|不少).*?(品牌|型号|产品|款|家)",
    r"(网上搜索|小红书|知乎|抖音|看了很多|查了很多|做了很多功课|做功课|做攻略|看攻略|看测评).*?(对比|比较|选|选择)",
    r"(选了很久|纠结很久|研究了很久).*?(最后|最终|终于|确定|选择|下单|买)",
    r"(最终|最后|终于).*?(选择|确定|选了|买了|下单)",
]
```

但要配合排除规则，不能只靠正则加分。

---

## 10. “比较”作为程度副词必须排除

以下词组不能触发购前对比，也不能给 C 加分：

```text
比较满意
比较适合
比较柔和
比较亮
比较舒服
比较好看
比较简单
比较负责
比较不错
比较细
比较高
比较自然
比较专业
```

处理方式：

```text
matched_keywords 中不记录这些词
match_score 不加分
```

如果评论只命中这些词，不得进入 C。

---

## 11. 本批样本的正确分类

### 样本 1

```text
客服月夜很负责，买之前和之后，我问的比较细，客服都耐心的解答，非常不错，对孩子的眼睛友好，棒棒哒！
```

正确结果：

```text
pre_purchase_decision = True
ai_candidate = False
ai_influence_level = D
ai_evidence_type = none
exclude_reason = ""
```

理由：

- “买之前”是明确购前咨询；
- 来源是客服；
- “比较细”是程度副词，不是商品对比；
- 所以是 D，不是 C。

### 样本 2

```text
明基昨天下单今天就到了！和之前的灯对比了一下，个人觉得明基的显色度会更高……
```

正确结果：

```text
pre_purchase_decision = False
ai_candidate = False
ai_influence_level = ""
ai_evidence_type = none
excluded_by_rule = True
exclude_reason = "post_purchase_comparison"
```

理由：

- “下单今天就到了”是买后语境；
- “和之前的灯对比”是买后体验对比；
- 不是购前调研；
- 不进入 A-D。

### 样本 3

```text
月容服务好，产品也还行，就是价格比京东贵不好，淘宝百亿补贴和第三方比价的都是骗人的，完全不给赔。
```

正确结果：

```text
pre_purchase_decision = False
ai_candidate = False
ai_influence_level = ""
ai_evidence_type = none
excluded_by_rule = True
exclude_reason = "after_purchase_price_dispute"
```

理由：

- 这是价格/赔付争议；
- “比价”不是购前调研；
- 不进入 A-D。

### 样本 4

```text
物流很快，下单后没两天就收到了，师傅上门安装很及时，之前没用过大路灯还需要适应下，感觉色温和之前家里用的灯对比下来还是不太习惯。客服挺有耐心的……
```

正确结果：

```text
pre_purchase_decision = False
ai_candidate = False
ai_influence_level = ""
ai_evidence_type = none
excluded_by_rule = True
exclude_reason = "post_purchase_experience"
```

理由：

- 物流、安装、收货都是买后语境；
- “之前家里用的灯对比”是买后体验对比；
- 客服服务也是买后体验描述；
- 不进入 A-D。

### 样本 5

```text
收到了，很满意，物流上有点小插曲，客服也帮忙积极解决了……1、接受任何不满意，包邮全额退；2、101天免费试用……
```

正确结果：

```text
pre_purchase_decision = False
ai_candidate = False
ai_influence_level = ""
ai_evidence_type = none
excluded_by_rule = True
exclude_reason = "merchant_reply_like_text"
```

理由：

- 前半段是买后体验；
- 后半段是商家回复/店铺承诺；
- “竞品比质量”来自商家话术，不是消费者购前对比；
- 不进入 A-D。

---

## 12. match_score 调整建议

### 12.1 C 级加分项

以下可以给 C 加分：

```text
做了很多功课 +3
网上搜索 +3
看了很多测评/攻略 +3
对比很多品牌/型号 +3
选了很久/纠结很久 +2
最终选择/终于确定 +2
```

### 12.2 买后语境扣分或直接拦截

以下命中时，优先直接拦截，不建议只扣分：

```text
收到了
到货了
用了
用了一下午
物流
安装
售后
和之前的灯对比
价格比京东贵
第三方比价
包邮退
免费试用
十年质保
```

如果暂时不方便做拦截，至少设置分数上限：

```text
post_purchase_comparison 命中：match_score <= 2，不能为 C
price_dispute 命中：match_score <= 2，不能为 C
merchant_reply_like_text 命中：match_score <= 1，不能为 C
comparison_adverb 命中：不加分
```

---

## 13. 判断优先级最终版

单条评论按以下顺序处理：

```text
1. 清洗文本，尽量剥离 merchant_reply；
2. 判断是否商家回复/商家承诺话术；
   - 是：不进入 A-D；
3. 判断是否价格/赔付争议；
   - 是：不进入 A-D；
4. 判断是否买后体验对比；
   - 是且无强购前锚点：不进入 A-D；
5. 判断是否具体 AI；
   - 是：A；
6. 判断是否泛 AI / 算法入口；
   - 是：B；
7. 判断是否高强度购前调研；
   - 是：C；
8. 判断是否普通购前决策；
   - 是：D；
9. 其他内容：
   - 不进入 A-D。
```

---

## 14. 给 Codex 的实现提醒

本次不要新增输出字段。

重点修改：

```text
analysis/pre_purchase.py
analysis/evidence_rules.py
analysis/ai_keyword_matcher.py
config/ai_keywords.yaml
```

实现目标：

1. C 级必须从“购前高强度调研”触发；
2. 买后体验对比不能触发 C；
3. 价格比价/赔付争议不能触发 C；
4. 商家回复不能触发 C；
5. 程度副词“比较满意/比较细”等不能触发 C；
6. 非购前内容不要标 D，应该留空或 N/A；
7. D 只保留给“普通购前决策评论”。

验收标准：

- 本文第 11 节 5 条样本必须全部通过；
- 样本 1 = D；
- 样本 2/3/4/5 = 不进入 A-D；
- 不得再出现这些样本被标为 C 且高分的情况。
