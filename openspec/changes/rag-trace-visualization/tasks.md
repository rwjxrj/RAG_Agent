## 1. 后端 Trace 契约

- [x] 1.1 定义 trace 快照字段结构，覆盖 `intent`、`selected_tool`、`decision_reason`、`node_path`、`tool_result`、`latency` 和节点状态。
- [x] 1.2 在 AnswerService 问答入口聚合 trace 上下文，确保 intent hit、Agentic Router、RAG 路径和非 RAG 路径都能产出一致快照。
- [x] 1.3 将现有 `debug_metadata.timings` 映射为毫秒级 `latency.total_ms` 和节点级 `latency.nodes`。
- [x] 1.4 为 Router 低置信、异常回退和 intent cache 命中补充明确 trace 状态。

## 2. 流式 Trace 事件

- [ ] 2.1 梳理当前 streaming conversation SSE 事件格式，确定可选 `trace` 事件的兼容写法。
- [ ] 2.2 在流式入口输出节点开始、完成、跳过或回退的增量 trace 事件。
- [ ] 2.3 确保不支持 trace 事件的客户端仍能按现有方式接收最终答案。

## 3. 前端可视化

- [ ] 3.1 在问答界面新增轻量执行时间线，显示当前节点、已完成节点、跳过节点和失败回退状态。
- [ ] 3.2 展示 Agentic Router 的 `selected_tool`、`decision_reason` 和置信度或回退状态。
- [ ] 3.3 展示 `tool_result` 摘要，包括最终 decision、引用数量、追问数量和总耗时。
- [ ] 3.4 对未知未来节点使用通用节点渲染，保证内部流程重构时前端仍兼容。

## 4. 测试与验收

- [ ] 4.1 增加后端测试：intent hit、`rag_search`、`direct_response`、`clarify`、`human_handoff`、低置信回退、异常回退的 trace 快照。
- [ ] 4.2 增加流式入口测试：trace 事件可选输出且不破坏现有答案事件。
- [ ] 4.3 增加前端测试或截图验证：时间线能展示 running、completed、skipped、fallback 状态。
- [ ] 4.4 验证三类入口 trace 字段语义一致，外部 API 顶层字段保持兼容。
