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
    """Backward-compatible facade for API callers.

    Lifecycle: If AnswerService creates the LLM gateway (llm param not provided),
    it owns the gateway and must close it after use. Call aclose() or use
    async context manager to prevent resource leaks.
    """

    def __init__(
        self,
        retrieval: RetrievalService | None = None,
        llm: LLMGateway | None = None,
        reviewer: ReviewerGate | None = None,
        runner: PipelineRunner | None = None,
        agentic_router: AgenticRouter | None = None,
    ) -> None:
        self._owns_retrieval = retrieval is None
        resolved_retrieval = retrieval or RetrievalService()
        self._owns_llm = llm is None
        resolved_llm = llm or get_llm_gateway()
        resolved_reviewer = reviewer or ReviewerGate()
        resolved_router = agentic_router or AgenticRouter()
        self._llm = resolved_llm
        self._retrieval = resolved_retrieval
        self._runner = runner or PipelineRunner(
            retrieval=resolved_retrieval,
            llm=resolved_llm,
            reviewer=resolved_reviewer,
            agentic_router=resolved_router,
            intent_matcher=match_intent,
            normalizer=normalize_query,
            language_detector=detect_language,
        )

    async def aclose(self) -> None:
        """Close owned resources (idempotent)."""
        if self._owns_retrieval and hasattr(self._retrieval, "aclose"):
            self._owns_retrieval = False
            try:
                await self._retrieval.aclose()
            except Exception:
                pass
        if self._owns_llm and hasattr(self._llm, "aclose"):
            self._owns_llm = False
            try:
                await self._llm.aclose()
            except Exception:
                pass

    async def __aenter__(self) -> "AnswerService":
        return self

    async def __aexit__(self, *args) -> None:
        await self.aclose()

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
