"""GENERATE phase: LLM generation + optional self-critic."""

import json
import re

from app.core.logging import get_logger
from app.core.config import get_settings
from app.search.base import EvidenceChunk
from app.services.answer_utils import (
    apply_answer_plan,
    build_answer_plan,
    format_answer_plan_instruction,
    format_evidence_for_prompt,
    parse_llm_response,
)
from app.services.archi_config import get_self_critic_enabled
from app.services.branding_config import get_system_prompt
from app.services.conversation_context import truncate_for_prompt
from app.services.flow_debug import _pipeline_log
from app.services.orchestrator import OrchestratorContext
from app.services.schemas import GenerateResult
from app.services.phases.relevance_check import execute_relevance_check
from app.services.self_critic import critique as self_critic

logger = get_logger(__name__)


_REASONING_SYSTEM_PROMPT = """You are an internal reasoning planner for a support RAG assistant.

Summarize evidence before final answer generation. Return JSON only:
{
  "evidence_summary": ["short point", "..."],
  "options": [
    {"option": "name", "supporting_chunks": ["chunk_id"], "tradeoffs": "short"}
  ],
  "coverage_check": {
    "covered": ["point"],
    "missing": ["point"]
  },
  "recommended_focus": "one short sentence"
}

Rules:
- Ground every point in the provided evidence.
- Compare options when evidence contains multiple valid paths/plans/methods.
- Keep output concise and deterministic.
- Never output markdown.
"""

_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"')\]]+",
    re.IGNORECASE,
)

_LINK_REQUEST_PATTERN = re.compile(
    r"\b(?:page\s+)?link\b|\blink\s+please\b|\bthat\s+link\b|\bthe\s+link\b|\burl\b|\bthat\s+page\b",
    re.IGNORECASE,
)


def _extract_urls_from_text(text: str) -> list[str]:
    """Extract http/https URLs from text. Deduplicates and preserves order."""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in _URL_PATTERN.finditer(text):
        url = m.group(0).rstrip(".,;:!?)")
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _is_link_request_query(query: str) -> bool:
    """True if user appears to be asking for a link/page from prior context."""
    q = (query or "").strip()
    if len(q) < 3:
        return False
    return bool(_LINK_REQUEST_PATTERN.search(q))


def _build_prior_citation_chunks(
    conversation_history: list[dict[str, str]],
) -> list[EvidenceChunk]:
    """Extract URLs from last assistant message and build synthetic evidence chunks."""
    if not conversation_history:
        return []
    for msg in reversed(conversation_history):
        if msg.get("role") == "assistant":
            content = msg.get("content") or ""
            urls = _extract_urls_from_text(content)
            if not urls:
                return []
            chunks: list[EvidenceChunk] = []
            for i, url in enumerate(urls[:10]):  # cap at 10
                chunk_id = f"prior-{i}"
                chunks.append(
                    EvidenceChunk(
                        chunk_id=chunk_id,
                        snippet=f"Link from prior discussion: {url}",
                        source_url=url,
                        doc_type="prior_citation",
                        score=0.0,
                        full_text=f"Link from prior discussion: {url}",
                    )
                )
            return chunks
    return []


def _parse_json_object(content: str) -> dict | None:
    text = (content or "").strip()
    if not text:
        return None
    if "```json" in text:
        start = text.find("```json")
        end = text.rfind("```")
        if start != -1 and end != -1 and end > start:
            text = text[start + 7 : end].strip()
    elif "```" in text:
        start = text.find("```")
        end = text.rfind("```")
        if start != -1 and end != -1 and end > start:
            text = text[start + 3 : end].strip()
    try:
        data = json.loads(text)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _reasoning_prepass_skip_reason(
    *,
    ctx: OrchestratorContext,
    settings,
    evidence_count: int,
) -> tuple[str | None, list[str]]:
    """Determine whether reasoning prepass can be skipped (fast-path).

    Returns (skip_reason, blockers):
    - skip_reason: a string when all conditions pass → skip reasoning prepass;
      None when any blocker prevents skipping → run reasoning prepass.
    - blockers: list of all conditions that prevented fast-path (empty when skipped).
    """
    blockers: list[str] = []

    # Hard gate: master switch
    if not bool(getattr(settings, "generate_reasoning_skip_simple_lookup", True)):
        return None, ["fastpath_master_switch_disabled"]
    # Hard gate: quality gate must pass
    if not ctx.passes_quality_gate:
        return None, ["quality_gate_not_passed"]
    # Hard gate: need evidence
    if not ctx.evidence:
        return None, ["no_evidence"]

    # Evidence count threshold (default 8, was 5)
    max_fastpath_chunks = max(
        1,
        int(getattr(settings, "generate_reasoning_fastpath_max_evidence_chunks", 8) or 8),
    )
    if evidence_count > max_fastpath_chunks:
        blockers.append(f"evidence_count_exceeds_max({evidence_count}>{max_fastpath_chunks})")

    # Missing signals — relaxed: allow when quality gate passed (configurable)
    quality_report = ctx.quality_report
    missing_signals = list(getattr(quality_report, "missing_signals", []) or [])
    if missing_signals:
        allow_missing = bool(getattr(
            settings, "generate_reasoning_fastpath_allow_missing_signals", True,
        ))
        if not allow_missing:
            blockers.append(f"missing_signals({','.join(missing_signals)})")

    # Conversation history — relaxed: allow when quality gate passed (configurable)
    if ctx.conversation_history:
        allow_history = bool(getattr(
            settings, "generate_reasoning_fastpath_allow_conversation_history", True,
        ))
        if not allow_history:
            blockers.append("has_conversation_history")

    query_spec = ctx.query_spec
    risk_level = (
        query_spec.query_intent.risk_level.strip().lower()
        if query_spec
        else "low"
    )
    # Risk level — relaxed: medium allowed when config toggle set; high always blocks
    if risk_level == "high":
        blockers.append("risk_level_high")
    elif risk_level == "medium":
        allow_medium = bool(getattr(
            settings, "generate_reasoning_fastpath_allow_medium_risk", True,
        ))
        if not allow_medium:
            blockers.append("risk_level_medium")

    answer_shape = (
        ctx.retrieve_output.active_answer_shape
        or (query_spec.answer_contract.answer_shape if query_spec else "direct_lookup")
        or "direct_lookup"
    ).strip().lower()
    # Answer shape — relaxed: complex shapes allowed when quality gate passed (configurable)
    if answer_shape not in {"direct_lookup", "short_answer", "yes_no"}:
        allow_complex = bool(getattr(
            settings, "generate_reasoning_fastpath_allow_complex_shape", True,
        ))
        if not allow_complex:
            blockers.append(f"answer_shape_not_simple({answer_shape})")

    answer_type = (
        query_spec.answer_contract.answer_type.strip().lower()
        if query_spec
        else "general"
    )
    # Answer type — relaxed: only account excluded (was pricing, direct_link, account)
    if answer_type in {"account"}:
        blockers.append(f"answer_type_excluded({answer_type})")

    # Hard requirements — relaxed: allow when quality_report covers all (configurable)
    hard_requirements = list(ctx.retrieve_output.active_hard_requirements or [])
    if query_spec:
        hard_requirements.extend(query_spec.retrieval_hints.hard_requirements or [])
    if hard_requirements:
        allow_covered = bool(getattr(
            settings, "generate_reasoning_fastpath_covered_hard_requirements", True,
        ))
        if allow_covered:
            coverage = list(getattr(quality_report, "hard_requirement_coverage", []) or [])
            all_covered = len(coverage) > 0 and all(coverage)
            if not all_covered:
                blockers.append("hard_requirements_not_fully_covered")
        else:
            blockers.append("hard_requirements_present")

    if not blockers:
        return "simple_direct_lookup_quality_passed", []
    return None, blockers


async def _run_reasoning_prepass(
    *,
    ctx: OrchestratorContext,
    llm,
    model: str,
    settings,
) -> dict | None:
    if not bool(getattr(settings, "generate_reasoning_enabled", True)):
        return None
    if not ctx.evidence:
        return None

    max_chunks = max(1, int(getattr(settings, "generate_reasoning_max_chunks", 10) or 10))
    max_options = max(1, int(getattr(settings, "generate_reasoning_max_options", 5) or 5))
    max_tokens = max(64, int(getattr(settings, "generate_reasoning_max_tokens", 400) or 400))
    evidence_block = format_evidence_for_prompt(
        ctx.evidence[:max_chunks],
        max(240, int(getattr(settings, "llm_max_evidence_chars", 1200) // 2)),
    )
    ro = ctx.retrieve_output
    reasoning_context = {
        "answer_shape": (
            ro.active_answer_shape
            or (ctx.query_spec.answer_contract.answer_shape if ctx.query_spec else "direct_lookup")
        ),
        "evidence_families": (
            list(ro.active_evidence_families or [])
            or (list(ctx.query_spec.retrieval_hints.evidence_families or []) if ctx.query_spec else [])
        ),
        "required_evidence": (
            list(ro.active_required_evidence or [])
            or (list(ctx.query_spec.retrieval_hints.required_evidence or []) if ctx.query_spec else [])
        ),
        "max_options": max_options,
    }
    user_content = (
        f"Query: {ctx.effective_query}\n\n"
        f"Reasoning context: {json.dumps(reasoning_context, ensure_ascii=False)}\n\n"
        f"Evidence:\n{evidence_block}"
    )

    try:
        from app.core.tracing import llm_task_context

        with llm_task_context("generate_reasoning"):
            resp = await llm.chat(
                messages=[
                    {"role": "system", "content": _REASONING_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.0,
                model=model,
                max_tokens=max_tokens,
            )
        parsed = _parse_json_object(getattr(resp, "content", "") or "")
        if parsed is None:
            logger.warning("generate_reasoning_parse_failed")
        return parsed
    except Exception as exc:
        logger.warning("generate_reasoning_failed", error=str(exc))
        return None


async def _apply_relevance_check(ctx: OrchestratorContext, *, llm, orchestrator) -> None:
    """Run relevance check and filter conversation_history if not relevant."""
    if not ctx.conversation_history:
        return
    result = await execute_relevance_check(
        ctx.effective_query or ctx.query,
        ctx.conversation_history,
        llm=llm,
        orchestrator=orchestrator,
        trace_id=ctx.trace_id,
    )
    if result is None:
        return  # Fallback: keep full history
    ctx.generate_output.conversation_relevance = {
        "relevant": result.relevant,
        "reason": result.reason,
        "relevant_turn_count": result.relevant_turn_count,
    }
    if not result.relevant:
        ctx.conversation_history = []
        _pipeline_log("generate", "conversation_history_dropped", reason=result.reason[:80], trace_id=ctx.trace_id)
        return
    if isinstance(result.relevant_turn_count, int) and result.relevant_turn_count == 0:
        ctx.conversation_history = []
        return
    if isinstance(result.relevant_turn_count, int) and result.relevant_turn_count > 0:
        # Keep last N turns (each turn = user + assistant = 2 messages)
        keep = result.relevant_turn_count * 2
        ctx.conversation_history = list(ctx.conversation_history[-keep:])


async def execute_generate(
    ctx: OrchestratorContext,
    *,
    llm,
    orchestrator,
    settings,
) -> GenerateResult:
    """Generate an answer from evidence selected by retrieval/evidence selector."""
    await _apply_relevance_check(ctx, llm=llm, orchestrator=orchestrator)

    evidence = list(ctx.evidence or [])
    relevance = ctx.generate_output.conversation_relevance or {}
    if (
        getattr(get_settings(), "prior_citations_injection_enabled", True)
        and relevance.get("relevant") is True
        and ctx.conversation_history
        and _is_link_request_query(ctx.effective_query or ctx.query)
    ):
        prior_chunks = _build_prior_citation_chunks(ctx.conversation_history)
        if prior_chunks:
            evidence = prior_chunks + evidence
            ctx.evidence = evidence  # so self_critic and downstream see full set
            _pipeline_log(
                "generate",
                "prior_citations_injected",
                count=len(prior_chunks),
                trace_id=ctx.trace_id,
            )

    answer_plan = build_answer_plan(
        ctx.decision_result,
        ctx.query_spec,
        ctx.quality_report,
    )
    max_chars = settings.llm_max_evidence_chars
    evidence_block = format_evidence_for_prompt(evidence, max_chars)
    model = orchestrator.get_model_for_query(ctx.query)
    skip_reason, blockers = _reasoning_prepass_skip_reason(
        ctx=ctx,
        settings=settings,
        evidence_count=len(evidence),
    )
    if skip_reason:
        prepass_info: dict = {
            "skipped": True,
            "reason": skip_reason,
        }
        query_spec = ctx.query_spec
        prepass_info["skip_metadata"] = {
            "evidence_count": len(evidence),
            "answer_type": (
                query_spec.answer_contract.answer_type.strip().lower()
                if query_spec else "general"
            ),
            "answer_shape": (
                ctx.retrieve_output.active_answer_shape
                or (query_spec.answer_contract.answer_shape if query_spec else "direct_lookup")
                or "direct_lookup"
            ).strip().lower(),
            "risk_level": (
                query_spec.query_intent.risk_level.strip().lower()
                if query_spec else "low"
            ),
            "hard_requirements_covered": (
                bool(
                    getattr(ctx.quality_report, "hard_requirement_coverage", None)
                    and all(ctx.quality_report.hard_requirement_coverage)
                )
                if ctx.quality_report
                else False
            ),
            "fastpath_relaxations": {
                "conversation_history_allowed": bool(ctx.conversation_history),
                "medium_risk_allowed": (
                    query_spec.query_intent.risk_level.strip().lower() == "medium"
                    if query_spec else False
                ),
                "complex_shape_allowed": (
                    (
                        ctx.retrieve_output.active_answer_shape
                        or (query_spec.answer_contract.answer_shape if query_spec else "direct_lookup")
                        or "direct_lookup"
                    ).strip().lower() not in {"direct_lookup", "short_answer", "yes_no"}
                ),
            },
        }
        ctx.generate_output.reasoning_prepass = prepass_info
        reasoning_prewrite = None
    else:
        reasoning_prewrite = await _run_reasoning_prepass(
            ctx=ctx,
            llm=llm,
            model=model,
            settings=settings,
        )
        prepass_info = {
            "skipped": reasoning_prewrite is None,
            "reason": "disabled_or_unavailable" if reasoning_prewrite is None else "executed",
        }
        if blockers:
            prepass_info["blockers"] = blockers
        ctx.generate_output.reasoning_prepass = prepass_info
    if reasoning_prewrite:
        ctx.generate_output.reasoning_prewrite = reasoning_prewrite
    user_content = f"User question: {ctx.effective_query}\n\nEvidence:\n{evidence_block}"
    if reasoning_prewrite:
        user_content += (
            "\n\nInternal reasoning prewrite (must use before final answer):\n"
            + json.dumps(reasoning_prewrite, ensure_ascii=False)
        )
    system_prompt = get_system_prompt()
    system_prompt = (
        f"{system_prompt}\n\n"
        f"{format_answer_plan_instruction(answer_plan, ctx.quality_report, source_lang=ctx.source_lang, query_text=ctx.query)}"
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    if ctx.conversation_history:
        for msg in truncate_for_prompt(ctx.conversation_history):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_content})
    ctx.generate_output.messages = messages

    _pipeline_log("generate", "start", model=model, evidence_chunks=len(ctx.evidence), trace_id=ctx.trace_id)
    try:
        from app.core.tracing import llm_task_context

        with llm_task_context("generate"):
            llm_resp = await llm.chat(
                messages=messages,
                temperature=settings.llm_temperature,
                model=model,
            )
    except Exception as e:
        logger.error("answer_llm_failed", error=str(e))
        ctx.generate_output.error = str(e)
        raise

    ctx.generate_output.llm_resp = llm_resp
    if getattr(llm_resp, "finish_reason", None) == "length":
        logger.warning("llm_response_truncated", trace_id=ctx.trace_id)

    parsed = parse_llm_response(llm_resp.content)
    _upstream_decision = (ctx.decision_result.decision if ctx.decision_result else "") or ""
    _risk_level = (ctx.query_spec.query_intent.risk_level if ctx.query_spec else "low") or "low"
    decision, answer, followup, confidence = apply_answer_plan(
        answer_plan,
        parsed,
        passes_quality_gate=bool(ctx.passes_quality_gate),
        upstream_decision=_upstream_decision,
        risk_level=_risk_level,
    )
    citations = parsed.get("citations", [])

    self_critic_regenerated = False
    max_gen_attempts = 1 + getattr(settings, "self_critic_regenerate_max", 1)
    for gen_attempt in range(1, max_gen_attempts + 1):
        if get_self_critic_enabled() and gen_attempt < max_gen_attempts:
            critic_context = {
                "answer_shape": (
                    ro.active_answer_shape
                    or (ctx.query_spec.answer_contract.answer_shape if ctx.query_spec else "direct_lookup")
                ),
                "evidence_families": (
                    list(ro.active_evidence_families or [])
                    or list(ctx.query_spec.retrieval_hints.evidence_families or []) if ctx.query_spec else []
                ),
                "required_evidence": (
                    list(ro.active_required_evidence or [])
                    or list(ctx.query_spec.retrieval_hints.required_evidence or []) if ctx.query_spec else []
                ),
                "reasoning_prewrite": ctx.generate_output.reasoning_prewrite,
            }
            critique_result = await self_critic(
                ctx.effective_query,
                answer,
                citations,
                ctx.evidence,
                context=critic_context,
            )
            if critique_result and not critique_result.pass_:
                try:
                    from app.core.metrics import self_critic_regenerate_total

                    self_critic_regenerate_total.inc()
                except Exception:
                    pass
                logger.info("self_critic_fail", issues=critique_result.issues[:3])
                feedback = (
                    "\n\nPrevious attempt had issues: "
                    f"{', '.join(critique_result.issues[:2])}. "
                    f"Fix: {critique_result.suggested_fix}"
                )
                messages[-1]["content"] = messages[-1]["content"] + feedback
                try:
                    with llm_task_context("generate_regenerate"):
                        llm_resp = await llm.chat(
                            messages=messages,
                            temperature=settings.llm_temperature,
                            model=model,
                        )
                    parsed = parse_llm_response(llm_resp.content)
                    decision, answer, followup, confidence = apply_answer_plan(
                        answer_plan, parsed,
                        passes_quality_gate=bool(ctx.passes_quality_gate),
                        upstream_decision=_upstream_decision,
                        risk_level=_risk_level,
                    )
                    citations = parsed.get("citations", [])
                except Exception as err:
                    logger.warning("self_critic_regenerate_failed", error=str(err))
                self_critic_regenerated = True
                ctx.generate_output.llm_resp = llm_resp
        break
    ctx.generate_output.self_critic_regenerated = self_critic_regenerated
    candidate_payload = parsed.get("candidate", {}) if isinstance(parsed.get("candidate"), dict) else {}
    candidate_payload = dict(candidate_payload)
    candidate_payload["answer_text"] = answer
    candidate_payload["citations"] = citations
    candidate_payload["confidence"] = confidence
    if not candidate_payload.get("answer_mode"):
        target_mode = str(
            (answer_plan.generation_constraints or {}).get("target_answer_mode") or ""
        ).strip().upper()
        if target_mode not in {"PASS_EXACT", "PASS_PARTIAL", "ASK_USER"}:
            target_mode = "ASK_USER" if decision == "ASK_USER" else "PASS_EXACT"
        candidate_payload["answer_mode"] = target_mode
    ctx.generate_output.answer_candidate = candidate_payload

    _pipeline_log(
        "generate",
        "done",
        confidence=confidence,
        self_critic_regenerated=self_critic_regenerated,
        trace_id=ctx.trace_id,
    )
    ctx.generate_output.generated_decision = decision

    return GenerateResult(
        answer=answer,
        citations=citations,
        followup=followup,
        confidence=confidence,
        answer_plan=answer_plan,
        generated_decision=decision,
    )
