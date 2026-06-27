"""Normalizer fast-path: deterministic QuerySpec for high-confidence FAQ patterns.

Only covers simple, unambiguous Chinese customer-service short queries.
Outputs a complete QuerySpec — downstream retrieval planner sees no special objects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.logging import get_logger
from app.services.schemas import HypothesisSpec, QuerySpec

logger = get_logger(__name__)


@dataclass(frozen=True)
class _FastPathRule:
    """One deterministic fast-path rule."""

    name: str
    pattern: re.Pattern[str]
    intent: str
    answer_type: str
    answer_shape: str
    answer_expectation: str
    required_evidence: list[str]
    hard_requirements: list[str]
    soft_requirements: list[str]
    evidence_families: list[str]
    retrieval_profile: str
    doc_type_prior: list[str]
    keyword_queries: list[str]
    semantic_queries: list[str]
    rewrite_candidates: list[str]
    risk_level: str = "low"
    answer_mode: str = "PASS_EXACT"
    support_level: str = "strong"
    target_entity: str | None = None


# ---------------------------------------------------------------------------
# High-confidence rules — conservative, only unambiguous FAQ patterns
# ---------------------------------------------------------------------------

_RULES: list[_FastPathRule] = [
    # Service hours
    _FastPathRule(
        name="service_hours",
        pattern=re.compile(
            r"(?:(?:晚上|几点|什么时候|几时|啥时候|什么时间).{0,6}"
            r"(?:客服|人工|真人|在线|上班|服务|上班时间|工作时间|营业))"
            r"|(?:客服.{0,6}(?:上班时间|工作时间|几点|什么时候|在线))",
            re.IGNORECASE,
        ),
        intent="informational",
        answer_type="general",
        answer_shape="direct_lookup",
        answer_expectation="exact",
        required_evidence=["policy_language"],
        hard_requirements=[],
        soft_requirements=["policy_language"],
        evidence_families=["general_info"],
        retrieval_profile="generic_profile",
        doc_type_prior=["faq", "docs", "policy"],
        keyword_queries=["客服工作时间", "在线客服时间"],
        semantic_queries=["customer service hours", "live chat availability"],
        rewrite_candidates=["客服工作时间", "在线客服时间", "客服上班时间"],
        target_entity="service_hours",
    ),
    # Refund arrival time
    _FastPathRule(
        name="refund_arrival_time",
        pattern=re.compile(
            r"(?:退款|退钱|退费).{0,6}"
            r"(?:多久|几天|多长时间|什么时候|啥时候|到账|到帐|到卡|返回)",
            re.IGNORECASE,
        ),
        intent="policy",
        answer_type="policy",
        answer_shape="direct_lookup",
        answer_expectation="exact",
        required_evidence=["policy_language"],
        hard_requirements=[],
        soft_requirements=["policy_language"],
        evidence_families=["policy_terms"],
        retrieval_profile="policy_profile",
        doc_type_prior=["policy", "tos", "faq"],
        keyword_queries=["退款到账时间", "退款多久到账"],
        semantic_queries=["refund processing time", "how long for refund"],
        rewrite_candidates=["退款到账时间", "退款多久到账", "退款处理时间"],
        target_entity="refund_arrival",
    ),
    # Order hold / unpaid release time
    _FastPathRule(
        name="order_hold_time",
        pattern=re.compile(
            r"(?:下单|订单|付款|未付款|没付款|未支付).{0,6}"
            r"(?:多久|几天|保留|释放|取消|过期|超时|失效)",
            re.IGNORECASE,
        ),
        intent="informational",
        answer_type="general",
        answer_shape="direct_lookup",
        answer_expectation="exact",
        required_evidence=["policy_language"],
        hard_requirements=[],
        soft_requirements=["policy_language"],
        evidence_families=["policy_terms"],
        retrieval_profile="policy_profile",
        doc_type_prior=["policy", "faq", "docs"],
        keyword_queries=["未付款订单保留时间", "订单超时取消"],
        semantic_queries=["unpaid order hold time", "order expiration"],
        rewrite_candidates=["未付款订单保留时间", "订单超时取消", "下单未付款多久释放"],
        target_entity="order_hold",
    ),
    # Return/exchange period
    _FastPathRule(
        name="return_period",
        pattern=re.compile(
            r"(?:几天|多少天|多久|多长时间).{0,4}"
            r"(?:能退|可以退|能换|可以换|退换|退货|退款|退换货)",
            re.IGNORECASE,
        ),
        intent="policy",
        answer_type="policy",
        answer_shape="direct_lookup",
        answer_expectation="exact",
        required_evidence=["policy_language"],
        hard_requirements=[],
        soft_requirements=["policy_language"],
        evidence_families=["policy_terms"],
        retrieval_profile="policy_profile",
        doc_type_prior=["policy", "tos", "faq"],
        keyword_queries=["退换货期限", "几天内能退"],
        semantic_queries=["return policy period", "how many days to return"],
        rewrite_candidates=["退换货期限", "几天内能退", "退款退货期限"],
        target_entity="return_period",
    ),
    # Wash/care/size/selection FAQ
    _FastPathRule(
        name="faq_selection",
        pattern=re.compile(
            r"(?:洗护|尺码|怎么选|如何选|选哪个|推荐|哪个好|哪个适合)",
            re.IGNORECASE,
        ),
        intent="informational",
        answer_type="general",
        answer_shape="direct_lookup",
        answer_expectation="best_effort",
        required_evidence=[],
        hard_requirements=[],
        soft_requirements=[],
        evidence_families=["general_info"],
        retrieval_profile="generic_profile",
        doc_type_prior=["faq", "docs", "howto"],
        keyword_queries=[],
        semantic_queries=[],
        rewrite_candidates=[],
        target_entity=None,
    ),
]


# ---------------------------------------------------------------------------
# Exclusion patterns — queries that must NOT hit fast-path
# ---------------------------------------------------------------------------

_EXCLUSION_PATTERNS: list[re.Pattern[str]] = [
    # Pronouns / referential ambiguity
    re.compile(r"(?:这个|那个|它|这|那|这东西|那东西)(?:还|能|可以|有)", re.IGNORECASE),
    # High-risk execution requests
    re.compile(r"(?:帮我|替我|给我|我要)(?:退款|取消|退|注销|删除|关闭)", re.IGNORECASE),
    # Multi-condition / complex queries
    re.compile(r"(?:而且|并且|同时|还要|另外|以及|或者).{2,}", re.IGNORECASE),
    # Account / payment anomaly
    re.compile(r"(?:账号|账户|密码|被盗|异常|被盗|安全|支付|扣款|多扣)", re.IGNORECASE),
    # Complaint / escalation
    re.compile(r"(?:投诉|举报|升级|主管|经理|负责人|不满意)", re.IGNORECASE),
]


def _is_excluded(query: str) -> bool:
    """Return True if the query matches any exclusion pattern."""
    for pat in _EXCLUSION_PATTERNS:
        if pat.search(query):
            return True
    return False


def try_fastpath(query: str) -> tuple[QuerySpec, str] | None:
    """Attempt deterministic fast-path for a simple FAQ query.

    Returns (QuerySpec, rule_name) on hit, None on miss.
    Never returns a special/simplified structure — output is a full QuerySpec.
    """
    q = (query or "").strip()
    if not q or len(q) < 3:
        return None
    if _is_excluded(q):
        return None

    for rule in _RULES:
        if rule.pattern.search(q):
            spec = _build_spec_from_rule(rule, q)
            logger.info(
                "normalizer_fastpath_hit",
                rule=rule.name,
                query_preview=q[:80],
            )
            return spec, rule.name

    return None


def _build_spec_from_rule(rule: _FastPathRule, query: str) -> QuerySpec:
    """Build a complete QuerySpec from a fast-path rule."""
    kw = rule.keyword_queries or [query]
    sem = rule.semantic_queries or [query]
    rewrites = rule.rewrite_candidates or [query]

    primary_hypothesis = HypothesisSpec(
        name="primary",
        evidence_families=list(rule.evidence_families),
        answer_shape=rule.answer_shape,
        retrieval_profile=rule.retrieval_profile,
        required_evidence=list(rule.required_evidence),
        hard_requirements=list(rule.hard_requirements),
        soft_requirements=list(rule.soft_requirements),
        doc_type_prior=list(rule.doc_type_prior),
        preferred_sources=[d for d in rule.doc_type_prior if d in {"conversation", "faq", "blog"}],
        rewrite_candidates=list(rewrites[:5]),
        query_hint=query,
    )

    return QuerySpec(
        intent=rule.intent,
        entities=[],
        constraints={"doc_type_prior": rule.doc_type_prior} if rule.doc_type_prior else {},
        required_evidence=list(rule.required_evidence),
        risk_level=rule.risk_level,
        keyword_queries=list(kw),
        semantic_queries=list(sem),
        clarifying_questions=[],
        is_ambiguous=False,
        skip_retrieval=False,
        canned_response=None,
        out_of_scope=False,
        original_query=query,
        source_lang="zh",
        translation_needed=True,
        canonical_query_en=rule.semantic_queries[0] if rule.semantic_queries else query,
        user_goal=rule.intent,
        resolved_slots={},
        missing_slots=[],
        ambiguity_type=None,
        answerable_without_clarification=True,
        missing_info_blocking=[],
        missing_info_for_refinement=[],
        blocking_clarifying_questions=[],
        refinement_questions=[],
        assistant_should_lead=False,
        hard_requirements=list(rule.hard_requirements),
        soft_requirements=list(rule.soft_requirements),
        evidence_families=list(rule.evidence_families),
        answer_shape=rule.answer_shape,
        answer_type=rule.answer_type,
        target_entity=rule.target_entity,
        answer_expectation=rule.answer_expectation,
        acceptable_related_types=[],
        answer_mode=rule.answer_mode,
        support_level=rule.support_level,
        blocking_missing_slots=[],
        primary_hypothesis=primary_hypothesis,
        fallback_hypotheses=[],
        doc_type_prior=list(rule.doc_type_prior),
        retrieval_profile=rule.retrieval_profile,
        rewrite_candidates=list(rewrites),
        answer_mode_hint="strong",
        extraction_mode="rule_fastpath",
        fastpath_rule=rule.name,
        config_overrides_applied=[],
    )
