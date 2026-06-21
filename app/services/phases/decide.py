"""DECIDE phase: deterministic decision router."""

from app.services.decision_router import route as decision_route
from app.services.flow_debug import _pipeline_log
from app.services.orchestrator import OrchestratorContext
from app.services.schemas import DecideResult


async def execute_decide(ctx: OrchestratorContext) -> DecideResult:
    """Run decision router to determine answer lane."""
    required_evidence = ctx.retrieve_output.active_required_evidence
    dr = decision_route(
        ctx.query_spec,
        ctx.quality_report,
        ctx.evidence,
        required_evidence,
        ctx.passes_quality_gate,
    )
    _pipeline_log(
        "decide", "done",
        decision=dr.decision,
        reason=dr.reason,
        lane=dr.resolved_lane(),
        passes_quality_gate=ctx.passes_quality_gate,
        evidence_count=len(ctx.evidence),
        trace_id=ctx.trace_id,
    )
    if dr.decision != "PASS":
        try:
            from app.core.metrics import decision_total
            decision_total.labels(decision=dr.decision).inc()
        except Exception:
            pass
        if dr.decision == "ESCALATE":
            try:
                from app.core.metrics import escalation_rate
                escalation_rate.inc()
            except Exception:
                pass
    return DecideResult(decision_result=dr)
