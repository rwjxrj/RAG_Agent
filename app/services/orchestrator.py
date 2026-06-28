"""Orchestrator: workflow state machine, model routing, retry lifecycle.

Drives the RAG pipeline per RAG_DEVELOPMENT_STRATEGY Workstream 1:
- Runtime context management
- State transitions
- Decision reason logging

The orchestrator is the source of truth for flow control. Handlers execute
each phase and return results; the orchestrator updates context and determines
the next action.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
import asyncio
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.llm_config import get_llm_fallback_model, get_llm_model
from app.services.model_router import get_model_for_task
from app.services.schemas import (
    AnswerPlan,
    CandidatePool,
    DecisionResult,
    EvidenceAssessment,
    EvidenceSet,
    GeneratePhaseOutput,
    OrchestratorDebug,
    QuerySpec,
    RetrievePhaseOutput,
    RetrievalPlan,
    ReviewResult,
    VerifyPhaseOutput,
)

logger = get_logger(__name__)


class OrchestratorAction(str, Enum):
    """Next action in workflow."""

    INTENT_CACHE = "intent_cache"
    AGENTIC_ROUTE = "agentic_route"
    NORMALIZE = "normalize"
    SKIP_RETRIEVAL = "skip_retrieval"
    UNDERSTAND = "understand"
    RETRIEVE = "retrieve"
    ASSESS_EVIDENCE = "assess_evidence"
    DECIDE = "decide"
    GENERATE = "generate"
    VERIFY = "verify"
    ASK_USER = "ask_user"
    ESCALATE = "escalate"
    RETRY_RETRIEVE = "retry_retrieve"
    DONE = "done"


class OrchestratorState(str, Enum):
    """Workflow state."""

    INIT = "init"
    INTENT_CACHE = "intent_cache"
    AGENTIC_ROUTE = "agentic_route"
    NORMALIZE = "normalize"
    SKIP_RETRIEVAL = "skip_retrieval"
    UNDERSTANDING = "understanding"
    RETRIEVING = "retrieving"
    ASSESSING = "assessing"
    DECIDING = "deciding"
    GENERATING = "generating"
    REVIEWING = "reviewing"
    RETRYING = "retrying"
    COMPLETE = "complete"


@dataclass
class PhaseResult:
    """Result from executing one phase. Fields used depend on the action."""

    query_spec: QuerySpec | None = None
    effective_query: str = ""
    source_lang: str = "en"
    skip_retrieval: bool = False
    canned_response: str | None = None
    evidence_pack: Any = None
    evidence: list[Any] = field(default_factory=list)
    quality_report: Any = None
    passes_quality_gate: bool = False
    decision_result: DecisionResult | None = None
    answer_plan: AnswerPlan | None = None
    answer: str = ""
    citations: list[Any] = field(default_factory=list)
    followup: list[str] = field(default_factory=list)
    confidence: float = 0.0
    generated_decision: str | None = None
    reviewer_result: Any = None
    retry_query_override: str | None = None
    hypothesis_judge: dict[str, Any] | None = None
    early_output: Any = None
    agentic_debug: dict[str, Any] | None = None


@dataclass
class OrchestratorContext:
    """Context passed through workflow. Single source of truth for pipeline state."""

    query: str
    state: OrchestratorState = OrchestratorState.INIT
    trace_id: str | None = None
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    attempt: int = 1
    max_attempts: int = 2
    evidence: list[Any] = field(default_factory=list)
    query_spec: QuerySpec | None = None
    effective_query: str = ""
    source_lang: str = "en"
    retrieval_plan: RetrievalPlan | None = None
    candidate_pool: CandidatePool | None = None
    evidence_set: EvidenceSet | None = None
    evidence_assessment: EvidenceAssessment | None = None
    evidence_pack: Any = None
    quality_report: Any = None
    passes_quality_gate: bool = False
    decision_result: DecisionResult | None = None
    answer_lane: str | None = None
    answer_plan: AnswerPlan | None = None
    review_result: ReviewResult | None = None
    model_override: str | None = None
    retrieval_attempt: int = 0
    stage_reasons: list[str] = field(default_factory=list)
    retrieval_history: list[RetrievalPlan] = field(default_factory=list)
    termination_reason: str | None = None
    answer: str = ""
    citations: list[Any] = field(default_factory=list)
    followup: list[str] = field(default_factory=list)
    confidence: float = 0.0
    generated_decision: str | None = None
    retry_query_override: str | None = None
    hypothesis_judge: dict[str, Any] | None = None
    retrieve_output: RetrievePhaseOutput = field(default_factory=RetrievePhaseOutput)
    generate_output: GeneratePhaseOutput = field(default_factory=GeneratePhaseOutput)
    verify_output: VerifyPhaseOutput = field(default_factory=VerifyPhaseOutput)
    orchestrator_debug: OrchestratorDebug = field(default_factory=OrchestratorDebug)
    last_reviewer_result: Any = None  # Replaces runtime-injected _last_reviewer_result
    trace_collector: Any = None
    early_output: Any = None
    skip_retrieval: bool = False
    agentic_debug: dict[str, Any] = field(default_factory=dict)
    # Quality gate retry diagnostics (Issue 4)
    retry_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    previous_source_set: set[str] = field(default_factory=set)
    previous_missing_signals: list[str] = field(default_factory=list)

    def can_retry(self) -> bool:
        """Whether another retrieval attempt is still allowed."""
        return self.retrieval_attempt < self.max_attempts

    def current_lane(self) -> str | None:
        """Return the best-known answer lane for this context."""
        if self.review_result:
            return self.review_result.final_lane
        if self.decision_result:
            return self.decision_result.resolved_lane()
        return self.answer_lane

    def add_stage_reason(self, stage: str, reason: str) -> None:
        """Append decision reason for explainability (strategy: decision reason logging)."""
        self.stage_reasons.append(f"{stage}: {reason}")


def _reviewer_status_to_str(reviewer_result: Any) -> str | None:
    """Map ReviewerResult.status to string for next_action."""
    if reviewer_result is None:
        return None
    status = getattr(reviewer_result, "status", None)
    if status is None:
        return None
    return str(status.value) if hasattr(status, "value") else str(status)


_VERIFY_REPAIR_RETRY_REASONS = {"type_mismatch", "overclaim", "unsupported_exact"}
_TIMED_ACTIONS = {
    OrchestratorAction.NORMALIZE: "query_extract",
    OrchestratorAction.RETRIEVE: "retrieve",
    OrchestratorAction.ASSESS_EVIDENCE: "assess_evidence",
    OrchestratorAction.GENERATE: "generate",
    OrchestratorAction.VERIFY: "verify",
}


def _record_phase_timing(ctx: OrchestratorContext, key: str, elapsed_seconds: float) -> None:
    timings = ctx.orchestrator_debug.phase_timings
    try:
        current = float(timings.get(key, 0.0) or 0.0)
    except (TypeError, ValueError):
        current = 0.0
    timings[key] = current + max(0.0, elapsed_seconds)


def _extract_rerank_timing(result: PhaseResult) -> float:
    pack = result.evidence_pack
    stats = getattr(pack, "retrieval_stats", None) if pack else None
    if not isinstance(stats, dict):
        return 0.0
    timings = stats.get("timings")
    if isinstance(timings, dict):
        value = timings.get("rerank")
    else:
        value = stats.get("rerank_seconds")
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


class PipelineRunner:
    """State machine orchestrator for support flow. Drives pipeline per strategy."""

    def __init__(
        self,
        primary_model: str | None = None,
        fallback_model: str | None = None,
        retrieval: Any = None,
        llm: Any = None,
        reviewer: Any = None,
        agentic_router: Any = None,
        intent_matcher: Any = None,
        normalizer: Any = None,
        language_detector: Any = None,
    ):
        if retrieval is None:
            from app.services.retrieval import RetrievalService
            retrieval = RetrievalService()
        owns_llm = llm is None
        if llm is None:
            from app.services.llm_gateway import get_llm_gateway
            llm = get_llm_gateway()
        if reviewer is None:
            from app.services.reviewer import ReviewerGate
            reviewer = ReviewerGate()
        if agentic_router is None:
            from app.services.agentic_router import AgenticRouter
            agentic_router = AgenticRouter()
        if intent_matcher is None:
            from app.services.branding_config import match_intent
            intent_matcher = match_intent
        if normalizer is None:
            from app.services.normalizer import normalize
            normalizer = normalize
        if language_detector is None:
            from app.services.language_detect import detect_language
            language_detector = detect_language
        self._settings = get_settings()
        self._owns_llm = owns_llm  # True 表示 PipelineRunner 自己创建了网关
        self._retrieval = retrieval
        self._llm = llm
        self._reviewer = reviewer
        self._agentic_router = agentic_router
        self._intent_matcher = intent_matcher
        self._normalizer = normalizer
        self._language_detector = language_detector
        self.primary_model = primary_model or get_llm_model()
        self.fallback_model = fallback_model or get_llm_fallback_model()
        self.models = [self.primary_model, self.fallback_model]

    def get_model_for_query(self, query: str) -> str:
        """Model for generate phase (primary/gpt-5.2)."""
        return get_model_for_task("generate")

    def get_model_for_task(self, task: str, query: str = "") -> str:
        """Task-aware routing: primary for generate/self_critic, economy for rest."""
        _ = query
        return get_model_for_task(task)

    def _schedule_verify_targeted_retry(
        self,
        ctx: OrchestratorContext,
        reviewer_result: Any,
    ) -> bool:
        """Schedule one targeted retry after verify when failure is retryable."""
        if not bool(getattr(self._settings, "targeted_retry_enabled", True)):
            return False
        if reviewer_result is None:
            return False
        if not ctx.can_retry():
            return False
        if ctx.verify_output.targeted_retry_used:
            return False

        retry_reason = str(getattr(reviewer_result, "retry_reason", "") or "").strip().lower()
        if retry_reason not in _VERIFY_REPAIR_RETRY_REASONS:
            return False
        suggested_queries = [
            str(q).strip()
            for q in (getattr(reviewer_result, "suggested_queries", None) or [])
            if str(q).strip()
        ]
        if not suggested_queries:
            return False

        ctx.retry_query_override = suggested_queries[0]
        ctx.verify_output.targeted_retry_pending = True
        ctx.verify_output.targeted_retry_used = True
        ctx.verify_output.targeted_retry_reason = retry_reason
        ctx.verify_output.targeted_retry_queries = suggested_queries[:3]
        return True

    def next_action(
        self,
        ctx: OrchestratorContext,
        reviewer_status: str | None = None,
        has_evidence: bool = False,
    ) -> OrchestratorAction:
        """Determine next action from current state and reviewer result."""
        if ctx.state == OrchestratorState.INIT:
            return OrchestratorAction.INTENT_CACHE

        if ctx.state == OrchestratorState.INTENT_CACHE:
            return OrchestratorAction.DONE if ctx.early_output else OrchestratorAction.AGENTIC_ROUTE

        if ctx.state == OrchestratorState.AGENTIC_ROUTE:
            return OrchestratorAction.DONE if ctx.early_output else OrchestratorAction.NORMALIZE

        if ctx.state == OrchestratorState.NORMALIZE:
            return (
                OrchestratorAction.SKIP_RETRIEVAL
                if ctx.skip_retrieval
                else OrchestratorAction.RETRIEVE
            )

        if ctx.state == OrchestratorState.SKIP_RETRIEVAL:
            return OrchestratorAction.DONE

        if ctx.state == OrchestratorState.UNDERSTANDING:
            return OrchestratorAction.RETRIEVE

        if ctx.state == OrchestratorState.RETRIEVING:
            if has_evidence:
                return OrchestratorAction.ASSESS_EVIDENCE
            if (
                ctx.query_spec
                and ctx.query_spec.clarification_needs.answerable_without_clarification is False
            ):
                return OrchestratorAction.DECIDE
            if ctx.can_retry():
                return OrchestratorAction.RETRY_RETRIEVE
            return OrchestratorAction.ASK_USER

        if ctx.state == OrchestratorState.ASSESSING:
            if (
                not ctx.passes_quality_gate
                and ctx.can_retry()
                and not self._quality_assessment_unavailable(ctx)
            ):
                # Retry convergence: stop retrying when it won't help (Issue 4)
                if self._should_stop_retry(ctx):
                    logger.info(
                        "retry_convergence_stop",
                        trace_id=ctx.trace_id,
                        retrieval_attempt=ctx.retrieval_attempt,
                        reason=ctx.orchestrator_debug.convergence_reason if hasattr(ctx.orchestrator_debug, 'convergence_reason') else "unknown",
                    )
                    return OrchestratorAction.DECIDE
                return OrchestratorAction.RETRY_RETRIEVE
            # Max attempts exhausted without convergence — set exhaustion reason
            if (
                not ctx.passes_quality_gate
                and not ctx.can_retry()
                and not self._quality_assessment_unavailable(ctx)
                and ctx.orchestrator_debug.convergence_reason is None
            ):
                ctx.orchestrator_debug.convergence_reason = "max_retries_exhausted"
                logger.info(
                    "retry_exhausted",
                    trace_id=ctx.trace_id,
                    retrieval_attempt=ctx.retrieval_attempt,
                    max_attempts=ctx.max_attempts,
                )
            return OrchestratorAction.DECIDE

        if ctx.state == OrchestratorState.DECIDING:
            lane = ctx.current_lane()
            if lane in (
                "CANDIDATE_VERIFY",
                "PASS_EXACT",
                "PASS_PARTIAL",
                "PASS",
            ):
                return OrchestratorAction.GENERATE
            if lane == "TARGETED_RETRY":
                if not bool(getattr(self._settings, "targeted_retry_enabled", True)):
                    return OrchestratorAction.ASK_USER
                if ctx.can_retry():
                    return OrchestratorAction.RETRY_RETRIEVE
                return OrchestratorAction.ASK_USER
            if lane == "ESCALATE":
                return OrchestratorAction.ESCALATE
            if lane == "ASK_USER":
                return OrchestratorAction.ASK_USER
            if ctx.can_retry():
                return OrchestratorAction.RETRY_RETRIEVE
            return OrchestratorAction.ASK_USER

        if ctx.state == OrchestratorState.GENERATING:
            return OrchestratorAction.VERIFY

        if ctx.state == OrchestratorState.REVIEWING:
            if reviewer_status == "PASS":
                return OrchestratorAction.DONE
            if reviewer_status in ("TRIM_UNSUPPORTED", "DOWNGRADE_LANE"):
                return OrchestratorAction.DONE
            if reviewer_status == "ESCALATE":
                return OrchestratorAction.ESCALATE
            if reviewer_status == "ASK_USER":
                if ctx.verify_output.targeted_retry_pending:
                    return OrchestratorAction.RETRY_RETRIEVE
                return OrchestratorAction.ASK_USER
            return OrchestratorAction.ASK_USER

        if ctx.state == OrchestratorState.RETRYING:
            return OrchestratorAction.RETRIEVE

        return OrchestratorAction.DONE

    @staticmethod
    def _quality_assessment_unavailable(ctx: OrchestratorContext) -> bool:
        """Detect quality-gate infrastructure failures that retrieval cannot fix."""
        report = ctx.quality_report
        signals = getattr(report, "missing_signals", None) or []
        reason = str(getattr(report, "reason", "") or "").lower()
        return "quality_llm_failed" in signals or "quality assessment failed" in reason

    def _should_stop_retry(self, ctx: OrchestratorContext) -> bool:
        """Determine if retry should be stopped due to convergence (Issue 4).

        Six convergence conditions:
        1. Same missing_signals as previous attempt AND no new sources found.
        2. Source set unchanged — retrieval saturated, retrying won't help.
        3. Top-5 evidence already covers expected source types — retrying won't help.
        4. Consecutive infrastructure failures — selector/quality LLM keeps failing, retrying won't help.
        5. Consecutive quality gate failures — quality never passes after N rounds, retrying won't help.
        5b. Soft contradiction — LLM says pass but code overrides (missing_signals/coverage gap), retrying won't resolve.
        """
        if not bool(getattr(self._settings, "quality_gate_retry_convergence_enabled", True)):
            return False

        if not ctx.retry_diagnostics:
            return False

        latest = ctx.retry_diagnostics[-1]
        current_missing = sorted(latest.get("missing_signals", []))
        source_set_changed = latest.get("source_set_changed")

        # Condition 1: Same missing_signals and no new sources
        if (
            current_missing == ctx.previous_missing_signals
            and source_set_changed is False
        ):
            ctx.orchestrator_debug.convergence_reason = "same_missing_signals_no_new_sources"
            return True

        # Condition 2: Source set unchanged (retrieval saturated)
        if source_set_changed is False:
            ctx.orchestrator_debug.convergence_reason = "source_set_unchanged_retry_saturated"
            return True

        # Condition 3: Top-5 evidence already covers expected source types
        if self._top_sources_cover_expected(ctx):
            ctx.orchestrator_debug.convergence_reason = "top_sources_cover_expected"
            return True

        # Condition 4: Consecutive infrastructure failures (selector or quality LLM)
        if len(ctx.retry_diagnostics) >= 2:
            prev = ctx.retry_diagnostics[-2]
            if self._is_infra_failure(latest) and self._is_infra_failure(prev):
                ctx.orchestrator_debug.convergence_reason = "consecutive_infrastructure_failures"
                return True

        # Condition 5: Consecutive quality gate failures — quality never passes
        # Catches the EVAL-008 scenario where source_set and missing_signals change
        # each round but quality gate never passes, so retrying won't help.
        max_consec = int(getattr(self._settings, "quality_gate_max_consecutive_failures", 3))
        if len(ctx.retry_diagnostics) >= max_consec:
            tail = ctx.retry_diagnostics[-max_consec:]
            if all(not d.get("gate_pass") for d in tail):
                ctx.orchestrator_debug.convergence_reason = "consecutive_gate_failures_exhausted"
                return True

        # Condition 5b: Soft contradiction — LLM says pass but code overrides.
        # Catches EVAL-007: LLM returns gate_pass=True + missing_signals non-empty
        # every round. The contradiction guard correctly forces gate_pass=False,
        # but retrying won't resolve the semantic disagreement.
        if len(ctx.retry_diagnostics) >= 2:
            tail2 = ctx.retry_diagnostics[-2:]
            all_overridden = all(
                not d.get("gate_pass") and d.get("raw_llm_gate_pass") is True
                for d in tail2
            )
            if all_overridden:
                ctx.orchestrator_debug.convergence_reason = "soft_contradiction_llm_agrees_evidence_sufficient"
                return True

        return False

    @staticmethod
    def _is_infra_failure(diagnostic: dict) -> bool:
        """Check if a diagnostic entry shows an infrastructure (LLM) failure."""
        return bool(
            diagnostic.get("evidence_selector_llm_failed")
            or diagnostic.get("quality_llm_failed")
        )

    def _top_sources_cover_expected(self, ctx: OrchestratorContext) -> bool:
        """Check if the top-5 evidence chunks already cover expected source types.

        If the top-5 chunks have the same source URLs as the expected doc types
        from the query spec, retrying retrieval won't find new information.
        """
        if not ctx.evidence or not ctx.query_spec:
            return False

        top_chunks = ctx.evidence[:5]
        if not top_chunks:
            return False

        expected_doc_types = set(
            ctx.query_spec.doc_type_prior
            or getattr(ctx.query_spec.retrieval_hints, "doc_type_prior", [])
            or []
        )
        if not expected_doc_types:
            return False

        # Check if top-5 chunks already come from expected source types
        covered_types: set[str] = set()
        for chunk in top_chunks:
            doc_type = getattr(chunk, "doc_type", None) or ""
            if doc_type:
                covered_types.add(doc_type)
            source_url = getattr(chunk, "source_url", None) or ""
            # Infer doc type from source URL patterns
            for dt in expected_doc_types:
                if dt in source_url.lower():
                    covered_types.add(dt)

        # If all expected doc types are already covered, retrying won't help
        if expected_doc_types.issubset(covered_types):
            return True

        return False

    def _apply_result(
        self,
        ctx: OrchestratorContext,
        action: OrchestratorAction,
        result: PhaseResult,
    ) -> None:
        """Update context after executing an action. Handles state transitions."""
        if action == OrchestratorAction.INTENT_CACHE:
            ctx.early_output = result.early_output
            ctx.state = OrchestratorState.INTENT_CACHE
            ctx.add_stage_reason("intent_cache", "hit" if result.early_output else "miss")

        elif action == OrchestratorAction.AGENTIC_ROUTE:
            ctx.early_output = result.early_output
            ctx.agentic_debug = result.agentic_debug or {}
            ctx.state = OrchestratorState.AGENTIC_ROUTE
            ctx.add_stage_reason(
                "agentic_route",
                str(ctx.agentic_debug.get("route") or ctx.agentic_debug.get("reason") or "rag_search"),
            )

        elif action == OrchestratorAction.NORMALIZE:
            ctx.query_spec = result.query_spec
            ctx.effective_query = result.effective_query or ctx.query
            ctx.source_lang = result.source_lang or "en"
            ctx.skip_retrieval = result.skip_retrieval
            ctx.state = OrchestratorState.NORMALIZE
            ctx.add_stage_reason(
                "normalize",
                "skip_retrieval" if result.skip_retrieval else "query_spec_ready",
            )

        elif action == OrchestratorAction.SKIP_RETRIEVAL:
            ctx.early_output = result.early_output
            ctx.state = OrchestratorState.SKIP_RETRIEVAL
            ctx.add_stage_reason("skip_retrieval", "canned_response")

        elif action == OrchestratorAction.UNDERSTAND:
            if result.query_spec:
                ctx.query_spec = result.query_spec
            ctx.effective_query = result.effective_query or ctx.query
            ctx.source_lang = result.source_lang or "en"
            ctx.state = OrchestratorState.UNDERSTANDING
            ctx.add_stage_reason("understand", "query_spec_ready")

        elif action == OrchestratorAction.RETRIEVE:
            ctx.evidence_pack = result.evidence_pack
            ctx.evidence = result.evidence
            if result.evidence_pack:
                ctx.retrieval_plan = getattr(result.evidence_pack, "retrieval_plan", None)
                ctx.candidate_pool = getattr(result.evidence_pack, "candidate_pool", None)
                ctx.evidence_set = getattr(result.evidence_pack, "evidence_set", None)
            ctx.state = OrchestratorState.RETRIEVING
            ctx.add_stage_reason("retrieve", f"chunks={len(result.evidence)}")

        elif action == OrchestratorAction.ASSESS_EVIDENCE:
            ctx.quality_report = result.quality_report
            ctx.passes_quality_gate = result.passes_quality_gate
            ctx.state = OrchestratorState.ASSESSING
            ctx.add_stage_reason(
                "assess_evidence",
                f"gate={'pass' if result.passes_quality_gate else 'fail'}",
            )

        elif action == OrchestratorAction.DECIDE:
            ctx.decision_result = result.decision_result
            ctx.answer_lane = (
                result.decision_result.resolved_lane() if result.decision_result else None
            )
            ctx.state = OrchestratorState.DECIDING
            ctx.add_stage_reason(
                "decide",
                result.decision_result.reason if result.decision_result else "unknown",
            )

        elif action == OrchestratorAction.GENERATE:
            ctx.answer = result.answer
            ctx.citations = result.citations
            ctx.followup = result.followup
            ctx.confidence = result.confidence
            ctx.answer_plan = result.answer_plan
            ctx.generated_decision = result.generated_decision
            ctx.state = OrchestratorState.GENERATING
            ctx.add_stage_reason(
                "generate",
                f"llm_complete decision={result.generated_decision or 'unknown'}",
            )

        elif action == OrchestratorAction.VERIFY:
            rr = result.reviewer_result
            status_str = _reviewer_status_to_str(rr) or "unknown"
            status_map = {
                "PASS": "accept",
                "ASK_USER": "downgrade_lane",
                "ESCALATE": "escalate",
                "TRIM_UNSUPPORTED": "trim_unsupported_claims",
                "DOWNGRADE_LANE": "downgrade_lane",
            }
            schema_status = status_map.get(status_str, status_str.lower())
            if status_str == "TRIM_UNSUPPORTED" and getattr(rr, "trimmed_answer", None):
                ctx.answer = rr.trimmed_answer
            if status_str == "DOWNGRADE_LANE":
                if getattr(rr, "trimmed_answer", None):
                    ctx.answer = rr.trimmed_answer
                ctx.answer_lane = getattr(rr, "final_lane", None) or "PASS_PARTIAL"
            if status_str == "PASS" and getattr(rr, "final_lane", None):
                ctx.answer_lane = rr.final_lane
            calibrated_confidence = getattr(rr, "calibrated_confidence", None)
            if isinstance(calibrated_confidence, (int, float)):
                ctx.confidence = max(0.0, min(1.0, float(calibrated_confidence)))
            if status_str == "ASK_USER":
                scheduled = self._schedule_verify_targeted_retry(ctx, rr)
                if scheduled:
                    ctx.add_stage_reason(
                        "verify_repair",
                        f"targeted_retry:{ctx.verify_output.targeted_retry_reason}",
                    )
            ctx.review_result = ReviewResult(
                status=schema_status,
                unsupported_claims=getattr(rr, "unsupported_claims", None) or getattr(rr, "missing_fields", []) or [],
                weakly_supported_claims=getattr(rr, "weakly_supported_claims", []) or [],
                claim_to_citation_map=getattr(rr, "claim_to_citation_map", {}) or {},
                reviewer_notes=getattr(rr, "reasons", []) or [],
                final_lane=getattr(rr, "final_lane", None) or status_str,
                suggested_retry_plan=None,
            )
            ctx.hypothesis_judge = result.hypothesis_judge
            ctx.state = OrchestratorState.REVIEWING
            ctx.add_stage_reason("verify", _reviewer_status_to_str(rr) or "unknown")

        elif action == OrchestratorAction.RETRY_RETRIEVE:
            ctx.verify_output.targeted_retry_pending = False
            ctx.review_result = None
            ctx.decision_result = None
            ctx.retrieval_attempt += 1
            ctx.state = OrchestratorState.RETRYING
            ctx.add_stage_reason("retry_retrieve", f"attempt={ctx.retrieval_attempt}")

    async def _phase_intent_cache(self, ctx: OrchestratorContext) -> PhaseResult:
        from app.services.schemas import AnswerOutput

        trace = ctx.trace_collector
        if trace:
            trace.start_node("intent_cache")
        intent = self._intent_matcher(ctx.query)
        if not intent:
            if trace:
                trace.set_intent(False)
                trace.skip_node("intent_cache", reason="miss")
            return PhaseResult()
        if trace:
            trace.set_intent(True, intent.intent)
            trace.complete_node("intent_cache")
            trace.skip_node("agentic_router", reason="intent_cache_hit")
        return PhaseResult(early_output=AnswerOutput(
            decision="PASS",
            answer=intent.answer,
            followup_questions=[],
            citations=[],
            confidence=1.0,
            debug={
                "trace_id": ctx.trace_id,
                "intent_cache": intent.intent,
                "agentic_router": {"skipped": True, "reason": "intent_cache_hit"},
            },
        ))

    async def _phase_agentic_route(self, ctx: OrchestratorContext) -> PhaseResult:
        from app.services.agentic_router import AgenticRoute, AgenticRouter, AgenticRouterInput
        from app.services.schemas import AnswerOutput

        trace = ctx.trace_collector
        if trace:
            trace.start_node("agentic_router")
        try:
            decision = self._agentic_router.route(AgenticRouterInput(
                query=ctx.query,
                conversation_history=ctx.conversation_history,
                source="reply",
                trace_id=ctx.trace_id,
            ))
        except Exception:
            decision = AgenticRouter.safe_fallback("router_exception")
        debug = decision.to_debug()
        trace_result = {
            "route": decision.route,
            "tool": decision.tool,
            "confidence": decision.confidence,
            "fallback_to_rag": decision.fallback_to_rag,
        }
        if trace:
            if decision.fallback_to_rag:
                trace.fallback_node(
                    "agentic_router",
                    reason=decision.reason,
                    selected_tool=decision.tool,
                    decision_reason=decision.reason,
                    tool_result=trace_result,
                )
            else:
                trace.complete_node(
                    "agentic_router",
                    selected_tool=decision.tool,
                    decision_reason=decision.reason,
                    tool_result=trace_result,
                )
        output = None
        if decision.route == AgenticRoute.DIRECT_RESPONSE:
            app_name = (self._settings.app_name or "").strip()
            answer = f"你好，欢迎使用 {app_name} 客服。有什么可以帮你？" if app_name else "你好，有什么可以帮你？"
            if trace:
                trace.complete_node("direct_response", tool_result={"decision": "PASS"})
            output = AnswerOutput(decision="PASS", answer=answer, followup_questions=[], citations=[], confidence=decision.confidence, debug={"trace_id": ctx.trace_id, "agentic_router": debug})
        elif decision.route == AgenticRoute.CLARIFY:
            followups = decision.clarifying_questions[:3] or ["请补充更多关键信息。"]
            if trace:
                trace.complete_node("clarify", tool_result={"decision": "ASK_USER", "followup_count": len(followups)})
            output = AnswerOutput(decision="ASK_USER", answer="我还需要一点信息才能准确处理这个问题。", followup_questions=followups, citations=[], confidence=decision.confidence, debug={"trace_id": ctx.trace_id, "agentic_router": debug})
        elif decision.route == AgenticRoute.HUMAN_HANDOFF:
            if trace:
                trace.complete_node("human_handoff", tool_result={"decision": "ESCALATE"})
            output = AnswerOutput(decision="ESCALATE", answer="这个请求需要人工客服处理，我会将问题转交给人工跟进。", followup_questions=[], citations=[], confidence=decision.confidence, debug={"trace_id": ctx.trace_id, "agentic_router": debug})
        return PhaseResult(early_output=output, agentic_debug=debug)

    async def _phase_normalize(self, ctx: OrchestratorContext) -> PhaseResult:
        from app.services.archi_config import get_language_detect_enabled

        trace = ctx.trace_collector
        if trace:
            trace.start_node("query_extract")
        source_lang = self._language_detector(ctx.query) if get_language_detect_enabled() else "en"
        query_spec = None
        if getattr(self._settings, "normalizer_enabled", True):
            query_spec = await self._normalizer(
                ctx.query,
                ctx.conversation_history,
                source_lang=source_lang,
            )
        if trace:
            trace.complete_node("query_extract")
        effective_query = (
            query_spec.query_slots.canonical_query_en
            if query_spec and query_spec.query_slots.canonical_query_en
            else ctx.query
        )
        if query_spec:
            hints = query_spec.retrieval_hints
            ctx.retrieve_output.active_required_evidence = list(hints.required_evidence or [])
            ctx.retrieve_output.active_hard_requirements = list(hints.hard_requirements or [])
            ctx.retrieve_output.active_hypothesis_name = getattr(
                hints.primary_hypothesis,
                "name",
                "primary",
            )
            # Configured value is the hard ceiling; fallback hypotheses count
            # as initial candidates within that budget, not additional attempts.
            ctx.max_attempts = max(1, self._settings.max_retrieval_attempts)
        return PhaseResult(
            query_spec=query_spec,
            effective_query=effective_query,
            source_lang=source_lang,
            skip_retrieval=bool(query_spec and query_spec.skip_retrieval),
        )

    async def _phase_skip_retrieval(self, ctx: OrchestratorContext) -> PhaseResult:
        from app.services.schemas import AnswerOutput

        canned = (getattr(ctx.query_spec, "canned_response", None) or "").strip()
        if not canned:
            app_name = (self._settings.app_name or "").strip()
            canned = f"你好，欢迎使用 {app_name} 客服。有什么可以帮你？" if app_name else "你好，有什么可以帮你？"
        if ctx.trace_collector:
            ctx.trace_collector.complete_node("direct_response", tool_result={"decision": "PASS"})
        return PhaseResult(early_output=AnswerOutput(
            decision="PASS",
            answer=canned,
            followup_questions=[],
            citations=[],
            confidence=1.0,
            debug={"trace_id": ctx.trace_id, "skip_retrieval": True},
        ))

    async def execute(
        self,
        ctx: OrchestratorContext,
        action: OrchestratorAction,
    ) -> PhaseResult:
        """Execute a phase with dependencies owned by the orchestrator."""
        from app.services.phases import (
            execute_assess_evidence,
            execute_decide,
            execute_generate,
            execute_retrieve,
            execute_verify,
        )

        if action == OrchestratorAction.INTENT_CACHE:
            return await self._phase_intent_cache(ctx)
        if action == OrchestratorAction.AGENTIC_ROUTE:
            return await self._phase_agentic_route(ctx)
        if action == OrchestratorAction.NORMALIZE:
            return await self._phase_normalize(ctx)
        if action == OrchestratorAction.SKIP_RETRIEVAL:
            return await self._phase_skip_retrieval(ctx)
        if action == OrchestratorAction.UNDERSTAND:
            return PhaseResult(
                query_spec=ctx.query_spec,
                effective_query=ctx.effective_query or ctx.query,
                source_lang=ctx.source_lang,
            )
        if action == OrchestratorAction.RETRIEVE:
            return await execute_retrieve(
                ctx,
                retrieval=self._retrieval,
                orchestrator=self,
                settings=self._settings,
            )
        if action == OrchestratorAction.ASSESS_EVIDENCE:
            return await execute_assess_evidence(ctx)
        if action == OrchestratorAction.DECIDE:
            return await execute_decide(ctx)
        if action == OrchestratorAction.GENERATE:
            return await execute_generate(
                ctx,
                llm=self._llm,
                orchestrator=self,
                settings=self._settings,
            )
        if action == OrchestratorAction.VERIFY:
            return await execute_verify(ctx, reviewer=self._reviewer)
        return PhaseResult()

    async def build_output(
        self,
        ctx: OrchestratorContext,
        action: OrchestratorAction,
    ) -> Any:
        """Build the terminal answer using this orchestrator's model routing."""
        from app.services.output_builder import build_output

        return await build_output(ctx, action, orchestrator=self)

    async def _run_context(
        self,
        ctx: OrchestratorContext,
    ) -> Any:
        """Drive the full pipeline until a terminal action."""
        terminal_actions = {
            OrchestratorAction.DONE,
            OrchestratorAction.ASK_USER,
            OrchestratorAction.ESCALATE,
        }
        max_iterations = 50
        iterations = 0

        while iterations < max_iterations:
            iterations += 1
            has_evidence = bool(ctx.evidence)
            reviewer_status = _reviewer_status_to_str(
                ctx.last_reviewer_result
            )

            action = self.next_action(ctx, reviewer_status, has_evidence)

            if action in terminal_actions:
                ctx.termination_reason = action.value
                ctx.state = OrchestratorState.COMPLETE
                try:
                    from app.services.flow_debug import _pipeline_log
                    _pipeline_log("orchestrator", "terminated", action=action.value, trace_id=ctx.trace_id, stage_reasons=ctx.stage_reasons[-5:])
                except Exception:
                    pass
                logger.debug(
                    "orchestrator_terminated",
                    action=action.value,
                    trace_id=ctx.trace_id,
                    stage_reasons=ctx.stage_reasons[-5:],
                )
                if ctx.early_output is not None:
                    # Patch early_output debug with terminal context so downstream
                    # consumers (eval, telemetry) see termination_reason and route.
                    try:
                        debug = getattr(ctx.early_output, "debug", None)
                        if isinstance(debug, dict):
                            debug.setdefault("termination_reason", ctx.termination_reason)
                            debug.setdefault("stage_reasons", list(ctx.stage_reasons))
                    except Exception:
                        pass
                    return ctx.early_output
                return await self.build_output(ctx, action)

            if action == OrchestratorAction.RETRY_RETRIEVE:
                self._apply_result(ctx, action, PhaseResult())
            else:
                phase_started = time.perf_counter()
                timing_key = _TIMED_ACTIONS.get(action)
                try:
                    try:
                        from app.services.flow_debug import _pipeline_log
                        _pipeline_log("orchestrator", "execute", action=action.value, state=ctx.state.value, trace_id=ctx.trace_id)
                    except Exception:
                        pass
                    result = await self.execute(ctx, action)
                except Exception as e:
                    if timing_key:
                        _record_phase_timing(
                            ctx,
                            timing_key,
                            time.perf_counter() - phase_started,
                        )
                    logger.error("orchestrator_execute_failed", action=action.value, error=str(e))
                    ctx.orchestrator_debug.error = str(e)
                    return await self.build_output(ctx, OrchestratorAction.ESCALATE)
                if timing_key:
                    _record_phase_timing(
                        ctx,
                        timing_key,
                        time.perf_counter() - phase_started,
                    )
                if action == OrchestratorAction.RETRIEVE:
                    _record_phase_timing(ctx, "rerank", _extract_rerank_timing(result))
                self._apply_result(ctx, action, result)
                if action == OrchestratorAction.VERIFY and result.reviewer_result:
                    ctx.last_reviewer_result = result.reviewer_result

        ctx.termination_reason = "max_iterations"
        ctx.state = OrchestratorState.COMPLETE
        logger.warning("orchestrator_max_iterations", trace_id=ctx.trace_id)
        return await self.build_output(ctx, OrchestratorAction.ASK_USER)

    async def run(
        self,
        query: str | OrchestratorContext,
        conversation_history: list[dict[str, str]] | None = None,
        trace_id: str | None = None,
        source_lang: str = "en",
    ) -> Any:
        """Run the public pipeline entry point while preserving context-level tests."""
        if isinstance(query, OrchestratorContext):
            return await self._run_context(query)

        from app.core.tracing import llm_call_log_var, llm_usage_var
        from app.services.archi_config import get_debug_llm_calls
        from app.services.output_builder import format_phase_timings
        from app.services.trace_collector import TraceCollector

        total_started = time.perf_counter()
        trace = TraceCollector(trace_id=trace_id, source="reply")
        llm_usage_var.set([])
        # Always initialize lightweight LLM call log — heavy fields (messages,
        # response, tokens, cost) are still gated by debug_llm_calls in _record_llm_attempt.
        llm_call_log_var.set([])
        ctx = OrchestratorContext(
            query=query,
            trace_id=trace_id,
            conversation_history=conversation_history or [],
            source_lang=source_lang,
            trace_collector=trace,
        )
        # End-to-end pipeline timeout protection
        timeout_s = float(getattr(self._settings, "pipeline_timeout_seconds", 120.0) or 0)
        try:
            try:
                if timeout_s > 0:
                    output = await asyncio.wait_for(self._run_context(ctx), timeout=timeout_s)
                else:
                    output = await self._run_context(ctx)
            except asyncio.TimeoutError:
                logger.warning("pipeline_timeout", trace_id=trace_id, timeout_s=timeout_s)
                ctx.termination_reason = "pipeline_timeout"
                ctx.state = OrchestratorState.COMPLETE
                from app.services.schemas import AnswerOutput
                output = AnswerOutput(
                    decision="ESCALATE",
                    answer="处理超时，请稍后重试。",
                    followup_questions=[],
                    citations=[],
                    confidence=0.0,
                    debug={"pipeline_timeout": True, "timeout_seconds": timeout_s},
                )
            if not ctx.early_output and not ctx.skip_retrieval:
                trace.complete_node("retrieve")
                trace.complete_node("assess_evidence")
                if ctx.retrieval_attempt > 1:
                    trace.complete_node("retry")
                trace.complete_node("generate")
                trace.complete_node("verify")
            timings = dict(ctx.orchestrator_debug.phase_timings)
            timings["total"] = time.perf_counter() - total_started
            normalized_timings = format_phase_timings(timings)
            output.debug = output.debug or {}
            output.debug["timings"] = normalized_timings
            output.debug.update(normalized_timings)
            output.debug["retry_count"] = max(0, int(ctx.retrieval_attempt or 0))
            if ctx.retry_diagnostics:
                output.debug["retry_diagnostics"] = ctx.retry_diagnostics
            if ctx.orchestrator_debug.convergence_reason:
                output.debug["convergence_reason"] = ctx.orchestrator_debug.convergence_reason
            if ctx.agentic_debug:
                output.debug["agentic_router"] = ctx.agentic_debug
            trace.set_tool_result(
                decision=output.decision,
                citations_count=len(output.citations or []),
                followup_count=len(output.followup_questions or []),
                confidence=output.confidence,
            )
            trace.set_latency(normalized_timings)
            output.debug["trace"] = trace.to_debug()
            return output
        finally:
            if self._owns_llm and hasattr(self._llm, "aclose"):
                await self._llm.aclose()


# Transitional import compatibility. PipelineRunner is the sole implementation.
Orchestrator = PipelineRunner
