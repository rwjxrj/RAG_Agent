"""ASSESS_EVIDENCE phase: quality gate. LLM-only."""

from app.services.evidence_quality import evaluate_quality, passes_quality_gate
from app.services.flow_debug import _pipeline_log
from app.services.orchestrator import OrchestratorContext
from app.services.schemas import AssessResult


async def execute_assess_evidence(ctx: OrchestratorContext) -> AssessResult:
    """Run quality gate on retrieved evidence. LLM evaluates; no rule-based logic."""
    ro = ctx.retrieve_output
    required_evidence = ro.active_required_evidence
    hard_requirements = ro.active_hard_requirements
    product_type = ""
    if ctx.query_spec and ctx.query_spec.query_slots.resolved_slots:
        product_type = str((ctx.query_spec.query_slots.resolved_slots or {}).get("product_type", "")).strip()
    quality_context = {
        "answer_shape": (
            ro.active_answer_shape
            or (ctx.query_spec.answer_contract.answer_shape if ctx.query_spec else "direct_lookup")
        ),
        "evidence_families": (
            list(ro.active_evidence_families or [])
            or (list(ctx.query_spec.retrieval_hints.evidence_families or []) if ctx.query_spec else [])
        ),
        "active_hypothesis_name": ro.active_hypothesis_name,
        "retrieval_profile": getattr(ctx.retrieval_plan, "profile", None),
        "evidence_set_uncovered_requirements": (
            list(getattr(ctx.evidence_set, "uncovered_requirements", None) or [])
            if ctx.evidence_set
            else []
        ),
        "candidate_doc_type_counts": (
            dict(getattr(ctx.candidate_pool, "doc_type_counts", None) or {})
            if ctx.candidate_pool
            else {}
        ),
    }

    quality_report = await evaluate_quality(
        ctx.effective_query or ctx.query,
        ctx.evidence,
        required_evidence,
        hard_requirements=hard_requirements,
        product_type=product_type or None,
        conversation_history=ctx.conversation_history or None,
        context=quality_context,
    )
    try:
        from app.core.metrics import evidence_quality_score
        evidence_quality_score.observe(quality_report.quality_score)
    except Exception:
        pass
    gate_passed = passes_quality_gate(
        quality_report,
        required_evidence,
        hard_requirements=hard_requirements,
    )
    _pipeline_log(
        "assess", "done",
        passes_quality_gate=gate_passed,
        quality_score=quality_report.quality_score,
        completeness_score=quality_report.completeness_score,
        actionability_score=quality_report.actionability_score,
        missing_signals=quality_report.missing_signals,
        hard_requirement_coverage=quality_report.hard_requirement_coverage,
        active_hypothesis=ro.active_hypothesis_name,
        trace_id=ctx.trace_id,
    )
    history = list(ro.hypothesis_history)
    if history:
        history[-1]["quality_score"] = quality_report.quality_score
        history[-1]["gate_pass"] = gate_passed
        history[-1]["reason"] = quality_report.reason
        ro.hypothesis_history = history
    return AssessResult(
        quality_report=quality_report,
        passes_quality_gate=gate_passed,
    )
