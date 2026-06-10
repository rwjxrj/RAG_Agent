## Why

当前问答 RAG 检索过程对用户来说像一个黑盒：前端只能看到最终答案，无法感知系统正在执行 intent 判断、工具选择、检索、证据评估、生成或校验。随着 Agentic Router 已经加入链路，用户需要看到“当前正在做什么”和“为什么这么做”，否则 Agent 感仍然偏弱。

本变更规划 RAG 问答 trace 可视化能力：在不改变现有问答顶层返回结构、不引入 LangGraph 或其他工作流框架的前提下，定义一套可被前端消费的 trace 事件/快照契约，用于展示 `intent`、`selected_tool`、`decision_reason`、`node_path`、`tool_result` 和 `latency` 等执行状态。

## What Changes

- 新增 RAG trace 可视化规格，用于描述问答执行过程的可观测状态。
- 规划后端在现有 debug/timing 基础上输出结构化 trace 信息，覆盖 intent、Agentic Router、RAG 阶段和最终工具结果。
- 规划前端展示轻量执行进度：当前节点、已完成节点、工具选择、决策原因、工具结果摘要和阶段耗时。
- 规划三类入口保持一致：`/reply/generate`、同步会话、流式会话都应使用同一 trace 字段语义。
- 规划稳定逻辑节点名：`node_path` 使用与实现细节解耦的阶段名称，避免后续内部重构时重写前端展示模型。
- 不修改数据库、不修改 Docker、不新增第三方依赖、不改变认证逻辑。
- 不替换现有 RAG 主链路，也不改变 Agentic Router 的路由决策语义。
- 明确现在和后续实现都不引入 LangGraph。

## Capabilities

### New Capabilities

- `rag-trace-visualization`: 定义问答 RAG 执行过程的 trace 输出、前端展示语义、字段契约、入口一致性、延迟统计和工作流框架无关的节点命名要求。

### Modified Capabilities

- 无。现有 `agentic-router` capability 的路由行为不变，本变更只新增 trace 可视化能力。

## Impact

- 未来后端影响范围：`AnswerService.generate()`、Agentic Router debug 写入、RAG Orchestrator 阶段 timings、会话持久化 debug metadata、流式入口事件输出。
- 未来前端影响范围：Conversations 问答页面、可能复用的 reply 调试展示、流式消息状态区。
- 外部 API 顶层字段保持兼容；trace 信息应作为可选 `debug.trace` 或等价可选字段出现，客户端不得依赖其必然存在。
- 不涉及数据库 schema、迁移、Docker、认证、依赖安装或知识库入库逻辑。
