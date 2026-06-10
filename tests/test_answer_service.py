"""Tests for answer service helpers."""

import pytest

from app.services.answer_utils import (
    apply_answer_plan,
    build_answer_plan,
    collect_rewrite_candidates,
    parse_llm_response,
    render_calibrated_candidate,
    resolve_retrieval_query,
)
from app.services.agentic_router import AgenticRoute, AgenticRouterDecision
from app.services.answer_service import AnswerService
from app.services.evidence_quality import QualityReport
from app.services.retry_planner import RetryStrategy
from app.services.schemas import AnswerOutput, DecisionResult, QuerySpec


class FakeRouter:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    def route(self, payload):
        self.calls.append(payload)
        return self.decision


class FakeOrchestrator:
    def __init__(self, output: AnswerOutput | None = None):
        self.output = output
        self.calls = []

    async def run(self, ctx, handlers):
        self.calls.append(ctx)
        if self.output is not None:
            return self.output
        return AnswerOutput(
            decision="PASS",
            answer="RAG answered.",
            followup_questions=[],
            citations=[],
            confidence=0.7,
            debug={},
        )


def make_answer_service(*, router, orchestrator: FakeOrchestrator | None = None) -> AnswerService:
    return AnswerService(
        retrieval=object(),
        llm=object(),
        reviewer=object(),
        orchestrator=orchestrator or FakeOrchestrator(),
        agentic_router=router,
    )


@pytest.mark.asyncio
async def test_intent_cache_hit_skips_agentic_router(monkeypatch):
    class MatchedIntent:
        intent = "hello"
        answer = "intent answer"

    decision = AgenticRouterDecision(
        route=AgenticRoute.RAG_SEARCH,
        tool="rag_search",
        reason="support_knowledge_question",
        confidence=0.86,
    )
    router = FakeRouter(decision)
    service = make_answer_service(router=router)
    monkeypatch.setattr("app.services.answer_service.match_intent", lambda query: MatchedIntent())

    output = await service.generate("你好", trace_id="trace-intent")

    assert output.decision == "PASS"
    assert output.answer == "intent answer"
    assert router.calls == []
    assert output.debug["intent_cache"] == "hello"
    assert output.debug["agentic_router"] == {
        "skipped": True,
        "reason": "intent_cache_hit",
    }


@pytest.mark.asyncio
async def test_intent_cache_hit_includes_trace(monkeypatch):
    class MatchedIntent:
        intent = "hello"
        answer = "intent answer"

    decision = AgenticRouterDecision(
        route=AgenticRoute.RAG_SEARCH,
        tool="rag_search",
        reason="support_knowledge_question",
        confidence=0.86,
    )
    router = FakeRouter(decision)
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
async def test_direct_response_returns_pass_without_rag(monkeypatch):
    monkeypatch.setattr("app.services.answer_service.match_intent", lambda query: None)
    decision = AgenticRouterDecision(
        route=AgenticRoute.DIRECT_RESPONSE,
        tool="direct_response",
        reason="greeting_or_capability",
        confidence=0.88,
    )
    router = FakeRouter(decision)
    orchestrator = FakeOrchestrator()
    service = make_answer_service(router=router, orchestrator=orchestrator)

    output = await service.generate("你好", trace_id="trace-router")

    assert output.decision == "PASS"
    assert output.citations == []
    assert output.confidence == 0.88
    assert output.debug["trace_id"] == "trace-router"
    assert output.debug["agentic_router"]["route"] == "direct_response"
    assert router.calls[0].source == "reply"
    assert orchestrator.calls == []


@pytest.mark.asyncio
async def test_clarify_returns_ask_user_with_followups():
    decision = AgenticRouterDecision(
        route=AgenticRoute.CLARIFY,
        tool="clarify",
        reason="missing_critical_conditions",
        confidence=0.78,
        clarifying_questions=["你需要哪个地区？"],
    )
    service = make_answer_service(router=FakeRouter(decision))

    output = await service.generate("帮我推荐一个套餐")

    assert output.decision == "ASK_USER"
    assert output.followup_questions == ["你需要哪个地区？"]
    assert output.citations == []
    assert output.debug["agentic_router"]["route"] == "clarify"


@pytest.mark.asyncio
async def test_human_handoff_returns_escalate():
    decision = AgenticRouterDecision(
        route=AgenticRoute.HUMAN_HANDOFF,
        tool="human_handoff",
        reason="human_only_action",
        confidence=0.9,
        risk_flags=["account_or_billing_action"],
    )
    service = make_answer_service(router=FakeRouter(decision))

    output = await service.generate("帮我退款")

    assert output.decision == "ESCALATE"
    assert output.citations == []
    assert output.debug["agentic_router"]["route"] == "human_handoff"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route", "expected_decision", "expected_node"),
    [
        (AgenticRoute.DIRECT_RESPONSE, "PASS", "direct_response"),
        (AgenticRoute.CLARIFY, "ASK_USER", "clarify"),
        (AgenticRoute.HUMAN_HANDOFF, "ESCALATE", "human_handoff"),
    ],
)
async def test_non_rag_routes_include_terminal_trace(monkeypatch, route, expected_decision, expected_node):
    monkeypatch.setattr("app.services.answer_service.match_intent", lambda query: None)
    decision = AgenticRouterDecision(
        route=route,
        tool=route,
        reason="test_reason",
        confidence=0.8,
        clarifying_questions=["请补充地区"] if route == AgenticRoute.CLARIFY else [],
    )
    service = make_answer_service(router=FakeRouter(decision))

    output = await service.generate("你好", trace_id="trace-route")

    trace = output.debug["trace"]
    assert output.decision == expected_decision
    assert trace["selected_tool"] == route
    assert trace["decision_reason"] == "test_reason"
    assert expected_node in trace["node_path"]
    assert "retrieve" not in trace["node_path"]
    assert trace["tool_result"]["decision"] == expected_decision


@pytest.mark.asyncio
async def test_rag_route_preserves_existing_output_debug_and_citations():
    decision = AgenticRouterDecision(
        route=AgenticRoute.RAG_SEARCH,
        tool="rag_search",
        reason="support_knowledge_question",
        confidence=0.86,
    )
    expected = AnswerOutput(
        decision="PASS",
        answer="Windows VPS starts at the cited plan.",
        followup_questions=[],
        citations=[{"chunk_id": "c1", "source_url": "https://example.com/windows"}],
        confidence=0.7,
        debug={"existing": True},
    )
    service = make_answer_service(
        router=FakeRouter(decision),
        orchestrator=FakeOrchestrator(output=expected),
    )

    output = await service.generate("Windows VPS 多少钱？")

    assert output is expected
    assert output.citations == [{"chunk_id": "c1", "source_url": "https://example.com/windows"}]
    assert output.debug["existing"] is True
    assert output.debug["agentic_router"]["route"] == "rag_search"


@pytest.mark.asyncio
async def test_rag_route_includes_agentic_router_and_rag_trace(monkeypatch):
    async def no_query_spec(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.answer_service.normalize_query", no_query_spec)
    decision = AgenticRouterDecision(
        route=AgenticRoute.RAG_SEARCH,
        tool="rag_search",
        reason="support_knowledge_question",
        confidence=0.86,
    )
    expected = AnswerOutput(
        decision="PASS",
        answer="RAG answered.",
        followup_questions=[],
        citations=[{"chunk_id": "c1"}],
        confidence=0.7,
        debug={},
    )
    service = make_answer_service(
        router=FakeRouter(decision),
        orchestrator=FakeOrchestrator(output=expected),
    )

    output = await service.generate("Windows VPS 多少钱？", trace_id="trace-rag")

    trace = output.debug["trace"]
    assert trace["selected_tool"] == "rag_search"
    assert trace["decision_reason"] == "support_knowledge_question"
    assert "agentic_router" in trace["node_path"]
    assert "query_extract" in trace["node_path"]
    assert trace["tool_result"]["decision"] == "PASS"
    assert trace["tool_result"]["citations_count"] == 1


@pytest.mark.asyncio
async def test_router_exception_falls_back_to_rag():
    class BrokenRouter:
        def route(self, payload):
            raise RuntimeError("boom")

    expected = AnswerOutput(
        decision="PASS",
        answer="RAG still answered.",
        followup_questions=[],
        citations=[{"chunk_id": "c1", "source_url": "https://example.com"}],
        confidence=0.6,
        debug={},
    )
    service = make_answer_service(
        router=BrokenRouter(),
        orchestrator=FakeOrchestrator(output=expected),
    )

    output = await service.generate("VPS 怎么配置？")

    assert output.answer == "RAG still answered."
    assert output.debug["agentic_router"]["reason"] == "router_exception"
    assert output.debug["agentic_router"]["fallback_to_rag"] is True


@pytest.mark.asyncio
async def test_router_exception_trace_marks_fallback(monkeypatch):
    async def no_query_spec(*args, **kwargs):
        return None

    class BrokenRouter:
        def route(self, payload):
            raise RuntimeError("boom")

    monkeypatch.setattr("app.services.answer_service.normalize_query", no_query_spec)
    service = make_answer_service(router=BrokenRouter(), orchestrator=FakeOrchestrator())

    output = await service.generate("VPS 怎么配置？", trace_id="trace-fallback")

    trace = output.debug["trace"]
    assert trace["status"] == "fallback"
    assert trace["selected_tool"] == "rag_search"
    assert trace["decision_reason"] == "router_exception"
    assert any(
        node["id"] == "agentic_router" and node["status"] == "fallback"
        for node in trace["nodes"]
    )


def test_collect_rewrite_candidates_dedupes_case_insensitive():
    spec = QuerySpec(
        intent="transactional",
        entities=[],
        constraints={},
        required_evidence=[],
        risk_level="low",
        keyword_queries=[],
        semantic_queries=[],
        clarifying_questions=[],
        is_ambiguous=False,
        rewrite_candidates=["Pricing Query", "pricing query", "Dedicated pricing"],
    )

    candidates = collect_rewrite_candidates("pricing query", spec)

    assert candidates == ["pricing query", "Dedicated pricing"]


def test_resolve_retrieval_query_uses_rewrite_candidate_on_retry():
    spec = QuerySpec(
        intent="transactional",
        entities=[],
        constraints={},
        required_evidence=[],
        risk_level="low",
        keyword_queries=[],
        semantic_queries=[],
        clarifying_questions=[],
        is_ambiguous=False,
        rewrite_candidates=["pricing query", "dedicated monthly pricing"],
    )

    query, source, candidates = resolve_retrieval_query(
        base_query="pricing query",
        attempt=2,
        query_spec=spec,
        retry_strategy=None,
    )

    assert query == "dedicated monthly pricing"
    assert source == "rewrite_candidate_1"
    assert candidates == ["pricing query", "dedicated monthly pricing"]


def test_resolve_retrieval_query_prefers_retry_strategy_suggestion():
    spec = QuerySpec(
        intent="transactional",
        entities=[],
        constraints={},
        required_evidence=[],
        risk_level="low",
        keyword_queries=[],
        semantic_queries=[],
        clarifying_questions=[],
        is_ambiguous=False,
        rewrite_candidates=["pricing query", "dedicated monthly pricing"],
    )
    strategy = RetryStrategy(suggested_query="policy refund terms")

    query, source, _ = resolve_retrieval_query(
        base_query="pricing query",
        attempt=2,
        query_spec=spec,
        retry_strategy=strategy,
        explicit_override="reviewer suggested query",
    )

    assert query == "policy refund terms"
    assert source == "retry_strategy_suggested_query"


def test_build_answer_plan_for_pass_partial_lane():
    spec = QuerySpec(
        intent="transactional",
        entities=[],
        constraints={},
        required_evidence=["has_any_url"],
        risk_level="low",
        keyword_queries=[],
        semantic_queries=[],
        clarifying_questions=[],
        is_ambiguous=False,
        hard_requirements=["numbers_units"],
    )
    dr = DecisionResult(
        decision="PASS",
        reason="partial_sufficient",
        clarifying_questions=[],
        partial_links=[],
        answer_policy="bounded",
        lane="PASS_PARTIAL",
    )
    report = QualityReport(
        quality_score=0.35,
        feature_scores={"numbers_units": 0.1},
        missing_signals=["missing_links"],
        staleness_risk=None,
        boilerplate_risk=0.0,
    )

    plan = build_answer_plan(dr, spec, report)

    assert plan.lane == "CANDIDATE_VERIFY"
    assert plan.allowed_claim_scope == "partial"
    assert plan.tone_policy == "cautious"
    assert "numbers_units" in plan.required_citations


def test_apply_answer_plan_bounds_pass_partial_output():
    plan = build_answer_plan(
        DecisionResult(
            decision="PASS",
            reason="partial_sufficient",
            clarifying_questions=["Which region do you prefer?"],
            partial_links=[],
            answer_policy="bounded",
            lane="PASS_PARTIAL",
        ),
        None,
        None,
    )

    decision, answer, followup, confidence = apply_answer_plan(
        plan,
        {
            "decision": "ASK_USER",
            "answer": "The available evidence shows the service starts at $10/month.",
            "followup_questions": ["Which plan do you want?"],
            "confidence": 0.92,
        },
    )

    assert decision == "PASS"
    assert followup == ["Which plan do you want?"]
    assert confidence == 0.6
    assert "unverified" in answer.lower() or "best available" in answer.lower() or "best we have" in answer.lower()


def test_apply_answer_plan_uses_router_followup_for_pass_partial_when_llm_omits_it():
    plan = build_answer_plan(
        DecisionResult(
            decision="PASS",
            reason="answerable_with_refinement",
            clarifying_questions=["What budget range works for you?"],
            partial_links=[],
            answer_policy="bounded",
            lane="PASS_PARTIAL",
        ),
        None,
        None,
    )

    decision, answer, followup, confidence = apply_answer_plan(
        plan,
        {
            "decision": "PASS",
            "answer": "A good starting point is 4 GB RAM and 2 vCPU.",
            "followup_questions": [],
            "confidence": 0.8,
        },
    )

    assert decision == "PASS"
    assert "starting point" in answer
    assert followup == ["What budget range works for you?"]
    assert confidence == 0.6


def test_empty_llm_parse_fallback_stays_clarification_under_pass_partial_plan():
    plan = build_answer_plan(
        DecisionResult(
            decision="PASS",
            reason="partial_sufficient",
            clarifying_questions=[],
            partial_links=[],
            answer_policy="bounded",
            lane="PASS_PARTIAL",
        ),
        None,
        None,
    )

    parsed = parse_llm_response("")
    decision, answer, followup, confidence = apply_answer_plan(plan, parsed)

    assert decision == "ASK_USER"
    assert "one more detail" in answer.lower()
    assert "trouble formatting" not in answer.lower()
    assert "best we have" not in answer.lower()
    assert followup == ["Could you provide more details about your question?"]
    assert confidence == 0.0


def test_render_calibrated_candidate_for_pass_exact():
    answer, followup = render_calibrated_candidate(
        {
            "answer_text": "Order at https://example.com/order/windows-vps",
            "followup_questions": ["Do you need monthly or yearly billing?"],
            "disclaimers": [],
        },
        calibrated_lane="PASS_EXACT",
        fallback_answer="fallback",
        fallback_followup=[],
    )

    assert "https://example.com/order/windows-vps" in answer
    assert followup == ["Do you need monthly or yearly billing?"]


def test_render_calibrated_candidate_adds_partial_disclaimer_when_missing():
    answer, followup = render_calibrated_candidate(
        {
            "answer_text": "Closest page we found is https://example.com/pricing/windows-vps.",
            "followup_questions": [],
            "disclaimers": [],
        },
        calibrated_lane="PASS_PARTIAL",
        fallback_answer="fallback",
        fallback_followup=["Which region do you need?"],
    )

    assert "best we have" in answer.lower() or "best available" in answer.lower() or "closest" in answer.lower()
    assert followup == ["Which region do you need?"]


def test_render_calibrated_candidate_adds_partial_disclaimer_without_candidate():
    answer, followup = render_calibrated_candidate(
        None,
        calibrated_lane="PASS_PARTIAL",
        fallback_answer="Closest page we found is https://example.com/pricing/windows-vps.",
        fallback_followup=["Which region do you need?"],
    )

    assert "best we have" in answer.lower() or "best available" in answer.lower() or "closest" in answer.lower()
    assert followup == ["Which region do you need?"]


def test_parse_llm_response_supports_optional_advice_block():
    parsed = parse_llm_response(
        """
        {
          "decision": "PASS",
          "candidate": {
            "answer_type": "general",
            "answer_mode": "PASS_PARTIAL",
            "answer_text": "Based on our docs, NEWSEO1 starts at $16/month and NEWSEO2 starts at $26/month.",
            "citations": [{"chunk_id": "chunk-price-1", "source_url": "https://example.com/seo", "doc_type": "pricing"}],
            "advice": {
              "enabled": true,
              "text": "If you are just starting out, I would begin with NEWSEO2 for a safer default.",
              "basis": ["balanced default", "budget not provided"],
              "confidence": 0.58
            }
          }
        }
        """
    )

    candidate = parsed["candidate"]
    assert candidate["answer_text"].startswith("Based on our docs")
    assert candidate["advice_enabled"] is True
    assert "NEWSEO2" in candidate["advice_text"]
    assert candidate["advice_basis"] == ["balanced default", "budget not provided"]


def test_render_calibrated_candidate_appends_safe_advice_block():
    answer, followup = render_calibrated_candidate(
        {
            "answer_text": "Based on our docs, NEWSEO1 starts at $16/month and NEWSEO2 starts at $26/month.",
            "followup_questions": ["What budget range works for you?"],
            "disclaimers": [],
            "advice_enabled": True,
            "advice_text": "If you are just starting out, I would begin with NEWSEO2 for a safer default.",
            "metadata": {},
        },
        calibrated_lane="PASS_PARTIAL",
        fallback_answer="fallback",
        fallback_followup=[],
    )

    assert "my recommendation:" in answer.lower()
    assert "NEWSEO2" in answer
    assert followup == ["What budget range works for you?"]


def test_render_calibrated_candidate_drops_fact_like_advice_block():
    answer, _ = render_calibrated_candidate(
        {
            "answer_text": "Based on our docs, NEWSEO1 starts at $16/month and NEWSEO2 starts at $26/month.",
            "followup_questions": [],
            "disclaimers": [],
            "advice_enabled": True,
            "advice_text": "Choose NEWSEO3 at $46/month here: https://example.com/newseo3",
            "metadata": {},
        },
        calibrated_lane="PASS_EXACT",
        fallback_answer="fallback",
        fallback_followup=[],
    )

    assert "my recommendation:" not in answer.lower()
    assert "https://example.com/newseo3" not in answer
