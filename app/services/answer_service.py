"""Stable AnswerService facade over the PipelineRunner."""

from app.services.agentic_router import AgenticRouter
from app.services.branding_config import match_intent
from app.services.llm_gateway import LLMGateway, get_llm_gateway
from app.services.orchestrator import PipelineRunner
from app.services.language_detect import detect_language
from app.services.normalizer import normalize as normalize_query
from app.services.retrieval import RetrievalService
from app.services.schemas import AnswerOutput
from app.services.reviewer import ReviewerGate

__all__ = ["AnswerOutput", "AnswerService"]

class AnswerService:
    """Backward-compatible facade for API callers."""

    def __init__(
        self,
        retrieval: RetrievalService | None = None,
        llm: LLMGateway | None = None,
        reviewer: ReviewerGate | None = None,
        runner: PipelineRunner | None = None,
        agentic_router: AgenticRouter | None = None,
    ) -> None:
        resolved_retrieval = retrieval or RetrievalService()
        resolved_llm = llm or get_llm_gateway()
        resolved_reviewer = reviewer or ReviewerGate()
        resolved_router = agentic_router or AgenticRouter()
        self._runner = runner or PipelineRunner(
            retrieval=resolved_retrieval,
            llm=resolved_llm,
            reviewer=resolved_reviewer,
            agentic_router=resolved_router,
            intent_matcher=match_intent,
            normalizer=normalize_query,
            language_detector=detect_language,
        )

    async def generate(
        self,
        query: str,
        conversation_history: list[dict[str, str]] | None = None,
        trace_id: str | None = None,
    ) -> AnswerOutput:
        """Delegate answer generation to the single pipeline owner."""
        return await self._runner.run(
            query,
            conversation_history=conversation_history,
            trace_id=trace_id,
        )
