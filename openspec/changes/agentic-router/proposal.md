## Why

当前客服问答链路在 intent cache 未命中后默认进入固定 RAG 流程，所有问题都会被当作知识库问题处理。这样对问候、能力询问、信息不足、账号账单安全等需要人工处理的问题缺少“先判断再选择工具”的 Agent 决策感。

本变更规划一个轻量 Agentic Router：放在 intent cache 未命中之后、现有 RAG 流程之前，先判断用户问题类型，再选择 `rag_search`、`direct_response`、`clarify` 或 `human_handoff`。低置信或异常时必须默认回退现有 RAG，保证行为可回退。

## What Changes

- 新增 Agentic Router 的规格与设计规划，用于描述 RAG 前工具选择能力。
- 明确 Router 触发位置：guardrails 之后、intent cache 未命中之后、固定 RAG 流程之前。
- 明确 intent cache 命中时 Router 跳过，仍直接返回预设 intent answer。
- 明确 Router 可选择四类工具：`rag_search`、`direct_response`、`clarify`、`human_handoff`。
- 明确外部 API 顶层返回结构保持不变，仅允许在 `debug.agentic_router` 增加可选调试字段。
- 明确新 Router 与现有 `app/services/decision_router.py` 的职责边界：前者是 RAG 前工具选择器，后者仍是检索后证据决策器。
- 本 change 当前只创建 OpenSpec/Comet 规划产物，不实施业务代码。

## Capabilities

### New Capabilities

- `agentic-router`: 定义 intent cache 未命中后、RAG 前的轻量工具选择能力，包括路由输入输出、工具语义、回退策略、debug 返回和验收测试。

### Modified Capabilities

- 无。本次不修改现有 OpenSpec capability；当前仓库 `openspec/specs/` 下没有可复用的既有规格。

## Impact

- 规划影响的未来实现入口：`/reply/generate`、同步会话、流式会话三类问答入口。
- 规划影响的未来服务边界：未来可新增独立 Router 服务模块，但不替换现有 RAG 编排。
- 规划影响的未来返回字段：仅在 `debug` 中增加可选 `agentic_router` 字段，外部顶层返回保持 `answer`、`decision`、`followup_questions`、`citations`、`confidence`、`debug` 不变。
- 不引入新第三方依赖，不修改数据库、Docker、认证、迁移或现有 API 路由。
- 不改变现有 RAG 主流程：`query extract → retrieve → assess evidence → retry → generate → verify`。
