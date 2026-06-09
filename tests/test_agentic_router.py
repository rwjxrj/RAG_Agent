import pytest

from app.services.agentic_router import (
    AgenticRoute,
    AgenticRouter,
    AgenticRouterDecision,
    AgenticRouterInput,
)


def test_router_input_keeps_supported_source_and_history():
    payload = AgenticRouterInput(
        query="Windows VPS 多少钱？",
        conversation_history=[{"role": "user", "content": "你好"}],
        source="reply",
        trace_id="trace-1",
    )

    assert payload.query == "Windows VPS 多少钱？"
    assert payload.conversation_history == [{"role": "user", "content": "你好"}]
    assert payload.source == "reply"
    assert payload.trace_id == "trace-1"


def test_router_decision_debug_payload_is_stable():
    decision = AgenticRouterDecision(
        route=AgenticRoute.RAG_SEARCH,
        tool="rag_search",
        reason="support_knowledge_question",
        confidence=0.86,
        query_for_tool="Windows VPS pricing",
        clarifying_questions=[],
        risk_flags=[],
        fallback_to_rag=False,
    )

    assert decision.to_debug() == {
        "route": "rag_search",
        "tool": "rag_search",
        "reason": "support_knowledge_question",
        "confidence": 0.86,
        "skipped": False,
        "fallback_to_rag": False,
    }


def test_invalid_route_raises_value_error():
    with pytest.raises(ValueError, match="Unsupported agentic route"):
        AgenticRouterDecision(
            route="unsupported",
            tool="unsupported",
            reason="bad_route",
            confidence=0.5,
            clarifying_questions=[],
            risk_flags=[],
            fallback_to_rag=False,
        )


def test_router_default_route_is_rag_search_for_knowledge_question():
    router = AgenticRouter()

    decision = router.route(AgenticRouterInput(query="怎么配置 VPS 的防火墙？"))

    assert decision.route == AgenticRoute.RAG_SEARCH
    assert decision.tool == "rag_search"
    assert decision.reason == "support_knowledge_question"
    assert decision.confidence >= 0.8
    assert decision.fallback_to_rag is False


def test_direct_response_for_greeting():
    router = AgenticRouter()

    decision = router.route(AgenticRouterInput(query="你好"))

    assert decision.route == AgenticRoute.DIRECT_RESPONSE
    assert decision.tool == "direct_response"
    assert decision.reason == "greeting_or_capability"
    assert decision.confidence >= 0.8


def test_direct_response_for_capability_question():
    router = AgenticRouter()

    decision = router.route(AgenticRouterInput(query="你能帮我做什么？"))

    assert decision.route == AgenticRoute.DIRECT_RESPONSE
    assert decision.reason == "greeting_or_capability"


def test_clarify_for_missing_critical_conditions():
    router = AgenticRouter()

    decision = router.route(AgenticRouterInput(query="帮我推荐一个套餐"))

    assert decision.route == AgenticRoute.CLARIFY
    assert decision.tool == "clarify"
    assert decision.reason == "missing_critical_conditions"
    assert 1 <= len(decision.clarifying_questions) <= 3


def test_human_handoff_for_billing_and_execution_request():
    router = AgenticRouter()

    decision = router.route(AgenticRouterInput(query="帮我把订单退款并删除账号"))

    assert decision.route == AgenticRoute.HUMAN_HANDOFF
    assert decision.tool == "human_handoff"
    assert decision.reason == "human_only_action"
    assert "account_or_billing_action" in decision.risk_flags


def test_low_confidence_falls_back_to_rag():
    router = AgenticRouter(confidence_threshold=0.95)

    decision = router.route(AgenticRouterInput(query="这个可以吗"))

    assert decision.route == AgenticRoute.RAG_SEARCH
    assert decision.tool == "rag_search"
    assert decision.reason == "router_low_confidence"
    assert decision.fallback_to_rag is True


def test_exception_safe_route_falls_back_to_rag():
    decision = AgenticRouter.safe_fallback("router_exception")

    assert decision.route == AgenticRoute.RAG_SEARCH
    assert decision.reason == "router_exception"
    assert decision.fallback_to_rag is True
