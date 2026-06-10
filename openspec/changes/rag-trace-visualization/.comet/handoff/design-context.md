# Comet Design Handoff

- Change: rag-trace-visualization
- Phase: design
- Mode: compact
- Context hash: 41a4ec14ede55aef106e8d5e5ffef2812e1b855e1a667081c200bc86555caaeb

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/rag-trace-visualization/proposal.md

- Source: openspec/changes/rag-trace-visualization/proposal.md
- Lines: 1-33
- SHA256: c3db4224d5a4d50c807d139cf94de48ff02b3879c1eefa10357388ff6363b9b9

```md
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
```

## openspec/changes/rag-trace-visualization/design.md

- Source: openspec/changes/rag-trace-visualization/design.md
- Lines: 1-173
- SHA256: 02ea172bb8dac2ab7877f5653c18a9d0d4729f7c7f3fd1cc6ced40b4fd632e05

[TRUNCATED]

```md
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
```

Full source: openspec/changes/rag-trace-visualization/design.md

## openspec/changes/rag-trace-visualization/tasks.md

- Source: openspec/changes/rag-trace-visualization/tasks.md
- Lines: 1-26
- SHA256: 06577b11ae86b3b6a16c1b0ae72956f4784e0b2c1d4ae42b74f10ad6a5a4e8ae

```md
## 1. 后端 Trace 契约

- [ ] 1.1 定义 trace 快照字段结构，覆盖 `intent`、`selected_tool`、`decision_reason`、`node_path`、`tool_result`、`latency` 和节点状态。
- [ ] 1.2 在 AnswerService 问答入口聚合 trace 上下文，确保 intent hit、Agentic Router、RAG 路径和非 RAG 路径都能产出一致快照。
- [ ] 1.3 将现有 `debug_metadata.timings` 映射为毫秒级 `latency.total_ms` 和节点级 `latency.nodes`。
- [ ] 1.4 为 Router 低置信、异常回退和 intent cache 命中补充明确 trace 状态。

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
```

## openspec/changes/rag-trace-visualization/specs/rag-trace-visualization/spec.md

- Source: openspec/changes/rag-trace-visualization/specs/rag-trace-visualization/spec.md
- Lines: 1-78
- SHA256: e7bcbe56648b61a7db968a4289537b7753083ef5b0a080bdb75f1d45784f7e04

```md
## ADDED Requirements

### Requirement: Trace exposes RAG execution progress
The system SHALL expose a structured, optional trace for supported question-answering flows so the frontend can show the current execution progress.

#### Scenario: Final response includes trace snapshot
- **WHEN** a supported non-streaming question-answering request completes
- **THEN** the response metadata MUST be able to include a trace snapshot containing execution status, node path, selected tool, decision reason, tool result, and latency summary

#### Scenario: Trace remains optional
- **WHEN** a client does not read trace metadata
- **THEN** the existing top-level API response fields MUST remain compatible and sufficient for normal answer rendering

### Requirement: Trace records intent and Agentic Router decisions
The system SHALL record intent cache and Agentic Router decision information in the trace when those stages are reached.

#### Scenario: Intent cache hit is visible
- **WHEN** intent cache matches a configured intent
- **THEN** the trace MUST indicate the matched intent key and MUST indicate that Agentic Router was skipped

#### Scenario: Router-selected tool is visible
- **WHEN** intent cache misses and Agentic Router selects a route
- **THEN** the trace MUST include `selected_tool`, `decision_reason`, and Router confidence or fallback status when available

### Requirement: Trace node path uses stable logical names
The system SHALL represent execution path with stable logical node names rather than implementation-specific function or class names.

#### Scenario: RAG path records logical nodes
- **WHEN** a request enters the standard RAG path
- **THEN** `node_path` MUST include logical nodes such as `guardrails`, `intent_cache`, `agentic_router`, `query_extract`, `retrieve`, `assess_evidence`, `generate`, and `verify`

#### Scenario: Non-RAG path records terminal tool
- **WHEN** Agentic Router selects `direct_response`, `clarify`, or `human_handoff`
- **THEN** `node_path` MUST include the selected terminal tool node and MUST NOT imply that retrieval or generation ran

### Requirement: Trace reports tool result summaries
The system SHALL summarize tool outcomes without exposing sensitive internal details.

#### Scenario: RAG result summarizes evidence output
- **WHEN** the RAG path completes
- **THEN** `tool_result` MUST be able to include the final decision, citation count, follow-up count, and confidence when available

#### Scenario: Human handoff hides internal details
- **WHEN** the route is `human_handoff`
- **THEN** `tool_result` MUST summarize the handoff decision without exposing private account, billing, security, or exception details

### Requirement: Trace reports latency by total and node
The system SHALL report latency in a frontend-friendly format.

#### Scenario: Total latency is available
- **WHEN** a trace snapshot is produced
- **THEN** it MUST include total latency in milliseconds when measurable

#### Scenario: Node latency is available when measured
- **WHEN** a node or RAG phase timing is measured
- **THEN** the trace MUST expose that timing as node-level latency in milliseconds

### Requirement: Streaming entrypoint can emit trace progress events
The system SHALL allow the streaming conversation entrypoint to emit optional trace progress events before the final answer is complete.

#### Scenario: Stream emits running node event
- **WHEN** a streaming request starts a traceable node
- **THEN** the stream MAY emit a trace event containing `trace_id`, `node_id`, `status`, and current `node_path`

#### Scenario: Clients can ignore trace events
- **WHEN** a client does not support trace events
- **THEN** the stream MUST still deliver the answer using the existing response behavior

### Requirement: Trace remains workflow-framework agnostic
The system SHALL keep trace fields independent from any workflow framework and MUST NOT require LangGraph.

#### Scenario: Node path remains stable across internal refactors
- **WHEN** the RAG flow internals are refactored without changing user-facing behavior
- **THEN** existing trace consumers MUST be able to render the flow from `node_path` and node status without requiring a new top-level response contract

#### Scenario: Unknown future nodes are renderable
- **WHEN** a future implementation emits additional node IDs
- **THEN** the frontend MUST be able to render them as generic trace nodes rather than failing
```

