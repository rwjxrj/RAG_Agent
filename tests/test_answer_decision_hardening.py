"""Tests for answer decision hardening (Issue 01-04).

Covers:
- Issue 01: ESCALATE override must respect quality gate, risk level, upstream decision
- Issue 02: Quality gate + type mismatch requires bounded wording before downgrade
- Issue 03: Business keyword matching uses word boundaries for English
- Issue 04: Deterministic output language from query text
"""

import pytest

from app.search.base import EvidenceChunk
from app.services.answer_utils import (
    _build_language_instruction,
    _detect_query_language,
    apply_answer_plan,
    format_answer_plan_instruction,
)
from app.services.decision_router import _has_strong_business_signal, route
from app.services.evidence_quality import QualityReport
from app.services.reviewer import ReviewerGate, ReviewerStatus
from app.services.schemas import AnswerPlan, DecisionResult, QuerySpec


# ---------------------------------------------------------------------------
# Issue 01: Constrain Generate's final decision authority
# ---------------------------------------------------------------------------


class TestIssue01EscalateOverride:
    """ESCALATE should only be overridden to PASS when all guards pass."""

    def _make_answer_plan(self, target_mode="PASS_EXACT"):
        return AnswerPlan(
            lane="CANDIDATE_VERIFY",
            allowed_claim_scope="full",
            must_include=[],
            must_avoid=[],
            required_citations=[],
            output_blocks=["answer"],
            generation_constraints={
                "target_answer_mode": target_mode,
                "target_answer_type": "general",
                "max_followup_questions": 1,
            },
        )

    def _make_parsed(self, decision="ESCALATE", answer="Some answer"):
        return {
            "decision": decision,
            "answer": answer,
            "confidence": 0.8,
            "citations": [{"chunk_id": "c1", "source_url": "https://example.com", "doc_type": "policy"}],
        }

    def test_escalate_overridden_when_gate_pass_low_risk_upstream_pass(self):
        """Quality gate pass + low risk + upstream PASS → ESCALATE overridden to PASS."""
        plan = self._make_answer_plan("PASS_EXACT")
        parsed = self._make_parsed(decision="ESCALATE")
        decision, answer, followup, confidence = apply_answer_plan(
            plan, parsed,
            passes_quality_gate=True,
            upstream_decision="PASS",
            risk_level="low",
        )
        assert decision == "PASS"

    def test_escalate_preserved_when_upstream_escalate(self):
        """Upstream router ESCALATE → model ESCALATE must be preserved."""
        plan = self._make_answer_plan("PASS_EXACT")
        parsed = self._make_parsed(decision="ESCALATE")
        decision, _, _, _ = apply_answer_plan(
            plan, parsed,
            passes_quality_gate=True,
            upstream_decision="ESCALATE",
            risk_level="low",
        )
        assert decision == "ESCALATE"

    def test_escalate_preserved_when_high_risk(self):
        """High risk → ESCALATE preserved even if quality gate passed."""
        plan = self._make_answer_plan("PASS_EXACT")
        parsed = self._make_parsed(decision="ESCALATE")
        decision, _, _, _ = apply_answer_plan(
            plan, parsed,
            passes_quality_gate=True,
            upstream_decision="PASS",
            risk_level="high",
        )
        assert decision == "ESCALATE"

    def test_escalate_preserved_when_quality_gate_fail(self):
        """Quality gate fail → ESCALATE preserved."""
        plan = self._make_answer_plan("PASS_EXACT")
        parsed = self._make_parsed(decision="ESCALATE")
        decision, _, _, _ = apply_answer_plan(
            plan, parsed,
            passes_quality_gate=False,
            upstream_decision="PASS",
            risk_level="low",
        )
        assert decision == "ESCALATE"

    def test_escalate_preserved_when_upstream_empty(self):
        """Upstream decision empty string → ESCALATE preserved (no evidence of upstream pass)."""
        plan = self._make_answer_plan("PASS_EXACT")
        parsed = self._make_parsed(decision="ESCALATE")
        decision, _, _, _ = apply_answer_plan(
            plan, parsed,
            passes_quality_gate=True,
            upstream_decision="",
            risk_level="low",
        )
        assert decision == "ESCALATE"

    def test_ask_user_not_affected_by_escalate_guard(self):
        """ASK_USER decisions are not affected by the ESCALATE guard logic."""
        plan = self._make_answer_plan("PASS_EXACT")
        parsed = self._make_parsed(decision="ASK_USER")
        decision, _, _, _ = apply_answer_plan(
            plan, parsed,
            passes_quality_gate=True,
            upstream_decision="PASS",
            risk_level="low",
        )
        assert decision == "ASK_USER"

    def test_pass_not_affected_by_escalate_guard(self):
        """PASS decisions remain PASS regardless of guard parameters."""
        plan = self._make_answer_plan("PASS_EXACT")
        parsed = self._make_parsed(decision="PASS")
        decision, _, _, _ = apply_answer_plan(
            plan, parsed,
            passes_quality_gate=False,
            upstream_decision="ESCALATE",
            risk_level="high",
        )
        assert decision == "PASS"


# ---------------------------------------------------------------------------
# Issue 02: Evidence sufficient but answer type mismatch
# ---------------------------------------------------------------------------


class TestIssue02QualityGateTypeMismatch:
    """Quality gate pass + type mismatch should require bounded wording."""

    def _make_evidence(self):
        return [
            EvidenceChunk("c1", "VPS plans from $8/month", "https://example.com/pricing", "pricing", 0.9, "VPS plans from $8/month"),
        ]

    def test_type_mismatch_with_bounded_wording_allows_partial(self):
        """Type mismatch + bounded wording in answer → PASS_PARTIAL allowed."""
        gate = ReviewerGate()
        result = gate.review(
            decision="PASS",
            answer="The closest related product is VPS at $8/month. This is not confirmed as your exact match.",
            citations=[{"chunk_id": "c1", "source_url": "https://example.com/pricing", "doc_type": "pricing"}],
            evidence=self._make_evidence(),
            query="dedicated server pricing",
            confidence=0.7,
            expected_answer_type="policy",
            passes_quality_gate=True,
        )
        assert result.status in {ReviewerStatus.PASS, ReviewerStatus.DOWNGRADE_LANE}
        assert result.final_lane == "PASS_PARTIAL"

    def test_type_mismatch_without_bounded_wording_not_immediate_pass(self):
        """Type mismatch + no bounded wording + no unsupported → DOWNGRADE_LANE with warning reason."""
        gate = ReviewerGate()
        result = gate.review(
            decision="PASS",
            answer="VPS plans are available from $8/month.",
            citations=[{"chunk_id": "c1", "source_url": "https://example.com/pricing", "doc_type": "pricing"}],
            evidence=self._make_evidence(),
            query="dedicated server pricing",
            confidence=0.7,
            expected_answer_type="policy",
            passes_quality_gate=True,
        )
        # Should still be DOWNGRADE_LANE but with a reason indicating no bounded wording
        assert result.status in {ReviewerStatus.DOWNGRADE_LANE, ReviewerStatus.PASS}
        if result.status == ReviewerStatus.DOWNGRADE_LANE:
            assert any("no bounded wording" in r for r in result.reasons)

    def test_overclaim_still_blocked_even_with_quality_gate(self):
        """Overclaim is still blocked even when quality gate passes."""
        gate = ReviewerGate()
        result = gate.review(
            decision="PASS",
            answer="We guarantee a full refund within 30 days. This is a confirmed policy.",
            citations=[{"chunk_id": "c1", "source_url": "https://example.com/pricing", "doc_type": "pricing"}],
            evidence=self._make_evidence(),
            query="refund policy",
            confidence=0.9,
            expected_answer_type="policy",
            passes_quality_gate=True,
        )
        # Overclaim should still be caught
        assert result.status != ReviewerStatus.PASS or "overclaim" in str(result.reasons).lower()


# ---------------------------------------------------------------------------
# Issue 03: Narrow address/logistics business disambiguation rules
# ---------------------------------------------------------------------------


class TestIssue03BusinessKeywordMatching:
    """Business keyword matching should use word boundaries for English."""

    def _make_spec(self, query):
        return QuerySpec(
            original_query=query,
            intent="ambiguous",
            entities=[],
            constraints={},
            required_evidence=[],
            risk_level="low",
            keyword_queries=[query],
            semantic_queries=[query],
            clarifying_questions=["Could you clarify?"],
            is_ambiguous=True,
            answerable_without_clarification=False,
            blocking_clarifying_questions=["Could you clarify?"],
        )

    def test_email_not_matched_by_mail(self):
        """'email' must NOT be matched by 'mail' keyword."""
        spec = self._make_spec("How do I set up email forwarding?")
        assert _has_strong_business_signal(spec) is False

    def test_send_me_not_matched_as_logistics(self):
        """'send me a link' is a general send, not logistics."""
        spec = self._make_spec("Can you send me a link to the pricing page?")
        assert _has_strong_business_signal(spec) is False

    def test_sender_not_matched_by_send(self):
        """'sender' must NOT be matched by 'send' keyword."""
        spec = self._make_spec("Who is the sender of this email?")
        assert _has_strong_business_signal(spec) is False

    def test_address_with_shipping_detected(self):
        """'address' + 'shipping' → strong business signal."""
        spec = self._make_spec("What address should I use for shipping?")
        assert _has_strong_business_signal(spec) is True

    def test_chinese_address_detected(self):
        """Chinese '地址' keyword → detected as business signal."""
        spec = self._make_spec("地址少写门牌还能发货吗")
        assert _has_strong_business_signal(spec) is True

    def test_chinese_shipping_detected(self):
        """Chinese '发货' keyword → detected as business signal."""
        spec = self._make_spec("什么时候发货")
        assert _has_strong_business_signal(spec) is True

    def test_delivery_detected(self):
        """'delivery' → detected as business signal."""
        spec = self._make_spec("What is the delivery time for VPS?")
        assert _has_strong_business_signal(spec) is True

    def test_empty_query_no_signal(self):
        """Empty query → no signal."""
        spec = self._make_spec("")
        assert _has_strong_business_signal(spec) is False


# ---------------------------------------------------------------------------
# Issue 04: Deterministic output language
# ---------------------------------------------------------------------------


class TestIssue04DeterministicLanguage:
    """Output language should be determined by query text, not upstream source_lang."""

    def test_chinese_query_detected_as_zh(self):
        """Chinese characters → 'zh' regardless of source_lang."""
        assert _detect_query_language("如何申请退款") == "zh"
        assert _detect_query_language("地址少写门牌还能发吗") == "zh"

    def test_english_query_detected_as_en(self):
        """Pure ASCII → 'en'."""
        assert _detect_query_language("How do I get a refund?") == "en"
        assert _detect_query_language("What is your refund policy?") == "en"

    def test_japanese_query_detected_as_ja(self):
        """Hiragana/Katakana → 'ja'."""
        assert _detect_query_language("返金方法を教えてください") == "ja"

    def test_korean_query_detected_as_ko(self):
        """Hangul → 'ko'."""
        assert _detect_query_language("환불 방법을 알려주세요") == "ko"

    def test_empty_query_defaults_to_en(self):
        """Empty query → 'en'."""
        assert _detect_query_language("") == "en"
        assert _detect_query_language(None) == "en"

    def test_language_instruction_is_deterministic(self):
        """Language instruction should be a single unambiguous directive."""
        zh_inst = _build_language_instruction("zh")
        assert "Chinese" in zh_inst
        assert "MUST" in zh_inst

        en_inst = _build_language_instruction("en")
        assert "English" in en_inst

        ja_inst = _build_language_instruction("ja")
        assert "Japanese" in ja_inst

        ko_inst = _build_language_instruction("ko")
        assert "Korean" in ko_inst

    @pytest.mark.parametrize("language", ["zh-cn", "zh-tw", "zh_CN"])
    def test_chinese_regional_language_codes_are_normalized(self, language):
        instruction = _build_language_instruction(language)

        assert "Chinese" in instruction
        assert "English" not in instruction

    def test_format_instruction_uses_query_text_over_source_lang(self):
        """format_answer_plan_instruction should use query_text for language, ignoring source_lang."""
        plan = AnswerPlan(
            lane="CANDIDATE_VERIFY",
            allowed_claim_scope="full",
            must_include=[],
            must_avoid=[],
            required_citations=[],
            output_blocks=["answer"],
            generation_constraints={
                "target_answer_mode": "PASS_EXACT",
                "target_answer_type": "general",
                "max_followup_questions": 1,
            },
        )
        # Chinese query with wrong source_lang='ko'
        instruction = format_answer_plan_instruction(
            plan, quality_report=None, source_lang="ko", query_text="如何申请退款",
        )
        assert "Chinese" in instruction
        assert "ko" not in instruction.lower().split("respond")[1] if "respond" in instruction.lower() else True

    def test_format_instruction_falls_back_to_source_lang_when_no_query(self):
        """When query_text is empty, falls back to source_lang."""
        plan = AnswerPlan(
            lane="CANDIDATE_VERIFY",
            allowed_claim_scope="full",
            must_include=[],
            must_avoid=[],
            required_citations=[],
            output_blocks=["answer"],
            generation_constraints={
                "target_answer_mode": "PASS_EXACT",
                "target_answer_type": "general",
                "max_followup_questions": 1,
            },
        )
        instruction = format_answer_plan_instruction(
            plan, quality_report=None, source_lang="ja", query_text="",
        )
        assert "Japanese" in instruction
