"""ASSESS_EVIDENCE phase: quality gate. LLM-only."""

from app.services.evidence_quality import (
    evaluate_quality,
    passes_quality_gate,
    verify_policy_quality_false_negative,
)
from app.services.flow_debug import _pipeline_log
from app.services.orchestrator import OrchestratorContext
from app.services.schemas import AssessResult


def _collect_source_set(ctx: OrchestratorContext) -> set[str]:
    """Collect the set of source URLs from current evidence."""
    sources: set[str] = set()
    for chunk in (ctx.evidence or []):
        url = getattr(chunk, "source_url", None) or ""
        if url:
            sources.add(url)
    return sources


def _record_retry_diagnostics(ctx: OrchestratorContext, gate_passed: bool, quality_report=None) -> None:
    """Record structured diagnostics for quality gate retry analysis (Issue 4)."""
    ro = ctx.retrieve_output
    quality_report = quality_report or ctx.quality_report
    if quality_report is None:
        return

    current_source_set = _collect_source_set(ctx)
    current_missing_signals = sorted(
        list(getattr(quality_report, "missing_signals", []) or [])
    )

    diagnostic: dict = {
        "retrieval_attempt": ctx.retrieval_attempt,
        "gate_pass": gate_passed,
        "raw_llm_gate_pass": getattr(quality_report, "gate_pass", None),
        "quality_score": getattr(quality_report, "quality_score", None),
        "completeness_score": getattr(quality_report, "completeness_score", None),
        "actionability_score": getattr(quality_report, "actionability_score", None),
        "missing_signals": current_missing_signals,
        "hard_requirement_coverage": dict(
            getattr(quality_report, "hard_requirement_coverage", {}) or {}
        ),
        "selected_query": (
            ro.retry_strategy_applied.get("selected_retrieval_query")
            if ro.retry_strategy_applied
            else None
        ),
        "active_hypothesis_name": ro.active_hypothesis_name,
        "required_evidence": list(ro.active_required_evidence or []),
        "hard_requirements": list(ro.active_hard_requirements or []),
        "evidence_selector_used_llm": (
            ro.retry_strategy_applied.get("evidence_selector_used_llm")
            if ro.retry_strategy_applied
            else None
        ),
        "evidence_selector_skip_reason": (
            ro.retry_strategy_applied.get("evidence_selector_skip_reason")
            if ro.retry_strategy_applied
            else None
        ),
        "evidence_selector_trigger_reason": (
            ro.retry_strategy_applied.get("evidence_selector_trigger_reason")
            if ro.retry_strategy_applied
            else None
        ),
        "evidence_selector_llm_failed": (
            ro.retry_strategy_applied.get("evidence_selector_llm_failed", False)
            if ro.retry_strategy_applied
            else False
        ),
        "quality_llm_failed": "quality_llm_failed" in current_missing_signals,
        "verification_applied": bool(getattr(quality_report, "verification_applied", False)),
        "verification_chunk_id": getattr(quality_report, "verification_chunk_id", None),
        "verification_quote": getattr(quality_report, "verification_quote", None),
        "verification_reason": getattr(quality_report, "verification_reason", None),
        "source_set_changed": (
            current_source_set != ctx.previous_source_set
            if ctx.retrieval_attempt > 0
            else None
        ),
        "source_count": len(current_source_set),
        "evidence_count": len(ctx.evidence or []),
    }

    ctx.retry_diagnostics.append(diagnostic)
    ctx.previous_source_set = current_source_set
    ctx.previous_missing_signals = current_missing_signals


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
    initial_gate_passed = passes_quality_gate(
        quality_report,
        required_evidence,
        hard_requirements=hard_requirements,
    )
    answer_shape = str(quality_context["answer_shape"] or "").strip().lower()
    policy_requirements = set(required_evidence or []) | set(hard_requirements or [])
    missing_signals = set(quality_report.missing_signals or [])
    should_verify = (
        not initial_gate_passed
        and ctx.retrieval_attempt == 0
        and answer_shape in {"direct_lookup", "yes_no", "short_answer"}
        and "policy_language" in policy_requirements
        and "quality_llm_failed" not in missing_signals
    )
    if should_verify:
        verification = await verify_policy_quality_false_negative(
            ctx.effective_query or ctx.query,
            ctx.evidence,
        )
        quality_report.verification_reason = verification.reason
        if verification.supported:
            quality_report.verification_applied = True
            quality_report.verification_chunk_id = verification.chunk_id
            quality_report.verification_quote = verification.quote
            # The focused verifier has independently established direct support
            # with an exact quote, so gaps from the superseded quality verdict
            # are no longer authoritative. Other hard requirements remain guarded
            # by their explicit coverage entries below.
            quality_report.missing_signals = []
            coverage = dict(quality_report.hard_requirement_coverage or {})
            coverage["policy_language"] = True
            quality_report.hard_requirement_coverage = coverage
            if not quality_report.missing_signals and all(coverage.values()):
                quality_report.gate_pass = True
                quality_report.reason = verification.reason or quality_report.reason
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

    # Record retry diagnostics (Issue 4)
    _record_retry_diagnostics(ctx, gate_passed, quality_report)

    return AssessResult(
        quality_report=quality_report,
        passes_quality_gate=gate_passed,
    )
