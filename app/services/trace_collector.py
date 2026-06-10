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
            "label": self.label
            or TRACE_NODE_LABELS.get(self.id, self.id.replace("_", " ").title()),
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
    intent: dict[str, Any] = field(
        default_factory=lambda: {"matched": False, "key": None}
    )
    selected_tool: str | None = None
    decision_reason: str | None = None
    tool_result: dict[str, Any] = field(default_factory=dict)
    _nodes: dict[str, TraceNode] = field(default_factory=dict)
    _node_path: list[str] = field(default_factory=list)
    _latency: dict[str, float] = field(default_factory=dict)

    def _node(self, node_id: str) -> TraceNode:
        if node_id not in self._nodes:
            self._nodes[node_id] = TraceNode(
                id=node_id,
                label=TRACE_NODE_LABELS.get(node_id),
            )
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

    def fallback_node(
        self,
        node_id: str,
        reason: str | None = None,
        **metadata: Any,
    ) -> None:
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
        self.tool_result = {key: value for key, value in result.items() if value is not None}

    def set_latency(self, timings: dict[str, float]) -> None:
        self._latency = dict(timings or {})

    def to_debug(self) -> dict[str, Any]:
        nodes_latency: dict[str, int] = {}
        for key, seconds in self._latency.items():
            if key == "total":
                continue
            value = _milliseconds(seconds)
            if value is not None:
                nodes_latency[key] = value
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
