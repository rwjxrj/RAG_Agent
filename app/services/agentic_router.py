"""Pre-RAG Agentic Router for lightweight tool selection."""

from __future__ import annotations

from dataclasses import dataclass, field


class AgenticRoute:
    RAG_SEARCH = "rag_search"
    DIRECT_RESPONSE = "direct_response"
    CLARIFY = "clarify"
    HUMAN_HANDOFF = "human_handoff"

    ALL = {RAG_SEARCH, DIRECT_RESPONSE, CLARIFY, HUMAN_HANDOFF}


@dataclass
class AgenticRouterInput:
    query: str
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    source: str = "reply"
    trace_id: str | None = None


@dataclass
class AgenticRouterDecision:
    route: str
    tool: str
    reason: str
    confidence: float
    query_for_tool: str | None = None
    clarifying_questions: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    fallback_to_rag: bool = False

    def __post_init__(self) -> None:
        if self.route not in AgenticRoute.ALL:
            raise ValueError(f"Unsupported agentic route: {self.route}")
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    def to_debug(self, *, skipped: bool = False) -> dict[str, object]:
        return {
            "route": self.route,
            "tool": self.tool,
            "reason": self.reason,
            "confidence": self.confidence,
            "skipped": skipped,
            "fallback_to_rag": self.fallback_to_rag,
        }


class AgenticRouter:
    def __init__(self, confidence_threshold: float = 0.55) -> None:
        self._confidence_threshold = confidence_threshold

    def route(self, payload: AgenticRouterInput) -> AgenticRouterDecision:
        query = (payload.query or "").strip()
        return AgenticRouterDecision(
            route=AgenticRoute.RAG_SEARCH,
            tool=AgenticRoute.RAG_SEARCH,
            reason="support_knowledge_question",
            confidence=0.86 if query else 0.0,
            query_for_tool=query or None,
            clarifying_questions=[],
            risk_flags=[],
            fallback_to_rag=False,
        )
