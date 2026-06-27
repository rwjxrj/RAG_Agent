"""Tests for evidence selector service."""

import pytest
from unittest.mock import AsyncMock, patch

from app.search.base import SearchChunk
from app.services.evidence_selector import (
    EvidenceSelectionResult,
    select_evidence_for_query,
)


def _make_chunk(cid: str, text: str = "content", doc_type: str = "faq", url: str = "") -> SearchChunk:
    return SearchChunk(
        chunk_id=cid,
        document_id="d1",
        chunk_text=text,
        source_url=url or f"https://example.com/{cid}",
        doc_type=doc_type,
        score=0.8,
    )


@pytest.mark.asyncio
async def test_select_evidence_empty_reranked():
    """Empty reranked returns empty selection."""
    result = await select_evidence_for_query("query", [], required_evidence=["numbers_units"])
    assert result.selected == []
    assert result.uncovered_requirements == ["numbers_units"]


@pytest.mark.asyncio
async def test_select_evidence_disabled_uses_top_k(monkeypatch):
    """When evidence_selector_use_llm=False, return top-k."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type("S", (), {"evidence_selector_use_llm": False})(),
    )
    chunks = [
        (_make_chunk("c1"), 0.9),
        (_make_chunk("c2"), 0.8),
        (_make_chunk("c3"), 0.7),
        (_make_chunk("c4"), 0.6),
        (_make_chunk("c5"), 0.5),
    ]
    result = await select_evidence_for_query("query", chunks, top_k_fallback=3)
    assert len(result.selected) == 3
    assert result.selected[0][0].chunk_id == "c1"
    assert result.used_llm is False


@pytest.mark.asyncio
async def test_select_evidence_skips_llm_when_no_required_evidence(monkeypatch):
    """When there is no coverage requirement, selector should not spend an LLM call."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type("S", (), {"evidence_selector_use_llm": True})(),
    )
    chunks = [
        (_make_chunk("c1"), 0.9),
        (_make_chunk("c2"), 0.8),
        (_make_chunk("c3"), 0.7),
    ]
    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        result = await select_evidence_for_query("query", chunks, required_evidence=[], top_k_fallback=2)

    mock_gw.assert_not_called()
    assert [chunk.chunk_id for chunk, _ in result.selected] == ["c1", "c2"]
    assert result.used_llm is False
    assert result.reasoning == "top_k_no_required_evidence"
    assert result.skip_reason == "no_required_evidence"


@pytest.mark.asyncio
async def test_select_evidence_skips_llm_for_single_weak_required_evidence(monkeypatch):
    """A single weak coverage hint should not spend selector LLM by itself."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type("S", (), {"evidence_selector_use_llm": True})(),
    )
    chunks = [
        (_make_chunk("c1", doc_type="faq"), 0.9),
        (_make_chunk("c2", doc_type="policy"), 0.8),
        (_make_chunk("c3", doc_type="conversation"), 0.7),
    ]

    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        result = await select_evidence_for_query(
            "退款多久到账？",
            chunks,
            required_evidence=["policy_language"],
            answer_shape="direct_lookup",
            answer_type="general",
            risk_level="low",
            top_k_fallback=2,
        )

    mock_gw.assert_not_called()
    assert [chunk.chunk_id for chunk, _ in result.selected] == ["c1", "c2"]
    assert result.used_llm is False
    assert result.skip_reason == "single_weak_required_evidence"
    assert result.reasoning == "deterministic_selector_skip"


@pytest.mark.asyncio
async def test_select_evidence_calls_llm_when_hard_requirements_present(monkeypatch):
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type("S", (), {
            "evidence_selector_use_llm": True,
            "evidence_selector_skip_single_policy_language": False,
        })(),
    )
    chunks = [
        (_make_chunk("c1", doc_type="faq"), 0.9),
        (_make_chunk("c2", doc_type="policy"), 0.8),
    ]
    mock_resp = type(
        "R",
        (),
        {
            "content": '{"selected_chunk_ids": ["c2"], "coverage_map": {"policy_language": "c2"}, "uncovered_requirements": [], "reasoning": "hard requirement"}',
        },
    )()

    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        mock_gw.return_value.chat = AsyncMock(return_value=mock_resp)
        with patch("app.services.evidence_selector.get_model_for_task", return_value="gpt-4o-mini"):
            result = await select_evidence_for_query(
                "退款政策是什么？",
                chunks,
                required_evidence=["policy_language"],
                hard_requirements=["policy_language"],
                answer_shape="direct_lookup",
                answer_type="general",
                risk_level="low",
            )

    assert result.used_llm is True
    assert result.trigger_reason == "hard_requirements_present"


@pytest.mark.asyncio
async def test_select_evidence_calls_llm_for_complex_policy_answer_type(monkeypatch):
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type("S", (), {"evidence_selector_use_llm": True})(),
    )
    chunks = [
        (_make_chunk("c1", doc_type="faq"), 0.9),
        (_make_chunk("c2", doc_type="policy"), 0.8),
    ]
    mock_resp = type(
        "R",
        (),
        {
            "content": '{"selected_chunk_ids": ["c2"], "coverage_map": {"policy_language": "c2"}, "uncovered_requirements": [], "reasoning": "policy answer"}',
        },
    )()

    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        mock_gw.return_value.chat = AsyncMock(return_value=mock_resp)
        with patch("app.services.evidence_selector.get_model_for_task", return_value="gpt-4o-mini"):
                result = await select_evidence_for_query(
                    "退款政策是什么？",
                    chunks,
                    required_evidence=["policy_language"],
                    answer_shape="procedural",
                    answer_type="policy",
                    risk_level="low",
                )

    assert result.used_llm is True
    assert result.trigger_reason == "answer_type_policy"


@pytest.mark.asyncio
async def test_select_evidence_skips_llm_for_low_risk_policy_exact_direct_lookup_with_single_weak_requirement(monkeypatch):
    """Normalizer labels many simple FAQs as policy+exact; that alone should not force selector LLM."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type("S", (), {"evidence_selector_use_llm": True})(),
    )
    chunks = [
        (_make_chunk("c1", doc_type="faq"), 0.9),
        (_make_chunk("c2", doc_type="policy"), 0.8),
        (_make_chunk("c3", doc_type="faq"), 0.7),
    ]

    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        result = await select_evidence_for_query(
            "你们晚上几点还有真人客服呀？",
            chunks,
            required_evidence=["policy_language"],
            hard_requirements=[],
            answer_shape="direct_lookup",
            answer_type="policy",
            answer_expectation="exact",
            risk_level="low",
            top_k_fallback=2,
        )

    mock_gw.assert_not_called()
    assert result.used_llm is False
    assert result.skip_reason == "single_weak_required_evidence"


@pytest.mark.asyncio
async def test_select_evidence_llm_success(monkeypatch):
    """When LLM succeeds, return selected chunks."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type("S", (), {"evidence_selector_use_llm": True})(),
    )
    chunks = [
        (_make_chunk("c1", doc_type="pricing"), 0.9),
        (_make_chunk("c2", doc_type="faq"), 0.8),
        (_make_chunk("c3", doc_type="policy"), 0.7),
    ]
    mock_resp = type("R", (), {
        "content": '{"selected_chunk_ids": ["c1", "c3"], "coverage_map": {"numbers_units": "c1"}, "uncovered_requirements": [], "reasoning": "selected pricing and policy"}',
    })()
    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        mock_gw.return_value.chat = AsyncMock(return_value=mock_resp)
        with patch("app.services.evidence_selector.get_model_for_task", return_value="gpt-4o-mini"):
            result = await select_evidence_for_query(
                "query",
                chunks,
                required_evidence=["numbers_units"],
                hard_requirements=["numbers_units"],
            )
    assert len(result.selected) == 2
    assert result.selected[0][0].chunk_id == "c1"
    assert result.selected[1][0].chunk_id == "c3"
    assert result.coverage_map == {"numbers_units": "c1"}
    assert result.used_llm is True


@pytest.mark.asyncio
async def test_select_evidence_llm_fallback_on_error(monkeypatch):
    """When LLM fails, fallback to top-k."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type("S", (), {"evidence_selector_use_llm": True})(),
    )
    chunks = [
        (_make_chunk("c1"), 0.9),
        (_make_chunk("c2"), 0.8),
        (_make_chunk("c3"), 0.7),
    ]
    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        mock_gw.return_value.chat = AsyncMock(side_effect=Exception("LLM error"))
        result = await select_evidence_for_query(
            "query",
            chunks,
            required_evidence=["numbers_units"],
            hard_requirements=["numbers_units"],
            top_k_fallback=2,
        )
    assert len(result.selected) == 2
    assert result.selected[0][0].chunk_id == "c1"
    assert result.used_llm is False
    assert result.trigger_reason == "hard_requirements_present"


@pytest.mark.asyncio
async def test_select_evidence_llm_invalid_ids_fallback(monkeypatch):
    """When LLM returns invalid chunk IDs, fallback to top-k."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type("S", (), {"evidence_selector_use_llm": True})(),
    )
    chunks = [
        (_make_chunk("c1"), 0.9),
        (_make_chunk("c2"), 0.8),
    ]
    mock_resp = type("R", (), {
        "content": '{"selected_chunk_ids": ["invalid_id"], "coverage_map": {}, "uncovered_requirements": [], "reasoning": "bad"}',
    })()
    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        mock_gw.return_value.chat = AsyncMock(return_value=mock_resp)
        with patch("app.services.evidence_selector.get_model_for_task", return_value="gpt-4o-mini"):
            result = await select_evidence_for_query(
                "query",
                chunks,
                required_evidence=["numbers_units"],
                hard_requirements=["numbers_units"],
                top_k_fallback=2,
            )
    assert len(result.selected) == 2  # fallback
    assert result.used_llm is True  # LLM was called but returned invalid


@pytest.mark.asyncio
async def test_select_evidence_validates_policy_language_mapping(monkeypatch):
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type(
            "S",
            (),
            {"evidence_selector_use_llm": True, "reviewer_policy_doc_types": ["policy", "tos"]},
        )(),
    )
    chunks = [
        (_make_chunk("c1", doc_type="faq"), 0.9),
        (_make_chunk("c2", doc_type="policy"), 0.8),
    ]
    mock_resp = type("R", (), {
        "content": '{"selected_chunk_ids": ["c1", "c2"], "coverage_map": {"policy_language": "c1"}, "uncovered_requirements": [], "reasoning": "picked faq"}',
    })()
    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        mock_gw.return_value.chat = AsyncMock(return_value=mock_resp)
        with patch("app.services.evidence_selector.get_model_for_task", return_value="gpt-4o-mini"):
            result = await select_evidence_for_query(
                "query",
                chunks,
                required_evidence=["policy_language"],
                answer_type="policy",
            )
    assert result.coverage_map == {}
    assert result.uncovered_requirements == ["policy_language"]


@pytest.mark.asyncio
async def test_select_evidence_rebalances_toward_structured_docs(monkeypatch):
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type(
            "S",
            (),
            {
                "evidence_selector_use_llm": False,
                "evidence_selector_structured_doc_types": "howto,docs,faq,policy,tos,pricing",
                "evidence_selector_conversation_cap": 1,
                "evidence_selector_min_structured_share": 0.75,
            },
        )(),
    )
    chunks = [
        (_make_chunk("conv1", doc_type="conversation"), 0.95),
        (_make_chunk("conv2", doc_type="conversation"), 0.9),
        (_make_chunk("how1", doc_type="howto"), 0.7),
        (_make_chunk("doc1", doc_type="docs"), 0.68),
        (_make_chunk("faq1", doc_type="faq"), 0.66),
    ]

    result = await select_evidence_for_query("how to configure", chunks, top_k_fallback=4)

    selected_doc_types = [(c.doc_type or "").lower() for c, _ in result.selected]
    assert selected_doc_types.count("conversation") <= 1
    assert sum(1 for dt in selected_doc_types if dt in {"howto", "docs", "faq"}) >= 2


# ---------------------------------------------------------------------------
# Phase 2 trigger condition tests (Issue 2 gap fills)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_evidence_calls_llm_for_pricing_answer_type(monkeypatch):
    """answer_type=pricing should trigger selector LLM."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type("S", (), {"evidence_selector_use_llm": True})(),
    )
    chunks = [
        (_make_chunk("c1", doc_type="pricing"), 0.9),
        (_make_chunk("c2", doc_type="faq"), 0.8),
    ]
    mock_resp = type("R", (), {
        "content": '{"selected_chunk_ids": ["c1"], "coverage_map": {}, "uncovered_requirements": [], "reasoning": "pricing"}',
    })()

    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        mock_gw.return_value.chat = AsyncMock(return_value=mock_resp)
        with patch("app.services.evidence_selector.get_model_for_task", return_value="gpt-4o-mini"):
            result = await select_evidence_for_query(
                "价格多少",
                chunks,
                required_evidence=["numbers_units"],
                answer_type="pricing",
                answer_shape="comparison",
                risk_level="low",
            )

    assert result.used_llm is True
    assert result.trigger_reason == "answer_type_pricing"


@pytest.mark.asyncio
async def test_select_evidence_calls_llm_for_direct_link_answer_type(monkeypatch):
    """answer_type=direct_link should trigger selector LLM."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type("S", (), {"evidence_selector_use_llm": True})(),
    )
    chunks = [
        (_make_chunk("c1", doc_type="docs"), 0.9),
        (_make_chunk("c2", doc_type="faq"), 0.8),
    ]
    mock_resp = type("R", (), {
        "content": '{"selected_chunk_ids": ["c1"], "coverage_map": {}, "uncovered_requirements": [], "reasoning": "link"}',
    })()

    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        mock_gw.return_value.chat = AsyncMock(return_value=mock_resp)
        with patch("app.services.evidence_selector.get_model_for_task", return_value="gpt-4o-mini"):
            result = await select_evidence_for_query(
                "给我一个链接",
                chunks,
                required_evidence=["has_any_url"],
                answer_type="direct_link",
                answer_shape="procedural",
                risk_level="low",
            )

    assert result.used_llm is True
    assert result.trigger_reason == "answer_type_direct_link"


@pytest.mark.asyncio
async def test_select_evidence_calls_llm_for_exact_answer_expectation(monkeypatch):
    """answer_expectation=exact with non-weak evidence should trigger selector LLM."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type("S", (), {"evidence_selector_use_llm": True})(),
    )
    chunks = [
        (_make_chunk("c1", doc_type="faq"), 0.9),
        (_make_chunk("c2", doc_type="policy"), 0.8),
    ]
    mock_resp = type("R", (), {
        "content": '{"selected_chunk_ids": ["c1"], "coverage_map": {}, "uncovered_requirements": [], "reasoning": "exact"}',
    })()

    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        mock_gw.return_value.chat = AsyncMock(return_value=mock_resp)
        with patch("app.services.evidence_selector.get_model_for_task", return_value="gpt-4o-mini"):
            result = await select_evidence_for_query(
                "具体数字是什么",
                chunks,
                required_evidence=["numbers_units"],
                answer_shape="procedural",
                answer_type="general",
                answer_expectation="exact",
                risk_level="low",
            )

    assert result.used_llm is True
    assert result.trigger_reason == "answer_expectation_exact"


@pytest.mark.asyncio
async def test_select_evidence_calls_llm_for_medium_risk(monkeypatch):
    """risk_level=medium should trigger selector LLM even with simple query."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type("S", (), {"evidence_selector_use_llm": True})(),
    )
    chunks = [
        (_make_chunk("c1", doc_type="policy"), 0.9),
        (_make_chunk("c2", doc_type="faq"), 0.8),
    ]
    mock_resp = type("R", (), {
        "content": '{"selected_chunk_ids": ["c1"], "coverage_map": {}, "uncovered_requirements": [], "reasoning": "medium risk"}',
    })()

    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        mock_gw.return_value.chat = AsyncMock(return_value=mock_resp)
        with patch("app.services.evidence_selector.get_model_for_task", return_value="gpt-4o-mini"):
            result = await select_evidence_for_query(
                "退款怎么操作",
                chunks,
                required_evidence=["policy_language"],
                answer_shape="direct_lookup",
                answer_type="general",
                risk_level="medium",
            )

    assert result.used_llm is True
    assert result.trigger_reason == "risk_level_medium"


@pytest.mark.asyncio
async def test_select_evidence_calls_llm_for_high_risk(monkeypatch):
    """risk_level=high should trigger selector LLM even with simple query."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type("S", (), {"evidence_selector_use_llm": True})(),
    )
    chunks = [
        (_make_chunk("c1", doc_type="policy"), 0.9),
        (_make_chunk("c2", doc_type="tos"), 0.8),
    ]
    mock_resp = type("R", (), {
        "content": '{"selected_chunk_ids": ["c1", "c2"], "coverage_map": {}, "uncovered_requirements": [], "reasoning": "high risk"}',
    })()

    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        mock_gw.return_value.chat = AsyncMock(return_value=mock_resp)
        with patch("app.services.evidence_selector.get_model_for_task", return_value="gpt-4o-mini"):
            result = await select_evidence_for_query(
                "账号被盗了",
                chunks,
                required_evidence=["policy_language"],
                answer_shape="direct_lookup",
                answer_type="general",
                risk_level="high",
            )

    assert result.used_llm is True
    assert result.trigger_reason == "risk_level_high"


@pytest.mark.asyncio
async def test_select_evidence_calls_llm_for_multiple_required_evidence(monkeypatch):
    """Two or more required evidence types should trigger selector LLM."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type("S", (), {"evidence_selector_use_llm": True})(),
    )
    chunks = [
        (_make_chunk("c1", doc_type="policy"), 0.9),
        (_make_chunk("c2", doc_type="pricing"), 0.8),
    ]
    mock_resp = type("R", (), {
        "content": '{"selected_chunk_ids": ["c1", "c2"], "coverage_map": {"policy_language": "c1", "numbers_units": "c2"}, "uncovered_requirements": [], "reasoning": "multi"}',
    })()

    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        mock_gw.return_value.chat = AsyncMock(return_value=mock_resp)
        with patch("app.services.evidence_selector.get_model_for_task", return_value="gpt-4o-mini"):
            result = await select_evidence_for_query(
                "退款政策和金额",
                chunks,
                required_evidence=["policy_language", "numbers_units"],
                answer_shape="comparison",
                answer_type="general",
                risk_level="low",
            )

    assert result.used_llm is True
    assert result.trigger_reason == "multiple_required_evidence"


@pytest.mark.asyncio
async def test_select_evidence_skips_llm_for_direct_lookup_with_structured_candidates(monkeypatch):
    """direct_lookup + all top candidates are structured docs should skip LLM even when metadata trigger fires."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type("S", (), {
            "evidence_selector_use_llm": True,
            "evidence_selector_structured_doc_types": "howto,docs,faq,policy,tos,pricing",
            "evidence_selector_conversation_cap": 1,
            "evidence_selector_min_structured_share": 0.6,
        })(),
    )
    chunks = [
        (_make_chunk("c1", doc_type="faq"), 0.95),
        (_make_chunk("c2", doc_type="policy"), 0.9),
        (_make_chunk("c3", doc_type="docs"), 0.85),
        (_make_chunk("c4", doc_type="howto"), 0.8),
    ]

    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        result = await select_evidence_for_query(
            "退款多久到账",
            chunks,
            required_evidence=["policy_language", "numbers_units"],
            answer_shape="direct_lookup",
            answer_type="policy",
            answer_expectation="exact",
            risk_level="low",
            top_k_fallback=3,
        )

    mock_gw.assert_not_called()
    assert result.used_llm is False
    assert result.skip_reason == "direct_lookup_deterministic"


@pytest.mark.asyncio
async def test_select_evidence_keeps_llm_for_direct_lookup_with_non_structured_candidates(monkeypatch):
    """direct_lookup with non-structured top candidates should NOT skip LLM when trigger fires."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: type("S", (), {
            "evidence_selector_use_llm": True,
            "evidence_selector_structured_doc_types": "howto,docs,faq,policy,tos,pricing",
            "evidence_selector_conversation_cap": 1,
            "evidence_selector_min_structured_share": 0.6,
        })(),
    )
    chunks = [
        (_make_chunk("c1", doc_type="conversation"), 0.95),
        (_make_chunk("c2", doc_type="conversation"), 0.9),
        (_make_chunk("c3", doc_type="policy"), 0.85),
    ]
    mock_resp = type("R", (), {
        "content": '{"selected_chunk_ids": ["c3"], "coverage_map": {}, "uncovered_requirements": [], "reasoning": "mixed"}',
    })()

    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        mock_gw.return_value.chat = AsyncMock(return_value=mock_resp)
        with patch("app.services.evidence_selector.get_model_for_task", return_value="gpt-4o-mini"):
            result = await select_evidence_for_query(
                "退款政策",
                chunks,
                required_evidence=["policy_language", "numbers_units"],
                answer_shape="direct_lookup",
                answer_type="policy",
                risk_level="low",
            )

    assert result.used_llm is True


# ============================================================
# Phase 4: Single policy_language structured-doc override tests
# ============================================================


def _settings_with_policy_override(allow: bool = True):
    """Return a settings mock for evidence_selector with the policy_language override toggle."""
    return type("S", (), {
        "evidence_selector_use_llm": True,
        "evidence_selector_structured_doc_types": "howto,docs,faq,policy,tos,pricing",
        "evidence_selector_conversation_cap": 1,
        "evidence_selector_min_structured_share": 0.6,
        "evidence_selector_skip_single_policy_language": allow,
    })()


@pytest.mark.asyncio
async def test_skip_single_policy_language_structured(monkeypatch):
    """唯一 hard_requirement 是 policy_language 且候选全为结构化文档时应跳过 LLM."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: _settings_with_policy_override(allow=True),
    )
    chunks = [
        (_make_chunk("c1", doc_type="policy"), 0.95),
        (_make_chunk("c2", doc_type="faq"), 0.9),
        (_make_chunk("c3", doc_type="docs"), 0.85),
        (_make_chunk("c4", doc_type="howto"), 0.8),
    ]

    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        result = await select_evidence_for_query(
            "退款政策",
            chunks,
            required_evidence=["policy_language"],
            hard_requirements=["policy_language"],
            answer_shape="direct_lookup",
            risk_level="low",
            top_k_fallback=3,
        )

    mock_gw.assert_not_called()
    assert result.used_llm is False


@pytest.mark.asyncio
async def test_keep_llm_single_policy_language_config_disabled(monkeypatch):
    """toggle=False 时，即使满足其他条件也应保持 LLM 调用."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: _settings_with_policy_override(allow=False),
    )
    chunks = [
        (_make_chunk("c1", doc_type="policy"), 0.95),
        (_make_chunk("c2", doc_type="faq"), 0.9),
        (_make_chunk("c3", doc_type="docs"), 0.85),
    ]
    mock_resp = type("R", (), {
        "content": '{"selected_chunk_ids": ["c1"], "coverage_map": {"policy_language": "c1"}, "uncovered_requirements": [], "reasoning": "policy"}',
    })()

    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        mock_gw.return_value.chat = AsyncMock(return_value=mock_resp)
        with patch("app.services.evidence_selector.get_model_for_task", return_value="test-model"):
            result = await select_evidence_for_query(
                "退款政策",
                chunks,
                required_evidence=["policy_language"],
                hard_requirements=["policy_language"],
                answer_shape="direct_lookup",
                risk_level="low",
            )

    assert result.used_llm is True


@pytest.mark.asyncio
async def test_keep_llm_multiple_hard_requirements_with_policy_language(monkeypatch):
    """多个 hard_requirements（含 policy_language）时不应触发 override."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: _settings_with_policy_override(allow=True),
    )
    chunks = [
        (_make_chunk("c1", doc_type="policy"), 0.95),
        (_make_chunk("c2", doc_type="pricing"), 0.9),
        (_make_chunk("c3", doc_type="faq"), 0.85),
    ]
    mock_resp = type("R", (), {
        "content": '{"selected_chunk_ids": ["c1", "c2"], "coverage_map": {"policy_language": "c1", "numbers_units": "c2"}, "uncovered_requirements": [], "reasoning": "multi"}',
    })()

    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        mock_gw.return_value.chat = AsyncMock(return_value=mock_resp)
        with patch("app.services.evidence_selector.get_model_for_task", return_value="test-model"):
            result = await select_evidence_for_query(
                "退款政策和金额",
                chunks,
                required_evidence=["policy_language", "numbers_units"],
                hard_requirements=["policy_language", "numbers_units"],
                answer_shape="direct_lookup",
                risk_level="low",
            )

    assert result.used_llm is True


@pytest.mark.asyncio
async def test_keep_llm_single_policy_language_non_structured_candidates(monkeypatch):
    """唯一 hard_requirement 是 policy_language 但候选非结构化时不应触发 override."""
    monkeypatch.setattr(
        "app.services.evidence_selector.get_settings",
        lambda: _settings_with_policy_override(allow=True),
    )
    chunks = [
        (_make_chunk("c1", doc_type="conversation"), 0.95),
        (_make_chunk("c2", doc_type="conversation"), 0.9),
        (_make_chunk("c3", doc_type="policy"), 0.85),
    ]
    mock_resp = type("R", (), {
        "content": '{"selected_chunk_ids": ["c3"], "coverage_map": {"policy_language": "c3"}, "uncovered_requirements": [], "reasoning": "policy"}',
    })()

    with patch("app.services.evidence_selector.get_llm_gateway") as mock_gw:
        mock_gw.return_value.chat = AsyncMock(return_value=mock_resp)
        with patch("app.services.evidence_selector.get_model_for_task", return_value="test-model"):
            result = await select_evidence_for_query(
                "退款政策",
                chunks,
                required_evidence=["policy_language"],
                hard_requirements=["policy_language"],
                answer_shape="direct_lookup",
                risk_level="low",
            )

    assert result.used_llm is True
