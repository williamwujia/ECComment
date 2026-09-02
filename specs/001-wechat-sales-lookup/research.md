# Research: 微信销量快查

## 1. 微信客服消息流程

**Decision**: 使用“回调通知 → `sync_msg` 拉取真实消息 → 异步处理 → `send_msg` 回复”的微信客服流程。

**Rationale**: 回调事件只提供同步所需标识，不应假定其中包含商品分享正文。收到有效通知后，服务需持久化游标和待处理状态、快速确认，再持续拉取分页消息；这样可覆盖消息突发和回调重放。

**Alternatives considered**: 同步在回调内解析、查询并回复。拒绝，因为数据服务可能超过回调安全等待时间，失败或重试会造成重复查询和重复回复。

**Sources**: [微信客服概述](https://developer.work.weixin.qq.com/document/path/94638)、[接收消息和事件](https://developer.work.weixin.qq.com/document/path/94670)、[读取消息](https://developer.work.weixin.qq.com/document/path/94671)。

## 2. 回调安全与可靠回复

**Decision**: 在解密或处理前验证回调签名；使用 Token 和 EncodingAESKey 完成 URL 验证、消息解密与拒绝无效请求。处理状态使用稳定的微信消息标识去重，回复使用确定性消息标识。

**Rationale**: 回调端点是公开入口，签名验证与 AES 解密保护来源真实性和内容机密性。确定性入站/出站标识、可恢复状态和有限指数退避能在重放、重启和临时下游失败下实现“最多一次业务查询、最多一次最终回复”。

**Alternatives considered**: 仅用本地随机查询编号去重。拒绝，因为重放事件无法稳定匹配随机编号。

**Sources**: [回调 URL 验证与加解密](https://developer.work.weixin.qq.com/document/path/90930)。

## 3. 回复会话限制

**Decision**: 仅在微信客服允许回复的会话状态与时间窗口内调用消息发送；不能发送时记录终态并向运营告警，不进行无限重试。

**Rationale**: 微信客服 API 管理账号和用户会话窗口约束会影响异步回复能力。服务必须在提交耗时估算前检查可回复状态，并将发送失败作为可追溯状态。

**Alternatives considered**: 将数据服务完成即视为用户已收到回复。拒绝，因为发送可能受会话窗口或账号状态限制。

**Sources**: [发送消息](https://developer.work.weixin.qq.com/document/path/94677)。

## 4. 服务边界与存储

**Decision**: 新建独立 `wechat_sales/` 服务和专用 SQLite 数据库；ECComment 作为网络数据服务通过适配器调用，现有 Streamlit 和项目 Excel 不参与回调状态处理。

**Rationale**: 现有应用入口为 Streamlit，适合看板会话而非外部 Webhook。仓库已有 SQLite WAL、事务和唯一约束的可复用模式；SQLite 足以满足当前 10 并发用户和按日额度的 MVP 范围。

**Alternatives considered**: 在 `tracker_ui.py` 中直接暴露回调，或把状态写入项目 Excel。均拒绝：前者耦合 UI 生命周期，后者不能保证并发去重和实时配额原子性。

## 5. 销量口径与外部契约

**Decision**: 微信服务不解析短链、不抓取评论、不计算销量；它只接受 ECComment 的完整估算结果。成功结果必须包含 5% 评论率假设和评论日期覆盖率。

**Rationale**: 这维持 MVP 的黑盒边界，同时符合现有 D-003 销量口径：仅有效主评论按日期统计，估算值不是平台真实订单。

**Alternatives considered**: 微信入口自行补抓或补算。拒绝，因为会重复 ECComment 职责，并显著扩大公开 Webhook 的风险与范围。
