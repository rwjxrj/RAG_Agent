import json

import pytest

from app.core.tracing import current_llm_task_var
from app.search.base import EvidenceChunk
from app.services.evidence_quality import QualityReport
from app.services.orchestrator import OrchestratorContext
from app.services.phases.generate import execute_generate
from app.services.schemas import DecisionResult, QuerySpec


class _FakeLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content
        self.finish_reason = "stop"


class _RecordingLLM:
    def __init__(self) -> None:
        self.tasks: list[str] = []

    async def chat(self, *, messages, temperature, model, max_tokens=None):
        self.tasks.append(current_llm_task_var.get())
        if current_llm_task_var.get() == "generate_reasoning":
            return _FakeLLMResponse(
                json.dumps(
                    {
                        "evidence_summary": ["summary"],
                        "options": [],
                        "coverage_check": {"covered": ["policy"], "missing": []},
                        "recommended_focus": "answer directly",
                    }
                )
            )
        return _FakeLLMResponse(
            json.dumps(
                {
                    "decision": "PASS",
                    "candidate": {
                        "answer_text": "退款通常会在 3 个工作日内到账。",
                        "citations": [
                            {
                                "chunk_id": "chunk-refund",
                                "source_url": "eval://retrieval/refund",
                                "doc_type": "policy",
                            }
                        ],
                        "confidence": 0.82,
                        "answer_mode": "PASS_EXACT",
                    },
                },
                ensure_ascii=False,
            )
        )


class _FakeOrchestrator:
    def get_model_for_query(self, query: str) -> str:
        return "test-model"

    def get_model_for_task(self, task: str) -> str:
        return "test-model"


class _Settings:
    llm_max_evidence_chars = 1200
    llm_temperature = 0.0
    generate_reasoning_enabled = True
    generate_reasoning_max_chunks = 10
    generate_reasoning_max_options = 5
    generate_reasoning_max_tokens = 400
    self_critic_regenerate_max = 0
    # Phase 4 relaxation toggles — default False to keep Phase 3 behavior in existing tests.
    # New tests explicitly enable them.
    generate_reasoning_fastpath_allow_conversation_history = False
    generate_reasoning_fastpath_allow_medium_risk = False
    generate_reasoning_fastpath_allow_complex_shape = False


def _simple_generate_context() -> OrchestratorContext:
    spec = QuerySpec(
        intent="informational",
        entities=[],
        constraints={},
        required_evidence=[],
        risk_level="low",
        keyword_queries=[],
        semantic_queries=[],
        clarifying_questions=[],
        answer_shape="direct_lookup",
        answer_type="policy",
        answer_mode="PASS_EXACT",
    )
    ctx = OrchestratorContext(
        query="退款多久到账？",
        effective_query="退款多久到账？",
        query_spec=spec,
        passes_quality_gate=True,
        evidence=[
            EvidenceChunk(
                chunk_id="chunk-refund",
                snippet="退款通常会在 3 个工作日内到账。",
                source_url="eval://retrieval/refund",
                doc_type="policy",
                score=1.0,
                full_text="退款通常会在 3 个工作日内到账。",
            )
        ],
        quality_report=QualityReport(
            quality_score=0.9,
            feature_scores={},
            missing_signals=[],
            staleness_risk=None,
            boilerplate_risk=0.0,
            gate_pass=True,
            reason="sufficient",
        ),
        decision_result=DecisionResult(
            decision="PASS",
            reason="sufficient",
            clarifying_questions=[],
            partial_links=[],
            lane="PASS_EXACT",
        ),
    )
    ctx.retrieve_output.active_answer_shape = "direct_lookup"
    return ctx


@pytest.mark.asyncio
async def test_simple_quality_pass_generate_skips_reasoning_prepass():
    llm = _RecordingLLM()
    ctx = _simple_generate_context()

    result = await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_Settings(),
    )

    assert result.answer == "退款通常会在 3 个工作日内到账。"
    assert llm.tasks == ["generate"]
    assert ctx.generate_output.reasoning_prewrite is None
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is True
    assert prepass["reason"] == "simple_direct_lookup_quality_passed"
    assert "skip_metadata" in prepass
    meta = prepass["skip_metadata"]
    assert meta["evidence_count"] == 1
    assert meta["answer_type"] == "policy"
    assert meta["answer_shape"] == "direct_lookup"
    assert meta["risk_level"] == "low"
    assert meta["hard_requirements_covered"] is False


@pytest.mark.asyncio
async def test_generate_uses_original_query_language_when_effective_query_is_english():
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.query = "你们的退款政策是什么？"
    ctx.effective_query = "What is your refund policy?"
    ctx.source_lang = "zh-cn"

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_Settings(),
    )

    system_prompt = ctx.generate_output.messages[0]["content"]
    assert "respond entirely in Chinese" in system_prompt
    assert "respond entirely in English" not in system_prompt


@pytest.mark.asyncio
async def test_high_risk_generate_keeps_reasoning_prepass():
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.query_spec.query_intent.risk_level = "high"

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_Settings(),
    )

    assert llm.tasks == ["generate_reasoning", "generate"]
    assert ctx.generate_output.reasoning_prewrite is not None
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is False
    assert prepass["reason"] == "executed"
    assert "blockers" in prepass
    assert any("risk_level_high" in b for b in prepass["blockers"])


@pytest.mark.asyncio
async def test_config_can_disable_simple_reasoning_fastpath():
    class SettingsWithoutFastPath(_Settings):
        generate_reasoning_skip_simple_lookup = False

    llm = _RecordingLLM()
    ctx = _simple_generate_context()

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=SettingsWithoutFastPath(),
    )

    assert llm.tasks == ["generate_reasoning", "generate"]
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is False
    assert prepass["reason"] == "executed"
    assert prepass.get("blockers", ["fastpath_master_switch_disabled"]) == ["fastpath_master_switch_disabled"]


# ---------------------------------------------------------------------------
# Phase 3 Issue 1: relaxed fast-path tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_signals_allowed_when_quality_gate_passed():
    """missing_signals non空但 quality gate 已通过 → 允许跳过 (default True)."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.quality_report.missing_signals = ["format_check"]

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_Settings(),
    )

    assert llm.tasks == ["generate"]
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is True
    assert prepass["reason"] == "simple_direct_lookup_quality_passed"


@pytest.mark.asyncio
async def test_missing_signals_block_when_config_disabled():
    """missing_signals 非空且 allow_missing_signals=False → 阻止跳过."""
    class NoMissingSignals(_Settings):
        generate_reasoning_fastpath_allow_missing_signals = False

    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.quality_report.missing_signals = ["format_check"]

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=NoMissingSignals(),
    )

    assert llm.tasks == ["generate_reasoning", "generate"]
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is False
    assert any("missing_signals" in b for b in prepass.get("blockers", []))


@pytest.mark.asyncio
async def test_pricing_answer_type_allows_fastpath():
    """pricing answer_type 不再阻止 fast-path（从排除列表移除）."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.query_spec.answer_contract.answer_type = "pricing"

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_Settings(),
    )

    assert llm.tasks == ["generate"]
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is True


@pytest.mark.asyncio
async def test_direct_link_answer_type_allows_fastpath():
    """direct_link answer_type 不再阻止 fast-path（从排除列表移除）."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.query_spec.answer_contract.answer_type = "direct_link"

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_Settings(),
    )

    assert llm.tasks == ["generate"]
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is True


@pytest.mark.asyncio
async def test_account_answer_type_still_blocked():
    """account answer_type 仍在排除列表中."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.query_spec.answer_contract.answer_type = "account"

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_Settings(),
    )

    assert llm.tasks == ["generate_reasoning", "generate"]
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is False
    assert any("answer_type_excluded(account)" in b for b in prepass.get("blockers", []))


@pytest.mark.asyncio
async def test_evidence_threshold_raised_to_8():
    """evidence chunk 数量 <=8 时仍允许 fast-path（阈值从 5 提升到 8）."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    # 扩展到 7 个 evidence chunks
    ctx.evidence = ctx.evidence * 7

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_Settings(),
    )

    assert llm.tasks == ["generate"]
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is True


@pytest.mark.asyncio
async def test_evidence_at_exact_boundary_allows_fastpath():
    """evidence chunk 数量恰好等于阈值 8 时仍允许 fast-path（检查是 > 而非 >=）."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.evidence = ctx.evidence * 8  # 恰好 8 个 chunks

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_Settings(),
    )

    assert llm.tasks == ["generate"]
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is True
    assert prepass["skip_metadata"]["evidence_count"] == 8


@pytest.mark.asyncio
async def test_evidence_one_over_boundary_blocks():
    """evidence chunk 数量为阈值+1（9 个）时阻止 fast-path."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.evidence = ctx.evidence * 9  # 9 个 chunks > 阈值 8

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_Settings(),
    )

    assert llm.tasks == ["generate_reasoning", "generate"]
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is False
    assert any("evidence_count_exceeds_max(9>8)" in b for b in prepass.get("blockers", []))


@pytest.mark.asyncio
async def test_evidence_exceeds_threshold_blocks():
    """evidence chunk 数量超过阈值时阻止 fast-path."""
    class LowThreshold(_Settings):
        generate_reasoning_fastpath_max_evidence_chunks = 3

    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.evidence = ctx.evidence * 5  # 5 chunks > threshold 3

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=LowThreshold(),
    )

    assert llm.tasks == ["generate_reasoning", "generate"]
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is False
    assert any("evidence_count_exceeds_max" in b for b in prepass.get("blockers", []))


@pytest.mark.asyncio
async def test_hard_requirements_covered_allows_fastpath():
    """hard_requirements 非空但 quality_report 全部覆盖 → 允许跳过."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.retrieve_output.active_hard_requirements = ["refund_policy"]
    ctx.quality_report.hard_requirement_coverage = [True]

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_Settings(),
    )

    assert llm.tasks == ["generate"]
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is True
    meta = prepass["skip_metadata"]
    assert meta["hard_requirements_covered"] is True


@pytest.mark.asyncio
async def test_hard_requirements_not_covered_blocks():
    """hard_requirements 非空且 coverage 包含 False → 阻止跳过."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.retrieve_output.active_hard_requirements = ["refund_policy"]
    ctx.quality_report.hard_requirement_coverage = [False]

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_Settings(),
    )

    assert llm.tasks == ["generate_reasoning", "generate"]
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is False
    assert any("hard_requirements_not_fully_covered" in b for b in prepass.get("blockers", []))


@pytest.mark.asyncio
async def test_hard_requirements_block_when_config_disabled():
    """hard_requirements 非空且 covered_hard_requirements=False → 阻止跳过."""
    class NoCoveredReq(_Settings):
        generate_reasoning_fastpath_covered_hard_requirements = False

    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.retrieve_output.active_hard_requirements = ["refund_policy"]
    ctx.quality_report.hard_requirement_coverage = [True]

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=NoCoveredReq(),
    )

    assert llm.tasks == ["generate_reasoning", "generate"]
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is False
    assert any("hard_requirements_present" in b for b in prepass.get("blockers", []))


@pytest.mark.asyncio
async def test_blockers_collects_multiple_reasons():
    """多个条件同时阻止 fast-path 时，blockers 列表包含所有原因."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.query_spec.query_intent.risk_level = "high"
    ctx.conversation_history = [{"role": "user", "content": "hi"}]
    ctx.query_spec.answer_contract.answer_type = "account"

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_Settings(),
    )

    assert "generate_reasoning" in llm.tasks
    assert "generate" in llm.tasks
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is False
    blockers = prepass.get("blockers", [])
    assert any("has_conversation_history" in b for b in blockers)
    assert any("risk_level_high" in b for b in blockers)
    assert any("answer_type_excluded(account)" in b for b in blockers)


@pytest.mark.asyncio
async def test_medium_risk_blocks_fastpath():
    """risk_level=medium 应阻止 fast-path，blockers 中包含 risk_level_medium."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.query_spec.query_intent.risk_level = "medium"

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_Settings(),
    )

    assert "generate_reasoning" in llm.tasks
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is False
    assert any("risk_level_medium" in b for b in prepass.get("blockers", []))


@pytest.mark.asyncio
async def test_non_simple_answer_shape_blocks_fastpath():
    """answer_shape 不在 {direct_lookup, short_answer, yes_no} 中时阻止 fast-path."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.retrieve_output.active_answer_shape = "comparison"

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_Settings(),
    )

    assert "generate_reasoning" in llm.tasks
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is False
    assert any("answer_shape_not_simple(comparison)" in b for b in prepass.get("blockers", []))


# ============================================================
# Phase 4: Relaxed fast-path tests
# ============================================================


def _relaxed_settings() -> _Settings:
    """Return _Settings with all Phase 4 relaxation toggles enabled."""
    s = _Settings()
    s.generate_reasoning_fastpath_allow_conversation_history = True
    s.generate_reasoning_fastpath_allow_medium_risk = True
    s.generate_reasoning_fastpath_allow_complex_shape = True
    return s


@pytest.mark.asyncio
async def test_conversation_history_allows_fastpath():
    """conversation_history 存在但 toggle=True 时应允许 fast-path."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.conversation_history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_relaxed_settings(),
    )

    assert "generate_reasoning" not in llm.tasks
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is True
    assert prepass["skip_metadata"]["fastpath_relaxations"]["conversation_history_allowed"] is True


@pytest.mark.asyncio
async def test_conversation_history_blocks_when_disabled():
    """conversation_history 存在且 toggle=False 时阻止 fast-path."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.conversation_history = [{"role": "user", "content": "hi"}]

    settings = _Settings()
    settings.generate_reasoning_fastpath_allow_conversation_history = False

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=settings,
    )

    assert "generate_reasoning" in llm.tasks
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is False
    assert any("has_conversation_history" in b for b in prepass.get("blockers", []))


@pytest.mark.asyncio
async def test_medium_risk_allows_fastpath():
    """risk_level=medium 且 toggle=True 时应允许 fast-path."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.query_spec.query_intent.risk_level = "medium"

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_relaxed_settings(),
    )

    assert "generate_reasoning" not in llm.tasks
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is True
    assert prepass["skip_metadata"]["fastpath_relaxations"]["medium_risk_allowed"] is True


@pytest.mark.asyncio
async def test_medium_risk_blocks_when_disabled():
    """risk_level=medium 且 toggle=False 时阻止 fast-path."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.query_spec.query_intent.risk_level = "medium"

    settings = _Settings()
    settings.generate_reasoning_fastpath_allow_medium_risk = False

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=settings,
    )

    assert "generate_reasoning" in llm.tasks
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is False
    assert any("risk_level_medium" in b for b in prepass.get("blockers", []))


@pytest.mark.asyncio
async def test_high_risk_always_blocks():
    """risk_level=high 无论 toggle 如何设置都应阻止 fast-path."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.query_spec.query_intent.risk_level = "high"

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_relaxed_settings(),  # all toggles True
    )

    assert "generate_reasoning" in llm.tasks
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is False
    assert any("risk_level_high" in b for b in prepass.get("blockers", []))


@pytest.mark.asyncio
async def test_complex_answer_shape_allows_fastpath():
    """answer_shape=procedural 且 toggle=True 时应允许 fast-path."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.retrieve_output.active_answer_shape = "procedural"

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_relaxed_settings(),
    )

    assert "generate_reasoning" not in llm.tasks
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is True
    assert prepass["skip_metadata"]["fastpath_relaxations"]["complex_shape_allowed"] is True


@pytest.mark.asyncio
async def test_complex_answer_shape_blocks_when_disabled():
    """answer_shape=procedural 且 toggle=False 时阻止 fast-path."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.retrieve_output.active_answer_shape = "procedural"

    settings = _Settings()
    settings.generate_reasoning_fastpath_allow_complex_shape = False

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=settings,
    )

    assert "generate_reasoning" in llm.tasks
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is False
    assert any("answer_shape_not_simple(procedural)" in b for b in prepass.get("blockers", []))


@pytest.mark.asyncio
async def test_all_relaxations_combined_allows_fastpath():
    """conversation_history + medium risk + procedural shape 全部放宽时应跳过 fast-path."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.conversation_history = [{"role": "user", "content": "hi"}]
    ctx.query_spec.query_intent.risk_level = "medium"
    ctx.retrieve_output.active_answer_shape = "procedural"

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_relaxed_settings(),
    )

    assert "generate_reasoning" not in llm.tasks
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is True
    relaxations = prepass["skip_metadata"]["fastpath_relaxations"]
    assert relaxations["conversation_history_allowed"] is True
    assert relaxations["medium_risk_allowed"] is True
    assert relaxations["complex_shape_allowed"] is True


@pytest.mark.asyncio
async def test_all_relaxations_disabled_phase3_compat():
    """所有放宽 toggle 关闭时恢复 Phase 3 行为：三个 blocker 都应出现."""
    llm = _RecordingLLM()
    ctx = _simple_generate_context()
    ctx.conversation_history = [{"role": "user", "content": "hi"}]
    ctx.query_spec.query_intent.risk_level = "medium"
    ctx.retrieve_output.active_answer_shape = "procedural"

    await execute_generate(
        ctx,
        llm=llm,
        orchestrator=_FakeOrchestrator(),
        settings=_Settings(),  # all toggles False (Phase 3 behavior)
    )

    assert "generate_reasoning" in llm.tasks
    prepass = ctx.generate_output.reasoning_prepass
    assert prepass["skipped"] is False
    blockers = prepass.get("blockers", [])
    assert any("has_conversation_history" in b for b in blockers)
    assert any("risk_level_medium" in b for b in blockers)
    assert any("answer_shape_not_simple(procedural)" in b for b in blockers)
