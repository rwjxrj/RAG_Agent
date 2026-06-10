---
comet_change: rag-trace-visualization
role: technical-design
canonical_spec: openspec
---

# RAG Trace 可视化技术设计

## 结论

采用轻量 `TraceCollector` 思路：在现有问答链路中收集稳定逻辑节点状态，最终写入可选 `debug.trace` 快照；流式入口额外输出可选 `trace` SSE 事件。现在和后续实现都不引入 LangGraph，不新增第三方依赖，不改数据库、Docker、认证或现有 API 顶层返回结构。

## 背景

当前问答链路已经包含 guardrails、intent cache、Agentic Router、query extract、retrieve、assess evidence、retry、generate、verify。后端已有 `debug_metadata.timings` 和 `debug.agentic_router`，但这些字段偏调试，前端无法清晰展示“现在执行到哪一步”“选择了什么工具”“为什么这么选”“每一步花了多久”。

本设计只把现有执行过程结构化为前端可消费 trace，不改变 RAG 主流程和 Agentic Router 的决策语义。

## 目标

- 展示 `intent`、`selected_tool`、`decision_reason`、`node_path`、`tool_result`、`latency`。
- 支持非流式接口返回最终 trace 快照。
- 支持流式接口输出可选 trace 进度事件。
- 前端以紧凑时间线展示 running、completed、skipped、fallback、failed。
- 使用稳定逻辑节点名，避免绑定 Python 函数名、类名或任何工作流框架。

## 非目标

- 不引入 LangGraph，后续实现也不以 LangGraph 为目标。
- 不新增依赖。
- 不新增数据库表或迁移。
- 不改变外部 API 顶层字段。
- 不实现复杂流程图编辑器。

## 推荐架构

### 后端 TraceCollector

新增或等价实现一个轻量 trace 收集器，作用域限定在一次 `AnswerService.generate()` 调用内。它只负责记录节点状态，不参与业务决策。

概念接口：

```python
trace.start_node("agentic_router")
trace.complete_node(
    "agentic_router",
    selected_tool="rag_search",
    decision_reason="support_knowledge_question",
    tool_result={"route": "rag_search", "confidence": 0.86},
)
snapshot = trace.to_debug()
```

推荐节点名：

- `guardrails`
- `intent_cache`
- `agentic_router`
- `query_extract`
- `retrieve`
- `assess_evidence`
- `retry`
- `generate`
- `verify`
- `direct_response`
- `clarify`
- `human_handoff`

### Trace 快照契约

最终响应在 `debug.trace` 下追加可选快照：

```json
{
  "trace_id": "trace-id",
  "source": "reply|conversation|stream",
  "status": "completed|failed|fallback",
  "intent": {
    "matched": false,
    "key": null
  },
  "selected_tool": "rag_search",
  "decision_reason": "support_knowledge_question",
  "node_path": ["guardrails", "intent_cache", "agentic_router", "query_extract", "retrieve", "assess_evidence", "generate", "verify"],
  "tool_result": {
    "decision": "PASS",
    "citations_count": 3,
    "followup_count": 0,
    "confidence": 0.82
  },
  "latency": {
    "total_ms": 1840,
    "nodes": {
      "retrieve": 430,
      "generate": 980,
      "verify": 160
    }
  },
  "nodes": []
}
```

`debug.trace` 是可选字段，客户端必须能在缺失时保持现有渲染。

### 流式事件

当前 streaming conversation 已有 `status`、`ping`、`content`、`citations`、`done`。后续可增加可选事件：

```json
{
  "type": "trace",
  "data": {
    "trace_id": "trace-id",
    "node_id": "retrieve",
    "status": "running",
    "node_path": ["guardrails", "intent_cache", "agentic_router", "query_extract", "retrieve"]
  }
}
```

旧客户端忽略未知 `type` 即可，不影响最终答案。

## 前端展示

在会话消息气泡中增加一块轻量执行时间线：

- 消息生成中展示当前 running 节点。
- 消息完成后展示最终 node_path 和每个节点耗时。
- Agentic Router 节点展示 `selected_tool`、`decision_reason`、confidence 或 fallback。
- 最终节点展示 `tool_result` 摘要：decision、引用数、追问数、总耗时。
- 未知节点使用通用节点样式渲染。

UI 应保持客服工作台风格：紧凑、可扫描、默认不喧宾夺主。可以放在现有“调试详情”区域，也可以在流式生成中显示精简状态条。

## 错误与回退

- intent cache 命中：`intent.matched=true`，`agentic_router` 节点标记 `skipped`。
- Router 低置信：`agentic_router` 标记 `fallback`，`selected_tool=rag_search`。
- Router 异常：不得暴露内部异常，只记录安全 reason，例如 `router_exception`。
- RAG 阶段异常：trace 可标记 `failed`，最终仍遵循现有输出行为。

## 测试策略

后端测试：

- intent cache hit 产生 intent trace，Router skipped。
- `rag_search` 产生完整 RAG node_path 和 citations_count。
- `direct_response`、`clarify`、`human_handoff` 不伪造 retrieve/generate 节点。
- Router 低置信和异常回退为 `rag_search`。
- timings 秒级字段能映射为毫秒级 latency。

流式测试：

- `trace` 事件可选输出。
- 原有 `content`、`citations`、`done` 行为不变。
- 不支持 trace 的客户端仍能完成回答。

前端验证：

- 时间线展示 running、completed、skipped、fallback。
- 长 reason 和未知节点不撑破布局。
- 无 `debug.trace` 的历史消息仍正常显示。

## 风险与缓解

- trace 信息过多：默认展示摘要，详细内容放入调试详情。
- 字段与现有 timings 重复：后端复用 timings 数据，trace 只负责 UI 友好结构。
- 流式实时节点难以精确：先保证关键节点事件，细粒度阶段可以逐步补齐。
- 前端依赖 debug 字段：明确 `debug.trace` 可选，缺失时不影响现有消息。

## 验收

- OpenSpec `rag-trace-visualization` 严格校验通过。
- 设计不包含引入 LangGraph 的实现要求。
- 后续 build 任务可按后端 trace、流式事件、前端时间线、测试验收分批执行。
