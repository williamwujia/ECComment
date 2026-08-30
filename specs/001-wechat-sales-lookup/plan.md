# Implementation Plan: 微信销量快查

**Branch**: `001-wechat-sales-lookup` | **Date**: 2026-08-30 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-wechat-sales-lookup/spec.md`

## Summary

提供独立、公开的微信客服入口：接收用户原始淘宝分享文字，使用持久化消息队列式状态处理调用外部 ECComment 数据服务，并将单次销量估算回复给原用户。服务快速确认微信回调，异步拉取和处理真实消息，以专用 SQLite 库实现消息幂等、每日 10 次限额、审计和 360 天数据清理。现有 Streamlit 看板与项目 Excel 不承担 Webhook 或并发消息状态。

## Technical Context

**Language/Version**: Python 3.10+

**Primary Dependencies**: FastAPI、Uvicorn、HTTPX、Cryptography；现有 Pandas 销量口径代码仅在 ECComment 数据服务侧复用

**Storage**: 专用 SQLite 数据库（WAL 模式）；项目 Excel 仅为 ECComment 数据源，不保存微信消息状态

**Testing**: pytest 单元、契约和集成测试；以 WeCom 与 ECComment 假客户端覆盖无网络验证

**Target Platform**: 现有 Linux 服务器上的独立 systemd 服务，经 Nginx HTTPS 精确路径对外暴露

**Project Type**: 现有 Python/Streamlit 仓库内的独立 Web 服务

**Performance Goals**: 在 ECComment 45 秒内完成时，95% 有效查询在 60 秒内回复；10 个并发用户的查询互不串扰；回调确认不等待估算完成

**Constraints**: 单用户每自然日 10 次；查询日志保留 360 天后删除或不可逆脱敏；消息和回复各至多一次；凭据仅来自部署环境；严格遵循微信客服回调验签、解密及可回复会话窗口

**Scale/Scope**: 所有进入指定微信客服会话的用户；仅单个淘宝商品的文本查询；不包含多轮对话、支付、批量或 ECComment 内部采集改造

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

已核对 constitution 1.0.0：本计划满足可审计数据操作、凭据最小化、外部契约测试、运行隔离和记录同步五项原则。独立 Web 服务与专用 SQLite 状态库属于经记录的复杂度，避免了将公开回调耦合到 Streamlit 或 Excel。生产部署仍须完成非生产微信客服与 ECComment 的真实契约验证。

## Project Structure

### Documentation (this feature)

```text
specs/001-wechat-sales-lookup/
├── plan.md              # This file ($speckit-plan command output)
├── research.md          # Phase 0 output ($speckit-plan command)
├── data-model.md        # Phase 1 output ($speckit-plan command)
├── quickstart.md        # Phase 1 output ($speckit-plan command)
├── contracts/           # Phase 1 output ($speckit-plan command)
└── tasks.md             # Phase 2 output ($speckit-tasks command - NOT created by $speckit-plan)
```

### Source Code (repository root)

```text
wechat_sales/
├── app.py                 # HTTPS-proxied callback and health endpoints
├── config.py              # Environment-only configuration validation
├── crypto.py              # Callback verification and message decryption
├── wecom_client.py        # sync_msg and send_msg client contract
├── eccomment_client.py    # External estimate-service adapter
├── repository.py          # SQLite transactions, dedupe, quota, retention
├── worker.py              # Durable pending-work processor and recovery scan
├── formatter.py           # User-safe Chinese success/failure replies
└── models.py              # Domain states and validated result shapes

tests/
├── test_wechat_sales_callback.py
├── test_wechat_sales_repository.py
├── test_wechat_sales_worker.py
├── test_wechat_sales_contracts.py
└── test_wechat_sales_retention.py

deploy/
├── systemd/wechat-sales.service
└── nginx/wechat-sales-location.conf
```

**Structure Decision**: 新增独立 `wechat_sales/` 服务而不修改 `tracker_ui.py` 的 Streamlit 请求模型。该服务只读取自己的 SQLite 状态库并通过明确的外部 ECComment 契约取得结果；现有项目工作簿不接受微信入口写入。

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| 独立 Web 服务 | 微信客服需要公开 HTTPS 回调、快速确认、验签、后台恢复和独立重启 | 将回调放入 Streamlit 会将 UI 会话和外部消息流耦合，且不能可靠实现快速确认与持久状态恢复 |
| 专用 SQLite 状态库 | 需要事务性去重、每日额度和 360 天清理 | 项目 Excel 面向批量评论数据，不支持并发消息幂等或安全的实时配额计数 |
