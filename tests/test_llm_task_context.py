from types import SimpleNamespace

import pytest

from app.core.tracing import current_llm_task_var
from app.search.base import EvidenceChunk, SearchChunk
from app.services.evidence_evaluator import evaluate_evidence
from app.services.evidence_selector import select_evidence_for_query
from app.services.llm_gateway import LLMResponse


@pytest.mark.asyncio
async def test_evidence_evaluator_restores_previous_llm_task_context(monkeypatch):
    """Evidence evaluation must not leak its LLM task label into later calls."""

    observed_tasks: list[str | None] = []

    class FakeGateway:
        async def chat(self, **kwargs):
            observed_tasks.append(current_llm_task_var.get())
            return LLMResponse(
                content='{"relevance_score": 1, "coverage_gaps": [], "retry_needed": false}',
                model="fake-model",
                provider="test",
                input_tokens=1,
                output_tokens=1,
            )

    monkeypatch.setattr(
        "app.services.evidence_evaluator.get_settings",
        lambda: SimpleNamespace(evidence_evaluator_enabled=True),
    )
    monkeypatch.setattr("app.services.evidence_evaluator.get_llm_gateway", lambda: FakeGateway())
    monkeypatch.setattr("app.services.evidence_evaluator.get_model_for_task", lambda task: "fake-model")

    outer_token = current_llm_task_var.set("outer_task")
    try:
        result = await evaluate_evidence(
            "query",
            None,
            [
                EvidenceChunk(
                    chunk_id="chunk-1",
                    snippet="answer evidence",
                    source_url="eval://retrieval/doc-001",
                    doc_type="faq",
                    score=1.0,
                    full_text="answer evidence",
                )
            ],
        )

        assert result is not None
        assert observed_tasks == ["evidence_evaluator"]
        assert current_llm_task_var.get() == "outer_task"
    finally:
        current_llm_task_var.reset(outer_token)


@pytest.mark.asyncio
async def test_evidence_selector_labels_and_restores_llm_task_context(monkeypatch):
    """Evidence selector LLM calls should be labelled instead of appearing as unknown."""

    observed_tasks: list[str | None] = []

    class FakeGateway:
        async def chat(self, **kwargs):
            observed_tasks.append(current_llm_task_var.get())
            return LLMResponse(
                content='{"selected_chunk_ids": ["chunk-1"], "coverage_map": {}, "uncovered_requirements": [], "reasoning": "ok"}',
                model="fake-model",
                provider="test",
                input_tokens=1,
                output_tokens=1,
            )

    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: SimpleNamespace(
            evidence_selector_use_llm=True,
            evidence_selector_structured_doc_types="faq,policy,tos,pricing,howto,docs",
            evidence_selector_conversation_cap=1,
            evidence_selector_min_structured_share=0.6,
            reviewer_policy_doc_types=[],
        ),
    )
    monkeypatch.setattr("app.services.evidence_selector.get_llm_gateway", lambda: FakeGateway())
    monkeypatch.setattr("app.services.evidence_selector.get_model_for_task", lambda task: "fake-model")

    outer_token = current_llm_task_var.set("outer_task")
    try:
        result = await select_evidence_for_query(
            "query",
            [
                (
                    SearchChunk(
                        chunk_id="chunk-1",
                        document_id="doc-1",
                        chunk_text="answer evidence",
                        source_url="eval://retrieval/doc-001",
                        doc_type="faq",
                        score=1.0,
                    ),
                    1.0,
                )
            ],
            required_evidence=["numbers_units"],
            hard_requirements=["numbers_units"],
        )

        assert result.used_llm is True
        assert [chunk.chunk_id for chunk, _ in result.selected] == ["chunk-1"]
        assert observed_tasks == ["evidence_selector"]
        assert current_llm_task_var.get() == "outer_task"
    finally:
        current_llm_task_var.reset(outer_token)
