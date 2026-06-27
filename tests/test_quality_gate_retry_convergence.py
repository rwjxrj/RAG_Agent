"""Tests for quality gate retry diagnostics and convergence (Issue 4)."""

import pytest
from unittest.mock import MagicMock, patch

from app.services.orchestrator import (
    OrchestratorAction,
    OrchestratorContext,
    OrchestratorState,
    PipelineRunner,
)
from app.services.schemas import OrchestratorDebug


def _make_ctx(**overrides) -> OrchestratorContext:
    """Create a minimal OrchestratorContext for testing."""
    defaults = dict(
        query="退款多久到账",
        state=OrchestratorState.ASSESSING,
        max_attempts=3,
        passes_quality_gate=False,
        retrieval_attempt=1,
        evidence=[],
        retry_diagnostics=[],
        previous_source_set=set(),
        previous_missing_signals=[],
    )
    defaults.update(overrides)
    return OrchestratorContext(**defaults)


def _make_settings(**overrides):
    """Create a mock settings object."""
    defaults = dict(
        quality_gate_retry_convergence_enabled=True,
        quality_gate_max_consecutive_failures=3,
        max_retrieval_attempts=3,
        targeted_retry_enabled=True,
    )
    defaults.update(overrides)
    return type("Settings", (), defaults)()


def _make_runner(**settings_overrides) -> PipelineRunner:
    """Create a PipelineRunner with mock settings."""
    runner = PipelineRunner.__new__(PipelineRunner)
    runner._settings = _make_settings(**settings_overrides)
    return runner


# ---------------------------------------------------------------------------
# _should_stop_retry tests
# ---------------------------------------------------------------------------


def test_should_stop_retry_no_diagnostics():
    """No diagnostics → don't stop retry."""
    runner = _make_runner()
    ctx = _make_ctx(retry_diagnostics=[])
    assert runner._should_stop_retry(ctx) is False


def test_should_stop_retry_same_missing_signals_no_new_sources():
    """Same missing_signals and no new sources → stop retry."""
    runner = _make_runner()
    # sorted(["policy_language", "numbers_units"]) == ["numbers_units", "policy_language"]
    sorted_signals = sorted(["policy_language", "numbers_units"])
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["policy_language", "numbers_units"],
                "source_set_changed": False,
            }
        ],
        previous_missing_signals=sorted_signals,
    )
    assert runner._should_stop_retry(ctx) is True
    assert ctx.orchestrator_debug.convergence_reason == "same_missing_signals_no_new_sources"


def test_should_stop_retry_same_missing_signals_but_new_sources():
    """Same missing_signals but new sources found → don't stop retry."""
    runner = _make_runner()
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["policy_language"],
                "source_set_changed": True,
            }
        ],
        previous_missing_signals=["policy_language"],
    )
    assert runner._should_stop_retry(ctx) is False


def test_should_stop_retry_different_missing_signals_but_source_unchanged():
    """Different missing_signals but source set unchanged → stop retry (condition 4: retrieval saturated)."""
    runner = _make_runner()
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["numbers_units"],
                "source_set_changed": False,
            }
        ],
        previous_missing_signals=["policy_language"],
    )
    assert runner._should_stop_retry(ctx) is True
    assert ctx.orchestrator_debug.convergence_reason == "source_set_unchanged_retry_saturated"


def test_should_stop_retry_disabled():
    """When convergence is disabled, never stop retry."""
    runner = _make_runner(quality_gate_retry_convergence_enabled=False)
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["policy_language"],
                "source_set_changed": False,
            }
        ],
        previous_missing_signals=["policy_language"],
    )
    assert runner._should_stop_retry(ctx) is False


# ---------------------------------------------------------------------------
# _top_sources_cover_expected tests
# ---------------------------------------------------------------------------


def test_top_sources_cover_expected_yes():
    """Top-5 chunks cover all expected doc types → stop retry."""
    runner = _make_runner()
    mock_spec = MagicMock()
    mock_spec.doc_type_prior = ["policy", "faq"]
    mock_spec.retrieval_hints = MagicMock()
    mock_spec.retrieval_hints.doc_type_prior = []

    chunks = [
        MagicMock(doc_type="policy", source_url="https://example.com/policy/refund"),
        MagicMock(doc_type="faq", source_url="https://example.com/faq/refund"),
    ]
    ctx = _make_ctx(evidence=chunks, query_spec=mock_spec)
    assert runner._top_sources_cover_expected(ctx) is True


def test_top_sources_cover_expected_partial():
    """Top-5 chunks only cover some expected doc types → don't stop retry."""
    runner = _make_runner()
    mock_spec = MagicMock()
    mock_spec.doc_type_prior = ["policy", "faq", "tos"]
    mock_spec.retrieval_hints = MagicMock()
    mock_spec.retrieval_hints.doc_type_prior = []

    chunks = [
        MagicMock(doc_type="policy", source_url="https://example.com/policy/refund"),
        MagicMock(doc_type="faq", source_url="https://example.com/faq/refund"),
    ]
    ctx = _make_ctx(evidence=chunks, query_spec=mock_spec)
    assert runner._top_sources_cover_expected(ctx) is False


def test_top_sources_cover_expected_no_evidence():
    """No evidence → don't stop retry."""
    runner = _make_runner()
    ctx = _make_ctx(evidence=[], query_spec=MagicMock())
    assert runner._top_sources_cover_expected(ctx) is False


def test_top_sources_cover_expected_no_query_spec():
    """No query_spec → don't stop retry."""
    runner = _make_runner()
    ctx = _make_ctx(evidence=[MagicMock()], query_spec=None)
    assert runner._top_sources_cover_expected(ctx) is False


def test_top_sources_cover_expected_no_doc_type_prior():
    """No doc_type_prior → don't stop retry."""
    runner = _make_runner()
    mock_spec = MagicMock()
    mock_spec.doc_type_prior = []
    mock_spec.retrieval_hints = MagicMock()
    mock_spec.retrieval_hints.doc_type_prior = []
    ctx = _make_ctx(evidence=[MagicMock()], query_spec=mock_spec)
    assert runner._top_sources_cover_expected(ctx) is False


# ---------------------------------------------------------------------------
# next_action integration tests
# ---------------------------------------------------------------------------


def test_next_action_assessing_convergence_stops_retry():
    """When convergence is detected, next_action returns DECIDE instead of RETRY_RETRIEVE."""
    runner = _make_runner()
    ctx = _make_ctx(
        state=OrchestratorState.ASSESSING,
        passes_quality_gate=False,
        retrieval_attempt=1,
        max_attempts=3,
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["policy_language"],
                "source_set_changed": False,
            }
        ],
        previous_missing_signals=["policy_language"],
    )
    action = runner.next_action(ctx, None, has_evidence=True)
    assert action == OrchestratorAction.DECIDE


def test_next_action_assessing_no_convergence_retries():
    """When convergence is NOT detected, next_action returns RETRY_RETRIEVE."""
    runner = _make_runner()
    ctx = _make_ctx(
        state=OrchestratorState.ASSESSING,
        passes_quality_gate=False,
        retrieval_attempt=1,
        max_attempts=3,
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["numbers_units"],
                "source_set_changed": True,
            }
        ],
        previous_missing_signals=["policy_language"],
    )
    action = runner.next_action(ctx, None, has_evidence=True)
    assert action == OrchestratorAction.RETRY_RETRIEVE


def test_next_action_assessing_convergence_disabled_retries():
    """When convergence is disabled, next_action returns RETRY_RETRIEVE even with same missing_signals."""
    runner = _make_runner(quality_gate_retry_convergence_enabled=False)
    ctx = _make_ctx(
        state=OrchestratorState.ASSESSING,
        passes_quality_gate=False,
        retrieval_attempt=1,
        max_attempts=3,
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["policy_language"],
                "source_set_changed": False,
            }
        ],
        previous_missing_signals=["policy_language"],
    )
    action = runner.next_action(ctx, None, has_evidence=True)
    assert action == OrchestratorAction.RETRY_RETRIEVE


# ---------------------------------------------------------------------------
# Assess phase diagnostic recording tests
# ---------------------------------------------------------------------------


def test_record_retry_diagnostics_records_data():
    """_record_retry_diagnostics populates ctx.retry_diagnostics."""
    from app.services.phases.assess import _record_retry_diagnostics

    mock_quality_report = MagicMock()
    mock_quality_report.quality_score = 0.4
    mock_quality_report.completeness_score = 0.3
    mock_quality_report.actionability_score = 0.5
    mock_quality_report.missing_signals = ["policy_language", "numbers_units"]
    mock_quality_report.hard_requirement_coverage = {"policy_language": False}

    ctx = _make_ctx(
        quality_report=mock_quality_report,
        evidence=[MagicMock(source_url="https://example.com/policy")],
        retrieval_attempt=1,
    )
    ctx.retrieve_output = MagicMock()
    ctx.retrieve_output.active_required_evidence = ["policy_language"]
    ctx.retrieve_output.active_hard_requirements = []
    ctx.retrieve_output.retry_strategy_applied = {
        "selected_retrieval_query": "refund time policy",
        "evidence_selector_used_llm": True,
        "evidence_selector_trigger_reason": "hard_requirements",
    }
    ctx.retrieve_output.active_hypothesis_name = "primary"
    ctx.retrieve_output.active_answer_shape = "direct_lookup"
    ctx.retrieve_output.active_evidence_families = ["policy_terms"]

    _record_retry_diagnostics(ctx, gate_passed=False)

    assert len(ctx.retry_diagnostics) == 1
    diag = ctx.retry_diagnostics[0]
    assert diag["retrieval_attempt"] == 1
    assert diag["gate_pass"] is False
    assert diag["quality_score"] == 0.4
    assert diag["missing_signals"] == sorted(["policy_language", "numbers_units"])
    assert diag["selected_query"] == "refund time policy"
    assert diag["evidence_selector_used_llm"] is True
    assert diag["source_count"] == 1


def test_record_retry_diagnostics_no_quality_report():
    """_record_retry_diagnostics does nothing when quality_report is None."""
    from app.services.phases.assess import _record_retry_diagnostics

    ctx = _make_ctx(quality_report=None)
    _record_retry_diagnostics(ctx, gate_passed=False)
    assert len(ctx.retry_diagnostics) == 0


def test_record_retry_diagnostics_updates_previous_state():
    """_record_retry_diagnostics updates previous_source_set and previous_missing_signals."""
    from app.services.phases.assess import _record_retry_diagnostics

    mock_quality_report = MagicMock()
    mock_quality_report.quality_score = 0.4
    mock_quality_report.completeness_score = 0.3
    mock_quality_report.actionability_score = 0.5
    mock_quality_report.missing_signals = ["policy_language"]
    mock_quality_report.hard_requirement_coverage = {}

    ctx = _make_ctx(
        quality_report=mock_quality_report,
        evidence=[MagicMock(source_url="https://example.com/policy")],
        retrieval_attempt=0,
    )
    ctx.retrieve_output = MagicMock()
    ctx.retrieve_output.active_required_evidence = []
    ctx.retrieve_output.active_hard_requirements = []
    ctx.retrieve_output.retry_strategy_applied = None
    ctx.retrieve_output.active_hypothesis_name = "primary"

    _record_retry_diagnostics(ctx, gate_passed=False)

    assert "https://example.com/policy" in ctx.previous_source_set
    assert ctx.previous_missing_signals == ["policy_language"]


def test_record_retry_diagnostics_reads_evidence_selector_from_bridge():
    """When retrieve phase bridges evidence_selector stats into retry_strategy_applied,
    _record_retry_diagnostics should record them correctly (Fix 1: data-flow bridge)."""
    from app.services.phases.assess import _record_retry_diagnostics

    mock_quality_report = MagicMock()
    mock_quality_report.quality_score = 0.5
    mock_quality_report.completeness_score = 0.4
    mock_quality_report.actionability_score = 0.6
    mock_quality_report.missing_signals = ["policy_language"]
    mock_quality_report.hard_requirement_coverage = {"policy_language": True}

    ctx = _make_ctx(
        quality_report=mock_quality_report,
        evidence=[MagicMock(source_url="https://example.com/policy")],
        retrieval_attempt=1,
    )
    ctx.retrieve_output = MagicMock()
    ctx.retrieve_output.active_required_evidence = ["policy_language"]
    ctx.retrieve_output.active_hard_requirements = []
    ctx.retrieve_output.active_hypothesis_name = "primary"
    ctx.retrieve_output.active_answer_shape = "direct_lookup"
    ctx.retrieve_output.active_evidence_families = ["policy_terms"]
    # Simulate the bridge from retrieve.py: evidence_selector stats in retry_strategy_applied
    ctx.retrieve_output.retry_strategy_applied = {
        "selected_retrieval_query": "退款政策",
        "evidence_selector_used_llm": False,
        "evidence_selector_skip_reason": "single_weak_required_evidence",
        "evidence_selector_trigger_reason": None,
    }

    _record_retry_diagnostics(ctx, gate_passed=True)

    assert len(ctx.retry_diagnostics) == 1
    diag = ctx.retry_diagnostics[0]
    assert diag["evidence_selector_used_llm"] is False
    assert diag["evidence_selector_skip_reason"] == "single_weak_required_evidence"
    assert diag["evidence_selector_trigger_reason"] is None
    assert diag["selected_query"] == "退款政策"


# ---------------------------------------------------------------------------
# Condition 4: source_set_unchanged_retry_saturated tests
# ---------------------------------------------------------------------------


def test_should_stop_retry_source_set_unchanged_stops_regardless():
    """source_set_changed=False stops retry even if missing_signals differ (condition 4)."""
    runner = _make_runner()
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 2,
                "gate_pass": False,
                "missing_signals": ["format_check", "numbers_units"],
                "source_set_changed": False,
            }
        ],
        previous_missing_signals=["policy_language"],
    )
    assert runner._should_stop_retry(ctx) is True
    assert ctx.orchestrator_debug.convergence_reason == "source_set_unchanged_retry_saturated"


def test_should_stop_retry_source_set_changed_continues():
    """source_set_changed=True does NOT trigger condition 4."""
    runner = _make_runner()
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["new_signal"],
                "source_set_changed": True,
            }
        ],
        previous_missing_signals=["policy_language"],
    )
    assert runner._should_stop_retry(ctx) is False


def test_should_stop_retry_source_set_none_continues():
    """source_set_changed=None (unknown) does NOT trigger condition 4."""
    runner = _make_runner()
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["policy_language"],
                "source_set_changed": None,
            }
        ],
        previous_missing_signals=["policy_language"],
    )
    # source_set_changed is None (not False), so condition 1 fails (requires False),
    # condition 4 fails (requires False), falls through to condition 3
    assert runner._should_stop_retry(ctx) is False


# ---------------------------------------------------------------------------
# OrchestratorDebug convergence_reason field
# ---------------------------------------------------------------------------


def test_orchestrator_debug_has_convergence_reason():
    debug = OrchestratorDebug()
    assert debug.convergence_reason is None
    debug.convergence_reason = "same_missing_signals_no_new_sources"
    assert debug.convergence_reason == "same_missing_signals_no_new_sources"


# ---------------------------------------------------------------------------
# Condition 4: consecutive infrastructure failures
# ---------------------------------------------------------------------------


def test_should_stop_retry_consecutive_infra_failures():
    """Two consecutive rounds with selector/quality LLM failures should stop retry."""
    runner = _make_runner()
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["policy_language"],
                "source_set_changed": True,
                "evidence_selector_llm_failed": True,
                "quality_llm_failed": False,
            },
            {
                "retrieval_attempt": 2,
                "gate_pass": False,
                "missing_signals": ["policy_language"],
                "source_set_changed": True,
                "evidence_selector_llm_failed": True,
                "quality_llm_failed": False,
            },
        ],
        previous_missing_signals=["policy_language"],
    )
    assert runner._should_stop_retry(ctx) is True
    assert ctx.orchestrator_debug.convergence_reason == "consecutive_infrastructure_failures"


def test_should_stop_retry_single_infra_failure_continues():
    """Only one round of infrastructure failure should NOT stop retry."""
    runner = _make_runner()
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["policy_language"],
                "source_set_changed": True,
                "evidence_selector_llm_failed": False,
                "quality_llm_failed": False,
            },
            {
                "retrieval_attempt": 2,
                "gate_pass": False,
                "missing_signals": ["policy_language"],
                "source_set_changed": True,
                "evidence_selector_llm_failed": True,
                "quality_llm_failed": False,
            },
        ],
        previous_missing_signals=["policy_language"],
    )
    # Only one round has infra failure → should not stop
    assert runner._should_stop_retry(ctx) is False


def test_should_stop_retry_consecutive_quality_llm_failures():
    """Two consecutive quality_llm_failed should also stop retry."""
    runner = _make_runner()
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["quality_llm_failed"],
                "source_set_changed": True,
                "evidence_selector_llm_failed": False,
                "quality_llm_failed": True,
            },
            {
                "retrieval_attempt": 2,
                "gate_pass": False,
                "missing_signals": ["quality_llm_failed"],
                "source_set_changed": True,
                "evidence_selector_llm_failed": False,
                "quality_llm_failed": True,
            },
        ],
        previous_missing_signals=["quality_llm_failed"],
    )
    assert runner._should_stop_retry(ctx) is True
    assert ctx.orchestrator_debug.convergence_reason == "consecutive_infrastructure_failures"


def test_should_stop_retry_infra_failure_disabled():
    """When convergence is disabled, infra failure condition does not fire."""
    runner = _make_runner(quality_gate_retry_convergence_enabled=False)
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": [],
                "source_set_changed": True,
                "evidence_selector_llm_failed": True,
                "quality_llm_failed": False,
            },
            {
                "retrieval_attempt": 2,
                "gate_pass": False,
                "missing_signals": [],
                "source_set_changed": True,
                "evidence_selector_llm_failed": True,
                "quality_llm_failed": False,
            },
        ],
    )
    assert runner._should_stop_retry(ctx) is False


# ---------------------------------------------------------------------------
# Condition 5: consecutive quality gate failures exhausted
# ---------------------------------------------------------------------------


def test_should_stop_retry_consecutive_gate_failures_stops():
    """3 consecutive rounds with gate_pass=False should stop retry (condition 5).
    This catches the EVAL-008 scenario where source_set changes and missing_signals
    shift each round but quality never passes."""
    runner = _make_runner()
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["policy_language", "numbers_units"],
                "source_set_changed": None,
            },
            {
                "retrieval_attempt": 2,
                "gate_pass": False,
                "missing_signals": ["policy_language", "time_range"],
                "source_set_changed": True,
            },
            {
                "retrieval_attempt": 3,
                "gate_pass": False,
                "missing_signals": ["exclusion_criteria", "numeric_examples"],
                "source_set_changed": True,
            },
        ],
        previous_missing_signals=["policy_language", "time_range"],
    )
    assert runner._should_stop_retry(ctx) is True
    assert ctx.orchestrator_debug.convergence_reason == "consecutive_gate_failures_exhausted"


def test_should_stop_retry_two_consecutive_failures_continues():
    """Only 2 consecutive gate_pass=False should NOT stop (below threshold of 3)."""
    runner = _make_runner()
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["policy_language"],
                "source_set_changed": None,
            },
            {
                "retrieval_attempt": 2,
                "gate_pass": False,
                "missing_signals": ["numbers_units"],
                "source_set_changed": True,
            },
        ],
        previous_missing_signals=["policy_language"],
    )
    assert runner._should_stop_retry(ctx) is False


def test_should_stop_retry_mixed_gate_pass_continues():
    """If any of the last N rounds has gate_pass=True, condition 5 does NOT fire."""
    runner = _make_runner()
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["policy_language"],
                "source_set_changed": None,
            },
            {
                "retrieval_attempt": 2,
                "gate_pass": True,
                "missing_signals": [],
                "source_set_changed": True,
            },
            {
                "retrieval_attempt": 3,
                "gate_pass": False,
                "missing_signals": ["numbers_units"],
                "source_set_changed": True,
            },
        ],
        previous_missing_signals=[],
    )
    # Round 2 passed → consecutive failure streak is broken
    assert runner._should_stop_retry(ctx) is False


def test_should_stop_retry_custom_threshold_two():
    """With max_consecutive_failures=2, stops after 2 consecutive failures."""
    runner = _make_runner(quality_gate_max_consecutive_failures=2)
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["policy_language"],
                "source_set_changed": None,
            },
            {
                "retrieval_attempt": 2,
                "gate_pass": False,
                "missing_signals": ["numbers_units"],
                "source_set_changed": True,
            },
        ],
        previous_missing_signals=["policy_language"],
    )
    assert runner._should_stop_retry(ctx) is True
    assert ctx.orchestrator_debug.convergence_reason == "consecutive_gate_failures_exhausted"


def test_should_stop_retry_condition5_disabled_when_convergence_off():
    """When convergence is disabled, condition 5 does not fire."""
    runner = _make_runner(quality_gate_retry_convergence_enabled=False)
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["policy_language"],
                "source_set_changed": None,
            },
            {
                "retrieval_attempt": 2,
                "gate_pass": False,
                "missing_signals": ["numbers_units"],
                "source_set_changed": True,
            },
            {
                "retrieval_attempt": 3,
                "gate_pass": False,
                "missing_signals": ["exclusion_criteria"],
                "source_set_changed": True,
            },
        ],
        previous_missing_signals=["numbers_units"],
    )
    assert runner._should_stop_retry(ctx) is False


# ---------------------------------------------------------------------------
# Condition 5b: soft contradiction — LLM says pass but code overrides
# ---------------------------------------------------------------------------


def test_should_stop_retry_soft_contradiction_stops():
    """2 consecutive rounds where LLM says gate_pass=True but code overrides to False
    should stop retry. This catches EVAL-007 where LLM consistently produces
    gate_pass=True + missing_signals non-empty."""
    runner = _make_runner()
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 0,
                "gate_pass": False,
                "raw_llm_gate_pass": True,
                "missing_signals": ["policy_language"],
                "source_set_changed": None,
            },
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "raw_llm_gate_pass": True,
                "missing_signals": ["policy_language", "negative_condition"],
                "source_set_changed": True,
            },
        ],
        previous_missing_signals=["policy_language"],
    )
    assert runner._should_stop_retry(ctx) is True
    assert ctx.orchestrator_debug.convergence_reason == "soft_contradiction_llm_agrees_evidence_sufficient"


def test_should_stop_retry_soft_contradiction_single_round_continues():
    """Only 1 round of soft contradiction should NOT stop (need 2 consecutive)."""
    runner = _make_runner()
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 0,
                "gate_pass": False,
                "raw_llm_gate_pass": True,
                "missing_signals": ["policy_language"],
                "source_set_changed": None,
            },
        ],
        previous_missing_signals=[],
    )
    assert runner._should_stop_retry(ctx) is False


def test_should_stop_retry_mixed_real_failure_and_contradiction():
    """One real failure (raw_llm_gate_pass=False) + one contradiction should NOT trigger 5b."""
    runner = _make_runner()
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 0,
                "gate_pass": False,
                "raw_llm_gate_pass": False,
                "missing_signals": ["quality_llm_failed"],
                "source_set_changed": None,
            },
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "raw_llm_gate_pass": True,
                "missing_signals": ["policy_language"],
                "source_set_changed": True,
            },
        ],
        previous_missing_signals=["quality_llm_failed"],
    )
    # Round 0: real failure, Round 1: contradiction → NOT both overridden
    assert runner._should_stop_retry(ctx) is False


# ---------------------------------------------------------------------------
# Issue 04: Exhaustion reason when max attempts reached
# ---------------------------------------------------------------------------


def test_next_action_max_attempts_sets_exhaustion_reason():
    """When max attempts exhausted, convergence_reason must be set (not None)."""
    runner = _make_runner(max_retrieval_attempts=2)
    ctx = _make_ctx(
        state=OrchestratorState.ASSESSING,
        passes_quality_gate=False,
        retrieval_attempt=2,  # == max_attempts → can_retry() = False
        max_attempts=2,
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["policy_language"],
                "source_set_changed": True,
            },
        ],
        previous_missing_signals=["policy_language"],
    )
    action = runner.next_action(ctx, None, has_evidence=True)
    assert action == OrchestratorAction.DECIDE
    assert ctx.orchestrator_debug.convergence_reason is not None
    assert "exhausted" in ctx.orchestrator_debug.convergence_reason


def test_next_action_convergence_still_works_before_limit():
    """Convergence detection still works when under the max attempt limit."""
    runner = _make_runner(max_retrieval_attempts=3)
    ctx = _make_ctx(
        state=OrchestratorState.ASSESSING,
        passes_quality_gate=False,
        retrieval_attempt=1,
        max_attempts=3,
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["policy_language"],
                "source_set_changed": False,
            },
        ],
        previous_missing_signals=["policy_language"],
    )
    action = runner.next_action(ctx, None, has_evidence=True)
    assert action == OrchestratorAction.DECIDE
    assert ctx.orchestrator_debug.convergence_reason == "same_missing_signals_no_new_sources"


def test_should_stop_retry_semantically_equivalent_signals():
    """Semantically equivalent missing signals with different wording should converge."""
    runner = _make_runner()
    ctx = _make_ctx(
        retry_diagnostics=[
            {
                "retrieval_attempt": 1,
                "gate_pass": False,
                "missing_signals": ["退款政策信息"],
                "source_set_changed": False,
            },
        ],
        previous_missing_signals=["refund_policy_info"],
    )
    # Different wording but source_set_changed=False → should stop via condition 2
    assert runner._should_stop_retry(ctx) is True
    assert ctx.orchestrator_debug.convergence_reason == "source_set_unchanged_retry_saturated"
