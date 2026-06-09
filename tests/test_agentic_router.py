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
