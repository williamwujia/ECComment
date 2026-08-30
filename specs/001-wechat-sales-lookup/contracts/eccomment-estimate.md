# ECComment Estimate Contract

微信服务依赖 ECComment 提供的受认证估算服务。该契约描述边界，不要求微信服务实现解析、抓取或销量计算。

## Request

`POST /api/sales/estimate`

| Field | Required | Description |
|---|---|---|
| `query` | Yes | 用户原样发送的商品分享文本。 |
| `source` | Yes | 固定为 `wechat`。 |
| `request_id` | Yes | 微信服务生成的稳定追踪编号。 |

请求使用部署时配置的服务凭据，不得记录该凭据。

## Successful result

| Field | Required | Validation |
|---|---|---|
| `status` | Yes | `ok`。 |
| `product_name` | Yes | 非空。 |
| `platform` | Yes | `taobao`。 |
| `period` | Yes | 非空统计周期。 |
| `estimated_sales` | Yes | 非负整数。 |
| `review_count` | Yes | 非负整数。 |
| `data_date` | Yes | 有效数据截至日期。 |
| `review_rate` | Yes | `0.05`。 |
| `date_coverage` | Yes | 有效评论日期的主评论数除以全部主评论数的 0–100 百分比。 |

## Unavailable result

`status=error` 并包含面向用户安全显示的错误分类。微信服务不得将服务内部错误、凭据或堆栈转发给用户。

## Failure semantics

- 超时、网络失败和 5xx 是可重试的临时失败，使用有界退避并保留状态。
- 4xx、缺少必需字段及明确的不可用结果为终态失败。
- 同一 `request_id` 的重复调用必须返回相同结果或可安全地被 ECComment 去重。
