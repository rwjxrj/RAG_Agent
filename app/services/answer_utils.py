"""Answer generation utilities: formatting, candidate parsing, retrieval query resolution."""

import json
import re
from typing import Any

from app.core.logging import get_logger
from app.search.base import EvidenceChunk
from app.services.evidence_quality import QualityReport
from app.services.normalization import (
    normalize_answer_mode as _sanitize_answer_mode,
    normalize_support_level as _sanitize_support_level,
    to_str_list as _to_str_list,
)
from app.services.schemas import AnswerPlan, DecisionResult, QuerySpec

logger = get_logger(__name__)

# Fallback: remove chunk citations leaked into answer text. Primary fix is prompt.
_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_PARTIAL_DEFAULT_DISCLAIMER = "That's the best we have from our docs."
_PARTIAL_DISCLAIMER_MARKERS = (
    "closest related",
    "closest official",
    "closest",
    "best available information",
    "best we have",
    "not confirmed",
    "not verified",
    "unverified",
    "could not verify",
    "we don't have that",
    "couldn't find",
    "don't have that",
)
_ADVICE_FACT_LIKE_PATTERN = re.compile(
    r"https?://|\$[\d,]+(?:\.\d+)?|\b\d+%|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    re.IGNORECASE,
)
_ADVICE_ENTITY_TOKEN_PATTERN = re.compile(r"\b[A-Z][A-Z0-9-]{2,}\b")
_DEFAULT_ADVICE_LABEL = "My recommendation:"
_ALLOWED_ANSWER_MODES = {"PASS_EXACT", "PASS_PARTIAL", "ASK_USER"}


def _sanitize_raw_citations(answer: str) -> str:
    """Remove raw chunk citations from answer text. Citations belong in citations array only."""
    if not answer or not answer.strip():
        return answer
    result: list[str] = []
    last_end = 0
    for m in _UUID_PATTERN.finditer(answer):
        seg_start = -1
        for needle in ("(Chunks ", "(Chunk ", "["):
            i = answer.rfind(needle, 0, m.start())
            if i != -1 and (seg_start < 0 or i > seg_start):
                seg_start = i
        if seg_start < 0:
            i = answer.rfind("(", 0, m.start())
            if i != -1:
                seg_start = i
        if seg_start < 0:
            i = answer.rfind(" Chunk ", 0, m.start())
            if i != -1:
                seg_start = i + 1
        seg_end = len(answer)
        for needle in (")", "]"):
            i = answer.find(needle, m.end())
            if i != -1:
                seg_end = min(seg_end, i + 1)
        if seg_start >= 0:
            result.append(answer[last_end:seg_start])
            last_end = seg_end
        else:
            result.append(answer[last_end:m.start()])
            last_end = m.end()
    result.append(answer[last_end:])
    cleaned = "".join(result)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    return default


def _to_citations(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        row: dict[str, str] = {}
        for key in ("chunk_id", "source_url", "doc_type"):
            v = str(item.get(key, "")).strip()
            if v:
                row[key] = v
        if row:
            out.append(row)
    return out


def _ensure_partial_disclaimer_text(
    answer: str,
    *,
    disclaimers: list[str] | None = None,
) -> str:
    text = (answer or "").strip()
    lower_answer = text.lower()
    if disclaimers:
        disclaimer_text = " ".join(_to_str_list(disclaimers, limit=2)).strip()
        if disclaimer_text and disclaimer_text.lower() not in lower_answer:
            return f"{text.rstrip()}\n\n{disclaimer_text}"
        return text
    if any(marker in lower_answer for marker in _PARTIAL_DISCLAIMER_MARKERS):
        return text
    return f"{text.rstrip()}\n\n{_PARTIAL_DEFAULT_DISCLAIMER}".strip()


def _normalize_candidate_payload(parsed: dict[str, Any]) -> dict[str, Any]:
    candidate_src = parsed.get("candidate") if isinstance(parsed.get("candidate"), dict) else {}
    advice_src = candidate_src.get("advice") if isinstance(candidate_src.get("advice"), dict) else {}
    decision = str(parsed.get("decision", "")).strip().upper()
    mode_from_decision = "ASK_USER" if decision == "ASK_USER" else "PASS_EXACT"
    answer_mode = _sanitize_answer_mode(
        candidate_src.get("answer_mode") or parsed.get("answer_mode"),
        default=mode_from_decision,
    )

    answer_text = str(candidate_src.get("answer_text") or parsed.get("answer") or "").strip()
    followup_questions = _to_str_list(
        candidate_src.get("followup_questions")
        if isinstance(candidate_src.get("followup_questions"), list)
        else parsed.get("followup_questions"),
        limit=3,
    )
    citations = _to_citations(
        candidate_src.get("citations")
        if isinstance(candidate_src.get("citations"), list)
        else parsed.get("citations"),
    )
    advice_text = str(
        advice_src.get("text")
        or candidate_src.get("advice_text")
        or ""
    ).strip()
    advice_basis = _to_str_list(
        advice_src.get("basis")
        if isinstance(advice_src.get("basis"), list)
        else candidate_src.get("advice_basis"),
        limit=4,
    )
    try:
        advice_confidence = float(
            advice_src.get("confidence", candidate_src.get("advice_confidence", 0.0))
        )
    except (TypeError, ValueError):
        advice_confidence = 0.0
    advice_confidence = max(0.0, min(1.0, advice_confidence))
    advice_enabled = _as_bool(
        advice_src.get("enabled")
        if "enabled" in advice_src
        else candidate_src.get("advice_enabled"),
        bool(advice_text),
    )

    try:
        confidence = float(candidate_src.get("confidence", parsed.get("confidence", 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    candidate = {
        "answer_type": str(
            candidate_src.get("answer_type")
            or parsed.get("answer_type")
            or "general"
        ).strip()
        or "general",
        "target_entity": (
            str(candidate_src.get("target_entity") or parsed.get("target_entity") or "").strip()
            or None
        ),
        "answer_expectation": str(
            candidate_src.get("answer_expectation")
            or parsed.get("answer_expectation")
            or "best_effort"
        ).strip()
        or "best_effort",
        "acceptable_related_types": _to_str_list(
            candidate_src.get("acceptable_related_types")
            if isinstance(candidate_src.get("acceptable_related_types"), list)
            else parsed.get("acceptable_related_types"),
            limit=6,
        ),
        "answer_mode": answer_mode,
        "support_level": _sanitize_support_level(
            candidate_src.get("support_level") or parsed.get("support_level"),
            default="partial" if answer_mode == "PASS_PARTIAL" else "strong",
        ),
        "answer_text": answer_text,
        "citations": citations,
        "confidence": confidence,
        "followup_questions": followup_questions,
        "disclaimers": _to_str_list(
            candidate_src.get("disclaimers")
            if isinstance(candidate_src.get("disclaimers"), list)
            else parsed.get("disclaimers"),
            limit=3,
        ),
        "advice_enabled": advice_enabled,
        "advice_text": advice_text,
        "advice_basis": advice_basis,
        "advice_confidence": advice_confidence,
        "metadata": (
            dict(candidate_src.get("metadata"))
            if isinstance(candidate_src.get("metadata"), dict)
            else {}
        ),
    }
    return candidate


def _normalize_parsed_payload(parsed: dict[str, Any]) -> dict[str, Any]:
    candidate = _normalize_candidate_payload(parsed)
    decision = str(parsed.get("decision", "")).strip().upper()
    if decision not in {"PASS", "ASK_USER", "ESCALATE"}:
        decision = "ASK_USER" if candidate["answer_mode"] == "ASK_USER" else "PASS"

    normalized = dict(parsed)
    normalized["candidate"] = candidate
    normalized["answer_type"] = candidate["answer_type"]
    normalized["target_entity"] = candidate["target_entity"]
    normalized["answer_mode"] = candidate["answer_mode"]
    normalized["support_level"] = candidate["support_level"]
    normalized["answer"] = candidate["answer_text"]
    normalized["followup_questions"] = candidate["followup_questions"]
    normalized["citations"] = candidate["citations"]
    normalized["confidence"] = candidate["confidence"]
    normalized["decision"] = decision
    return normalized


def format_evidence_for_prompt(
    evidence: list[EvidenceChunk],
    max_chars_per_chunk: int = 1200,
) -> str:
    """Format evidence for LLM prompt. Truncates each chunk to stay within context limits."""
    parts = []
    for e in evidence:
        text = (e.full_text or e.snippet) or ""
        if len(text) > max_chars_per_chunk:
            text = text[:max_chars_per_chunk] + "..."
        parts.append(
            f"[Chunk {e.chunk_id}]\n"
            f"Source: {e.source_url}\n"
            f"Type: {e.doc_type}\n"
            f"Content: {text}\n"
        )
    return "\n---\n".join(parts)


def parse_llm_response(content: str) -> dict[str, Any]:
    """Parse LLM JSON response into legacy fields + normalized candidate."""
    text = content.strip()
    if "```json" in text:
        match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
        if match:
            text = match.group(1)
    elif "```" in text:
        match = re.search(r"```\s*([\s\S]*?)\s*```", text)
        if match:
            text = match.group(1)

    try:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("LLM output must be a JSON object")
        return _normalize_parsed_payload(payload)
    except Exception as exc:
        logger.warning("llm_json_parse_failed", error=str(exc), content_preview=text[:200])
        fallback = {
            "decision": "ASK_USER",
            "answer": text[:500] if text else "",
            "followup_questions": ["Could you provide more details about your question?"],
            "citations": [],
            "confidence": 0.0,
            "answer_mode": "ASK_USER",
        }
        return _normalize_parsed_payload(fallback)


def _resolve_target_answer_mode(
    decision_router: DecisionResult | None,
    query_spec: QuerySpec | None,
) -> str:
    lane = (decision_router.resolved_lane() if decision_router else "").upper()
    if lane in {"PASS_WEAK", "PASS_PARTIAL"}:
        return "PASS_PARTIAL"
    if lane in {"PASS_STRONG", "PASS_EXACT"}:
        return "PASS_EXACT"
    if decision_router and decision_router.answer_policy == "bounded":
        return "PASS_PARTIAL"
    if decision_router and decision_router.decision == "ASK_USER":
        return "ASK_USER"
    if query_spec:
        raw_mode = query_spec.answer_contract.answer_mode.strip()
        if raw_mode:
            explicit = _sanitize_answer_mode(raw_mode)
            if explicit in _ALLOWED_ANSWER_MODES:
                return explicit
    return "PASS_EXACT"


def _should_allow_advice_block(
    query_spec: QuerySpec | None,
    *,
    target_mode: str,
) -> bool:
    if not query_spec:
        return False
    if target_mode == "ASK_USER":
        return False
    if query_spec.query_intent.risk_level.strip().lower() == "high":
        return False

    answer_type = query_spec.answer_contract.answer_type.strip().lower()
    if answer_type in {"policy", "direct_link", "clarification", "account"}:
        return False

    answer_shape = query_spec.answer_contract.answer_shape.strip().lower()
    if answer_shape in {"recommendation", "comparison"}:
        return True

    return bool(query_spec.clarification_needs.assistant_should_lead)


def build_answer_plan(
    decision_router: DecisionResult | None,
    query_spec: QuerySpec | None,
    quality_report: QualityReport | None,
) -> AnswerPlan:
    """Build a mode-calibrated AnswerPlan for candidate generation."""
    if query_spec and getattr(query_spec, "skip_retrieval", False):
        return AnswerPlan(
            lane="CANDIDATE_VERIFY",
            allowed_claim_scope="full",
            must_include=[
                "Return a friendly, concise greeting candidate (no evidence claims).",
            ],
            must_avoid=[],
            required_citations=[],
            output_blocks=["answer_candidate_json"],
            tone_policy="friendly",
            generation_constraints={
                "confidence_cap": 1.0,
                "target_answer_mode": "PASS_EXACT",
                "target_answer_type": "general",
                "target_entity": None,
            },
        )

    target_mode = _resolve_target_answer_mode(decision_router, query_spec)
    allow_advice_block = _should_allow_advice_block(query_spec, target_mode=target_mode)
    lane = decision_router.resolved_lane() if decision_router else "CANDIDATE_VERIFY"
    if lane in {"PASS_STRONG", "PASS_WEAK", "PASS_PARTIAL", "PASS_EXACT"}:
        lane = "CANDIDATE_VERIFY"
    if lane not in {"CANDIDATE_VERIFY", "TARGETED_RETRY", "ASK_USER", "ESCALATE"}:
        lane = "CANDIDATE_VERIFY"

    target_answer_type = (
        query_spec.answer_contract.answer_type.strip() or "general"
        if query_spec
        else "general"
    )
    target_entity = query_spec.query_intent.target_entity if query_spec else None
    required_for_exact = list(
        dict.fromkeys(
            query_spec.retrieval_hints.required_evidence
            if query_spec and query_spec.retrieval_hints.required_evidence
            else []
        )
    )
    required_for_partial = list(
        dict.fromkeys(
            (query_spec.retrieval_hints.hard_requirements or [])
            if query_spec and query_spec.retrieval_hints.hard_requirements
            else []
        )
    )

    if target_mode == "PASS_PARTIAL":
        missing_signals = quality_report.missing_signals[:3] if quality_report else []
        must_include = [
            "Return AnswerCandidate JSON only (no prose outside JSON).",
            "Use answer_mode=PASS_PARTIAL and keep claims bounded to supported evidence.",
            "Use natural, client-friendly language. When info is missing, say briefly (e.g. 'We don't have that' or 'I couldn't find that')—do not list long disclaimers.",
            "Add one short disclaimer in candidate.disclaimers if needed.",
        ]
        if missing_signals:
            must_include.append("Missing areas (do not list in answer—just say we don't have that if needed): " + ", ".join(missing_signals) + ".")
        if allow_advice_block:
            must_include.append(
                "Keep candidate.answer_text grounded in evidence. You may add candidate.advice only to suggest a default option or next step."
            )
        return AnswerPlan(
            lane="CANDIDATE_VERIFY",
            allowed_claim_scope="partial",
            must_include=must_include,
            must_avoid=[
                "Do not invent missing pricing, links, policy clauses, or setup steps.",
                "Do not present assumptions as confirmed facts.",
                "Do not use long legal-style disclaimers or lists of what is not provided.",
                "Do not put uncited facts, prices, links, or policy claims inside candidate.advice.",
            ],
            required_citations=required_for_partial,
            output_blocks=["answer_candidate_json"],
            tone_policy="cautious",
            generation_constraints={
                "confidence_cap": 0.6,
                "target_answer_mode": "PASS_PARTIAL",
                "target_answer_type": target_answer_type,
                "target_entity": target_entity,
                "max_followup_questions": 1,
                "default_followup_questions": (
                    (decision_router.clarifying_questions or [])[:1]
                    if decision_router
                    else []
                ),
                "bounded_suffix": "That's the best we have from our docs.",
                "allow_advice_block": allow_advice_block,
                "advice_label": _DEFAULT_ADVICE_LABEL,
                "max_advice_sentences": 2,
            },
        )

    if target_mode == "ASK_USER":
        return AnswerPlan(
            lane="CANDIDATE_VERIFY",
            allowed_claim_scope="none",
            must_include=[
                "Return AnswerCandidate JSON only.",
                "Use answer_mode=ASK_USER and provide one concise followup question.",
            ],
            must_avoid=["Do not fabricate details."],
            required_citations=[],
            output_blocks=["answer_candidate_json"],
            tone_policy="concise",
            generation_constraints={
                "confidence_cap": 0.3,
                "target_answer_mode": "ASK_USER",
                "target_answer_type": target_answer_type,
                "target_entity": target_entity,
                "max_followup_questions": 1,
            },
        )

    return AnswerPlan(
        lane="CANDIDATE_VERIFY",
        allowed_claim_scope="full",
        must_include=[
            "Return AnswerCandidate JSON only (no prose outside JSON).",
            "Use answer_mode=PASS_EXACT.",
            "Answer directly using only provided evidence.",
            "Cite each key claim with the provided chunks only.",
        ],
        must_avoid=[
            "Do not add facts that are not in the evidence.",
        ],
        required_citations=required_for_exact,
        output_blocks=["answer_candidate_json"],
        tone_policy="concise",
        generation_constraints={
            "confidence_cap": 0.9,
            "target_answer_mode": "PASS_EXACT",
            "target_answer_type": target_answer_type,
            "target_entity": target_entity,
            "max_followup_questions": 1,
            "allow_advice_block": allow_advice_block,
            "advice_label": _DEFAULT_ADVICE_LABEL,
            "max_advice_sentences": 2,
        },
    )


def _detect_query_language(query_text: str | None) -> str:
    """Detect language directly from query text using character ranges.

    Returns ISO 639-1 code: 'zh', 'ja', 'ko', or 'en'.
    More reliable than trusting upstream source_lang which can be misdetected.
    """
    text = (query_text or "").strip()
    if not text:
        return "en"

    zh_count = 0
    ja_count = 0  # Hiragana/Katakana
    ko_count = 0  # Hangul
    for ch in text:
        cp = ord(ch)
        # CJK Unified Ideographs (shared by zh/ja)
        if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:
            zh_count += 1
        # Japanese Hiragana/Katakana
        elif 0x3040 <= cp <= 0x309F or 0x30A0 <= cp <= 0x30FF:
            ja_count += 1
        # Korean Hangul
        elif 0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF:
            ko_count += 1

    # If Hiragana/Katakana present → Japanese
    if ja_count > 0:
        return "ja"
    # If Hangul present → Korean
    if ko_count > 0:
        return "ko"
    # If CJK characters present and no Japanese/Korean markers → Chinese
    if zh_count > 0:
        return "zh"
    return "en"


def _build_language_instruction(detected_lang: str) -> str:
    """Build deterministic language instruction for prompt.

    Returns a single, unambiguous language instruction to avoid conflicting
    directives when upstream source_lang is misdetected.
    """
    normalized_lang = (detected_lang or "en").strip().lower().replace("_", "-").split("-", 1)[0]
    lang_map = {
        "zh": "Chinese (中文)",
        "ja": "Japanese (日本語)",
        "ko": "Korean (한국어)",
        "en": "English",
    }
    target = lang_map.get(normalized_lang, "English")
    return f"LANGUAGE: You MUST respond entirely in {target}. Match the language of the user's question."


def format_answer_plan_instruction(
    answer_plan: AnswerPlan,
    quality_report: QualityReport | None,
    source_lang: str = "en",
    query_text: str = "",
) -> str:
    """Convert AnswerPlan into prompt instructions for AnswerCandidate JSON.

    Args:
        source_lang: Upstream detected language (may be incorrect).
        query_text: Original user query for direct language detection fallback.
    """
    constraints = answer_plan.generation_constraints or {}
    target_mode = _sanitize_answer_mode(
        constraints.get("target_answer_mode"),
        default="PASS_EXACT",
    )
    allow_advice_block = bool(constraints.get("allow_advice_block"))
    target_answer_type = str(constraints.get("target_answer_type", "general")).strip() or "general"
    target_entity = constraints.get("target_entity")

    # Detect language from query text directly; fall back to source_lang only
    # when query text is empty (e.g., in unit tests).
    detected_lang = _detect_query_language(query_text) if query_text else source_lang

    lines = [
        "ROUTING DECISION: CANDIDATE_VERIFY.",
        "Generate structured AnswerCandidate JSON in this pass. Do not output free-form prose.",
        _build_language_instruction(detected_lang),
        "Return JSON only with this schema:",
        "{",
        '  "candidate": {',
        f'    "answer_type": "{target_answer_type}",',
        f'    "target_entity": {json.dumps(target_entity)},',
        '    "answer_expectation": "exact|best_effort|clarify_first",',
        '    "acceptable_related_types": [],',
        f'    "answer_mode": "{target_mode}",',
        '    "support_level": "strong|partial|weak",',
        '    "answer_text": "final answer text or clarification request",',
        '    "citations": [{"chunk_id": "...", "source_url": "...", "doc_type": "..."}],',
        '    "confidence": 0.0,',
        '    "followup_questions": [],',
        '    "disclaimers": [],',
        (
            '    "advice": {"enabled": false, "text": "", "basis": [], "confidence": 0.0},'
            if allow_advice_block
            else '    "metadata": {}'
        ),
        '    "metadata": {}' if allow_advice_block else None,
        "  }",
        "}",
    ]
    lines = [line for line in lines if line is not None]

    if target_mode == "PASS_PARTIAL":
        lines.extend(
            [
                "For PASS_PARTIAL: keep only supported facts. Use natural, conversational tone.",
                "For PASS_PARTIAL: when info is unclear or missing, say briefly (e.g. 'We don't have that' or 'I couldn't find that')—no long disclaimers or lists of missing items.",
                "For PASS_PARTIAL: at most one short disclaimer in candidate.disclaimers; at most one followup question.",
            ]
        )
    elif target_mode == "ASK_USER":
        lines.extend(
            [
                "For ASK_USER: keep answer_text concise and provide one clarifying question.",
                "For ASK_USER: citations may be empty when no grounded answer is available.",
            ]
        )
    else:
        lines.extend(
            [
                "For PASS_EXACT: provide direct grounded answer and complete citations for key claims.",
                "For PASS_EXACT: do not include hedging disclaimers unless evidence is explicitly partial.",
            ]
        )

    if allow_advice_block:
        lines.extend(
            [
                "Use candidate.answer_text and candidate.citations as the grounded answer.",
                "candidate.advice is optional. Use it only when the user wants a recommendation, comparison, or a sensible default next step.",
                "candidate.advice must not add new facts, numbers, prices, links, policy claims, or setup steps that are not already supported in the evidence.",
                "Keep candidate.advice short (max 2 sentences). If it is not useful, set enabled=false and leave text empty.",
            ]
        )

    if quality_report and quality_report.missing_signals:
        lines.append(
            "Known missing (context only; do not list in answer—say briefly we don't have that): "
            + ", ".join(quality_report.missing_signals[:3]) + "."
        )

    return "\n".join(lines)


def apply_answer_plan(
    answer_plan: AnswerPlan,
    parsed: dict[str, Any],
    *,
    passes_quality_gate: bool = False,
    upstream_decision: str = "",
    risk_level: str = "low",
) -> tuple[str, str, list[str], float]:
    """Apply answer-mode calibration after parsing the LLM response.

    Args:
        passes_quality_gate: Whether the quality gate passed for this query.
        upstream_decision: Decision from the router (PASS, ASK_USER, ESCALATE).
        risk_level: Risk level from QuerySpec ('low', 'medium', 'high').
    """
    constraints = answer_plan.generation_constraints or {}
    target_mode = _sanitize_answer_mode(
        constraints.get("target_answer_mode"),
        default="PASS_EXACT",
    )
    parsed = _normalize_parsed_payload(parsed)
    candidate = parsed.get("candidate", {}) if isinstance(parsed.get("candidate"), dict) else {}

    candidate_mode = _sanitize_answer_mode(
        candidate.get("answer_mode"),
        default=target_mode,
    )
    answer = _sanitize_raw_citations(str(candidate.get("answer_text") or parsed.get("answer") or ""))
    if target_mode == "PASS_PARTIAL":
        if candidate_mode == "ASK_USER" and answer.strip():
            candidate_mode = "PASS_PARTIAL"
        elif candidate_mode != "ASK_USER":
            candidate_mode = "PASS_PARTIAL"
    if target_mode == "ASK_USER":
        candidate_mode = "ASK_USER"

    followup = _to_str_list(candidate.get("followup_questions"), limit=3)
    if not followup:
        followup = _to_str_list(parsed.get("followup_questions"), limit=3)

    try:
        confidence = float(candidate.get("confidence", parsed.get("confidence", 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    confidence_cap = constraints.get("confidence_cap")
    if isinstance(confidence_cap, (int, float)):
        confidence = min(confidence, float(confidence_cap))

    decision = str(parsed.get("decision", "")).strip().upper()
    if decision not in {"PASS", "ASK_USER", "ESCALATE"}:
        decision = "ASK_USER" if candidate_mode == "ASK_USER" else "PASS"
    if candidate_mode == "ASK_USER":
        decision = "ASK_USER"
    elif decision == "ESCALATE":
        # Only override ESCALATE to PASS when ALL conditions hold:
        # 1. Quality gate passed (evidence is sufficient)
        # 2. Risk level is not high (no safety concern)
        # 3. Upstream router did not itself ESCALATE (e.g., high_risk_insufficient)
        can_override_escalate = (
            passes_quality_gate
            and risk_level.lower() != "high"
            and upstream_decision not in {"ESCALATE", ""}
        )
        if can_override_escalate and target_mode in {"PASS_EXACT", "PASS_PARTIAL"}:
            decision = "PASS"
            logger.info(
                "generate_escalate_overridden",
                target_mode=target_mode,
                risk_level=risk_level,
                upstream_decision=upstream_decision,
                passes_quality_gate=passes_quality_gate,
                reason="low_risk_gate_pass",
            )
        else:
            logger.info(
                "generate_escalate_preserved",
                target_mode=target_mode,
                risk_level=risk_level,
                upstream_decision=upstream_decision,
                passes_quality_gate=passes_quality_gate,
            )
    else:
        decision = "PASS"

    if candidate_mode == "PASS_PARTIAL" and answer.strip():
        max_followup = constraints.get("max_followup_questions", 1)
        if isinstance(max_followup, int) and max_followup >= 0:
            followup = followup[:max_followup]
        default_followup = constraints.get("default_followup_questions", [])
        if not followup and isinstance(default_followup, list):
            followup = _to_str_list(default_followup, limit=max_followup or 1)

        disclaimers = _to_str_list(candidate.get("disclaimers"), limit=2)
        bounded_suffix = str(constraints.get("bounded_suffix", "")).strip()
        lower_answer = answer.lower()
        bounded_markers = (
            "closest related",
            "closest official",
            "best available information",
            "not confirmed",
            "unverified",
            "could not verify",
        )
        if disclaimers:
            disclaimer_text = " ".join(disclaimers).strip()
            if disclaimer_text and disclaimer_text.lower() not in lower_answer:
                answer = f"{answer.rstrip()}\n\n{disclaimer_text}"
        elif (
            bounded_suffix
            and bounded_suffix.lower() not in lower_answer
            and not any(marker in lower_answer for marker in bounded_markers)
        ):
            answer = f"{answer.rstrip()}\n\n{bounded_suffix}"

    if candidate_mode == "ASK_USER" and not answer.strip():
        answer = "We need one more detail before answering. Could you clarify your request?"

    if decision == "ASK_USER":
        max_followup = constraints.get("max_followup_questions", 1)
        if isinstance(max_followup, int) and max_followup >= 0:
            followup = followup[:max_followup]

    return decision, answer, followup, confidence


def render_calibrated_candidate(
    candidate: dict[str, Any] | None,
    *,
    calibrated_lane: str | None,
    fallback_answer: str,
    fallback_followup: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Render final prose only from calibrated candidate output."""
    lane = _sanitize_answer_mode(calibrated_lane, default="PASS_EXACT")
    if lane == "ASK_USER":
        return fallback_answer, list(fallback_followup or [])

    if not isinstance(candidate, dict):
        answer = fallback_answer
        if lane == "PASS_PARTIAL":
            answer = _ensure_partial_disclaimer_text(answer)
        return answer, list(fallback_followup or [])

    answer = _sanitize_raw_citations(str(candidate.get("answer_text") or "").strip())
    if not answer:
        answer = fallback_answer

    followup = _to_str_list(candidate.get("followup_questions"), limit=3)
    if not followup:
        followup = list(fallback_followup or [])

    if lane == "PASS_PARTIAL":
        answer = _ensure_partial_disclaimer_text(
            answer,
            disclaimers=_to_str_list(candidate.get("disclaimers"), limit=2),
        )

    advice_text = _render_advice_text(
        candidate,
        grounded_answer=answer,
    )
    if advice_text:
        answer = f"{answer.rstrip()}\n\n{advice_text}"

    return answer, followup


def _render_advice_text(
    candidate: dict[str, Any],
    *,
    grounded_answer: str,
) -> str:
    if not _as_bool(candidate.get("advice_enabled"), bool(candidate.get("advice_text"))):
        return ""

    advice = str(candidate.get("advice_text") or "").strip()
    if not advice:
        return ""

    advice = re.sub(r"^(my recommendation|recommendation|suggestion)\s*:\s*", "", advice, flags=re.I)
    advice = re.sub(r"\s+", " ", advice).strip()
    if len(advice) < 12:
        return ""
    if _ADVICE_FACT_LIKE_PATTERN.search(advice):
        return ""

    entity_tokens = {
        match.group(0)
        for match in _ADVICE_ENTITY_TOKEN_PATTERN.finditer(advice)
    }
    grounded_upper = grounded_answer.upper()
    if entity_tokens and any(token not in grounded_upper for token in entity_tokens):
        return ""

    if advice.lower() in grounded_answer.lower():
        return ""

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", advice) if s.strip()]
    if len(sentences) > 2:
        advice = " ".join(sentences[:2]).strip()

    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    label = str(metadata.get("advice_label") or _DEFAULT_ADVICE_LABEL).strip() or _DEFAULT_ADVICE_LABEL
    return f"{label} {advice}"


def collect_rewrite_candidates(
    base_query: str,
    query_spec: QuerySpec | None,
) -> list[str]:
    """Compatibility wrapper. Canonical implementation lives in retrieval_planner."""
    from app.services.retrieval_planner import collect_rewrite_candidates as _collect

    return _collect(base_query, query_spec)


def resolve_retrieval_query(
    *,
    base_query: str,
    attempt: int,
    query_spec: QuerySpec | None,
    retry_strategy: Any | None,
    explicit_override: str | None = None,
) -> tuple[str, str, list[str]]:
    """Compatibility wrapper. Canonical implementation lives in retrieval_planner."""
    from app.services.retrieval_planner import resolve_retrieval_query as _resolve

    return _resolve(
        base_query=base_query,
        attempt=attempt,
        query_spec=query_spec,
        retry_strategy=retry_strategy,
        explicit_override=explicit_override,
    )
