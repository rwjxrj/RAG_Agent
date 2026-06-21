"""Tests for QuerySpec sub-dataclasses and the refactored retrieval pipeline.

Verifies that:
1. QuerySpec sub-objects are correctly populated
2. Consumers can access fields via sub-objects
3. BudgetConfig/DocTypeStrategy parse correctly
"""

import pytest

from app.services.schemas import (
    QuerySpec,
    QueryIntent,
    RetrievalHints,
    ClarificationNeeds,
    AnswerContract,
    QuerySlots,
    HypothesisSpec,
)
from app.services.retrieval import BudgetConfig, DocTypeStrategy


# ---------------------------------------------------------------------------
# QuerySpec sub-dataclass population
# ---------------------------------------------------------------------------

class TestQuerySpecSubObjects:
    """Verify that __post_init__ correctly populates sub-objects."""

    @pytest.fixture
    def minimal_spec(self):
        return QuerySpec(
            intent="transactional",
            entities=["windows", "vps"],
            constraints={"budget": 50},
            required_evidence=["transaction_link"],
            risk_level="low",
            keyword_queries=["windows vps order"],
            semantic_queries=["windows vps order"],
            clarifying_questions=[],
        )

    @pytest.fixture
    def full_spec(self):
        return QuerySpec(
            intent="policy",
            entities=["refund"],
            constraints={},
            required_evidence=["policy_language"],
            risk_level="medium",
            keyword_queries=["refund policy"],
            semantic_queries=["refund policy"],
            clarifying_questions=["Which product?"],
            is_ambiguous=True,
            answer_mode="PASS_PARTIAL",
            support_level="partial",
            answer_type="pricing",
            answer_shape="recommendation",
            target_entity="refund_policy",
            retrieval_profile="policy_profile",
            primary_hypothesis=HypothesisSpec(
                name="refund_hypothesis",
                evidence_families=["policy_terms"],
                answer_shape="direct_lookup",
            ),
            canonical_query_en="What is the refund policy?",
            resolved_slots={"product_type": "vps", "os": "windows"},
        )

    def test_query_intent_populated(self, minimal_spec):
        assert isinstance(minimal_spec.query_intent, QueryIntent)
        assert minimal_spec.query_intent.intent == "transactional"
        assert minimal_spec.query_intent.entities == ["windows", "vps"]
        assert minimal_spec.query_intent.constraints == {"budget": 50}
        assert minimal_spec.query_intent.risk_level == "low"
        assert minimal_spec.query_intent.is_ambiguous is False

    def test_query_intent_with_full_spec(self, full_spec):
        assert full_spec.query_intent.is_ambiguous is True
        assert full_spec.query_intent.target_entity == "refund_policy"

    def test_retrieval_hints_populated(self, minimal_spec):
        assert isinstance(minimal_spec.retrieval_hints, RetrievalHints)
        assert minimal_spec.retrieval_hints.required_evidence == ["transaction_link"]
        assert minimal_spec.retrieval_hints.retrieval_profile == "generic_profile"

    def test_retrieval_hints_with_hypothesis(self, full_spec):
        assert full_spec.retrieval_hints.primary_hypothesis is not None
        assert full_spec.retrieval_hints.primary_hypothesis.name == "refund_hypothesis"
        assert full_spec.retrieval_hints.retrieval_profile == "policy_profile"

    def test_clarification_needs_populated(self, minimal_spec):
        assert isinstance(minimal_spec.clarification_needs, ClarificationNeeds)
        assert minimal_spec.clarification_needs.answerable_without_clarification is True
        assert minimal_spec.clarification_needs.clarifying_questions == []

    def test_clarification_needs_with_questions(self, full_spec):
        assert full_spec.clarification_needs.clarifying_questions == ["Which product?"]
        assert full_spec.clarification_needs.answerable_without_clarification is True

    def test_answer_contract_populated(self, minimal_spec):
        assert isinstance(minimal_spec.answer_contract, AnswerContract)
        assert minimal_spec.answer_contract.answer_mode == "PASS_EXACT"
        assert minimal_spec.answer_contract.answer_type == "general"
        assert minimal_spec.answer_contract.support_level == "strong"

    def test_answer_contract_with_full_spec(self, full_spec):
        assert full_spec.answer_contract.answer_mode == "PASS_PARTIAL"
        assert full_spec.answer_contract.support_level == "partial"
        assert full_spec.answer_contract.answer_type == "pricing"
        assert full_spec.answer_contract.answer_shape == "recommendation"

    def test_query_slots_populated(self, minimal_spec):
        assert isinstance(minimal_spec.query_slots, QuerySlots)
        assert minimal_spec.query_slots.source_lang == "en"
        assert minimal_spec.query_slots.resolved_slots is None

    def test_query_slots_with_full_spec(self, full_spec):
        assert full_spec.query_slots.canonical_query_en == "What is the refund policy?"
        assert full_spec.query_slots.resolved_slots == {"product_type": "vps", "os": "windows"}

    def test_backward_compatibility(self, full_spec):
        """Old field access still works."""
        assert full_spec.intent == full_spec.query_intent.intent
        assert full_spec.answer_mode == full_spec.answer_contract.answer_mode
        assert full_spec.retrieval_profile == full_spec.retrieval_hints.retrieval_profile
        assert full_spec.resolved_slots == full_spec.query_slots.resolved_slots


# ---------------------------------------------------------------------------
# BudgetConfig
# ---------------------------------------------------------------------------

class TestBudgetConfig:
    def test_default_values(self):
        cfg = BudgetConfig()
        assert cfg.hard_requirements == set()
        assert cfg.ensure_doc_types == []
        assert cfg.diversity_fetch_per_type == 6
        assert cfg.is_pricing_retrieval is False

    def test_with_values(self):
        cfg = BudgetConfig(
            hard_requirements={"transaction_link"},
            ensure_doc_types=["pricing"],
            is_pricing_retrieval=True,
            diversity_fetch_per_type=3,
        )
        assert cfg.hard_requirements == {"transaction_link"}
        assert cfg.ensure_doc_types == ["pricing"]
        assert cfg.is_pricing_retrieval is True


# ---------------------------------------------------------------------------
# DocTypeStrategy
# ---------------------------------------------------------------------------

class TestDocTypeStrategy:
    def test_default_values(self):
        s = DocTypeStrategy()
        assert s.profile == "generic_profile"
        assert s.primary_doc_types == []
        assert s.fetch_n == 20
        assert s.rerank_k == 10

    def test_with_values(self):
        s = DocTypeStrategy(
            profile="pricing_profile",
            primary_doc_types=["pricing"],
            authoritative_doc_types=["pricing"],
            supporting_doc_types=["faq"],
            fetch_n=30,
            rerank_k=15,
        )
        assert s.profile == "pricing_profile"
        assert s.fetch_n == 30
        assert s.rerank_k == 15


# ---------------------------------------------------------------------------
# Consumer access patterns (import verification)
# ---------------------------------------------------------------------------

class TestConsumerImports:
    """Verify that all consumer modules can import and use the refactored types."""

    def test_retrieval_planner_imports(self):
        from app.services.retrieval_planner import (
            _sanitize_answer_type,
            _normalize_product_family,
            _sanitize_doc_type_list,
            _valid_doc_types,
        )
        assert callable(_sanitize_answer_type)
        assert callable(_normalize_product_family)
        assert callable(_sanitize_doc_type_list)
        assert callable(_valid_doc_types)

    def test_decision_router_imports(self):
        from app.services.decision_router import _configured_exact_answer_types
        assert callable(_configured_exact_answer_types)

    def test_answer_utils_imports(self):
        from app.services.answer_utils import (
            _sanitize_answer_mode,
            _sanitize_support_level,
            _to_str_list,
        )
        assert callable(_sanitize_answer_mode)
        assert callable(_sanitize_support_level)
        assert callable(_to_str_list)

    def test_reviewer_imports(self):
        from app.services.reviewer import (
            _normalize_answer_mode,
            _normalize_support_level,
            _to_str_list,
            _configured_exact_answer_types,
        )
        assert callable(_normalize_answer_mode)
        assert callable(_normalize_support_level)
        assert callable(_to_str_list)
        assert callable(_configured_exact_answer_types)

    def test_source_loaders_imports(self):
        from app.services.source_loaders import _infer_page_kind, _normalize_product_family
        assert callable(_infer_page_kind)
        assert callable(_normalize_product_family)

