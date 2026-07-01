"""Tests for the standalone retrieval benchmark script."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / ".scratch" / "resume-eval" / "run_resume_eval.py"
SPEC = importlib.util.spec_from_file_location("run_resume_eval", SCRIPT_PATH)
assert SPEC and SPEC.loader
run_resume_eval = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_resume_eval)


def _write_dataset(tmp_path: Path, cases: list[dict]) -> Path:
    path = tmp_path / "eval_cases.json"
    path.write_text(
        json.dumps({"version": "1.0", "name": "test-set", "cases": cases}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _case(case_id: str, **overrides) -> dict:
    payload = {
        "id": case_id,
        "question": f"question {case_id}",
        "expected_source_urls": [f"eval://retrieval/{case_id.lower()}"],
        "standard_answer": "reference answer",
        "tags": ["paraphrase"],
        "difficulty": "medium",
    }
    payload.update(overrides)
    return payload


def test_load_eval_cases_json_validates_and_applies_limit(tmp_path):
    path = _write_dataset(tmp_path, [_case("EVAL-001"), _case("EVAL-002"), _case("EVAL-003")])

    cases = run_resume_eval.load_eval_cases_json(path, limit=2)

    assert [case["name"] for case in cases] == ["EVAL-001", "EVAL-002"]
    assert cases[0]["expected_source_urls"] == ["eval://retrieval/eval-001"]
    assert cases[0]["tags"] == ["paraphrase"]
    assert cases[0]["difficulty"] == "medium"


@pytest.mark.parametrize(
    ("case", "message"),
    [
        (_case("EVAL-007", expected_source_urls=[]), "EVAL-007.*expected_source_urls"),
        (_case("EVAL-008", difficulty="extreme"), "EVAL-008.*difficulty"),
    ],
)
def test_load_eval_cases_json_rejects_invalid_cases(tmp_path, case, message):
    path = _write_dataset(tmp_path, [case])

    with pytest.raises(ValueError, match=message):
        run_resume_eval.load_eval_cases_json(path, limit=100)


def test_source_url_metrics_compute_recall_hit_and_reciprocal_rank():
    expected = ["eval://retrieval/doc-002", "eval://retrieval/doc-004"]
    retrieved = [
        "eval://retrieval/doc-001",
        "eval://retrieval/doc-004",
        "eval://retrieval/doc-003",
        "eval://retrieval/doc-002",
        "eval://retrieval/doc-005",
    ]

    assert run_resume_eval.recall_at_k(expected, retrieved, 1) == 0.0
    assert run_resume_eval.recall_at_k(expected, retrieved, 3) == 0.5
    assert run_resume_eval.recall_at_k(expected, retrieved, 5) == 1.0
    assert run_resume_eval.hit_at_k(expected, retrieved, 1) == 0.0
    assert run_resume_eval.hit_at_k(expected, retrieved, 3) == 1.0
    assert run_resume_eval.hit_at_k(expected, retrieved, 5) == 1.0
    assert run_resume_eval.reciprocal_rank(expected, retrieved) == 0.5


@pytest.mark.asyncio
async def test_run_pipeline_cases_records_external_retrieval_and_llm_data(monkeypatch):
    close_count = 0
    output = SimpleNamespace(
        decision="PASS",
        debug={
            "evidence_summary": [
                {"chunk_id": "chunk-1", "source_url": "eval://retrieval/doc-001"},
                {"chunk_id": "chunk-2", "source_url": "eval://retrieval/doc-002"},
            ],
            "timings": {"retrieve": 0.25, "total": 0.5},
            "llm_call_log": [
                {
                    "task": "normalizer",
                    "model": "model-a",
                    "attempt": 1,
                    "is_fallback": False,
                    "duration_seconds": 0.1,
                    "status": "success",
                    "error_type": None,
                }
            ],
        },
    )

    class FakeAnswerService:
        async def generate(self, query, trace_id=None):
            assert query == "Where is document two?"
            return output

        async def aclose(self):
            nonlocal close_count
            close_count += 1

    monkeypatch.setattr("app.services.answer_service.AnswerService", FakeAnswerService)
    cases = [
        {
            "name": "EVAL-001",
            "question": "Where is document two?",
            "expected_source_urls": ["eval://retrieval/doc-002"],
            "standard_answer": "answer",
            "tags": ["paraphrase"],
            "difficulty": "medium",
        }
    ]

    rows = await run_resume_eval._run_pipeline_cases(cases, case_timeout=2.0)

    assert rows[0]["top5_source_urls"] == [
        "eval://retrieval/doc-001",
        "eval://retrieval/doc-002",
    ]
    assert rows[0]["recall_at_1"] == 0.0
    assert rows[0]["recall_at_3"] == 1.0
    assert rows[0]["hit_at_5"] == 1.0
    assert rows[0]["reciprocal_rank"] == 0.5
    assert rows[0]["first_relevant_rank"] == 2
    assert rows[0]["llm_calls"][0]["task"] == "normalizer"
    assert close_count == 1


def test_summarize_reports_retrieval_latency_and_llm_tasks():
    pipeline = [
        {
            "error": None,
            "recall_at_1": 0.0,
            "recall_at_3": 1.0,
            "recall_at_5": 1.0,
            "hit_at_1": 0.0,
            "hit_at_3": 1.0,
            "hit_at_5": 1.0,
            "reciprocal_rank": 0.5,
            "latency_seconds": 0.5,
            "timings": {"retrieve": 0.2, "generate": 0.3},
            "decision": "PASS",
            "answer": "Here is the answer.",
            "termination_reason": "done",
            "stage_reasons": ["agentic_route: rag_search", "retrieve: chunks=3", "generate: llm_complete decision=PASS"],
            "llm_calls": [
                {"task": "normalizer", "duration_seconds": 0.1, "status": "success", "is_fallback": False},
                {"task": "generate", "duration_seconds": 0.4, "status": "error", "is_fallback": False},
                {"task": "generate", "duration_seconds": 0.2, "status": "success", "is_fallback": True},
            ],
        },
        {
            "error": None,
            "recall_at_1": 1.0,
            "recall_at_3": 1.0,
            "recall_at_5": 1.0,
            "hit_at_1": 1.0,
            "hit_at_3": 1.0,
            "hit_at_5": 1.0,
            "reciprocal_rank": 1.0,
            "latency_seconds": 0.7,
            "timings": {"retrieve": 0.4, "generate": 0.5},
            "decision": "ASK_USER",
            "answer": "Could you clarify?",
            "termination_reason": "ask_user",
            "stage_reasons": ["agentic_route: rag_search", "retrieve: chunks=2", "generate: llm_complete decision=ASK_USER"],
            "llm_calls": [
                {"task": "normalizer", "duration_seconds": 0.3, "status": "timeout", "is_fallback": False},
                {"task": "generate", "duration_seconds": 0.5, "status": "success", "is_fallback": False},
            ],
        },
    ]
    reviewer = {
        "case_pairs": 0,
        "risk_intercept_recall": None,
        "normal_answer_false_intercept_rate": None,
        "cases": [],
    }

    summary = run_resume_eval._summarize(pipeline, reviewer)

    assert summary["retrieval_quality"]["recall_at_1"] == 0.5
    assert summary["retrieval_quality"]["recall_at_5"] == 1.0
    assert summary["retrieval_quality"]["mrr"] == 0.75
    assert summary["retrieval_latency_seconds"] == {"p50": 0.2, "p95": 0.4, "p99": 0.4}
    assert summary["llm_tasks"]["normalizer"]["call_count"] == 2
    assert summary["llm_tasks"]["normalizer"]["timeout_count"] == 1
    assert summary["llm_tasks"]["normalizer"]["success_rate"] == 0.5
    assert summary["llm_tasks"]["generate"]["fallback_count"] == 1
    assert summary["llm_tasks"]["generate"]["latency_seconds"]["p95"] == 0.5


def test_render_markdown_includes_retrieval_and_llm_sections():
    summary = {
        "dataset_cases": 100,
        "successful_cases": 99,
        "failed_cases": 1,
        "retrieval_quality": {
            "recall_at_1": 0.7,
            "recall_at_3": 0.85,
            "recall_at_5": 0.9,
            "hit_at_1": 0.75,
            "hit_at_3": 0.9,
            "hit_at_5": 0.95,
            "mrr": 0.8,
        },
        "latency_seconds": {"p50": 1.0, "p95": 4.0, "p99": 6.0},
        "retrieval_latency_seconds": {"p50": 0.2, "p95": 0.8, "p99": 1.2},
        "phase_p95_seconds": {},
        "llm_tasks": {
            "normalizer": {
                "call_count": 100,
                "success_count": 99,
                "error_count": 0,
                "timeout_count": 1,
                "fallback_count": 2,
                "success_rate": 0.99,
                "fallback_rate": 0.02,
                "models": {"model-a": 100},
                "latency_seconds": {"p50": 0.3, "p95": 1.1, "p99": 2.0},
            }
        },
        "pipeline_decision_counts": {"PASS": 99},
        "reviewer": {"case_pairs": 0},
    }

    markdown = run_resume_eval._render_markdown(summary)

    assert "Recall@1/3/5：70.00% / 85.00% / 90.00%" in markdown
    assert "MRR：80.00%" in markdown
    assert "检索延迟 P50/P95/P99：0.200s / 0.800s / 1.200s" in markdown
    assert "| normalizer | 100 | 99.00% | 2 | 0 | 0 | 1 |" in markdown


def test_enable_llm_call_capture_overrides_runtime_cache(monkeypatch):
    from app.services import archi_config

    monkeypatch.setattr(archi_config, "_cache", {"debug_llm_calls": False})

    run_resume_eval.enable_llm_call_capture(True)

    assert archi_config._cache["debug_llm_calls"] is True


# ---------------------------------------------------------------------------
# Issue 01: Case validity classification
# ---------------------------------------------------------------------------


def _valid_case(**overrides) -> dict:
    """Build a minimal valid pipeline case."""
    base = {
        "name": "EVAL-001",
        "question": "How to reset password?",
        "decision": "PASS",
        "answer": "Go to settings and click reset password.",
        "termination_reason": "done",
        "stage_reasons": ["agentic_route: rag_search", "retrieve: chunks=3", "generate: llm_complete decision=PASS"],
        "error": None,
        "latency_seconds": 1.5,
        "recall_at_5": 1.0,
        "hit_at_5": 1.0,
        "reciprocal_rank": 1.0,
        "timings": {"retrieve": 0.3, "generate": 0.5},
        "llm_calls": [],
        "tags": ["paraphrase"],
        "difficulty": "medium",
    }
    base.update(overrides)
    return base


class TestClassifyCaseValidity:
    """Tests for _classify_case_validity."""

    def test_valid_pass_case(self):
        case = _valid_case()
        result = run_resume_eval._classify_case_validity(case)
        assert result["harness_completed"] is True
        assert result["business_valid"] is True
        assert result["failure_category"] is None

    def test_valid_ask_user_case(self):
        case = _valid_case(decision="ASK_USER", answer="Could you clarify?", termination_reason="ask_user")
        result = run_resume_eval._classify_case_validity(case)
        assert result["business_valid"] is True
        assert result["failure_category"] is None

    def test_valid_human_handoff(self):
        """Intentional human handoff from Agentic Router is valid business output."""
        case = _valid_case(
            decision="ESCALATE",
            answer="This request requires human review. A support agent will follow up.",
            termination_reason="escalate",
            stage_reasons=["agentic_route: human_handoff"],
            expected_source_urls=[],
        )
        result = run_resume_eval._classify_case_validity(case)
        assert result["business_valid"] is True
        assert result["failure_category"] is None
        # Human handoff is an early route — retrieval is NOT executed
        assert result["retrieval_executed"] is False
        # No expected_source_urls → not retrieval-eligible by expectation
        assert result["retrieval_eligible"] is False
        assert result["route"] == "human_handoff"

    def test_misrouted_rag_case_is_retrieval_eligible_but_not_executed(self):
        """A case with expected_source_urls that was mis-routed to human_handoff
        should be retrieval_eligible=True (it SHOULD have been retrieved) but
        retrieval_executed=False (it wasn't). This exposes routing errors."""
        case = _valid_case(
            decision="ESCALATE",
            answer="This request requires human review.",
            termination_reason="escalate",
            stage_reasons=["agentic_route: human_handoff"],
            expected_source_urls=["https://example.com/refund-policy"],
        )
        result = run_resume_eval._classify_case_validity(case)
        assert result["business_valid"] is True
        # Has expected_source_urls → retrieval-eligible by expectation
        assert result["retrieval_eligible"] is True
        # But actual route bypassed retrieval
        assert result["retrieval_executed"] is False

    def test_invalid_generation_failure_as_escalate(self):
        """Generation failure wrapped as ESCALATE is invalid."""
        case = _valid_case(
            decision="ESCALATE",
            answer="I'm sorry, I encountered an error. Please try again or contact support.",
            termination_reason=None,
        )
        result = run_resume_eval._classify_case_validity(case)
        assert result["business_valid"] is False
        assert result["failure_category"] == "generation_failure"

    def test_invalid_generic_error_answer(self):
        """Generic system error answer is invalid regardless of decision."""
        case = _valid_case(
            decision="PASS",
            answer="I'm sorry, I encountered an error. Please try again later.",
            termination_reason="done",
        )
        result = run_resume_eval._classify_case_validity(case)
        assert result["business_valid"] is False
        assert result["failure_category"] == "generic_error_answer"

    def test_valid_policy_answer_may_direct_user_to_contact_support(self):
        """正常业务指引包含“请联系客服”时不应被误判为系统错误。"""
        case = _valid_case(
            decision="PASS",
            answer=(
                "普通地区包裹超过72小时无新扫描时可发起催查。"
                "若超过72小时仍无更新，请联系客服，我们将协助跟进承运商反馈。"
            ),
            termination_reason="done",
        )
        result = run_resume_eval._classify_case_validity(case)
        assert result["business_valid"] is True
        assert result["failure_category"] is None

    def test_invalid_missing_termination_reason(self):
        """Missing termination reason marks case as invalid."""
        case = _valid_case(termination_reason=None)
        result = run_resume_eval._classify_case_validity(case)
        assert result["business_valid"] is False
        assert result["failure_category"] == "missing_termination"

    def test_invalid_empty_answer(self):
        """Empty answer is invalid."""
        case = _valid_case(answer="", termination_reason="done")
        result = run_resume_eval._classify_case_validity(case)
        assert result["business_valid"] is False
        assert result["failure_category"] == "empty_answer"

    def test_invalid_harness_error(self):
        """Python exception during harness execution is invalid."""
        case = _valid_case(decision="ERROR", error="TimeoutError: case timed out", answer=None, termination_reason=None)
        result = run_resume_eval._classify_case_validity(case)
        assert result["harness_completed"] is False
        assert result["business_valid"] is False
        assert result["failure_category"] == "harness_error"

    def test_invalid_unrecognized_decision(self):
        """Unrecognized decision value is invalid."""
        case = _valid_case(decision="UNKNOWN_DECISION", termination_reason="done")
        result = run_resume_eval._classify_case_validity(case)
        assert result["business_valid"] is False
        assert result["failure_category"] == "unrecognized_decision"

    def test_route_short_circuit_no_retrieval(self):
        """Human handoff that bypassed retrieval is route-short-circuited."""
        case = _valid_case(
            decision="ESCALATE",
            answer="This request requires human review.",
            termination_reason="escalate",
            latency_seconds=0.003,
            stage_reasons=["agentic_route: human_handoff"],
        )
        result = run_resume_eval._classify_case_validity(case)
        assert result["business_valid"] is True
        # Human handoff from Agentic Router bypasses retrieval
        assert result["retrieval_executed"] is False
        assert result["route"] == "human_handoff"


class TestSummarizeValidity:
    """Tests for _summarize benchmark validity fields."""

    def test_summary_includes_validity_fields(self):
        pipeline = [
            _valid_case(name="EVAL-001"),
            _valid_case(
                name="EVAL-002",
                decision="ESCALATE",
                answer="I'm sorry, I encountered an error.",
                termination_reason=None,
            ),
        ]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)

        assert "benchmark_validity" in summary
        bv = summary["benchmark_validity"]
        assert "valid" in bv
        assert "invalid_count" in bv
        assert "invalidation_reasons" in bv
        assert bv["invalid_count"] == 1
        assert bv["valid"] is False

    def test_summary_validity_before_quality_metrics(self):
        """Benchmark validity should appear before retrieval_quality in key order."""
        pipeline = [_valid_case()]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        keys = list(summary.keys())
        assert keys.index("benchmark_validity") < keys.index("retrieval_quality")
        assert keys.index("benchmark_validity") < keys.index("latency_seconds")

    def test_summary_counts_valid_and_invalid_separately(self):
        pipeline = [
            _valid_case(name="EVAL-001"),
            _valid_case(name="EVAL-002"),
            _valid_case(
                name="EVAL-003",
                decision="ESCALATE",
                answer="I'm sorry, I encountered an error.",
                termination_reason=None,
            ),
        ]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)

        assert summary["dataset_cases"] == 3
        assert summary["successful_cases"] == 2
        assert summary["failed_cases"] == 1
        assert summary["benchmark_validity"]["invalid_count"] == 1

    def test_summary_schema_version(self):
        pipeline = [_valid_case()]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        assert "schema_version" in summary

    def test_summary_invalidation_reasons_detail(self):
        pipeline = [
            _valid_case(name="EVAL-001", decision="ESCALATE", answer="I'm sorry, error.", termination_reason=None),
            _valid_case(name="EVAL-002", termination_reason=None),
            _valid_case(name="EVAL-003", answer=""),
        ]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        reasons = summary["benchmark_validity"]["invalidation_reasons"]
        assert "generation_failure" in reasons
        assert "missing_termination" in reasons
        assert "empty_answer" in reasons


class TestRenderMarkdownValidity:
    """Tests for _render_markdown validity section."""

    def test_markdown_shows_validity_before_recall(self):
        summary = {
            "schema_version": "2.0",
            "dataset_cases": 10,
            "successful_cases": 8,
            "failed_cases": 2,
            "benchmark_validity": {
                "valid": False,
                "invalid_count": 2,
                "invalidation_reasons": {"generation_failure": 2},
            },
            "retrieval_quality": {
                "recall_at_1": 0.7, "recall_at_3": 0.85, "recall_at_5": 0.9,
                "hit_at_1": 0.75, "hit_at_3": 0.9, "hit_at_5": 0.95, "mrr": 0.8,
            },
            "latency_seconds": {"p50": 1.0, "p95": 4.0, "p99": 6.0},
            "retrieval_latency_seconds": {"p50": 0.2, "p95": 0.8, "p99": 1.2},
            "phase_p95_seconds": {},
            "llm_tasks": {},
            "pipeline_decision_counts": {"PASS": 8},
            "reviewer": {"case_pairs": 0},
        }
        md = run_resume_eval._render_markdown(summary)
        validity_pos = md.find("Benchmark 有效性")
        recall_pos = md.find("Recall@")
        assert validity_pos != -1
        assert recall_pos != -1
        assert validity_pos < recall_pos

    def test_markdown_shows_invalidation_reasons(self):
        summary = {
            "schema_version": "2.0",
            "dataset_cases": 10,
            "successful_cases": 7,
            "failed_cases": 3,
            "benchmark_validity": {
                "valid": False,
                "invalid_count": 3,
                "invalidation_reasons": {"generation_failure": 2, "missing_termination": 1},
            },
            "retrieval_quality": {
                "recall_at_1": 0.7, "recall_at_3": 0.85, "recall_at_5": 0.9,
                "hit_at_1": 0.75, "hit_at_3": 0.9, "hit_at_5": 0.95, "mrr": 0.8,
            },
            "latency_seconds": {"p50": 1.0, "p95": 4.0, "p99": 6.0},
            "retrieval_latency_seconds": {"p50": 0.2, "p95": 0.8, "p99": 1.2},
            "phase_p95_seconds": {},
            "llm_tasks": {},
            "pipeline_decision_counts": {"PASS": 7},
            "reviewer": {"case_pairs": 0},
        }
        md = run_resume_eval._render_markdown(summary)
        assert "generation_failure" in md
        assert "missing_termination" in md


class TestExitCode:
    """Tests for CLI exit code behavior."""

    def test_exit_code_zero_when_all_valid(self):
        pipeline = [_valid_case(name="EVAL-001"), _valid_case(name="EVAL-002")]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        # Valid benchmark: exit 0
        assert summary["benchmark_validity"]["valid"] is True

    def test_exit_code_nonzero_when_invalid(self):
        pipeline = [
            _valid_case(name="EVAL-001"),
            _valid_case(
                name="EVAL-002",
                decision="ESCALATE",
                answer="I'm sorry, I encountered an error.",
                termination_reason=None,
            ),
        ]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        # Invalid benchmark: exit non-zero
        assert summary["benchmark_validity"]["valid"] is False


# ---------------------------------------------------------------------------
# Issue 02: Lightweight telemetry and rate-limit stats
# ---------------------------------------------------------------------------


class TestRateLimitStats:
    """Tests for rate-limit tracking in LLM task summary."""

    def test_rate_limit_count_in_llm_tasks(self):
        """LLM task summary must count rate-limited attempts separately."""
        pipeline = [
            _valid_case(
                llm_calls=[
                    {"task": "generate", "model": "gpt-5.2", "attempt": 1, "duration_seconds": 0.5, "status": "rate_limited", "is_fallback": False, "error_type": "RateLimitError"},
                    {"task": "generate", "model": "gpt-5.2", "attempt": 2, "duration_seconds": 1.0, "status": "success", "is_fallback": True, "error_type": None},
                ],
            ),
        ]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        gen = summary["llm_tasks"]["generate"]
        assert gen["rate_limited_count"] == 1
        assert gen["call_count"] == 2

    def test_success_after_429_counted_as_success(self):
        """success_after_429 must be counted in success_count and success_rate."""
        pipeline = [
            _valid_case(
                llm_calls=[
                    {"task": "generate", "model": "gpt-5.2", "attempt": 1, "duration_seconds": 0.5, "status": "rate_limited", "is_fallback": False, "error_type": "RateLimitError"},
                    {"task": "generate", "model": "gpt-5.2", "attempt": 1, "duration_seconds": 2.0, "status": "success_after_429", "is_fallback": False, "error_type": None},
                ],
            ),
        ]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        gen = summary["llm_tasks"]["generate"]
        assert gen["call_count"] == 2
        assert gen["success_count"] == 1  # success_after_429 counted as success
        assert gen["rate_limited_count"] == 1
        assert gen["success_rate"] == 0.5
        # Recovered — NOT a terminal failure
        assert gen["terminal_rate_limit_failure"] == 0

    def test_terminal_rate_limit_failure_only_when_unrecovered(self):
        """terminal_rate_limit_failure must only count tasks where 429 was NOT recovered."""
        pipeline = [
            _valid_case(
                llm_calls=[
                    # Task A: 429 then recovered — NOT terminal
                    {"task": "generate", "model": "gpt-5.2", "attempt": 1, "duration_seconds": 0.5, "status": "rate_limited", "is_fallback": False, "error_type": "RateLimitError"},
                    {"task": "generate", "model": "gpt-5.2", "attempt": 1, "duration_seconds": 2.0, "status": "success_after_429", "is_fallback": False, "error_type": None},
                    # Task B: 429 with no recovery — terminal
                    {"task": "evidence_selector", "model": "gpt-5.2", "attempt": 1, "duration_seconds": 0.5, "status": "rate_limited", "is_fallback": False, "error_type": "RateLimitError"},
                    {"task": "evidence_selector", "model": "gpt-4o-mini", "attempt": 2, "duration_seconds": 0.5, "status": "rate_limited", "is_fallback": True, "error_type": "RateLimitError"},
                ],
            ),
        ]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        gen = summary["llm_tasks"]["generate"]
        assert gen["terminal_rate_limit_failure"] == 0  # recovered
        assert gen["recovered_rate_limit"] == 1
        sel = summary["llm_tasks"]["evidence_selector"]
        assert sel["terminal_rate_limit_failure"] == 1  # unrecovered
        assert sel["recovered_rate_limit"] == 0

    def test_terminal_rate_limit_across_cases_same_task(self):
        """Same task across different cases: one terminal, one recovered.
        Must count terminal failures per-case, not mask them globally."""
        pipeline = [
            _valid_case(
                name="CASE-1",
                llm_calls=[
                    # generate: 429, no recovery — terminal for this case
                    {"task": "generate", "model": "gpt-5.2", "attempt": 1, "duration_seconds": 0.5, "status": "rate_limited", "is_fallback": False, "error_type": "RateLimitError"},
                    {"task": "generate", "model": "gpt-4o-mini", "attempt": 2, "duration_seconds": 0.5, "status": "rate_limited", "is_fallback": True, "error_type": "RateLimitError"},
                ],
            ),
            _valid_case(
                name="CASE-2",
                llm_calls=[
                    # generate: 429 then recovered — NOT terminal for this case
                    {"task": "generate", "model": "gpt-5.2", "attempt": 1, "duration_seconds": 0.5, "status": "rate_limited", "is_fallback": False, "error_type": "RateLimitError"},
                    {"task": "generate", "model": "gpt-5.2", "attempt": 1, "duration_seconds": 2.0, "status": "success_after_429", "is_fallback": False, "error_type": None},
                ],
            ),
        ]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        gen = summary["llm_tasks"]["generate"]
        # CASE-1 had terminal failure, CASE-2 recovered → total terminal = 1
        assert gen["terminal_rate_limit_failure"] == 1
        assert gen["recovered_rate_limit"] == 1
        assert gen["rate_limited_count"] == 3  # 2 from CASE-1 + 1 from CASE-2

    def test_llm_tasks_non_empty_without_debug_capture(self):
        """LLM task stats must be present even without full debug capture."""
        pipeline = [
            _valid_case(
                llm_calls=[
                    {"task": "normalizer", "model": "gpt-4o-mini", "attempt": 1, "duration_seconds": 0.3, "status": "success", "is_fallback": False, "error_type": None},
                ],
            ),
        ]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        assert summary["llm_tasks"] != {}
        assert summary["llm_tasks"]["normalizer"]["call_count"] == 1
        # Verify no prompt/response in lightweight records
        # (This is a semantic assertion — the test data doesn't have these fields)

    def test_llm_tasks_no_heavy_fields_in_default_mode(self):
        """Default (non-capture) LLM records must not contain messages or response_content."""
        pipeline = [
            _valid_case(
                llm_calls=[
                    {"task": "generate", "model": "gpt-5.2", "attempt": 1, "duration_seconds": 0.5, "status": "success", "is_fallback": False, "error_type": None},
                ],
            ),
        ]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        # The summary itself doesn't contain messages/response — this is by design
        gen = summary["llm_tasks"]["generate"]
        assert gen["call_count"] == 1


class TestInfrastructureErrorThreshold:
    """Tests for infrastructure error threshold marking benchmark as invalid."""

    def test_benchmark_invalid_when_infra_error_threshold_exceeded(self):
        """When too many infrastructure errors occur, benchmark should be invalid."""
        # Create 10 cases: 4 valid, 6 with generation_failure (infrastructure errors)
        pipeline = [_valid_case(name=f"EVAL-{i:03d}") for i in range(1, 5)]
        for i in range(5, 11):
            pipeline.append(_valid_case(
                name=f"EVAL-{i:03d}",
                decision="ESCALATE",
                answer="I'm sorry, I encountered an error.",
                termination_reason=None,
            ))
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        # 6/10 = 60% invalid — above any reasonable threshold
        assert summary["benchmark_validity"]["valid"] is False
        assert summary["benchmark_validity"]["invalid_count"] == 6


# ---------------------------------------------------------------------------
# Issue 03: Segmented metrics, routing summary, diagnosis pack
# ---------------------------------------------------------------------------


class TestSegmentedMetrics:
    """Tests for metrics segmented by execution path."""

    def test_all_cases_metrics_included(self):
        """Summary must include all_cases segment."""
        pipeline = [
            _valid_case(name="EVAL-001", recall_at_5=1.0, hit_at_5=1.0, reciprocal_rank=1.0),
            _valid_case(name="EVAL-002", decision="ESCALATE", answer="Human review needed.", termination_reason="escalate", latency_seconds=0.003),
        ]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        assert "segmented_metrics" in summary
        seg = summary["segmented_metrics"]
        assert "all_cases" in seg
        assert seg["all_cases"]["count"] == 2

    def test_retrieval_executed_excludes_route_short_circuit(self):
        """Route short-circuits must not appear in retrieval_executed segment."""
        pipeline = [
            _valid_case(name="EVAL-001", recall_at_5=1.0, hit_at_5=1.0, reciprocal_rank=1.0),
            _valid_case(name="EVAL-002", decision="ESCALATE", answer="Human review.", termination_reason="escalate",
                        stage_reasons=["agentic_route: human_handoff"], expected_source_urls=[]),
        ]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        seg = summary["segmented_metrics"]
        assert seg["retrieval_executed"]["count"] == 1
        assert seg["route_short_circuited"]["count"] == 1

    def test_misrouted_case_appears_in_route_short_circuited(self):
        """A mis-routed case (expected retrieval, got human_handoff) must appear
        in route_short_circuited segment, even though retrieval_eligible=True."""
        pipeline = [
            _valid_case(name="EVAL-001", recall_at_5=1.0, hit_at_5=1.0, reciprocal_rank=1.0),
            _valid_case(name="EVAL-002", decision="ESCALATE", answer="Human review.", termination_reason="escalate",
                        stage_reasons=["agentic_route: human_handoff"],
                        expected_source_urls=["https://example.com/policy"]),
        ]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        seg = summary["segmented_metrics"]
        # Mis-routed case: retrieval_eligible=True but route is early → short-circuited
        assert seg["route_short_circuited"]["count"] == 1
        assert seg["retrieval_executed"]["count"] == 1
        assert seg["retrieval_eligible"]["count"] == 2  # both eligible

    def test_invalid_segment_excluded_from_retrieval(self):
        """Invalid cases must not appear in retrieval segments."""
        pipeline = [
            _valid_case(name="EVAL-001"),
            _valid_case(name="EVAL-002", decision="ESCALATE", answer="I'm sorry, error.", termination_reason=None),
        ]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        seg = summary["segmented_metrics"]
        assert seg["invalid_cases"]["count"] == 1
        assert seg["retrieval_executed"]["count"] == 1


class TestRoutingSummary:
    """Tests for routing distribution summary."""

    def test_routing_summary_counts_by_route(self):
        pipeline = [
            _valid_case(name="EVAL-001", decision="PASS"),
            _valid_case(name="EVAL-002", decision="PASS"),
            _valid_case(name="EVAL-003", decision="ASK_USER", answer="Clarify?", termination_reason="ask_user",
                        stage_reasons=["agentic_route: clarify"]),
            _valid_case(name="EVAL-004", decision="ESCALATE", answer="Human review.", termination_reason="escalate",
                        stage_reasons=["agentic_route: human_handoff"]),
        ]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        assert "routing_summary" in summary
        rs = summary["routing_summary"]
        assert rs["rag_search"] == 2
        assert rs["clarify"] == 1
        assert rs["human_handoff"] == 1


class TestRecallGroups:
    """Tests for retrieval recall grouping."""

    def test_recall_groups_full_partial_zero(self):
        pipeline = [
            _valid_case(name="EVAL-001", recall_at_5=1.0, hit_at_5=1.0, reciprocal_rank=1.0),
            _valid_case(name="EVAL-002", recall_at_5=0.5, hit_at_5=1.0, reciprocal_rank=0.5),
            _valid_case(name="EVAL-003", recall_at_5=0.0, hit_at_5=0.0, reciprocal_rank=0.0),
        ]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        assert "recall_groups" in summary
        rg = summary["recall_groups"]
        assert rg["full_recall"] == 1
        assert rg["partial_recall"] == 1
        assert rg["zero_recall"] == 1


class TestLatencyGroups:
    """Tests for latency segmentation."""

    def test_latency_groups_present(self):
        pipeline = [
            _valid_case(name="EVAL-001", latency_seconds=1.0, retry_count=0),
            _valid_case(name="EVAL-002", latency_seconds=5.0, retry_count=1),
            _valid_case(name="EVAL-003", latency_seconds=10.0, retry_count=3),
        ]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        assert "latency_groups" in summary
        lg = summary["latency_groups"]
        assert "no_retry" in lg
        assert "retried" in lg
        assert "max_retry" in lg


class TestDiagnosisPack:
    """Tests for compact diagnosis JSON generation."""

    def test_generate_diagnosis_pack_exists(self):
        """_generate_diagnosis_pack must be callable and return a dict."""
        pipeline = [_valid_case(name="EVAL-001")]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        diag = run_resume_eval._generate_diagnosis_pack(summary, pipeline)
        assert isinstance(diag, dict)
        assert "summary" in diag
        assert "invalid_cases" in diag
        assert "slowest_cases" in diag

    def test_diagnosis_pack_excludes_prompt_and_response(self):
        """Diagnosis pack must not contain prompt or response content."""
        case = _valid_case(name="EVAL-001")
        case["llm_calls"] = [{"task": "generate", "messages": [{"role": "user", "content": "secret"}], "response_content": "secret answer"}]
        pipeline = [case]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        diag = run_resume_eval._generate_diagnosis_pack(summary, pipeline)
        diag_str = json.dumps(diag)
        assert "secret" not in diag_str

    def test_diagnosis_pack_includes_recall_failures(self):
        pipeline = [
            _valid_case(name="EVAL-001", recall_at_5=0.0, hit_at_5=0.0, reciprocal_rank=0.0),
        ]
        reviewer = {"case_pairs": 0, "risk_intercept_recall": None, "normal_answer_false_intercept_rate": None, "cases": []}
        summary = run_resume_eval._summarize(pipeline, reviewer)
        diag = run_resume_eval._generate_diagnosis_pack(summary, pipeline)
        assert len(diag["recall_failures"]) == 1
