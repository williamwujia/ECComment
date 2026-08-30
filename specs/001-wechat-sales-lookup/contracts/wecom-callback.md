# WeCom Customer Service Callback Contract

## Inbound notification

公开 HTTPS 回调接收 URL 验证和事件通知。服务必须先验证签名，再解密有效载荷；无效签名不得进入持久化或业务处理。

成功事件通知仅被视为“需要同步消息”的信号。服务持久化同步令牌/游标状态后快速确认，并调用微信客服消息同步接口分页拉取实际用户消息。

## Message eligibility

- 仅文本消息进入本 MVP 的商品查询流程。
- 每条稳定入站消息标识最多建立一个 QueryRequest。
- 同一用户在同一自然日第 11 次及之后的有效消息创建 `rate_limited` 记录，不调用 ECComment。

## Outbound reply

仅对仍处于微信客服允许回复窗口的会话发送一条最终文本消息。出站消息标识从入站消息稳定派生，确保重试不会产生第二条结果。

无法发送时，QueryRequest 进入 `delivery_failed`，保留供运营排查；不得无限重试或泄露内部信息。
