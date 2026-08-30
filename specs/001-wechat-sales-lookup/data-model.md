# Data Model: 微信销量快查

## QueryRequest

一条入站微信消息对应的一次查询生命周期。

| Field | Rules |
|---|---|
| `request_id` | 用户可见的唯一查询编号；不可变。 |
| `wechat_message_id` | 稳定入站消息标识；唯一，用于幂等。 |
| `user_hash` | 以服务器密钥派生的不可逆用户标识；不得存明文用户标识。 |
| `raw_message` | 原始分享内容；仅在 360 天保留期内保存。 |
| `open_kfid` | 所属微信客服账号标识。 |
| `status` | `received`、`pulled`、`queued`、`estimating`、`replying`、`replied`、`failed`、`delivery_failed` 或 `rate_limited`。 |
| `received_at` / `completed_at` | 用于恢复、审计与到期清理。 |
| `result_summary` / `error_code` | 用户安全的结果摘要或分类失败原因；不得记录凭据和堆栈。 |

**Transitions**: `received → pulled → queued → estimating → replying → replied`；任一可恢复阶段可转为 `failed`；无法发送时转为 `delivery_failed`；在提交数据服务前达到额度时转为 `rate_limited`。重启后从非终态恢复处理。

## DailyUsage

每个用户在一个自然日的额度计数。

| Field | Rules |
|---|---|
| `user_hash` + `usage_date` | 联合唯一；按服务配置的业务时区确定自然日。 |
| `reserved_count` | 原子增加；最大值 10。 |
| `updated_at` | 用于审计和异常修复。 |

额度在首次接受一条新的、有效入站消息时预占；重复消息不重复占用。

## EstimateResult

ECComment 返回的完整业务结果。

| Field | Rules |
|---|---|
| `product_name` / `platform` | 非空；平台为淘宝。 |
| `period` / `data_date` | 说明统计范围及数据截至日期。 |
| `estimated_sales` / `review_count` | 非负数。 |
| `review_rate` | 当前必须为 5%。 |
| `date_coverage` | 具有有效评论日期的主评论数除以全部主评论数，范围 0–100%。 |

缺少任一必需字段的结果不可作为成功回复。

## DeliveryAttempt

一次向微信客服发送最终结果的审计项。

| Field | Rules |
|---|---|
| `request_id` | 关联 QueryRequest。 |
| `outbound_message_id` | 由入站消息稳定派生；唯一。 |
| `attempted_at` / `outcome` | 记录发送时间和成功、可重试失败或终态失败。 |
| `failure_code` | 仅记录分类代码，不保存响应中的敏感内容。 |
