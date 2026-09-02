# Quickstart: 微信销量快查验证

## Prerequisites

- 已配置微信客服账号、公开 HTTPS 回调、Token、EncodingAESKey、OpenKfId 和专用 Secret。
- 已配置可访问的 ECComment 估算服务及其凭据。
- 微信服务拥有一个不纳入版本控制的可写 SQLite 数据目录。

## Local validation

1. 设置测试环境变量与假 WeCom、ECComment 客户端。
2. 运行 `python -m pytest -q tests/test_wechat_sales_callback.py tests/test_wechat_sales_repository.py tests/test_wechat_sales_worker.py tests/test_wechat_sales_contracts.py tests/test_wechat_sales_retention.py`。
3. 验证有效回调快速确认后，会拉取一条文本消息、建立查询、调用假 ECComment 并产生一次成功回复。
4. 重放同一回调和消息，验证仅存在一次查询与一次出站消息。
5. 让同一假用户连续发送 11 条有效消息，验证第 11 条不调用 ECComment 且收到次日可重试提示。
6. 将完成时间设为 360 天前，运行清理任务，验证原始消息与用户可识别字段被删除或不可逆脱敏。

## Deployment validation

1. 安装独立 systemd 服务并使其仅绑定本机回环地址。
2. 配置 Nginx 的精确 HTTPS 回调路径，执行 `nginx -t`，确认新服务健康端点可经反代访问。
3. 使用微信客服 URL 验证请求确认签名验证和明文挑战回复正确。
4. 在真实测试会话中发送一段淘宝分享文字，确认用户只收到一条成功或安全失败回复，并按查询编号核对审计状态。
5. 重启服务后确认非终态查询被恢复，且不会产生重复 ECComment 调用或回复。
