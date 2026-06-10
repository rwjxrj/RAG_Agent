---
change: rag-trace-visualization
design-doc: docs/superpowers/specs/2026-06-10-rag-trace-visualization-design.md
base-ref: 89a37ac22ed26e59abcece71f1294e55af9cdf2e
---

# RAG Trace Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为问答 RAG 流程增加轻量 trace 快照和流式 trace 事件，并在前端用紧凑时间线展示当前执行状态。

**Architecture:** 后端新增一次请求内存级 `TraceCollector`，只记录稳定逻辑节点和摘要，不参与业务决策。`AnswerService.generate()` 将 intent、Agentic Router、RAG 阶段和非 RAG 终止路径写入 `debug.trace`，流式会话在最终答案前补充可选 `trace` SSE 事件。前端扩展 `FlowDebug` 类型和会话页调试面板，优先渲染 `debug.trace`，无 trace 时保持现有展示。

**Tech Stack:** FastAPI、pytest、React、TypeScript、Vite、lucide-react。不得引入 LangGraph、数据库迁移、Docker 改动或新第三方依赖。

---

## 文件结构

- Create: `app/services/trace_collector.py`
  - 负责定义 trace 节点状态、节点展示标签、耗时转换和最终快照生成。
- Modify: `app/services/answer_service.py`
  - 在固定问答链路中创建并填充 trace；所有返回路径都通过 `_finish()` 附加 `debug.trace`。
- Modify: `app/api/routes/conversations.py`
  - 在 `messages:stream` 中输出可选 `trace` 事件；不改变现有 `status`、`ping`、`content`、`citations`、`done` 事件。
- Modify: `frontend/src/api/client.ts`
  - 增加 `TraceSnapshot`、`TraceNode`、`TraceLatency`、`TraceEventData` 类型。
- Modify: `frontend/src/pages/ConversationDetail.tsx`
  - 增加流式 trace 状态和 `TraceTimeline` 组件；在调试详情展示最终 trace。
- Test: `tests/test_trace_collector.py`
  - 覆盖 collector 的节点状态、耗时、intent、工具摘要和安全序列化。
- Test: `tests/test_answer_service.py`
  - 扩展现有 Agentic Router 入口测试，覆盖各 route 的 `debug.trace`。
- Test: `tests/test_agentic_router_entrypoints.py`
  - 扩展流式入口断言，确保 trace 事件可出现且不破坏答案事件。
- Modify: `openspec/changes/rag-trace-visualization/tasks.md`
  - 每完成一批实现后勾选对应任务。
- Modify: `.agent-harness/02_RAG_FLOW.md`
  - 因实际修改 RAG 查询链路，需要同步补充 trace 可视化节点说明。

## Task 1: 后端 TraceCollector 契约

**Files:**
- Create: `app/services/trace_collector.py`
- Test: `tests/test_trace_collector.py`
- Modify: `openspec/changes/rag-trace-visualization/tasks.md`

- [ ] **Step 1: 写失败测试**

在 `tests/test_trace_collector.py` 新增：

```python
from app.services.trace_collector import TraceCollector


def test_trace_collector_builds_snapshot_with_required_fields():
    trace = TraceCollector(trace_id="trace-1", source="reply")

    trace.start_node("intent_cache")
    trace.skip_node("intent_cache", reason="miss")
    trace.start_node("agentic_router")
    trace.complete_node(
        "agentic_router",
        selected_tool="rag_search",
        decision_reason="support_knowledge_question",
        tool_result={"route": "rag_search", "confidence": 0.86},
    )
    trace.set_tool_result(decision="PASS", citations_count=2, followup_count=0, confidence=0.7)
    trace.set_latency({"query_extract": 0.012, "retrieve": 0.2, "total": 0.5})

    snapshot = trace.to_debug()

    assert snapshot["trace_id"] == "trace-1"
    assert snapshot["source"] == "reply"
    assert snapshot["status"] == "completed"
    assert snapshot["selected_tool"] == "rag_search"
    assert snapshot["decision_reason"] == "support_knowledge_question"
    assert snapshot["node_path"] == ["intent_cache", "agentic_router"]
    assert snapshot["tool_result"] == {
        "decision": "PASS",
        "citations_count": 2,
        "followup_count": 0,
        "confidence": 0.7,
    }
    assert snapshot["latency"]["total_ms"] == 500
    assert snapshot["latency"]["nodes"]["retrieve"] == 200
    assert snapshot["nodes"][0]["status"] == "skipped"
    assert snapshot["nodes"][1]["status"] == "completed"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_trace_collector.py -q`

Expected: FAIL，原因是 `app.services.trace_collector` 尚不存在。

- [ ] **Step 3: 实现最小 TraceCollector**

创建 `app/services/trace_collector.py`，核心实现应包含：

```python
"""Lightweight answer trace collection for UI progress visualization."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


TRACE_NODE_LABELS: dict[str, str] = {
    "guardrails": "Guardrails",
    "intent_cache": "Intent Cache",
    "agentic_router": "Agentic Router",
    "query_extract": "Query Extract",
    "retrieve": "Retrieve",
    "assess_evidence": "Assess Evidence",
    "retry": "Retry",
    "generate": "Generate",
    "verify": "Verify",
    "direct_response": "Direct Response",
    "clarify": "Clarify",
    "human_handoff": "Human Handoff",
}


def _milliseconds(seconds: float | int | None) -> int | None:
    if seconds is None:
        return None
    return max(0, int(round(float(seconds) * 1000)))


@dataclass
class TraceNode:
    id: str
    status: str = "pending"
    label: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    latency_ms: int | None = None
    selected_tool: str | None = None
    decision_reason: str | None = None
    tool_result: dict[str, Any] | None = None
    reason: str | None = None

    def to_debug(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "label": self.label or TRACE_NODE_LABELS.get(self.id, self.id.replace("_", " ").title()),
            "status": self.status,
        }
        if self.latency_ms is not None:
            payload["latency_ms"] = self.latency_ms
        if self.selected_tool:
            payload["selected_tool"] = self.selected_tool
        if self.decision_reason:
            payload["decision_reason"] = self.decision_reason
        if self.reason:
            payload["reason"] = self.reason
        if self.tool_result is not None:
            payload["tool_result"] = dict(self.tool_result)
        return payload


@dataclass
class TraceCollector:
    trace_id: str | None = None
    source: str = "reply"
    status: str = "completed"
    intent: dict[str, Any] = field(default_factory=lambda: {"matched": False, "key": None})
    selected_tool: str | None = None
    decision_reason: str | None = None
    tool_result: dict[str, Any] = field(default_factory=dict)
    _nodes: dict[str, TraceNode] = field(default_factory=dict)
    _node_path: list[str] = field(default_factory=list)
    _latency: dict[str, float] = field(default_factory=dict)

    def _node(self, node_id: str) -> TraceNode:
        if node_id not in self._nodes:
            self._nodes[node_id] = TraceNode(id=node_id, label=TRACE_NODE_LABELS.get(node_id))
        if node_id not in self._node_path:
            self._node_path.append(node_id)
        return self._nodes[node_id]

    def start_node(self, node_id: str) -> None:
        node = self._node(node_id)
        node.status = "running"
        node.started_at = time.perf_counter()

    def complete_node(self, node_id: str, **metadata: Any) -> None:
        self._finish_node(node_id, "completed", **metadata)

    def skip_node(self, node_id: str, reason: str | None = None) -> None:
        self._finish_node(node_id, "skipped", reason=reason)

    def fallback_node(self, node_id: str, reason: str | None = None, **metadata: Any) -> None:
        self.status = "fallback"
        self._finish_node(node_id, "fallback", reason=reason, **metadata)

    def fail_node(self, node_id: str, reason: str | None = None) -> None:
        self.status = "failed"
        self._finish_node(node_id, "failed", reason=reason)

    def _finish_node(self, node_id: str, status: str, **metadata: Any) -> None:
        node = self._node(node_id)
        node.status = status
        node.finished_at = time.perf_counter()
        if node.started_at is not None:
            node.latency_ms = _milliseconds(node.finished_at - node.started_at)
        node.selected_tool = metadata.get("selected_tool") or node.selected_tool
        node.decision_reason = metadata.get("decision_reason") or node.decision_reason
        node.reason = metadata.get("reason") or node.reason
        if metadata.get("tool_result") is not None:
            node.tool_result = dict(metadata["tool_result"])
        if node.selected_tool:
            self.selected_tool = node.selected_tool
        if node.decision_reason:
            self.decision_reason = node.decision_reason

    def set_intent(self, matched: bool, key: str | None = None) -> None:
        self.intent = {"matched": bool(matched), "key": key}

    def set_tool_result(self, **result: Any) -> None:
        self.tool_result = {k: v for k, v in result.items() if v is not None}

    def set_latency(self, timings: dict[str, float]) -> None:
        self._latency = dict(timings or {})

    def to_debug(self) -> dict[str, Any]:
        nodes_latency = {
            key: value
            for key, seconds in self._latency.items()
            if key != "total" and (value := _milliseconds(seconds)) is not None
        }
        return {
            "trace_id": self.trace_id,
            "source": self.source,
            "status": self.status,
            "intent": dict(self.intent),
            "selected_tool": self.selected_tool,
            "decision_reason": self.decision_reason,
            "node_path": list(self._node_path),
            "tool_result": dict(self.tool_result),
            "latency": {
                "total_ms": _milliseconds(self._latency.get("total")),
                "nodes": nodes_latency,
            },
            "nodes": [self._nodes[node_id].to_debug() for node_id in self._node_path],
        }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_trace_collector.py -q`

Expected: PASS。

- [ ] **Step 5: 更新任务状态并提交**

勾选 `openspec/changes/rag-trace-visualization/tasks.md` 中 `1.1` 和 `1.3`，然后提交：

```bash
git add app/services/trace_collector.py tests/test_trace_collector.py openspec/changes/rag-trace-visualization/tasks.md
git commit -m "feat: add answer trace collector"
```

## Task 2: AnswerService 集成最终 trace 快照

**Files:**
- Modify: `app/services/answer_service.py`
- Modify: `tests/test_answer_service.py`
- Modify: `openspec/changes/rag-trace-visualization/tasks.md`
- Modify: `.agent-harness/02_RAG_FLOW.md`

- [ ] **Step 1: 写失败测试**

在 `tests/test_answer_service.py` 扩展现有测试：

```python
@pytest.mark.asyncio
async def test_intent_cache_hit_includes_trace(monkeypatch):
    class MatchedIntent:
        intent = "hello"
        answer = "intent answer"

    router = FakeRouter(AgenticRouterDecision(route=AgenticRoute.RAG_SEARCH, tool="rag_search", reason="support_knowledge_question", confidence=0.86))
    service = make_answer_service(router=router)
    monkeypatch.setattr("app.services.answer_service.match_intent", lambda query: MatchedIntent())

    output = await service.generate("你好", trace_id="trace-intent")

    trace = output.debug["trace"]
    assert trace["intent"] == {"matched": True, "key": "hello"}
    assert trace["selected_tool"] is None
    assert trace["node_path"] == ["intent_cache", "agentic_router"]
    assert trace["nodes"][0]["status"] == "completed"
    assert trace["nodes"][1]["status"] == "skipped"


@pytest.mark.asyncio
async def test_rag_route_includes_agentic_router_and_rag_trace():
    decision = AgenticRouterDecision(route=AgenticRoute.RAG_SEARCH, tool="rag_search", reason="support_knowledge_question", confidence=0.86)
    expected = AnswerOutput(decision="PASS", answer="RAG answered.", followup_questions=[], citations=[{"chunk_id": "c1"}], confidence=0.7, debug={})
    service = make_answer_service(router=FakeRouter(decision), orchestrator=FakeOrchestrator(output=expected))

    output = await service.generate("Windows VPS 多少钱？", trace_id="trace-rag")

    trace = output.debug["trace"]
    assert trace["selected_tool"] == "rag_search"
    assert trace["decision_reason"] == "support_knowledge_question"
    assert "agentic_router" in trace["node_path"]
    assert "query_extract" in trace["node_path"]
    assert trace["tool_result"]["decision"] == "PASS"
    assert trace["tool_result"]["citations_count"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_answer_service.py::test_intent_cache_hit_includes_trace tests/test_answer_service.py::test_rag_route_includes_agentic_router_and_rag_trace -q`

Expected: FAIL，原因是 `debug.trace` 尚未写入。

- [ ] **Step 3: 集成 TraceCollector**

在 `app/services/answer_service.py` 增加导入：

```python
from app.services.trace_collector import TraceCollector
```

在 `generate()` 开始创建：

```python
trace = TraceCollector(trace_id=trace_id, source="reply")
trace.start_node("intent_cache")
```

调整 `_finish()`，在返回前补齐工具结果、耗时和 `debug.trace`：

```python
def _finish(output: AnswerOutput, *, retry_count: int = 0) -> AnswerOutput:
    phase_timings["total"] = time.perf_counter() - total_started
    output = _attach_answer_runtime_debug(output, phase_timings, retry_count=retry_count)
    output.debug = output.debug or {}
    trace.set_tool_result(
        decision=output.decision,
        citations_count=len(output.citations or []),
        followup_count=len(output.followup_questions or []),
        confidence=output.confidence,
    )
    trace.set_latency(phase_timings)
    output.debug["trace"] = trace.to_debug()
    return output
```

关键路径填充规则：

```python
intent = match_intent(query)
if intent:
    trace.set_intent(True, intent.intent)
    trace.complete_node("intent_cache")
    trace.skip_node("agentic_router", reason="intent_cache_hit")
    return _finish(...)

trace.set_intent(False)
trace.skip_node("intent_cache", reason="miss")
trace.start_node("agentic_router")
try:
    agentic_decision = self._agentic_router.route(...)
    router_status = "fallback" if agentic_decision.fallback_to_rag else "completed"
except Exception:
    agentic_decision = AgenticRouter.safe_fallback("router_exception")
    router_status = "fallback"

router_payload = {
    "route": agentic_decision.route.value,
    "tool": agentic_decision.tool,
    "confidence": agentic_decision.confidence,
    "fallback_to_rag": agentic_decision.fallback_to_rag,
}
if router_status == "fallback":
    trace.fallback_node("agentic_router", reason=agentic_decision.reason, selected_tool=agentic_decision.tool, decision_reason=agentic_decision.reason, tool_result=router_payload)
else:
    trace.complete_node("agentic_router", selected_tool=agentic_decision.tool, decision_reason=agentic_decision.reason, tool_result=router_payload)
```

非 RAG 终止路径在返回前追加终止节点：

```python
trace.complete_node("direct_response", tool_result={"decision": "PASS"})
trace.complete_node("clarify", tool_result={"decision": "ASK_USER", "followup_count": len(followups)})
trace.complete_node("human_handoff", tool_result={"decision": "ESCALATE"})
```

RAG 路径在对应阶段周围补充节点：

```python
trace.start_node("query_extract")
# normalize / detect language
trace.complete_node("query_extract")

trace.start_node("retrieve")
trace.start_node("assess_evidence")
trace.start_node("generate")
trace.start_node("verify")
```

如果无法在 `AnswerService` 精确知道 orchestrator 内部阶段开始结束，先在调用 orchestrator 前按已知逻辑节点建立路径，并用 `phase_timings` 映射节点耗时。后续细粒度事件由 Task 3 在流式事件中补充。

- [ ] **Step 4: 运行后端入口测试**

Run: `pytest tests/test_answer_service.py tests/test_agentic_router.py -q`

Expected: PASS。

- [ ] **Step 5: 同步 RAG harness 文档**

在 `.agent-harness/02_RAG_FLOW.md` 的查询流程说明中补充：

```markdown
- Trace 可视化：问答入口可在 `debug.trace` 下返回可选执行快照，包含 intent、Agentic Router 选择、稳定逻辑节点路径、工具摘要和耗时。该字段仅用于前端体验和调试，不改变 RAG 决策。
```

- [ ] **Step 6: 更新任务状态并提交**

勾选 `openspec/changes/rag-trace-visualization/tasks.md` 中 `1.2` 和 `1.4`，然后提交：

```bash
git add app/services/answer_service.py tests/test_answer_service.py .agent-harness/02_RAG_FLOW.md openspec/changes/rag-trace-visualization/tasks.md
git commit -m "feat: attach trace snapshots to answer output"
```

## Task 3: 流式 Trace 事件

**Files:**
- Modify: `app/api/routes/conversations.py`
- Modify: `tests/test_agentic_router_entrypoints.py`
- Modify: `openspec/changes/rag-trace-visualization/tasks.md`

- [ ] **Step 1: 写失败测试**

在 `tests/test_agentic_router_entrypoints.py` 增加：

```python
@pytest.mark.asyncio
async def test_stream_conversation_emits_optional_trace_event(monkeypatch):
    async def fake_generate(self, query, conversation_history=None, trace_id=None):
        return AnswerOutput(
            decision="PASS",
            answer="RAG answered.",
            followup_questions=[],
            citations=[],
            confidence=0.8,
            debug={
                "trace": {
                    "trace_id": trace_id,
                    "source": "stream",
                    "status": "completed",
                    "selected_tool": "rag_search",
                    "decision_reason": "support_knowledge_question",
                    "node_path": ["intent_cache", "agentic_router", "retrieve", "generate"],
                    "tool_result": {"decision": "PASS", "citations_count": 0, "followup_count": 0},
                    "latency": {"total_ms": 10, "nodes": {}},
                    "nodes": [
                        {"id": "intent_cache", "label": "Intent Cache", "status": "skipped"},
                        {"id": "agentic_router", "label": "Agentic Router", "status": "completed", "selected_tool": "rag_search"},
                    ],
                }
            },
        )

    monkeypatch.setattr("app.services.answer_service.AnswerService.generate", fake_generate)

    response = await conversations.send_message_stream(
        conversation_id="conv-1",
        body=MessageCreate(content="Windows VPS 多少钱？"),
        db=FakeDb(),
        _auth="test-key",
    )

    payload = "".join([chunk.decode() if isinstance(chunk, bytes) else chunk async for chunk in response.body_iterator])
    assert '"type": "trace"' in payload
    assert '"node_id": "agentic_router"' in payload
    assert '"type": "content"' in payload
    assert '"type": "done"' in payload
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agentic_router_entrypoints.py::test_stream_conversation_emits_optional_trace_event -q`

Expected: FAIL，原因是流式入口尚未输出 `trace` 类型事件。

- [ ] **Step 3: 输出兼容 trace 事件**

在 `send_message_stream()` 的 `output = await generate_task` 之后、保存 assistant message 之前增加：

```python
trace_snapshot = (output.debug or {}).get("trace")
if isinstance(trace_snapshot, dict):
    for node in trace_snapshot.get("nodes", []):
        if not isinstance(node, dict):
            continue
        yield sse({
            "type": "trace",
            "data": {
                "trace_id": trace_snapshot.get("trace_id"),
                "node_id": node.get("id"),
                "status": node.get("status"),
                "node_path": trace_snapshot.get("node_path", []),
                "selected_tool": node.get("selected_tool") or trace_snapshot.get("selected_tool"),
                "decision_reason": node.get("decision_reason") or trace_snapshot.get("decision_reason"),
                "latency_ms": node.get("latency_ms"),
                "tool_result": node.get("tool_result"),
            },
        })
```

这不是实时节点级执行，只是现有流式结构下的兼容进度事件。后续若 `AnswerService` 支持回调，可将同一事件形状提前输出。

- [ ] **Step 4: 运行流式入口测试**

Run: `pytest tests/test_agentic_router_entrypoints.py -q`

Expected: PASS，现有 `done`、`content` 行为不变。

- [ ] **Step 5: 更新任务状态并提交**

勾选 `openspec/changes/rag-trace-visualization/tasks.md` 中 `2.1`、`2.2`、`2.3`，然后提交：

```bash
git add app/api/routes/conversations.py tests/test_agentic_router_entrypoints.py openspec/changes/rag-trace-visualization/tasks.md
git commit -m "feat: emit trace events in conversation stream"
```

## Task 4: 前端 Trace 时间线

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/ConversationDetail.tsx`
- Modify: `openspec/changes/rag-trace-visualization/tasks.md`

- [ ] **Step 1: 扩展 TypeScript 类型**

在 `frontend/src/api/client.ts` 的 `FlowDebug` 前新增：

```ts
export type TraceNodeStatus = 'pending' | 'running' | 'completed' | 'skipped' | 'failed' | 'fallback'

export interface TraceNode {
  id: string
  label?: string
  status: TraceNodeStatus | string
  latency_ms?: number | null
  selected_tool?: string | null
  decision_reason?: string | null
  reason?: string | null
  tool_result?: Record<string, unknown> | null
}

export interface TraceSnapshot {
  trace_id?: string | null
  source?: string
  status?: string
  intent?: { matched?: boolean; key?: string | null }
  selected_tool?: string | null
  decision_reason?: string | null
  node_path?: string[]
  tool_result?: Record<string, unknown>
  latency?: { total_ms?: number | null; nodes?: Record<string, number> }
  nodes?: TraceNode[]
}

export interface TraceEventData {
  trace_id?: string | null
  node_id?: string | null
  status?: TraceNodeStatus | string
  node_path?: string[]
  selected_tool?: string | null
  decision_reason?: string | null
  latency_ms?: number | null
  tool_result?: Record<string, unknown> | null
}
```

并在 `FlowDebug` 中增加：

```ts
trace?: TraceSnapshot
agentic_router?: {
  route?: string
  tool?: string
  reason?: string
  confidence?: number
  skipped?: boolean
  fallback_to_rag?: boolean
}
```

- [ ] **Step 2: 增加流式 trace 状态**

在 `frontend/src/pages/ConversationDetail.tsx` 导入类型：

```ts
type TraceEventData,
type TraceSnapshot,
type TraceNode,
```

在组件状态中增加：

```ts
const [streamTrace, setStreamTrace] = useState<TraceSnapshot | null>(null)
```

发送前清空：

```ts
setStreamTrace(null)
```

SSE 解析中处理：

```ts
else if (data?.type === 'trace' && typeof data.data === 'object' && data.data) {
  const traceData = data.data as TraceEventData
  setStreamTrace((prev) => mergeTraceEvent(prev, traceData))
}
```

注意需要把 SSE payload 类型从 `{ type?: string; data?: string }` 扩展为：

```ts
let data: { type?: string; data?: unknown } | null = null
```

- [ ] **Step 3: 增加 trace 合并和时间线组件**

在同文件底部新增：

```tsx
function mergeTraceEvent(prev: TraceSnapshot | null, event: TraceEventData): TraceSnapshot {
  const nodeId = event.node_id || 'unknown'
  const existingNodes = prev?.nodes ?? []
  const nextNode: TraceNode = {
    id: nodeId,
    label: nodeId.replace(/_/g, ' '),
    status: event.status || 'running',
    latency_ms: event.latency_ms,
    selected_tool: event.selected_tool,
    decision_reason: event.decision_reason,
    tool_result: event.tool_result,
  }
  const nodes = existingNodes.some((node) => node.id === nodeId)
    ? existingNodes.map((node) => node.id === nodeId ? { ...node, ...nextNode } : node)
    : [...existingNodes, nextNode]
  return {
    ...(prev ?? {}),
    trace_id: event.trace_id ?? prev?.trace_id,
    selected_tool: event.selected_tool ?? prev?.selected_tool,
    decision_reason: event.decision_reason ?? prev?.decision_reason,
    node_path: event.node_path ?? prev?.node_path ?? nodes.map((node) => node.id),
    nodes,
  }
}

function TraceTimeline({ trace }: { trace?: TraceSnapshot | null }) {
  if (!trace) return null
  const nodes = trace.nodes?.length
    ? trace.nodes
    : (trace.node_path ?? []).map((id) => ({ id, label: id.replace(/_/g, ' '), status: 'completed' }))
  if (!nodes.length) return null
  return (
    <div className="mt-2 rounded-xl border border-sky-100 bg-sky-50 p-3 text-xs">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-zinc-500">
        {trace.selected_tool && <span>工具：<span className="text-zinc-300">{trace.selected_tool}</span></span>}
        {trace.decision_reason && <span>原因：<span className="text-zinc-300">{trace.decision_reason}</span></span>}
        {trace.latency?.total_ms != null && <span>耗时：<span className="text-zinc-300">{trace.latency.total_ms}ms</span></span>}
      </div>
      <ol className="space-y-1.5">
        {nodes.map((node) => (
          <li key={node.id} className="flex min-w-0 items-center gap-2">
            <span className={`h-2 w-2 shrink-0 rounded-full ${traceStatusClass(node.status)}`} />
            <span className="min-w-0 flex-1 truncate text-zinc-300">{node.label || node.id}</span>
            {node.latency_ms != null && <span className="shrink-0 text-zinc-500">{node.latency_ms}ms</span>}
            <span className="shrink-0 text-zinc-500">{traceStatusLabel(node.status)}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}

function traceStatusClass(status?: string) {
  if (status === 'completed') return 'bg-emerald-400'
  if (status === 'running') return 'bg-violet-400 animate-pulse'
  if (status === 'skipped') return 'bg-zinc-500'
  if (status === 'fallback') return 'bg-amber-400'
  if (status === 'failed') return 'bg-red-400'
  return 'bg-zinc-600'
}

function traceStatusLabel(status?: string) {
  if (status === 'completed') return '完成'
  if (status === 'running') return '执行中'
  if (status === 'skipped') return '跳过'
  if (status === 'fallback') return '回退'
  if (status === 'failed') return '失败'
  return status || '待执行'
}
```

- [ ] **Step 4: 在消息区渲染时间线**

在 streaming assistant 气泡中内容后增加：

```tsx
<TraceTimeline trace={streamTrace} />
```

在 `FlowDebugPanel` 顶部增加：

```tsx
{debug.trace && (
  <DebugSection icon={<Zap size={13} />} title="执行 Trace">
    <TraceTimeline trace={debug.trace} />
  </DebugSection>
)}
```

并把 `hasDebug` 判定补充 `debug.trace`：

```ts
debug.trace || debug.decision != null || ...
```

- [ ] **Step 5: 运行前端构建**

Run: `cd frontend; npm run build`

Expected: PASS。

- [ ] **Step 6: 更新任务状态并提交**

勾选 `openspec/changes/rag-trace-visualization/tasks.md` 中 `3.1`、`3.2`、`3.3`、`3.4`，然后提交：

```bash
git add frontend/src/api/client.ts frontend/src/pages/ConversationDetail.tsx openspec/changes/rag-trace-visualization/tasks.md
git commit -m "feat: show answer trace timeline"
```

## Task 5: 验收与一致性验证

**Files:**
- Modify: `tests/test_answer_service.py`
- Modify: `tests/test_agentic_router_entrypoints.py`
- Modify: `openspec/changes/rag-trace-visualization/tasks.md`

- [ ] **Step 1: 补齐路由矩阵测试**

在 `tests/test_answer_service.py` 为以下场景断言 `debug.trace`：

```python
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route", "expected_decision", "expected_node"),
    [
        (AgenticRoute.DIRECT_RESPONSE, "PASS", "direct_response"),
        (AgenticRoute.CLARIFY, "ASK_USER", "clarify"),
        (AgenticRoute.HUMAN_HANDOFF, "ESCALATE", "human_handoff"),
    ],
)
async def test_non_rag_routes_include_terminal_trace(route, expected_decision, expected_node):
    decision = AgenticRouterDecision(
        route=route,
        tool=route.value,
        reason="test_reason",
        confidence=0.8,
        clarifying_questions=["请补充地区"] if route == AgenticRoute.CLARIFY else [],
    )
    service = make_answer_service(router=FakeRouter(decision))

    output = await service.generate("你好", trace_id="trace-route")

    assert output.decision == expected_decision
    assert expected_node in output.debug["trace"]["node_path"]
    assert "retrieve" not in output.debug["trace"]["node_path"]
```

- [ ] **Step 2: 补齐回退测试**

在 `tests/test_answer_service.py` 增加：

```python
@pytest.mark.asyncio
async def test_router_exception_trace_marks_fallback():
    class BrokenRouter:
        def route(self, payload):
            raise RuntimeError("boom")

    service = make_answer_service(router=BrokenRouter(), orchestrator=FakeOrchestrator())

    output = await service.generate("VPS 怎么配置？", trace_id="trace-fallback")

    trace = output.debug["trace"]
    assert trace["status"] == "fallback"
    assert trace["selected_tool"] == "rag_search"
    assert any(node["id"] == "agentic_router" and node["status"] == "fallback" for node in trace["nodes"])
```

- [ ] **Step 3: 运行后端测试**

Run: `pytest tests/test_trace_collector.py tests/test_answer_service.py tests/test_agentic_router.py tests/test_agentic_router_entrypoints.py -q`

Expected: PASS。

- [ ] **Step 4: 运行前端构建**

Run: `cd frontend; npm run build`

Expected: PASS。

- [ ] **Step 5: OpenSpec 严格校验**

Run: `openspec validate rag-trace-visualization --strict`

Expected: PASS。

- [ ] **Step 6: 更新任务状态并提交**

勾选 `openspec/changes/rag-trace-visualization/tasks.md` 中 `4.1`、`4.2`、`4.3`、`4.4`，然后提交：

```bash
git add tests/test_answer_service.py tests/test_agentic_router_entrypoints.py openspec/changes/rag-trace-visualization/tasks.md
git commit -m "test: cover answer trace visualization"
```

## 自查清单

- OpenSpec 覆盖：Task 1-5 覆盖最终快照、intent/Router、稳定节点名、工具摘要、耗时、流式事件、未知节点前端渲染。
- 顶层 API 兼容：只新增 `debug.trace` 和可选 SSE `trace` 事件，不移除现有字段。
- 安全边界：不引入 LangGraph，不新增依赖，不修改数据库、Docker、认证逻辑。
- Harness 同步：Task 2 修改 RAG 查询链路时同步 `.agent-harness/02_RAG_FLOW.md`。
- 分批执行建议：第一批执行 Task 1-2；第二批执行 Task 3-4；第三批执行 Task 5 和 build guard。
