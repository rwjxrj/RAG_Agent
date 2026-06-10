## Context

当前 RAG 查询线已经具备固定阶段：guardrails、intent cache、Agentic Router、query extract、retrieve、assess evidence、retry、generate、verify。后端已有 `debug_metadata.timings` 和 `debug.agentic_router`，但这些信息更偏调试字段，缺少统一的前端可视化契约。

用户期望在问答过程中看到系统正在执行什么，包括 `intent`、`selected_tool`、`decision_reason`、`node_path`、`tool_result`、`latency`。这不是要引入完整工作流引擎，而是把现有链路以轻量 trace 形式呈现出来，并保持字段与具体实现解耦。

## Goals / Non-Goals

**Goals:**

- 定义一套轻量 trace 数据模型，覆盖节点名称、状态、决策字段、工具结果和耗时。
- 保持现有 API 顶层返回兼容，将 trace 放在可选 debug/metadata 区域。
- 支持前端展示“当前执行中、已完成、跳过、失败回退”等状态。
- 支持三类问答入口语义一致，尤其是流式会话可以逐步展示节点进度。
- 让 `node_path` 使用稳定逻辑节点名，避免绑定 Python 函数名、类名或具体框架。

**Non-Goals:**

- 本阶段不引入 LangGraph。
- 后续实现也不引入 LangGraph。
- 不新增第三方依赖。
- 不修改数据库 schema 或持久化结构要求。
- 不改变 Agentic Router 的路由结果和 RAG 主链路行为。
- 不要求前端实现复杂可拖拽图编辑器；只规划用户可理解的执行流程展示。

## Decisions

### Decision 1: 使用可选 trace 快照作为最小契约

后端最终响应应可包含一个完整 trace 快照，用于非流式入口和历史消息回看。

概念结构：

```json
{
  "debug": {
    "trace": {
      "trace_id": "可选追踪 ID",
      "source": "reply|conversation|stream",
      "status": "running|completed|failed|fallback",
      "intent": {
        "matched": false,
        "key": null
      },
      "selected_tool": "rag_search",
      "decision_reason": "support_knowledge_question",
      "node_path": [
        "guardrails",
        "intent_cache",
        "agentic_router",
        "query_extract",
        "retrieve",
        "assess_evidence",
        "generate",
        "verify"
      ],
      "tool_result": {
        "decision": "PASS",
        "citations_count": 3,
        "followup_count": 0
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
  }
}
```

理由：当前系统已通过 debug 返回非业务字段，继续放在 debug 下可以避免破坏顶层 API。替代方案是在顶层新增 `trace` 字段，但会扩大客户端兼容面。

### Decision 2: 每个节点使用统一事件语义

每个 trace 节点建议具备统一字段：

```json
{
  "id": "agentic_router",
  "label": "Agentic Router",
  "status": "pending|running|completed|skipped|failed|fallback",
  "started_at": "ISO-8601 可选",
  "finished_at": "ISO-8601 可选",
  "latency_ms": 12,
  "selected_tool": "rag_search",
  "decision_reason": "support_knowledge_question",
  "tool_result": {
    "route": "rag_search",
    "confidence": 0.86
  }
}
```

理由：统一节点格式能同时服务最终快照、流式事件和未来 LangGraph 节点状态。替代方案是为每个阶段设计独立字段，但会让前端需要大量分支判断。

### Decision 3: `node_path` 采用稳定的逻辑节点名

`node_path` 不应直接绑定 Python 函数名，而应使用稳定逻辑名：

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

理由：稳定逻辑名更适合前端展示，也能承受内部函数、类或模块重构。替代方案是暴露内部类名/函数名，但会增加重构成本和泄露实现细节。

### Decision 4: 前端展示以进度时间线为主

前端建议优先展示紧凑时间线，而不是复杂流程图：

- 当前执行节点高亮。
- 已完成节点显示耗时。
- `selected_tool` 和 `decision_reason` 显示在 Agentic Router 节点。
- `tool_result` 显示在最终节点或工具节点。
- `latency.total_ms` 显示总耗时。

理由：客服问答场景需要快速理解状态，时间线比大型节点图更适合嵌入消息区。后续即使内部流程重构，前端仍按稳定节点状态渲染。

### Decision 5: 流式入口优先输出增量事件，非流式返回最终快照

同步接口可以只返回最终 trace 快照；流式接口可在 SSE 中增加可选 trace 事件：

```json
{
  "event": "trace",
  "data": {
    "trace_id": "trace-id",
    "node_id": "retrieve",
    "status": "running",
    "node_path": ["guardrails", "intent_cache", "agentic_router", "query_extract", "retrieve"]
  }
}
```

理由：流式会话最需要“正在执行什么”的即时反馈。替代方案是所有接口都轮询状态，但当前项目没有独立任务状态存储，复杂度更高。

## Risks / Trade-offs

- Trace 暴露过多内部信息 → 只展示稳定逻辑节点和摘要，错误详情不向用户泄露。
- 流式事件增加前端状态复杂度 → 先以可选事件实现，未识别事件的客户端仍可忽略。
- 耗时字段不完全精确 → 明确为用户体验和调试用途，不作为严格性能计费指标。
- 与现有 `debug_metadata.timings` 重复 → trace 可以复用 timings，但对外提供更适合 UI 的 `latency_ms` 和节点状态。
- 内部流程重构后节点增多 → 保持 `node_path` 为数组，允许未来追加子节点，不改变前端基础渲染。

## Migration Plan

1. 后续实现先在后端构造 trace 快照，不改变业务决策。
2. 为 Agentic Router 和 RAG 阶段填充最小节点状态。
3. 在同步/非流式接口返回最终快照。
4. 在流式接口补充可选 trace SSE 事件。
5. 前端先实现紧凑时间线展示，未知节点按通用节点渲染。
6. 后续内部流程重构时，继续将阶段状态映射到同一 trace 契约，不引入 LangGraph。

回滚策略：trace 是可选 debug/事件字段，关闭输出后应恢复到现有问答表现，不影响答案生成。

## Open Questions

- trace 默认是否只在 debug 模式展示，还是普通用户也展示精简版本？
- `tool_result` 是否需要对不同客户角色做脱敏或隐藏？
- 流式 SSE 事件名称最终采用 `trace` 还是复用现有事件通道，需要实现时以当前前端解析代码为准。
