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

    @staticmethod
    def safe_fallback(reason: str = "router_exception") -> AgenticRouterDecision:
        return AgenticRouterDecision(
            route=AgenticRoute.RAG_SEARCH,
            tool=AgenticRoute.RAG_SEARCH,
            reason=reason,
            confidence=0.0,
            clarifying_questions=[],
            risk_flags=[],
            fallback_to_rag=True,
        )

    def route(self, payload: AgenticRouterInput) -> AgenticRouterDecision:
        try:
            decision = self._route(payload)
        except Exception:
            return self.safe_fallback("router_exception")
        if decision.confidence < self._confidence_threshold:
            return self.safe_fallback("router_low_confidence")
        return decision

    def _route(self, payload: AgenticRouterInput) -> AgenticRouterDecision:
        query = (payload.query or "").strip()
        normalized = query.lower()
        if not query:
            return self.safe_fallback("router_low_confidence")

        if self._is_human_handoff(normalized):
            return AgenticRouterDecision(
                route=AgenticRoute.HUMAN_HANDOFF,
                tool=AgenticRoute.HUMAN_HANDOFF,
                reason="human_only_action",
                confidence=0.9,
                clarifying_questions=[],
                risk_flags=["account_or_billing_action"],
                fallback_to_rag=False,
            )

        if self._is_greeting_or_capability(normalized):
            return AgenticRouterDecision(
                route=AgenticRoute.DIRECT_RESPONSE,
                tool=AgenticRoute.DIRECT_RESPONSE,
                reason="greeting_or_capability",
                confidence=0.88,
                query_for_tool=query,
                clarifying_questions=[],
                risk_flags=[],
                fallback_to_rag=False,
            )

        if self._needs_clarification(normalized):
            return AgenticRouterDecision(
                route=AgenticRoute.CLARIFY,
                tool=AgenticRoute.CLARIFY,
                reason="missing_critical_conditions",
                confidence=0.78,
                clarifying_questions=[
                    "请补充你的使用场景、预算或目标产品。",
                    "如果是服务器类问题，请说明系统、地区和配置要求。",
                ],
                risk_flags=[],
                fallback_to_rag=False,
            )

        return AgenticRouterDecision(
            route=AgenticRoute.RAG_SEARCH,
            tool=AgenticRoute.RAG_SEARCH,
            reason="support_knowledge_question",
            confidence=0.86,
            query_for_tool=query or None,
            clarifying_questions=[],
            risk_flags=[],
            fallback_to_rag=False,
        )

    @staticmethod
    def _is_greeting_or_capability(normalized: str) -> bool:
        greetings = ("你好", "您好", "hi", "hello", "hey")
        capability_terms = ("你能做什么", "能帮我做什么", "你是谁", "怎么使用你")
        return normalized in greetings or any(term in normalized for term in capability_terms)

    @staticmethod
    def _needs_clarification(normalized: str) -> bool:
        vague_terms = ("推荐一个套餐", "推荐套餐", "选哪个", "哪个好", "这个可以吗")
        has_specific_product = any(term in normalized for term in ("vps", "服务器", "域名", "ssl", "备份", "防火墙"))
        return any(term in normalized for term in vague_terms) and not has_specific_product

    @staticmethod
    def _is_human_handoff(normalized: str) -> bool:
        sensitive_terms = ("账号", "账单", "发票", "安全", "删除", "退款", "订单", "改订单", "取消订单")
        execution_terms = ("帮我", "给我", "替我", "执行", "处理", "删除", "退款", "修改", "取消")
        return any(term in normalized for term in sensitive_terms) and any(term in normalized for term in execution_terms)
