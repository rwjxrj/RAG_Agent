"""Tests for normalizer fast-path (Issue 3)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.normalizer import normalize
from app.services.normalizer_fastpath import try_fastpath
from app.services.schemas import QuerySpec


# ---------------------------------------------------------------------------
# Direct fast-path module tests
# ---------------------------------------------------------------------------


def test_fastpath_service_hours():
    result = try_fastpath("晚上几点还有真人客服")
    assert result is not None
    spec, rule_name = result
    assert rule_name == "service_hours"
    assert spec.extraction_mode == "rule_fastpath"
    assert spec.intent == "informational"
    assert spec.answer_shape == "direct_lookup"
    assert spec.risk_level == "low"
    assert spec.is_ambiguous is False
    assert spec.required_evidence == ["policy_language"]
    assert spec.retrieval_profile == "generic_profile"
    assert "faq" in (spec.doc_type_prior or [])
    assert spec.primary_hypothesis is not None
    assert spec.keyword_queries
    assert spec.semantic_queries
    assert spec.canonical_query_en


def test_fastpath_service_hours_variant():
    result = try_fastpath("客服上班时间是几点")
    assert result is not None
    spec, rule_name = result
    assert rule_name == "service_hours"


def test_fastpath_refund_arrival_time():
    result = try_fastpath("退款多久到账")
    assert result is not None
    spec, rule_name = result
    assert rule_name == "refund_arrival_time"
    assert spec.intent == "policy"
    assert spec.answer_type == "policy"
    assert spec.retrieval_profile == "policy_profile"
    assert "policy" in (spec.doc_type_prior or [])


def test_fastpath_refund_arrival_variant():
    result = try_fastpath("退款什么时候到账")
    assert result is not None
    assert result[1] == "refund_arrival_time"


def test_fastpath_order_hold_time():
    result = try_fastpath("下单没付款多久释放")
    assert result is not None
    spec, rule_name = result
    assert rule_name == "order_hold_time"
    assert spec.intent == "informational"


def test_fastpath_order_hold_variant():
    result = try_fastpath("未付款订单保留多久")
    assert result is not None
    assert result[1] == "order_hold_time"


def test_fastpath_return_period():
    result = try_fastpath("几天内能退")
    assert result is not None
    spec, rule_name = result
    assert rule_name == "return_period"
    assert spec.intent == "policy"
    assert spec.retrieval_profile == "policy_profile"


def test_fastpath_return_period_variant():
    result = try_fastpath("多久可以退换货")
    assert result is not None
    assert result[1] == "return_period"


def test_fastpath_faq_selection():
    result = try_fastpath("怎么选尺码")
    assert result is not None
    spec, rule_name = result
    assert rule_name == "faq_selection"
    assert spec.answer_expectation == "best_effort"


def test_fastpath_faq_selection_variant():
    result = try_fastpath("推荐哪个好")
    assert result is not None
    assert result[1] == "faq_selection"


# ---------------------------------------------------------------------------
# Exclusion tests — queries that must NOT hit fast-path
# ---------------------------------------------------------------------------


def test_fastpath_excluded_referential():
    """Pronoun-based query should not hit fast-path."""
    result = try_fastpath("这个还能退吗")
    assert result is None


def test_fastpath_excluded_high_risk_execution():
    """High-risk execution request should not hit fast-path."""
    result = try_fastpath("帮我退款")
    assert result is None


def test_fastpath_excluded_high_risk_cancel():
    result = try_fastpath("替我取消订单")
    assert result is None


def test_fastpath_excluded_account_security():
    """Account/security queries should not hit fast-path."""
    result = try_fastpath("我的账号异常")
    assert result is None


def test_fastpath_excluded_complaint():
    result = try_fastpath("我要投诉")
    assert result is None


def test_fastpath_excluded_multi_condition():
    """Multi-condition queries should not hit fast-path."""
    result = try_fastpath("退款而且换货")
    assert result is None


def test_fastpath_empty_query():
    result = try_fastpath("")
    assert result is None


def test_fastpath_too_short():
    result = try_fastpath("退")
    assert result is None


def test_fastpath_no_match():
    """A query that doesn't match any rule should return None."""
    result = try_fastpath("VPS pricing for Windows")
    assert result is None


# ---------------------------------------------------------------------------
# QuerySpec completeness — downstream should not need special handling
# ---------------------------------------------------------------------------


def test_fastpath_spec_has_all_required_fields():
    result = try_fastpath("退款多久到账")
    assert result is not None
    spec, _ = result
    # Verify all critical fields are populated
    assert spec.intent
    assert spec.answer_type
    assert spec.answer_shape
    assert spec.retrieval_profile
    assert spec.risk_level
    assert spec.keyword_queries
    assert spec.semantic_queries
    assert spec.rewrite_candidates
    assert spec.primary_hypothesis is not None
    assert spec.extraction_mode == "rule_fastpath"
    assert spec.fastpath_rule == "refund_arrival_time"
    assert spec.source_lang == "zh"
    assert spec.translation_needed is True
    assert spec.canonical_query_en
    assert isinstance(spec.required_evidence, list)
    assert isinstance(spec.hard_requirements, list)
    assert isinstance(spec.soft_requirements, list)
    assert isinstance(spec.evidence_families, list)
    assert isinstance(spec.doc_type_prior, list)


@pytest.mark.parametrize(
    "query,expected_rule",
    [
        ("晚上几点还有真人客服", "service_hours"),
        ("退款多久到账", "refund_arrival_time"),
        ("下单没付款多久释放", "order_hold_time"),
        ("几天内能退货", "return_period"),
        ("洗护怎么选", "faq_selection"),
    ],
)
def test_fastpath_rule_name_matches(query: str, expected_rule: str):
    """Each rule should set fastpath_rule to its name on the QuerySpec."""
    result = try_fastpath(query)
    assert result is not None, f"Expected fast-path hit for '{query}'"
    spec, rule_name = result
    assert rule_name == expected_rule
    assert spec.fastpath_rule == expected_rule


def test_fastpath_build_spec_returns_valid_queryspec():
    """Regression: _build_spec_from_rule must construct a valid QuerySpec
    without TypeError from undeclared kwargs like fastpath_rule."""
    from app.services.normalizer_fastpath import _build_spec_from_rule, _RULES
    from app.services.schemas import QuerySpec

    rule = next(r for r in _RULES if r.name == "refund_arrival_time")
    spec = _build_spec_from_rule(rule, "退款多久到账")
    assert isinstance(spec, QuerySpec)
    assert spec.fastpath_rule == "refund_arrival_time"
    assert spec.extraction_mode == "rule_fastpath"
    assert spec.intent
    assert spec.keyword_queries


# ---------------------------------------------------------------------------
# Integration: normalize() function uses fast-path when enabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normalize_uses_fastpath_when_enabled(monkeypatch):
    """When fast-path is enabled and query matches, no LLM call is made."""
    monkeypatch.setattr(
        "app.services.normalizer.get_settings",
        lambda: type("S", (), {"normalizer_fastpath_enabled": True})(),
    )
    with patch("app.services.normalizer.get_llm_gateway") as mock_gw:
        spec = await normalize("退款多久到账")

    # LLM should NOT be called
    mock_gw.assert_not_called()
    assert spec.extraction_mode == "rule_fastpath"
    assert spec.intent == "policy"


@pytest.mark.asyncio
async def test_normalize_skips_fastpath_when_disabled(monkeypatch):
    """When fast-path is disabled, LLM is called even for simple queries."""
    monkeypatch.setattr(
        "app.services.normalizer.get_settings",
        lambda: type("S", (), {
            "normalizer_fastpath_enabled": False,
            "normalizer_llm_max_attempts": 1,
            "normalizer_llm_retry_backoff_ms": 0,
        })(),
    )
    mock_spec = MagicMock()
    mock_spec.extraction_mode = "llm_primary"
    with patch("app.services.normalizer._normalize_llm", new_callable=AsyncMock, return_value=mock_spec) as mock_llm:
        spec = await normalize("退款多久到账")

    mock_llm.assert_called_once()
    assert spec.extraction_mode == "llm_primary"


@pytest.mark.asyncio
async def test_normalize_skips_fastpath_with_conversation_history(monkeypatch):
    """Fast-path is not used when conversation_history is present."""
    monkeypatch.setattr(
        "app.services.normalizer.get_settings",
        lambda: type("S", (), {
            "normalizer_fastpath_enabled": True,
            "normalizer_llm_max_attempts": 1,
            "normalizer_llm_retry_backoff_ms": 0,
        })(),
    )
    mock_spec = MagicMock()
    mock_spec.extraction_mode = "llm_primary"
    with patch("app.services.normalizer._normalize_llm", new_callable=AsyncMock, return_value=mock_spec) as mock_llm:
        spec = await normalize(
            "退款多久到账",
            conversation_history=[{"role": "user", "content": "我之前买了VPS"}],
        )

    mock_llm.assert_called_once()
    assert spec.extraction_mode == "llm_primary"


@pytest.mark.asyncio
async def test_normalize_fastpath_miss_falls_back_to_llm(monkeypatch):
    """When fast-path doesn't match, LLM is called."""
    monkeypatch.setattr(
        "app.services.normalizer.get_settings",
        lambda: type("S", (), {
            "normalizer_fastpath_enabled": True,
            "normalizer_llm_max_attempts": 1,
            "normalizer_llm_retry_backoff_ms": 0,
        })(),
    )
    mock_spec = MagicMock()
    mock_spec.extraction_mode = "llm_primary"
    with patch("app.services.normalizer._normalize_llm", new_callable=AsyncMock, return_value=mock_spec) as mock_llm:
        spec = await normalize("Windows VPS pricing")

    mock_llm.assert_called_once()
    assert spec.extraction_mode == "llm_primary"
