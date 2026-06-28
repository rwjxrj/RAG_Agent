"""Tests for Orchestrator state machine per RAG_DEVELOPMENT_STRATEGY."""

import pytest

from app.services.orchestrator import (
    Orchestrator,
    PipelineRunner,
    OrchestratorAction,
    OrchestratorContext,
    OrchestratorState,
    PhaseResult,
)
from app.services.reviewer import ReviewerResult, ReviewerStatus
from app.services.schemas import DecisionResult, QuerySpec, ReviewResult, VerifyPhaseOutput
from app.services.evidence_quality import QualityReport


def _ctx(
    state: OrchestratorState = OrchestratorState.INIT,
    query: str = "test",
    max_attempts: int = 2,
    **kwargs,
) -> OrchestratorContext:
    return OrchestratorContext(query=query, state=state, max_attempts=max_attempts, **kwargs)


def test_next_action_init_returns_intent_cache():
    orch = Orchestrator()
    ctx = _ctx(OrchestratorState.INIT)
    assert orch.next_action(ctx) == OrchestratorAction.INTENT_CACHE


def test_next_action_understanding_returns_retrieve():
    orch = Orchestrator()
    ctx = _ctx(OrchestratorState.UNDERSTANDING)
    assert orch.next_action(ctx) == OrchestratorAction.RETRIEVE


def test_next_action_retrieving_with_evidence_returns_assess():
    orch = Orchestrator()
    ctx = _ctx(OrchestratorState.RETRIEVING, evidence=[{"id": "1"}])
    assert orch.next_action(ctx, has_evidence=True) == OrchestratorAction.ASSESS_EVIDENCE


def test_next_action_retrieving_no_evidence_can_retry_returns_retry():
    orch = Orchestrator()
    ctx = _ctx(OrchestratorState.RETRIEVING, retrieval_attempt=0, max_attempts=2)
    assert orch.next_action(ctx, has_evidence=False) == OrchestratorAction.RETRY_RETRIEVE


def test_next_action_retrieving_no_evidence_no_retry_returns_ask_user():
    orch = Orchestrator()
    ctx = _ctx(OrchestratorState.RETRIEVING, retrieval_attempt=2, max_attempts=2)
    assert orch.next_action(ctx, has_evidence=False) == OrchestratorAction.ASK_USER


def test_next_action_retrieving_blocking_clarification_skips_retry_and_decides():
    orch = Orchestrator()
    ctx = _ctx(
        OrchestratorState.RETRIEVING,
        retrieval_attempt=0,
        max_attempts=2,
        query_spec=QuerySpec(
            intent="ambiguous",
            entities=[],
            constraints={},
            required_evidence=[],
            risk_level="low",
            keyword_queries=[],
            semantic_queries=[],
            clarifying_questions=["Which product are you asking about?"],
            is_ambiguous=True,
            answerable_without_clarification=False,
            blocking_clarifying_questions=["Which product are you asking about?"],
        ),
    )
    assert orch.next_action(ctx, has_evidence=False) == OrchestratorAction.DECIDE


def test_next_action_assessing_quality_fail_can_retry_returns_retry():
    orch = Orchestrator()
    ctx = _ctx(
        OrchestratorState.ASSESSING,
        passes_quality_gate=False,
        retrieval_attempt=0,
        max_attempts=2,
    )
    assert orch.next_action(ctx) == OrchestratorAction.RETRY_RETRIEVE


def test_next_action_assessing_quality_llm_failure_skips_retry():
    orch = Orchestrator()
    ctx = _ctx(
        OrchestratorState.ASSESSING,
        passes_quality_gate=False,
        retrieval_attempt=0,
        max_attempts=4,
        quality_report=QualityReport(
            quality_score=0.0,
            feature_scores={},
            missing_signals=["quality_llm_failed"],
            staleness_risk=None,
            boilerplate_risk=None,
            gate_pass=False,
            reason="LLM quality assessment failed.",
        ),
    )

    assert orch.next_action(ctx) == OrchestratorAction.DECIDE


def test_next_action_assessing_quality_fail_no_retry_returns_decide():
    orch = Orchestrator()
    ctx = _ctx(
        OrchestratorState.ASSESSING,
        passes_quality_gate=False,
        retrieval_attempt=2,
        max_attempts=2,
    )
    assert orch.next_action(ctx) == OrchestratorAction.DECIDE


def test_next_action_deciding_pass_returns_generate():
    orch = Orchestrator()
    ctx = _ctx(OrchestratorState.DECIDING)
    ctx.decision_result = DecisionResult(
        decision="PASS",
        reason="sufficient",
        clarifying_questions=[],
        partial_links=[],
        lane="PASS_EXACT",
    )
    assert orch.next_action(ctx) == OrchestratorAction.GENERATE


def test_next_action_deciding_candidate_verify_returns_generate():
    orch = Orchestrator()
    ctx = _ctx(OrchestratorState.DECIDING)
    ctx.decision_result = DecisionResult(
        decision="PASS",
        reason="sufficient",
        clarifying_questions=[],
        partial_links=[],
        lane="CANDIDATE_VERIFY",
    )
    assert orch.next_action(ctx) == OrchestratorAction.GENERATE


def test_next_action_deciding_targeted_retry_returns_retry_when_available():
    orch = Orchestrator()
    ctx = _ctx(
        OrchestratorState.DECIDING,
        retrieval_attempt=0,
        max_attempts=2,
    )
    ctx.decision_result = DecisionResult(
        decision="PASS",
        reason="exact_targeted_retry",
        clarifying_questions=[],
        partial_links=[],
        lane="TARGETED_RETRY",
    )
    assert orch.next_action(ctx) == OrchestratorAction.RETRY_RETRIEVE


def test_next_action_deciding_targeted_retry_returns_ask_user_when_exhausted():
    orch = Orchestrator()
    ctx = _ctx(
        OrchestratorState.DECIDING,
        retrieval_attempt=2,
        max_attempts=2,
    )
    ctx.decision_result = DecisionResult(
        decision="PASS",
        reason="exact_targeted_retry",
        clarifying_questions=[],
        partial_links=[],
        lane="TARGETED_RETRY",
    )
    assert orch.next_action(ctx) == OrchestratorAction.ASK_USER


def test_next_action_deciding_escalate_returns_escalate():
    orch = Orchestrator()
    ctx = _ctx(OrchestratorState.DECIDING)
    ctx.decision_result = DecisionResult(
        decision="ESCALATE",
        reason="high_risk",
        clarifying_questions=[],
        partial_links=[],
        lane="ESCALATE",
    )
    assert orch.next_action(ctx) == OrchestratorAction.ESCALATE


def test_next_action_deciding_ask_user_returns_ask_user():
    """ASK_USER from decision router is terminal."""
    orch = Orchestrator()
    ctx = _ctx(
        OrchestratorState.DECIDING,
        retrieval_attempt=0,
        max_attempts=2,
    )
    ctx.decision_result = DecisionResult(
        decision="ASK_USER",
        reason="missing_evidence",
        clarifying_questions=[],
        partial_links=[],
        lane="ASK_USER",
    )
    assert orch.next_action(ctx) == OrchestratorAction.ASK_USER


def test_next_action_reviewing_pass_returns_done():
    orch = Orchestrator()
    ctx = _ctx(OrchestratorState.REVIEWING)
    ctx._last_reviewer_result = type("R", (), {"status": type("S", (), {"value": "PASS"})()})()
    assert orch.next_action(ctx, reviewer_status="PASS") == OrchestratorAction.DONE


def test_next_action_reviewing_retrieve_more_defaults_to_ask_user():
    orch = Orchestrator()
    ctx = _ctx(
        OrchestratorState.REVIEWING,
        retrieval_attempt=0,
        max_attempts=2,
    )
    assert orch.next_action(ctx, reviewer_status="RETRIEVE_MORE") == OrchestratorAction.ASK_USER


def test_next_action_reviewing_ask_user_can_schedule_targeted_retry():
    orch = Orchestrator()
    ctx = _ctx(
        OrchestratorState.GENERATING,
        retrieval_attempt=0,
        max_attempts=2,
    )
    rr = ReviewerResult(
        status=ReviewerStatus.ASK_USER,
        reasons=["Answer type mismatch for exact task."],
        suggested_queries=["windows vps order page", "windows vps product page"],
        missing_fields=["exact_answer_type"],
        retry_reason="type_mismatch",
    )
    orch._apply_result(
        ctx,
        OrchestratorAction.VERIFY,
        PhaseResult(reviewer_result=rr),
    )

    assert ctx.state == OrchestratorState.REVIEWING
    assert ctx.retry_query_override == "windows vps order page"
    assert ctx.verify_output.targeted_retry_pending is True
    assert orch.next_action(ctx, reviewer_status="ASK_USER") == OrchestratorAction.RETRY_RETRIEVE


def test_next_action_reviewing_ask_user_no_second_targeted_retry():
    orch = Orchestrator()
    ctx = _ctx(
        OrchestratorState.GENERATING,
        retrieval_attempt=1,
        max_attempts=2,
        verify_output=VerifyPhaseOutput(targeted_retry_used=True),
    )
    rr = ReviewerResult(
        status=ReviewerStatus.ASK_USER,
        reasons=["Answer type mismatch for exact task."],
        suggested_queries=["windows vps order page"],
        missing_fields=["exact_answer_type"],
        retry_reason="type_mismatch",
    )
    orch._apply_result(
        ctx,
        OrchestratorAction.VERIFY,
        PhaseResult(reviewer_result=rr),
    )

    assert ctx.verify_output.targeted_retry_pending is not True
    assert orch.next_action(ctx, reviewer_status="ASK_USER") == OrchestratorAction.ASK_USER


def test_next_action_reviewing_ask_user_no_targeted_retry_when_flag_disabled():
    orch = Orchestrator()
    orch._settings.targeted_retry_enabled = False
    ctx = _ctx(
        OrchestratorState.GENERATING,
        retrieval_attempt=0,
        max_attempts=2,
    )
    rr = ReviewerResult(
        status=ReviewerStatus.ASK_USER,
        reasons=["Answer type mismatch for exact task."],
        suggested_queries=["windows vps order page"],
        missing_fields=["exact_answer_type"],
        retry_reason="type_mismatch",
    )
    orch._apply_result(
        ctx,
        OrchestratorAction.VERIFY,
        PhaseResult(reviewer_result=rr),
    )

    assert ctx.verify_output.targeted_retry_pending is not True
    assert orch.next_action(ctx, reviewer_status="ASK_USER") == OrchestratorAction.ASK_USER


def test_next_action_retrying_returns_retrieve():
    orch = Orchestrator()
    ctx = _ctx(OrchestratorState.RETRYING)
    assert orch.next_action(ctx) == OrchestratorAction.RETRIEVE


def test_retry_retrieve_clears_review_result():
    """RETRY_RETRIEVE should clear review_result to prevent stale lane override."""
    orch = Orchestrator()
    ctx = _ctx(
        OrchestratorState.REVIEWING,
        retrieval_attempt=0,
        max_attempts=2,
    )
    ctx.review_result = ReviewResult(
        status="ask_user",
        unsupported_claims=[],
        weakly_supported_claims=[],
        claim_to_citation_map={},
        reviewer_notes=[],
        final_lane="ASK_USER",
    )
    ctx.decision_result = DecisionResult(
        decision="PASS",
        reason="evidence passed",
        clarifying_questions=[],
        partial_links=[],
        lane="CANDIDATE_VERIFY",
    )

    orch._apply_result(ctx, OrchestratorAction.RETRY_RETRIEVE, PhaseResult())

    assert ctx.review_result is None
    assert ctx.decision_result is None
    assert ctx.retrieval_attempt == 1
    assert ctx.state == OrchestratorState.RETRYING


def test_current_lane_prefers_decision_result_after_retry():
    """After retry clears review_result, decision_result should take precedence."""
    ctx = _ctx()
    ctx.review_result = None
    ctx.decision_result = DecisionResult(
        decision="PASS",
        reason="evidence passed",
        clarifying_questions=[],
        partial_links=[],
        lane="CANDIDATE_VERIFY",
    )
    assert ctx.current_lane() == "CANDIDATE_VERIFY"


def test_targeted_retry_end_to_end_state_transition():
    """Full state machine path: Reviewer ASK_USER → RETRY_RETRIEVE → DECIDE=CANDIDATE_VERIFY → GENERATE."""
    orch = Orchestrator()
    
    ctx = _ctx(
        OrchestratorState.REVIEWING,
        retrieval_attempt=0,
        max_attempts=3,
    )
    
    ctx.review_result = ReviewResult(
        status="ask_user",
        unsupported_claims=["claim1"],
        weakly_supported_claims=[],
        claim_to_citation_map={},
        reviewer_notes=["type mismatch"],
        final_lane="ASK_USER",
    )
    ctx.verify_output.targeted_retry_pending = True
    ctx.verify_output.targeted_retry_used = True
    ctx.retry_query_override = "better query"
    
    assert ctx.current_lane() == "ASK_USER"
    
    next_act = orch.next_action(ctx, reviewer_status="ASK_USER")
    assert next_act == OrchestratorAction.RETRY_RETRIEVE
    
    orch._apply_result(ctx, OrchestratorAction.RETRY_RETRIEVE, PhaseResult())
    
    assert ctx.state == OrchestratorState.RETRYING
    assert ctx.review_result is None
    assert ctx.decision_result is None
    assert ctx.retrieval_attempt == 1
    
    next_act = orch.next_action(ctx)
    assert next_act == OrchestratorAction.RETRIEVE
    
    ctx.state = OrchestratorState.ASSESSING
    ctx.passes_quality_gate = True
    
    next_act = orch.next_action(ctx, has_evidence=True)
    assert next_act == OrchestratorAction.DECIDE
    
    ctx.state = OrchestratorState.DECIDING
    ctx.decision_result = DecisionResult(
        decision="PASS",
        reason="evidence now sufficient",
        clarifying_questions=[],
        partial_links=[],
        lane="CANDIDATE_VERIFY",
    )
    
    assert ctx.current_lane() == "CANDIDATE_VERIFY"
    
    next_act = orch.next_action(ctx)
    assert next_act == OrchestratorAction.GENERATE
    ctx = _ctx()
    ctx.add_stage_reason("understand", "query_spec_ready")
    ctx.add_stage_reason("retrieve", "chunks=5")
    assert len(ctx.stage_reasons) == 2
    assert "understand: query_spec_ready" in ctx.stage_reasons[0]
    assert "retrieve: chunks=5" in ctx.stage_reasons[1]


def test_context_can_retry():
    ctx = _ctx(retrieval_attempt=0, max_attempts=2)
    assert ctx.can_retry() is True
    ctx.retrieval_attempt = 1
    assert ctx.can_retry() is True
    ctx.retrieval_attempt = 2
    assert ctx.can_retry() is False


def test_context_current_lane_from_decision_result():
    ctx = _ctx()
    ctx.decision_result = DecisionResult(
        decision="PASS",
        reason="sufficient",
        clarifying_questions=[],
        partial_links=[],
        lane="PASS_PARTIAL",
    )
    assert ctx.current_lane() == "PASS_PARTIAL"


@pytest.mark.asyncio
async def test_run_terminates_on_ask_user():
    """Run terminates when handler returns terminal output for ASK_USER."""
    class MockRunner(PipelineRunner):
        async def execute(self, ctx, action):
            if action == OrchestratorAction.UNDERSTAND:
                return PhaseResult(
                    query_spec=QuerySpec(
                        intent="informational",
                        entities=[],
                        constraints={},
                        required_evidence=[],
                        risk_level="low",
                        keyword_queries=[],
                        semantic_queries=[],
                        clarifying_questions=[],
                    ),
                    effective_query="test",
                )
            if action == OrchestratorAction.RETRIEVE:
                return PhaseResult(evidence=[], evidence_pack=None)
            raise NotImplementedError(action)

        async def build_output(self, ctx, action):
            return {"decision": action.value, "answer": ""}

    orch = MockRunner(retrieval=object(), llm=object(), reviewer=object())
    ctx = OrchestratorContext(
        query="test",
        state=OrchestratorState.UNDERSTANDING,
        max_attempts=1,
    )
    out = await orch.run(ctx)
    assert out["decision"] == "ask_user"


@pytest.mark.asyncio
async def test_run_records_phase_timings_for_executed_actions():
    """Run records timings without changing phase order or terminal output."""
    from app.services.reviewer import ReviewerResult, ReviewerStatus

    class MockRunner(PipelineRunner):
        async def execute(self, ctx, action):
            if action == OrchestratorAction.UNDERSTAND:
                return PhaseResult(effective_query="test")
            if action == OrchestratorAction.RETRIEVE:
                return PhaseResult(evidence=[{"id": "1"}])
            if action == OrchestratorAction.ASSESS_EVIDENCE:
                return PhaseResult(passes_quality_gate=True)
            if action == OrchestratorAction.DECIDE:
                return PhaseResult(
                    decision_result=DecisionResult(
                        decision="PASS",
                        reason="sufficient",
                        clarifying_questions=[],
                        partial_links=[],
                        lane="PASS_EXACT",
                    )
                )
            if action == OrchestratorAction.GENERATE:
                return PhaseResult(answer="answer", confidence=0.8)
            if action == OrchestratorAction.VERIFY:
                return PhaseResult(
                    reviewer_result=ReviewerResult(
                        status=ReviewerStatus.PASS,
                        reasons=[],
                        suggested_queries=[],
                        missing_fields=[],
                    )
                )
            raise NotImplementedError(action)

        async def build_output(self, ctx, action):
            return {
                "decision": action.value,
                "timings": ctx.orchestrator_debug.phase_timings,
            }

    orch = MockRunner(retrieval=object(), llm=object(), reviewer=object())
    ctx = OrchestratorContext(
        query="test",
        state=OrchestratorState.UNDERSTANDING,
        max_attempts=1,
    )

    out = await orch.run(ctx)

    assert out["decision"] == "done"
    timings = out["timings"]
    assert timings["retrieve"] >= 0.0
    assert timings["assess_evidence"] >= 0.0
    assert timings["generate"] >= 0.0
    assert timings["verify"] >= 0.0


@pytest.mark.asyncio
async def test_orchestrator_executes_retrieve_with_owned_dependency(monkeypatch):
    """Orchestrator owns phase dependencies instead of receiving a handler layer."""
    retrieval = object()
    llm = object()
    reviewer = object()
    calls = []

    async def fake_execute_retrieve(ctx, *, retrieval, orchestrator, settings):
        calls.append((ctx, retrieval, orchestrator, settings))
        return PhaseResult(evidence=[])

    monkeypatch.setattr(
        "app.services.phases.execute_retrieve",
        fake_execute_retrieve,
    )
    orch = Orchestrator(retrieval=retrieval, llm=llm, reviewer=reviewer)
    ctx = OrchestratorContext(query="test")

    result = await orch.execute(ctx, OrchestratorAction.RETRIEVE)

    assert result.evidence == []
    assert calls == [(ctx, retrieval, orch, orch._settings)]


@pytest.mark.asyncio
async def test_run_returns_cached_intent_before_router():
    class MatchedIntent:
        intent = "hello"
        answer = "cached answer"

    class RouterMustNotRun:
        def route(self, payload):
            raise AssertionError("router must be skipped on intent cache hit")

    orch = Orchestrator(
        retrieval=object(),
        llm=object(),
        reviewer=object(),
        agentic_router=RouterMustNotRun(),
        intent_matcher=lambda query: MatchedIntent(),
    )

    output = await orch.run(OrchestratorContext(query="你好", trace_id="trace-intent"))

    assert output.decision == "PASS"
    assert output.answer == "cached answer"
    assert output.debug["intent_cache"] == "hello"


def test_pipeline_runner_is_public_entrypoint_without_extra_context_dict():
    runner = PipelineRunner(retrieval=object(), llm=object(), reviewer=object())
    ctx = OrchestratorContext(query="test")

    assert runner.__class__.__name__ == "PipelineRunner"
    assert not hasattr(ctx, "extra")


# ---------------------------------------------------------------------------
# Pipeline timeout protection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_timeout_returns_escalate():
    """When pipeline exceeds timeout, should return ESCALATE decision."""
    import asyncio

    class SlowOrchestrator(Orchestrator):
        async def _run_context(self, ctx):
            await asyncio.sleep(10)  # Simulate slow pipeline
            return None  # Never reached

    orch = SlowOrchestrator(
        retrieval=object(),
        llm=object(),
        reviewer=object(),
    )
    # Override settings to use a very short timeout
    orch._settings = type("S", (), {"pipeline_timeout_seconds": 0.1})()

    output = await orch.run("test query", trace_id="trace-timeout")

    assert output.decision == "ESCALATE"
    assert output.debug.get("pipeline_timeout") is True
    assert output.debug.get("timeout_seconds") == 0.1


@pytest.mark.asyncio
async def test_run_no_timeout_when_disabled():
    """When pipeline_timeout_seconds=0, no timeout is applied."""

    class FastOrchestrator(Orchestrator):
        async def _run_context(self, ctx):
            from app.services.schemas import AnswerOutput
            return AnswerOutput(
                decision="PASS",
                answer="ok",
                followup_questions=[],
                citations=[],
                confidence=0.9,
            )

    orch = FastOrchestrator(
        retrieval=object(),
        llm=object(),
        reviewer=object(),
    )
    orch._settings = type("S", (), {"pipeline_timeout_seconds": 0})()

    output = await orch.run("test query", trace_id="trace-no-timeout")

    assert output.decision == "PASS"
