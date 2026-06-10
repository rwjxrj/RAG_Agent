"""Answer generation with grounding and reviewer gate.

Orchestrates the RAG pipeline via Orchestrator. Phase logic lives in
app.services.phases; helpers in answer_utils and flow_debug.
"""

import time

from app.core.config import get_settings
from app.services.flow_debug import _pipeline_log
from app.core.logging import get_logger
from app.services.agentic_router import (
    AgenticRoute,
    AgenticRouter,
    AgenticRouterInput,
)
from app.services.branding_config import match_intent
from app.services.llm_config import get_llm_fallback_model, get_llm_model
from app.services.llm_gateway import LLMGateway, get_llm_gateway
from app.services.orchestrator import (
    Orchestrator,
    OrchestratorAction,
    OrchestratorContext,
    OrchestratorState,
    PhaseResult,
)
from app.services.archi_config import get_language_detect_enabled
from app.services.language_detect import detect_language
from app.services.normalizer import normalize as normalize_query
from app.services.output_builder import (
    build_output as build_answer_output,
    format_phase_timings,
)
from app.services.phases import (
    execute_assess_evidence,
    execute_decide,
    execute_generate,
    execute_retrieve,
    execute_verify,
)
from app.services.retrieval import RetrievalService
from app.services.schemas import AnswerOutput, QuerySpec
from app.services.reviewer import ReviewerGate
from app.services.trace_collector import TraceCollector

__all__ = ["AnswerOutput", "AnswerService"]

logger = get_logger(__name__)


def _add_phase_timing(timings: dict[str, float], key: str, elapsed_seconds: float) -> None:
    timings[key] = float(timings.get(key, 0.0) or 0.0) + max(0.0, elapsed_seconds)


def _attach_answer_runtime_debug(
    output: AnswerOutput,
    timings: dict[str, float],
    *,
    retry_count: int = 0,
) -> AnswerOutput:
    normalized_timings = format_phase_timings(timings)
    output.debug["timings"] = normalized_timings
    output.debug.update(normalized_timings)
    output.debug["retry_count"] = max(0, int(retry_count or 0))
    return output


class AnswerService:
    """Orchestrates retrieval, LLM generation, and reviewer gate."""

    def __init__(
        self,
        retrieval: RetrievalService | None = None,
        llm: LLMGateway | None = None,
        reviewer: ReviewerGate | None = None,
        orchestrator: Orchestrator | None = None,
        agentic_router: AgenticRouter | None = None,
    ) -> None:
        self._settings = get_settings()
        self._retrieval = retrieval or RetrievalService()
        self._llm = llm or get_llm_gateway()
        self._reviewer = reviewer or ReviewerGate()
        self._agentic_router = agentic_router or AgenticRouter()
        self._orchestrator = orchestrator or Orchestrator(
            primary_model=get_llm_model(),
            fallback_model=get_llm_fallback_model(),
        )

    async def generate(
        self,
        query: str,
        conversation_history: list[dict[str, str]] | None = None,
        trace_id: str | None = None,
    ) -> AnswerOutput:
        """Generate grounded answer with retrieval and reviewer gate."""
        total_started = time.perf_counter()
        phase_timings: dict[str, float] = {}
        trace = TraceCollector(trace_id=trace_id, source="reply")
        trace.start_node("intent_cache")

        def _finish(output: AnswerOutput, *, retry_count: int = 0) -> AnswerOutput:
            phase_timings["total"] = time.perf_counter() - total_started
            output = _attach_answer_runtime_debug(
                output,
                phase_timings,
                retry_count=retry_count,
            )
            output.debug = output.debug or {}
            trace.set_tool_result(
                decision=output.decision,
                citations_count=len(output.citations or []),
                followup_count=len(output.followup_questions or []),
                confidence=output.confidence,
            )
            trace.set_latency(phase_timings)
            output.debug["trace"] = trace.to_debug()
            return output

        from app.core.tracing import llm_usage_var, llm_call_log_var
        llm_usage_var.set([])
        from app.services.archi_config import get_debug_llm_calls
        if get_debug_llm_calls():
            llm_call_log_var.set([])

        _pipeline_log("answer_service", "start", query=query[:80], history_len=len(conversation_history or []), trace_id=trace_id)

        intent = match_intent(query)
        if intent:
            trace.set_intent(True, intent.intent)
            trace.complete_node("intent_cache")
            trace.skip_node("agentic_router", reason="intent_cache_hit")
            _pipeline_log("answer_service", "intent_cache_hit", intent=intent.intent, trace_id=trace_id)
            logger.debug("intent_cache_hit", intent=intent.intent)
            return _finish(AnswerOutput(
                decision="PASS",
                answer=intent.answer,
                followup_questions=[],
                citations=[],
                confidence=1.0,
                debug={
                    "trace_id": trace_id,
                    "intent_cache": intent.intent,
                    "agentic_router": {
                        "skipped": True,
                        "reason": "intent_cache_hit",
                    },
                },
            ))

        trace.set_intent(False)
        trace.skip_node("intent_cache", reason="miss")
        trace.start_node("agentic_router")
        try:
            agentic_decision = self._agentic_router.route(AgenticRouterInput(
                query=query,
                conversation_history=conversation_history or [],
                source="reply",
                trace_id=trace_id,
            ))
        except Exception:
            agentic_decision = AgenticRouter.safe_fallback("router_exception")

        agentic_debug = agentic_decision.to_debug()
        agentic_trace_result = {
            "route": agentic_decision.route,
            "tool": agentic_decision.tool,
            "confidence": agentic_decision.confidence,
            "fallback_to_rag": agentic_decision.fallback_to_rag,
        }
        if agentic_decision.fallback_to_rag:
            trace.fallback_node(
                "agentic_router",
                reason=agentic_decision.reason,
                selected_tool=agentic_decision.tool,
                decision_reason=agentic_decision.reason,
                tool_result=agentic_trace_result,
            )
        else:
            trace.complete_node(
                "agentic_router",
                selected_tool=agentic_decision.tool,
                decision_reason=agentic_decision.reason,
                tool_result=agentic_trace_result,
            )

        if agentic_decision.route == AgenticRoute.DIRECT_RESPONSE:
            app_name = (self._settings.app_name or "").strip()
            answer = f"你好，欢迎使用 {app_name} 客服。有什么可以帮你？" if app_name else "你好，有什么可以帮你？"
            trace.complete_node("direct_response", tool_result={"decision": "PASS"})
            return _finish(AnswerOutput(
                decision="PASS",
                answer=answer,
                followup_questions=[],
                citations=[],
                confidence=agentic_decision.confidence,
                debug={"trace_id": trace_id, "agentic_router": agentic_debug},
            ))

        if agentic_decision.route == AgenticRoute.CLARIFY:
            followups = agentic_decision.clarifying_questions[:3] or ["请补充更多关键信息。"]
            trace.complete_node(
                "clarify",
                tool_result={"decision": "ASK_USER", "followup_count": len(followups)},
            )
            return _finish(AnswerOutput(
                decision="ASK_USER",
                answer="我还需要一点信息才能准确处理这个问题。",
                followup_questions=followups,
                citations=[],
                confidence=agentic_decision.confidence,
                debug={"trace_id": trace_id, "agentic_router": agentic_debug},
            ))

        if agentic_decision.route == AgenticRoute.HUMAN_HANDOFF:
            trace.complete_node("human_handoff", tool_result={"decision": "ESCALATE"})
            return _finish(AnswerOutput(
                decision="ESCALATE",
                answer="这个请求需要人工客服处理，我会将问题转交给人工跟进。",
                followup_questions=[],
                citations=[],
                confidence=agentic_decision.confidence,
                debug={"trace_id": trace_id, "agentic_router": agentic_debug},
            ))

        trace.start_node("query_extract")
        query_extract_started = time.perf_counter()
        source_lang = detect_language(query) if get_language_detect_enabled() else "en"
        query_spec: QuerySpec | None = None
        if getattr(self._settings, "normalizer_enabled", True):
            query_spec = await normalize_query(query, conversation_history, source_lang=source_lang)
            if query_spec:
                _pipeline_log(
                    "normalizer", "done",
                    intent=query_spec.intent,
                    user_goal=getattr(query_spec, "user_goal", ""),
                    required_evidence=query_spec.required_evidence,
                    hard_requirements=getattr(query_spec, "hard_requirements", []),
                    keyword_queries=(query_spec.keyword_queries or [])[:1],
                    retrieval_profile=getattr(query_spec, "retrieval_profile", ""),
                    trace_id=trace_id,
                )
        _add_phase_timing(
            phase_timings,
            "query_extract",
            time.perf_counter() - query_extract_started,
        )
        trace.complete_node("query_extract")

        effective_query = query
        if query_spec and query_spec.canonical_query_en:
            effective_query = query_spec.canonical_query_en

        if query_spec and query_spec.skip_retrieval:
            # Routine question: respond immediately with canned_response, no retrieval or LLM
            _pipeline_log("answer_service", "skip_retrieval_canned", trace_id=trace_id)
            canned = (query_spec.canned_response or "").strip()
            if not canned:
                app_name = (self._settings.app_name or "").strip()
                canned = f"你好，欢迎使用 {app_name} 客服。有什么可以帮你？" if app_name else "你好，有什么可以帮你？"
            trace.complete_node("direct_response", tool_result={"decision": "PASS"})
            return _finish(AnswerOutput(
                decision="PASS",
                answer=canned,
                followup_questions=[],
                citations=[],
                confidence=1.0,
                debug={"trace_id": trace_id, "skip_retrieval": True},
            ))

        required_evidence = (
            query_spec.required_evidence if query_spec else []
        )
        hard_requirements = (
            (query_spec.hard_requirements or [])
            if query_spec and getattr(query_spec, "hard_requirements", None) is not None
            else []
        )

        fallback_hypothesis_count = len(getattr(query_spec, "fallback_hypotheses", None) or []) if query_spec else 0
        max_attempts = max(self._settings.max_retrieval_attempts, 1 + fallback_hypothesis_count)
        _pipeline_log(
            "answer_service", "context_created",
            intent=getattr(query_spec, "intent", ""),
            user_goal=getattr(query_spec, "user_goal", ""),
            required_evidence=required_evidence,
            hard_requirements=hard_requirements,
            evidence_families=getattr(query_spec, "evidence_families", []),
            answer_shape=getattr(query_spec, "answer_shape", "direct_lookup"),
            effective_query=effective_query[:80],
            trace_id=trace_id,
        )
        ctx = OrchestratorContext(
            query=query,
            state=OrchestratorState.UNDERSTANDING,
            trace_id=trace_id,
            conversation_history=conversation_history or [],
            max_attempts=max_attempts,
            query_spec=query_spec,
            effective_query=effective_query,
            source_lang=source_lang,
            extra={
                "phase_timings": phase_timings,
                "required_evidence": required_evidence,
                "hard_requirements": hard_requirements,
                "primary_hypothesis_name": getattr(getattr(query_spec, "primary_hypothesis", None), "name", "primary") if query_spec else "primary",
            },
        )

        output = await self._orchestrator.run(ctx, self)
        trace.complete_node("retrieve")
        trace.complete_node("assess_evidence")
        if ctx.retrieval_attempt > 1:
            trace.complete_node("retry")
        trace.complete_node("generate")
        trace.complete_node("verify")
        output.debug = output.debug or {}
        output.debug["agentic_router"] = agentic_debug
        return _finish(output, retry_count=ctx.retrieval_attempt)

    async def _execute_understand(self, ctx: OrchestratorContext) -> PhaseResult:
        """UNDERSTAND: already done before orchestrator."""
        return PhaseResult(
            query_spec=ctx.query_spec,
            effective_query=ctx.effective_query or ctx.query,
            source_lang=ctx.source_lang,
        )

    async def execute(
        self, ctx: OrchestratorContext, action: OrchestratorAction
    ) -> PhaseResult:
        """Execute phase per OrchestratorHandlers protocol."""
        if action == OrchestratorAction.UNDERSTAND:
            return await self._execute_understand(ctx)
        if action == OrchestratorAction.RETRIEVE:
            return await execute_retrieve(
                ctx,
                retrieval=self._retrieval,
                orchestrator=self._orchestrator,
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
                orchestrator=self._orchestrator,
                settings=self._settings,
            )
        if action == OrchestratorAction.VERIFY:
            return await execute_verify(ctx, reviewer=self._reviewer)
        return PhaseResult()

    async def build_output(
        self, ctx: OrchestratorContext, action: OrchestratorAction
    ) -> AnswerOutput:
        """Build AnswerOutput for terminal actions per OrchestratorHandlers protocol."""
        return await build_answer_output(
            ctx,
            action,
            get_model_for_query=self._orchestrator.get_model_for_query,
        )
