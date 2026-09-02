---

description: "Actionable task list for 微信销量快查"
---

# Tasks: 微信销量快查

**Input**: Design documents from `/specs/001-wechat-sales-lookup/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`

**Tests**: 所有用户故事都有可验证的验收标准，因此先写对应 pytest 测试并确认其在实现前失败。

**Organization**: 任务按用户故事组织；每个故事在依赖的基础设施完成后均可独立验证。

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 建立隔离服务的目录、依赖和部署配置，不修改现有 Streamlit 入口。

- [ ] T001 Create the isolated `wechat_sales/` package and `tests/test_wechat_sales_*.py` test-module skeletons.
- [ ] T002 [P] Add Webhook service dependencies to `requirements-wechat.txt` and document local installation in `README.md`.
- [ ] T003 [P] Add secret-free environment-variable examples in `config/wechat_sales.env.example` and configuration notes in `deploy/README.md`.
- [ ] T004 [P] Add isolated service definitions in `deploy/systemd/wechat-sales.service` and `deploy/nginx/wechat-sales-location.conf`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 构建所有故事共享的安全配置、持久化状态和可替换外部客户端。

**⚠️ CRITICAL**: 此阶段完成前不得开始用户故事实现。

- [ ] T005 Implement validated environment-only settings and redacted logging in `wechat_sales/config.py`.
- [ ] T006 [P] Implement callback signature verification, AES decryption, and URL-verification helpers in `wechat_sales/crypto.py`.
- [ ] T007 Implement QueryRequest, EstimateResult, DeliveryAttempt, and lifecycle state definitions in `wechat_sales/models.py`.
- [ ] T008 Implement SQLite WAL schema, atomic inbound-message dedupe, per-user daily quota reservation, state transitions, and 360-day cleanup in `wechat_sales/repository.py`.
- [ ] T009 [P] Implement typed WeCom `sync_msg` and `send_msg` client boundaries in `wechat_sales/wecom_client.py`.
- [ ] T010 [P] Implement the authenticated ECComment estimate client and strict result validation in `wechat_sales/eccomment_client.py`.
- [ ] T011 Create deterministic fake WeCom and ECComment clients plus reusable SQLite fixtures in `tests/conftest.py`.

**Checkpoint**: 回调安全、事务性消息状态、额度计数和外部服务替身可用，用户故事可开始。

---

## Phase 3: User Story 1 - 发送商品分享并取得估算 (Priority: P1) 🎯 MVP

**Goal**: 用户发送完整淘宝分享内容后，服务异步取得完整 ECComment 结果并仅回复一次可读估算。

**Independent Test**: 对有效的已验签消息通知，拉取一条淘宝分享文本并在假 ECComment 返回完整结果后，验证唯一的中文结果回复包含所有 FR-004 字段。

### Tests for User Story 1

- [ ] T012 [P] [US1] Write valid callback URL-verification and encrypted-event acknowledgement tests in `tests/test_wechat_sales_callback.py`.
- [ ] T013 [P] [US1] Write complete ECComment-result contract and reply-format tests in `tests/test_wechat_sales_contracts.py`.
- [ ] T014 [P] [US1] Write single-message end-to-end worker test with a paginated `sync_msg` fixture in `tests/test_wechat_sales_worker.py`.

### Implementation for User Story 1

- [ ] T015 [US1] Implement Chinese success and safe failure message formatting in `wechat_sales/formatter.py`.
- [ ] T016 [US1] Implement durable cursor draining, eligible-text extraction, ECComment dispatch, and deterministic one-time reply workflow in `wechat_sales/worker.py`.
- [ ] T017 [US1] Implement callback and health routes with rapid acknowledgement in `wechat_sales/app.py`.
- [ ] T018 [US1] Wire the service composition, startup recovery scan, and graceful worker shutdown in `wechat_sales/app.py`.
- [ ] T019 [US1] Run `tests/test_wechat_sales_callback.py`, `tests/test_wechat_sales_contracts.py`, and `tests/test_wechat_sales_worker.py`; confirm the P1 independent test in `specs/001-wechat-sales-lookup/quickstart.md` passes.

**Checkpoint**: 有效商品分享可在一次回调处理链中得到一次包含完整口径信息的回复。

---

## Phase 4: User Story 2 - 得到可恢复的失败反馈 (Priority: P2)

**Goal**: 数据不可用、超时、不完整结果和受限会话均得到安全且可恢复的处理，不阻塞后续查询。

**Independent Test**: 以假客户端分别注入不可用、超时、缺字段和无法发送回复场景，验证用户安全消息、持久终态和后续新查询能力。

### Tests for User Story 2

- [ ] T020 [P] [US2] Write transient-retry, terminal-unavailable, and incomplete-result tests in `tests/test_wechat_sales_worker.py`.
- [ ] T021 [P] [US2] Write reply-window and delivery-failure contract tests in `tests/test_wechat_sales_contracts.py`.

### Implementation for User Story 2

- [ ] T022 [US2] Add bounded retry classification and restart-safe pending-work recovery in `wechat_sales/worker.py`.
- [ ] T023 [US2] Add explicit `failed` and `delivery_failed` state handling plus user-safe messages in `wechat_sales/worker.py` and `wechat_sales/formatter.py`.
- [ ] T024 [US2] Run the P2 tests and execute the unavailable/timeout/restart scenarios in `specs/001-wechat-sales-lookup/quickstart.md`.

**Checkpoint**: 下游失败不会暴露内部信息、不会卡住回调，并保留可恢复或可追溯的最终状态。

---

## Phase 5: User Story 3 - 查询可追溯且不重复 (Priority: P3)

**Goal**: 重放消息仅被处理一次；公开用户每天最多查询 10 次；运营可通过查询编号追踪结果，日志按期清理。

**Independent Test**: 重放同一消息、让一名用户发起第 11 次查询、模拟 10 名并发用户，以及运行到期清理，验证数据库状态、外部调用次数与用户反馈。

### Tests for User Story 3

- [ ] T025 [P] [US3] Write duplicate-callback/message, atomic quota, and 10-user isolation tests in `tests/test_wechat_sales_repository.py`.
- [ ] T026 [P] [US3] Write 360-day delete-or-anonymize retention tests in `tests/test_wechat_sales_retention.py`.
- [ ] T027 [P] [US3] Write query-ID traceability and rate-limit reply tests in `tests/test_wechat_sales_worker.py`.

### Implementation for User Story 3

- [ ] T028 [US3] Integrate per-user daily quota reservation and `rate_limited` feedback before ECComment dispatch in `wechat_sales/worker.py`.
- [ ] T029 [US3] Add scheduled retention execution and auditable cleanup outcomes in `wechat_sales/repository.py` and `wechat_sales/worker.py`.
- [ ] T030 [US3] Add query-status lookup support for operations in `wechat_sales/repository.py` without exposing it as a public customer endpoint.
- [ ] T031 [US3] Run the P3 tests and verify duplicate, 11th-query, isolation, traceability, and retention scenarios from `specs/001-wechat-sales-lookup/quickstart.md`.

**Checkpoint**: 公开入口具有可验证的去重、每日额度、用户隔离和 360 天数据生命周期。

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 验证生产隔离、文档、全量回归和记录一致性。

- [ ] T032 [P] Add deployment and rollback instructions for the new service to `deploy/README.md` and `README.md`.
- [ ] T033 [P] Add systemd/Nginx configuration validation coverage to `tests/test_wechat_sales_deploy.py`.
- [ ] T034 Verify no credentials, raw messages, user identifiers, tokens, ciphertext, or stack traces enter application logs in `tests/test_wechat_sales_security.py`.
- [ ] T035 Run the focused 微信销量快查 test suite and the repository regression suite with `python -m pytest -q`.
- [ ] T036 Execute every deployment-validation scenario in `specs/001-wechat-sales-lookup/quickstart.md` against a non-production WeCom account.
- [ ] T037 Update feature status and user-facing release records in `PROJECT_STATUS.md`, `CHANGELOG.md`, and `docs/DECISIONS.md`.
- [ ] T038 Add a deterministic 100-query 60-second success-rate measurement in `tests/test_wechat_sales_performance.py` and record the result in `specs/001-wechat-sales-lookup/quickstart.md`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1** has no dependencies.
- **Phase 2** depends on Phase 1 and blocks every user story.
- **US1** depends on Phase 2 and delivers the first demonstrable product slice.
- **US2** depends on the US1 worker/reply pipeline.
- **US3** depends on the Phase 2 repository and worker dispatch path; it may be implemented alongside US2 once US1 is stable.
- **Phase 6** depends on all desired stories.

### User Story Dependencies

- **US1 (P1)**: Foundation only; MVP scope.
- **US2 (P2)**: US1, because error handling extends its dispatch and reply lifecycle.
- **US3 (P3)**: Foundation plus US1 dispatch; persistence tests may begin earlier, but integration waits for US1.

### Parallel Opportunities

- T002–T004 can proceed in parallel after T001.
- T006, T009, T010 and T011 can proceed in parallel once configuration conventions are set.
- T012–T014, T020–T021 and T025–T027 are parallel test files within their stories.
- T032–T034 can proceed in parallel after the implementation is feature complete.

## Parallel Example: User Story 1

```text
T012 tests/test_wechat_sales_callback.py
T013 tests/test_wechat_sales_contracts.py
T014 tests/test_wechat_sales_worker.py
```

## Implementation Strategy

1. Complete Phases 1–2 and prove crypto, repository and fakes independently.
2. Complete US1 and run its independent test before adding retries or public-entry protections.
3. Add US2 and US3, then perform the cross-cutting security, deployment and regression validation.
4. Deploy only after the non-production WeCom callback and reply-window checks succeed.
