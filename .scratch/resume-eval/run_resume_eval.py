"""
简历（Resume）指标离线评测脚本

功能：对 RAG 问答管道的检索质量和 Reviewer 拦截能力进行离线评测。
评测维度：
  1. 管道评测（Pipeline）：遍历知识库中带有标准问法的 Chunk，调用完整 RAG 管道
     （AnswerService.generate），统计 Recall@5、端到端延迟、各阶段 P95 耗时。
  2. 审查器评测（Reviewer）：对同一证据分别传入标准答复和追加无依据承诺的答复，
     验证 ReviewerGate 能否拦截幻觉回答，并统计风险拦截召回率和正常回答误拦截率。

输出：
  - JSON 文件：包含完整评测数据和汇总指标
  - Markdown 文件：汇总指标的可读报告
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

# 将项目根目录加入 Python 路径，确保后续 import 能正确找到 app 包
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def recall_at_k(expected_ids: list[str], retrieved_ids: list[str], k: int) -> float | None:
    """计算 Recall@K：期望文档在前 K 个检索结果中的召回比例。

    Args:
        expected_ids: 期望检索到的文档 ID 列表。
        retrieved_ids: 实际检索到的文档 ID 列表。
        k: 取前 k 个检索结果计算。

    Returns:
        召回率（0~1），若期望列表为空则返回 None。
    """
    expected = {str(item) for item in expected_ids if item}
    if not expected:
        return None
    actual = {str(item) for item in retrieved_ids[:k] if item}
    return len(expected & actual) / len(expected)


def hit_at_k(expected_ids: list[str], retrieved_ids: list[str], k: int) -> float | None:
    """Return whether at least one expected identifier appears in the top K."""
    expected = {str(item) for item in expected_ids if item}
    if not expected:
        return None
    actual = {str(item) for item in retrieved_ids[:k] if item}
    return 1.0 if expected & actual else 0.0


def reciprocal_rank(expected_ids: list[str], retrieved_ids: list[str]) -> float | None:
    """Return the reciprocal rank of the first expected identifier."""
    expected = {str(item) for item in expected_ids if item}
    if not expected:
        return None
    for rank, item in enumerate(retrieved_ids, start=1):
        if str(item) in expected:
            return 1.0 / rank
    return 0.0


def percentile_nearest_rank(values: list[float], percentile: float) -> float | None:
    """计算百分位数（最近序数法 / Nearest Rank）。

    Args:
        values: 数值列表。
        percentile: 百分位（0~1），例如 0.95 对应 P95。

    Returns:
        对应百分位的值，若列表为空则返回 None。
    """
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[min(rank - 1, len(ordered) - 1)]


def _enum_value(value: Any) -> str:
    """获取枚举值的实际字符串表示。

    如果 value 是枚举类型（如 ReviewerStatus.PASS），返回其 .value；
    否则直接返回 str(value)。
    """
    return str(getattr(value, "value", value))


# ---------------------------------------------------------------------------
# Issue 01: Case validity classification
# ---------------------------------------------------------------------------

_VALID_DECISIONS = {"PASS", "ASK_USER", "ESCALATE"}

_GENERIC_ERROR_PATTERNS = [
    "i'm sorry, i encountered an error",
    "i apologize, but i encountered",
    "sorry, i encountered an error",
    "an error occurred",
    "please try again or contact support",
    "please try again later",
    "系统错误",
    "暂时无法",
    "遇到问题",
    "请联系客服",
]

# Intentional human handoff answer patterns (from Agentic Router)
_HUMAN_HANDOFF_PATTERNS = [
    "human review",
    "support agent will follow",
    "转人工",
    "人工客服",
]

# Route short-circuit latency threshold (seconds): ESCALATE faster than this
# likely bypassed retrieval (Agentic Router direct handoff).
_ROUTE_SHORT_CIRCUIT_LATENCY = 1.0

# Early-output routes that bypass retrieval entirely
_EARLY_ROUTES = {"direct_response", "clarify", "human_handoff", "intent_cache_hit"}


def _extract_route_info(case: dict[str, Any]) -> dict[str, Any]:
    """Extract route information from stage_reasons and debug metadata.

    Returns dict with:
    - route: str — the primary route taken (intent_cache_hit, direct_response,
               clarify, human_handoff, rag_search, skip_retrieval, unknown)
    - retrieval_started: bool — did the pipeline reach the RETRIEVE phase?
    """
    stage_reasons = case.get("stage_reasons") or []
    if not isinstance(stage_reasons, list):
        stage_reasons = []

    route = "unknown"
    retrieval_started = False

    for entry in stage_reasons:
        if not isinstance(entry, str):
            continue
        # stage_reasons are formatted as "stage: reason"
        if entry.startswith("intent_cache:") and "hit" in entry:
            route = "intent_cache_hit"
        elif entry.startswith("agentic_route:"):
            reason_part = entry.split(":", 1)[1].strip()
            if reason_part in ("direct_response", "clarify", "human_handoff"):
                route = reason_part
            elif reason_part in ("rag_search", "fallback_to_rag"):
                route = "rag_search"
        elif entry.startswith("skip_retrieval:"):
            route = "skip_retrieval"
        elif entry.startswith("retrieve:"):
            retrieval_started = True
            if route == "unknown":
                route = "rag_search"

    # If we have retrieval stage reasons, it's definitely rag_search
    if retrieval_started and route not in _EARLY_ROUTES:
        route = "rag_search"

    return {"route": route, "retrieval_started": retrieval_started}


def _classify_case_validity(case: dict[str, Any]) -> dict[str, Any]:
    """Classify a pipeline case into harness completion, business validity and failure category.

    Returns dict with:
    - harness_completed: bool — did the script finish without a Python exception?
    - business_valid: bool — is the output a valid business result?
    - failure_category: str | None — machine-readable reason when invalid
    - retrieval_eligible: bool — should this case be in retrieval metric denominators?
    - retrieval_executed: bool — did this case actually run retrieval?
    - route: str — the primary route taken
    """
    decision = str(case.get("decision") or "").strip().upper()
    error = case.get("error")
    answer = str(case.get("answer") or "").strip()
    termination = case.get("termination_reason")
    latency = float(case.get("latency_seconds") or 0)

    # 1. Harness completion
    harness_completed = decision != "ERROR" and error is None

    # 2. Business validity
    business_valid = True
    failure_category = None

    if not harness_completed:
        business_valid = False
        failure_category = "harness_error"
    elif decision not in _VALID_DECISIONS:
        business_valid = False
        failure_category = "unrecognized_decision"
    elif not answer:
        business_valid = False
        failure_category = "empty_answer"
    elif decision == "ESCALATE" and termination is None:
        # ESCALATE without normal termination = generation failure wrapped as escalation.
        # Check this BEFORE generic error patterns because the answer text is also generic.
        business_valid = False
        failure_category = "generation_failure"
    elif any(pat in answer.lower() for pat in _GENERIC_ERROR_PATTERNS):
        # Generic error answer — but check if it's an intentional human handoff first
        is_handoff = any(pat in answer.lower() for pat in _HUMAN_HANDOFF_PATTERNS)
        if is_handoff and decision == "ESCALATE" and termination == "escalate":
            business_valid = True
        else:
            business_valid = False
            failure_category = "generic_error_answer"
    elif termination is None:
        business_valid = False
        failure_category = "missing_termination"

    # 3. Route and retrieval eligibility
    route_info = _extract_route_info(case)
    route = route_info["route"]
    retrieval_started = route_info["retrieval_started"]

    # retrieval_eligible: based on EXPECTED behavior (does this case need retrieval?).
    # - Invalid cases: never eligible.
    # - Early routes (human_handoff, direct_response, clarify, intent_cache_hit)
    #   and skip_retrieval: NOT eligible, UNLESS the case has non-empty
    #   expected_source_urls (which means it SHOULD have been retrieved —
    #   exposing a routing error).
    # - RAG route: eligible.
    # - Unknown route with no expected_source_urls: eligible by default (legacy).
    if not business_valid:
        retrieval_eligible = False
        retrieval_executed = False
    else:
        expected_urls = case.get("expected_source_urls")
        has_expected_urls = isinstance(expected_urls, list) and len(expected_urls) > 0
        is_early_route = route in _EARLY_ROUTES or route == "skip_retrieval"

        if is_early_route and not has_expected_urls:
            # Correctly short-circuited — not retrieval-eligible
            retrieval_eligible = False
        elif is_early_route and has_expected_urls:
            # MIS-ROUTED: case expected retrieval but was short-circuited.
            # Mark eligible so the mismatch appears in metrics.
            retrieval_eligible = True
        elif expected_urls is not None and not has_expected_urls:
            # Explicitly non-retrieval case (empty expected_source_urls)
            retrieval_eligible = False
        else:
            retrieval_eligible = True

        # retrieval_executed: based on ACTUAL route
        retrieval_executed = retrieval_started and not is_early_route

    return {
        "harness_completed": harness_completed,
        "business_valid": business_valid,
        "failure_category": failure_category,
        "retrieval_eligible": retrieval_eligible,
        "retrieval_executed": retrieval_executed,
        "route": route,
    }


def _parse_entry(text: str) -> tuple[str, str] | None:
    """解析 Chunk 文本中的标准评测条目。

    目标格式（识别自中文关键字）：
        用户问法：[问题描述] 标准答复：[标准答案] 检索关键词：[...]

    由于字段之间以"用户问法""标准答复""检索关键词"等关键字分隔，
    无需关心具体的分隔符样式。

    Args:
        text: Chunk 的文本内容。

    Returns:
          (question, standard_answer) 元组，若解析失败则返回 None。
    """
    match = re.search(
        r"用户问法[:：]\s*(.*?)\s*标准答复[:：]\s*(.*?)\s*检索关键词[:：]",
        text or "",
        re.DOTALL,
    )
    if not match:
        return None
    question = re.sub(r"\s+", " ", match.group(1)).strip()
    answer = re.sub(r"\s+", " ", match.group(2)).strip()
    if not question or not answer:
        return None
    return question, answer


def is_eval_document_title(title: str) -> bool:
    """判断文档标题是否为有效的评测文档。

    约定：以 "00_" 开头的文档（如 "00_说明"、"00_模板"）为元数据文档，
    不包含实际评测数据，应排除。

    Args:
        title: 文档的标题。

    Returns:
        若标题不以 "00_" 开头则返回 True（表示是有效的评测文档）。
    """
    return not str(title or "").strip().startswith("00_")


def load_eval_cases_json(path: str | Path, limit: int) -> list[dict[str, Any]]:
    """Load and validate an external, non-ingested retrieval evaluation dataset."""
    dataset_path = Path(path)
    try:
        payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid evaluation dataset {dataset_path}: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("version") != "1.0":
        raise ValueError("Evaluation dataset version must be '1.0'")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("Evaluation dataset cases must be a non-empty list")

    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    allowed_difficulties = {"easy", "medium", "hard"}
    for index, raw_case in enumerate(raw_cases, start=1):
        if not isinstance(raw_case, dict):
            raise ValueError(f"Case #{index} must be an object")
        case_id = str(raw_case.get("id") or "").strip()
        if not case_id:
            raise ValueError(f"Case #{index} id must be a non-empty string")
        if case_id in seen_ids:
            raise ValueError(f"Case {case_id} id must be unique")
        seen_ids.add(case_id)

        question = str(raw_case.get("question") or "").strip()
        if not question:
            raise ValueError(f"Case {case_id} question must be a non-empty string")
        expected_urls = raw_case.get("expected_source_urls")
        if (
            not isinstance(expected_urls, list)
            or not expected_urls
            or any(not isinstance(url, str) or not url.strip() for url in expected_urls)
        ):
            raise ValueError(f"Case {case_id} expected_source_urls must be a non-empty string list")
        tags = raw_case.get("tags", [])
        if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag.strip() for tag in tags):
            raise ValueError(f"Case {case_id} tags must be a string list")
        difficulty = str(raw_case.get("difficulty") or "").strip()
        if difficulty not in allowed_difficulties:
            raise ValueError(f"Case {case_id} difficulty must be easy, medium, or hard")

        cases.append(
            {
                "name": case_id,
                "question": question,
                "expected_source_urls": list(dict.fromkeys(url.strip() for url in expected_urls)),
                "standard_answer": str(raw_case.get("standard_answer") or "").strip(),
                "tags": list(dict.fromkeys(tag.strip() for tag in tags)),
                "difficulty": difficulty,
            }
        )
        if len(cases) >= limit:
            break
    return cases


async def _load_cases(limit: int) -> list[dict[str, Any]]:
    """从数据库加载评测样例。

    筛选条件：
        1. Chunk 的 checksum 全局唯一（仅有一个 Chunk 引用该 checksum），
           确保评测结果不受重复数据干扰。
        2. Chunk 文本包含关键字"用户问法"（即含有标准评测条目）。
        3. 文档标题不以 "00_" 开头。

    Args:
        limit: 最大加载条数。

    Returns:
        包含 question、standard_answer、chunk_id、title、source_url、doc_type 的字典列表。
    """
    from sqlalchemy import func, select

    from app.db.models import Chunk, Document
    from app.db.session import async_session_factory

    # 子查询：筛选出 checksum 唯一的 Chunk（即该 checksum 仅被一个 Chunk 引用）
    unique_checksums = (
        select(Chunk.checksum.label("checksum"))
        .group_by(Chunk.checksum)
        .having(func.count(Chunk.id) == 1)
        .subquery()
    )
    stmt = (
        select(
            Chunk.id,
            Chunk.chunk_text,
            Document.title,
            Document.source_url,
            Document.doc_type,
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.checksum.in_(select(unique_checksums.c.checksum)))
        .where(Chunk.chunk_text.contains("用户问法"))
        .order_by(Document.title, Chunk.chunk_index)
    )
    async with async_session_factory() as session:
        rows = (await session.execute(stmt)).all()

    cases: list[dict[str, Any]] = []
    for chunk_id, chunk_text, title, source_url, doc_type in rows:
        if not is_eval_document_title(title):
            continue
        parsed = _parse_entry(chunk_text)
        if parsed is None:
            continue
        question, standard_answer = parsed
        cases.append(
            {
                "chunk_id": str(chunk_id),
                "chunk_text": chunk_text,
                "title": title,
                "source_url": source_url,
                "doc_type": doc_type,
                "question": question,
                "standard_answer": standard_answer,
            }
        )
        if len(cases) >= limit:
            break
    return cases


async def initialize_runtime() -> None:
    """初始化系统运行时缓存。

    预加载全局配置缓存（品牌信息、文档类型、LLM、嵌入模型、重排序模型、架构配置），
    确保后续评测时所有配置已就绪，避免冷启动影响首次请求的延迟统计。
    """
    from app.db.session import async_session_factory
    from app.services.archi_config import refresh_cache as refresh_archi_config
    from app.services.branding_config import refresh_cache as refresh_branding_config
    from app.services.doc_type_service import refresh_doc_type_cache
    from app.services.embedding_config import refresh_cache as refresh_embedding_config
    from app.services.llm_config import refresh_cache as refresh_llm_config
    from app.services.reranker_config import refresh_cache as refresh_reranker_config

    async with async_session_factory() as session:
        await refresh_branding_config(session)
        await refresh_doc_type_cache(session)
        await refresh_llm_config(session)
        await refresh_embedding_config(session)
        await refresh_reranker_config(session)
        await refresh_archi_config(session)


def override_embedding_base_url(base_url: str | None) -> None:
    """临时覆盖 Embedding 服务的 Base URL。

    允许在评测时指定不同的 Embedding 服务地址，用于对比不同模型的服务效果。

    Args:
        base_url: Embedding 服务的基础 URL。若为 None 或不传则不做覆盖。
    """
    if not base_url:
        return
    from app.services import embedding_config

    embedding_config._cache["embedding_base_url"] = base_url.rstrip("/")


def enable_llm_call_capture(enabled: bool) -> None:
    """Force LLM call capture for this evaluation process after DB cache refresh."""
    if not enabled:
        return
    from app.services import archi_config

    archi_config._cache["debug_llm_calls"] = True


async def _run_pipeline_cases(
    cases: list[dict[str, Any]],
    case_timeout: float,
    case_delay: float = 0.0,
) -> list[dict[str, Any]]:
    """遍历评测样例，对每一条运行完整的 RAG 管道。

    调用 AnswerService.generate 处理用户问题，并采集以下指标：
        - Recall@5：期望 Chunk 是否在检索结果前 5 条中
        - 端到端延迟（秒）
        - 各阶段耗时（如 query_extract、retrieve、rerank 等）
        - 管道最终决策（PASS / ASK_USER 等）

    Args:
        cases: 评测样例列表。
        case_timeout: 单条样例的超时时间（秒）。

    Returns:
        每个样例的评测结果字典列表。
    """
    from app.services.answer_service import AnswerService

    service = AnswerService()
    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        started = time.perf_counter()
        try:
            output = await asyncio.wait_for(
                service.generate(
                    query=case["question"],
                    trace_id=f"resume-eval-{index:03d}",
                ),
                timeout=case_timeout,
            )
            elapsed = time.perf_counter() - started
            debug = output.debug if isinstance(output.debug, dict) else {}
            evidence = debug.get("evidence_summary") or []
            # Keep both legacy chunk IDs and stable source URLs for leak-free datasets.
            ranked_chunk_ids = [
                str(row.get("chunk_id"))
                for row in evidence
                if isinstance(row, dict) and row.get("chunk_id")
            ]
            ranked_source_urls = [
                str(row.get("source_url"))
                for row in evidence
                if isinstance(row, dict) and row.get("source_url")
            ]
            top5_ids = ranked_chunk_ids[:5]
            top5_source_urls = ranked_source_urls[:5]
            expected_source_urls = list(case.get("expected_source_urls") or [])
            expected_chunk_ids = [str(case["chunk_id"])] if case.get("chunk_id") else []
            expected_items = expected_source_urls or expected_chunk_ids
            ranked_items = ranked_source_urls if expected_source_urls else ranked_chunk_ids
            first_reciprocal_rank = reciprocal_rank(expected_items, ranked_items)
            timings = debug.get("timings") if isinstance(debug.get("timings"), dict) else {}
            raw_llm_calls = debug.get("llm_call_log")
            llm_calls = raw_llm_calls if isinstance(raw_llm_calls, list) else []
            total_latency = float(timings.get("total") or elapsed)
            results.append(
                {
                    "name": case.get("name") or case.get("title") or f"case-{index:03d}",
                    "question": case["question"],
                    "expected_chunk_id": case.get("chunk_id"),
                    "expected_source_urls": expected_source_urls,
                    "top5_chunk_ids": top5_ids,
                    "top5_source_urls": top5_source_urls,
                    "recall_at_1": recall_at_k(expected_items, ranked_items, 1),
                    "recall_at_3": recall_at_k(expected_items, ranked_items, 3),
                    "recall_at_5": recall_at_k(expected_items, ranked_items, 5),
                    "hit_at_1": hit_at_k(expected_items, ranked_items, 1),
                    "hit_at_3": hit_at_k(expected_items, ranked_items, 3),
                    "hit_at_5": hit_at_k(expected_items, ranked_items, 5),
                    "reciprocal_rank": first_reciprocal_rank,
                    "first_relevant_rank": (
                        round(1.0 / first_reciprocal_rank)
                        if isinstance(first_reciprocal_rank, (int, float)) and first_reciprocal_rank > 0
                        else None
                    ),
                    "latency_seconds": total_latency,
                    "timings": timings,
                    "llm_calls": llm_calls,
                    "tags": list(case.get("tags") or []),
                    "difficulty": case.get("difficulty"),
                    "decision": _enum_value(output.decision),
                    "review_action": debug.get("review_action"),
                    "reviewer_reasons": debug.get("reviewer_reasons") or [],
                    "reasoning_prepass": debug.get("reasoning_prepass"),
                    "retry_count": debug.get("retry_count"),
                    "retry_diagnostics": debug.get("retry_diagnostics"),
                    "convergence_reason": debug.get("convergence_reason"),
                    # Answer and quality — needed for ESCALATE/ASK_USER diagnosis
                    "answer": getattr(output, "answer", None),
                    "confidence": getattr(output, "confidence", None),
                    "citations_count": len(getattr(output, "citations", None) or []),
                    # Decision routing — which path led to the final decision?
                    "decision_router": debug.get("decision_router"),
                    "stage_reasons": debug.get("stage_reasons"),
                    "termination_reason": debug.get("termination_reason"),
                    # Quality and review detail
                    "quality_report": debug.get("quality_report"),
                    "review_unsupported_claims": debug.get("review_unsupported_claims"),
                    "error": None,
                }
            )
        except Exception as exc:
            # 超时或其他异常情况，记录失败结果
            results.append(
                {
                    "name": case.get("name") or case.get("title") or f"case-{index:03d}",
                    "question": case["question"],
                    "expected_chunk_id": case.get("chunk_id"),
                    "expected_source_urls": list(case.get("expected_source_urls") or []),
                    "top5_chunk_ids": [],
                    "top5_source_urls": [],
                    "recall_at_1": None,
                    "recall_at_3": None,
                    "recall_at_5": None,
                    "hit_at_1": None,
                    "hit_at_3": None,
                    "hit_at_5": None,
                    "reciprocal_rank": None,
                    "first_relevant_rank": None,
                    "latency_seconds": time.perf_counter() - started,
                    "timings": {},
                    "llm_calls": [],
                    "tags": list(case.get("tags") or []),
                    "difficulty": case.get("difficulty"),
                    "decision": "ERROR",
                    "review_action": None,
                    "reviewer_reasons": [],
                    "reasoning_prepass": None,
                    "retry_count": None,
                    "retry_diagnostics": None,
                    "convergence_reason": None,
                    "answer": None,
                    "confidence": None,
                    "citations_count": 0,
                    "decision_router": None,
                    "stage_reasons": None,
                    "termination_reason": None,
                    "quality_report": None,
                    "review_unsupported_claims": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        print(f"pipeline {index}/{len(cases)}", flush=True)
        if case_delay > 0 and index < len(cases):
            await asyncio.sleep(case_delay)
    return results


def _run_reviewer_cases(cases: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    """运行审查器（ReviewerGate）的成对评测。

    对每个测试样例构造两个回答：
        1. 正例（positive）：使用标准答复，期望审查器通过（ReviewerStatus.PASS）。
        2. 负例（negative）：在标准答复后追加一段无依据的承诺（如"本店保证100%退款"），
           期望审核器能检测到该幻觉内容并拦截。

    评测指标：
        - risk_intercept_recall：风险拦截召回率 = 负例中被拦截的比例
          （越高越好，表示审查器能有效识别幻觉）
        - normal_answer_false_intercept_rate：正常回答误拦截率 = 正例中被拦截的比例
          （越低越好，表示审查器不会误判正常回答）

    Args:
        cases: 评测样例列表。
        limit: 最多评测的样例数。

    Returns:
        包含成对测试结果和汇总统计的字典。
    """
    from app.search.base import EvidenceChunk
    from app.services.reviewer import ReviewerGate, ReviewerStatus

    gate = ReviewerGate()
    rows: list[dict[str, Any]] = []
    # 模拟无依据承诺的幻觉文本（用于负例测试）
    fabricated = "本店保证所有订单均可获得100%退款，并承诺24小时内到账。"
    for case in cases[:limit]:
        evidence = [
            EvidenceChunk(
                chunk_id=case["chunk_id"],
                snippet=case["chunk_text"][:500],
                full_text=case["chunk_text"],
                source_url=case["source_url"],
                doc_type=case["doc_type"],
                score=1.0,
            )
        ]
        citations = [
            {
                "chunk_id": case["chunk_id"],
                "source_url": case["source_url"],
                "doc_type": case["doc_type"],
            }
        ]
        # 正例：标准答复（期望 PASS）
        positive = gate.review(
            decision="PASS",
            answer=case["standard_answer"],
            citations=citations,
            evidence=evidence,
            query=case["question"],
            confidence=0.9,
        )
        # 负例：标准答复 + 无依据承诺（期望被拦截）
        negative = gate.review(
            decision="PASS",
            answer=f'{case["standard_answer"]} {fabricated}',
            citations=citations,
            evidence=evidence,
            query=case["question"],
            confidence=0.9,
        )
        positive_status = _enum_value(positive.status)
        negative_status = _enum_value(negative.status)
        rows.append(
            {
                "question": case["question"],
                "positive_status": positive_status,
                "negative_status": negative_status,
                "positive_reasons": positive.reasons,
                "negative_reasons": negative.reasons,
            }
        )

    pass_value = _enum_value(ReviewerStatus.PASS)
    negative_blocked = sum(row["negative_status"] != pass_value for row in rows)
    positive_blocked = sum(row["positive_status"] != pass_value for row in rows)
    return {
        "case_pairs": len(rows),
        "risk_intercept_recall": negative_blocked / len(rows) if rows else None,
        "normal_answer_false_intercept_rate": positive_blocked / len(rows) if rows else None,
        "positive_status_counts": dict(Counter(row["positive_status"] for row in rows)),
        "negative_status_counts": dict(Counter(row["negative_status"] for row in rows)),
        "cases": rows,
    }


def _average_metric(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
    return sum(values) / len(values) if values else None


def _percentile_summary(values: list[float]) -> dict[str, float | None]:
    return {
        "p50": percentile_nearest_rank(values, 0.50),
        "p95": percentile_nearest_rank(values, 0.95),
        "p99": percentile_nearest_rank(values, 0.99),
    }


def _summarize_llm_tasks(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    # Collect all calls grouped by task (for global stats)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        calls = row.get("llm_calls") if isinstance(row.get("llm_calls"), list) else []
        for call in calls:
            if not isinstance(call, dict):
                continue
            task = str(call.get("task") or "unknown")
            grouped.setdefault(task, []).append(call)

    # Collect per-case-per-task terminal failures.
    # A case's task terminally failed if it has rate_limited events but no
    # success or success_after_429 events within that case's llm_calls.
    terminal_failures: dict[str, int] = {}
    for row in rows:
        calls = row.get("llm_calls") if isinstance(row.get("llm_calls"), list) else []
        case_task_calls: dict[str, list[dict[str, Any]]] = {}
        for call in calls:
            if not isinstance(call, dict):
                continue
            task = str(call.get("task") or "unknown")
            case_task_calls.setdefault(task, []).append(call)
        for task, task_calls in case_task_calls.items():
            statuses = Counter(str(c.get("status") or "unknown") for c in task_calls)
            has_rate_limit = statuses.get("rate_limited", 0) > 0
            has_success = statuses.get("success", 0) > 0 or statuses.get("success_after_429", 0) > 0
            if has_rate_limit and not has_success:
                terminal_failures[task] = terminal_failures.get(task, 0) + 1

    summary: dict[str, dict[str, Any]] = {}
    for task in sorted(grouped):
        calls = grouped[task]
        durations = [
            float(call["duration_seconds"])
            for call in calls
            if isinstance(call.get("duration_seconds"), (int, float))
        ]
        statuses = Counter(str(call.get("status") or "unknown") for call in calls)
        fallback_count = sum(bool(call.get("is_fallback")) for call in calls)
        call_count = len(calls)
        # success_after_429 is also a successful outcome
        effective_success = statuses.get("success", 0) + statuses.get("success_after_429", 0)
        summary[task] = {
            "call_count": call_count,
            "success_count": effective_success,
            "recovered_rate_limit": statuses.get("success_after_429", 0),
            "terminal_rate_limit_failure": terminal_failures.get(task, 0),
            "error_count": statuses.get("error", 0),
            "timeout_count": statuses.get("timeout", 0),
            "rate_limited_count": statuses.get("rate_limited", 0),
            "fallback_count": fallback_count,
            "success_rate": effective_success / call_count if call_count else None,
            "fallback_rate": fallback_count / call_count if call_count else None,
            "models": dict(Counter(str(call.get("model") or "unknown") for call in calls)),
            "latency_seconds": _percentile_summary(durations),
        }
    return summary


def _summarize_fastpath(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate generate_reasoning fast-path blocker statistics.

    Returns:
        dict with:
        - skipped_count: number of cases where fast-path was taken
        - executed_count: number of cases where generate_reasoning ran
        - blocker_counts: frequency of each blocker string
        - relaxation_counts: frequency of each relaxation that allowed skip
        - per_case: list of {name, skipped, blockers/skip_metadata}
    """
    skipped = 0
    executed = 0
    blocker_counts: dict[str, int] = {}
    relaxation_counts: dict[str, int] = {}
    per_case: list[dict[str, Any]] = []

    for row in rows:
        prepass = row.get("reasoning_prepass")
        if not isinstance(prepass, dict):
            continue
        case_info: dict[str, Any] = {"name": row.get("name")}
        reason = prepass.get("reason") or ""
        if reason == "simple_direct_lookup_quality_passed":
            # True fast-path: reasoning prepass was intentionally skipped
            skipped += 1
            case_info["skipped"] = True
            case_info["reason"] = reason
            meta = prepass.get("skip_metadata") or {}
            relaxations = meta.get("fastpath_relaxations") or {}
            for key, val in relaxations.items():
                if val:
                    relaxation_counts[key] = relaxation_counts.get(key, 0) + 1
            case_info["skip_metadata"] = meta
        else:
            # Executed, blocked, or disabled_or_unavailable — reasoning was NOT fast-pathed
            executed += 1
            case_info["skipped"] = False
            case_info["reason"] = reason
            blockers = prepass.get("blockers") or []
            for b in blockers:
                # Normalize: strip parenthetical details for aggregation
                base = b.split("(")[0] if "(" in b else b
                blocker_counts[base] = blocker_counts.get(base, 0) + 1
            case_info["blockers"] = blockers
        per_case.append(case_info)

    return {
        "skipped_count": skipped,
        "executed_count": executed,
        "blocker_counts": dict(sorted(blocker_counts.items(), key=lambda x: -x[1])),
        "relaxation_counts": dict(sorted(relaxation_counts.items(), key=lambda x: -x[1])),
        "per_case": per_case,
    }


def _summarize_retry(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate retry convergence diagnostics across eval cases.

    Returns:
        dict with:
        - retried_count: number of cases that had >0 retries
        - convergence_reasons: distribution of convergence reasons
        - never_converged: cases where retries happened but no convergence_reason
        - per_case: list of per-case retry details
    """
    retried = 0
    convergence_reasons: dict[str, int] = {}
    never_converged: list[str] = []
    per_case: list[dict[str, Any]] = []

    for row in rows:
        retry_count = row.get("retry_count")
        if not isinstance(retry_count, int) or retry_count == 0:
            continue
        retried += 1
        name = row.get("name", "")
        convergence_reason = row.get("convergence_reason")
        if convergence_reason:
            convergence_reasons[convergence_reason] = (
                convergence_reasons.get(convergence_reason, 0) + 1
            )
        else:
            never_converged.append(name)

        diagnostics = row.get("retry_diagnostics") or []
        round_details: list[dict[str, Any]] = []
        for d in diagnostics:
            if not isinstance(d, dict):
                continue
            round_details.append({
                "attempt": d.get("retrieval_attempt"),
                "gate_pass": d.get("gate_pass"),
                "raw_llm_gate_pass": d.get("raw_llm_gate_pass"),
                "missing_signals": d.get("missing_signals"),
                "source_set_changed": d.get("source_set_changed"),
                "quality_score": d.get("quality_score"),
                "selector_llm_failed": d.get("evidence_selector_llm_failed"),
                "quality_llm_failed": d.get("quality_llm_failed"),
            })
        per_case.append({
            "name": name,
            "retry_count": retry_count,
            "convergence_reason": convergence_reason,
            "rounds": round_details,
        })

    return {
        "retried_count": retried,
        "convergence_reasons": dict(
            sorted(convergence_reasons.items(), key=lambda x: -x[1])
        ),
        "never_converged": never_converged,
        "per_case": per_case,
    }


def _segment_metrics(classified: list[tuple[dict, dict]]) -> dict[str, Any]:
    """Split metrics by execution path: all, retrieval_eligible, retrieval_executed, route_short_circuited, invalid."""
    def _metrics_for(rows: list[dict]) -> dict[str, Any]:
        if not rows:
            return {"count": 0, "recall_at_5": None, "hit_at_5": None, "mrr": None, "latency_p50": None, "latency_p95": None}
        return {
            "count": len(rows),
            "recall_at_5": _average_metric(rows, "recall_at_5"),
            "hit_at_5": _average_metric(rows, "hit_at_5"),
            "mrr": _average_metric(rows, "reciprocal_rank"),
            "latency_p50": percentile_nearest_rank([float(r["latency_seconds"]) for r in rows], 0.50),
            "latency_p95": percentile_nearest_rank([float(r["latency_seconds"]) for r in rows], 0.95),
        }

    all_rows = [row for row, _ in classified]
    valid_rows = [row for row, vc in classified if vc["business_valid"]]
    eligible_rows = [row for row, vc in classified if vc["retrieval_eligible"]]
    retrieval_rows = [row for row, vc in classified if vc["retrieval_executed"]]
    # route_short_circuited: valid cases that did NOT execute retrieval,
    # based on actual route (not eligibility). This catches both correctly
    # short-circuited cases AND mis-routed cases.
    short_circuit_rows = [row for row, vc in classified if vc["business_valid"] and not vc["retrieval_executed"]]
    invalid_rows = [row for row, vc in classified if not vc["business_valid"]]

    return {
        "all_cases": _metrics_for(all_rows),
        "retrieval_eligible": _metrics_for(eligible_rows),
        "retrieval_executed": _metrics_for(retrieval_rows),
        "route_short_circuited": _metrics_for(short_circuit_rows),
        "invalid_cases": _metrics_for(invalid_rows),
    }


def _routing_summary(classified: list[tuple[dict, dict]]) -> dict[str, Any]:
    """Count valid cases by actual route (from stage_reasons), not final decision."""
    counts: dict[str, int] = {"rag_search": 0, "direct_response": 0, "clarify": 0, "human_handoff": 0, "intent_cache_hit": 0, "skip_retrieval": 0, "unknown": 0}
    for row, vc in classified:
        if not vc["business_valid"]:
            continue
        route = vc.get("route", "unknown")
        if route in counts:
            counts[route] += 1
        else:
            counts["unknown"] += 1
    return counts


def _recall_groups(retrieval_rows: list[dict]) -> dict[str, int]:
    """Group retrieval-executed cases by recall level."""
    full = 0
    partial = 0
    zero = 0
    for row in retrieval_rows:
        r5 = row.get("recall_at_5")
        if not isinstance(r5, (int, float)):
            continue
        if r5 >= 1.0:
            full += 1
        elif r5 > 0:
            partial += 1
        else:
            zero += 1
    return {"full_recall": full, "partial_recall": partial, "zero_recall": zero}


def _latency_groups(valid_rows: list[dict]) -> dict[str, Any]:
    """Split latency by retry count: no_retry, retried, max_retry."""
    no_retry = []
    retried = []
    max_retry = []
    for row in valid_rows:
        lat = float(row.get("latency_seconds") or 0)
        rc = row.get("retry_count")
        if isinstance(rc, int) and rc >= 3:
            max_retry.append(lat)
        elif isinstance(rc, int) and rc > 0:
            retried.append(lat)
        else:
            no_retry.append(lat)

    def _stats(vals: list[float]) -> dict[str, Any]:
        return {
            "count": len(vals),
            "p50": percentile_nearest_rank(vals, 0.50),
            "p95": percentile_nearest_rank(vals, 0.95),
            "p99": percentile_nearest_rank(vals, 0.99),
        }

    return {
        "no_retry": _stats(no_retry),
        "retried": _stats(retried),
        "max_retry": _stats(max_retry),
    }


def _generate_diagnosis_pack(
    summary: dict[str, Any],
    pipeline: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate compact diagnosis JSON for AI review.

    Includes: summary, invalid cases, route-short-circuited, recall failures,
    slowest cases, retried cases. Excludes prompts, responses, full evidence.
    """
    classified = [(row, _classify_case_validity(row)) for row in pipeline]

    # Invalid cases
    invalid = []
    for row, vc in classified:
        if not vc["business_valid"]:
            invalid.append({
                "name": row.get("name"),
                "decision": row.get("decision"),
                "failure_category": vc["failure_category"],
                "answer_preview": str(row.get("answer") or "")[:100],
            })

    # Route short-circuited
    short_circuited = []
    for row, vc in classified:
        if vc["business_valid"] and not vc["retrieval_executed"]:
            short_circuited.append({
                "name": row.get("name"),
                "decision": row.get("decision"),
                "latency_seconds": row.get("latency_seconds"),
            })

    # Recall failures
    recall_failures = []
    for row, vc in classified:
        if vc["retrieval_executed"]:
            r5 = row.get("recall_at_5")
            if isinstance(r5, (int, float)) and r5 < 1.0:
                recall_failures.append({
                    "name": row.get("name"),
                    "recall_at_5": r5,
                    "expected_source_urls": row.get("expected_source_urls"),
                    "top5_source_urls": row.get("top5_source_urls"),
                    "tags": row.get("tags"),
                    "difficulty": row.get("difficulty"),
                })

    # Slowest cases (top 10)
    valid_rows = [row for row, vc in classified if vc["business_valid"]]
    slowest = sorted(valid_rows, key=lambda r: -float(r.get("latency_seconds") or 0))[:10]
    slowest_info = []
    for row in slowest:
        info: dict[str, Any] = {
            "name": row.get("name"),
            "latency_seconds": row.get("latency_seconds"),
            "decision": row.get("decision"),
            "retry_count": row.get("retry_count"),
        }
        timings = row.get("timings") or {}
        phase_timings = {k: v for k, v in timings.items() if isinstance(v, (int, float)) and v > 0.01}
        if phase_timings:
            info["phase_timings"] = phase_timings
        slowest_info.append(info)

    # Retried cases
    retried = []
    for row in valid_rows:
        rc = row.get("retry_count")
        if isinstance(rc, int) and rc > 0:
            retried.append({
                "name": row.get("name"),
                "retry_count": rc,
                "convergence_reason": row.get("convergence_reason"),
                "latency_seconds": row.get("latency_seconds"),
            })

    return {
        "summary": {
            "dataset_cases": summary.get("dataset_cases"),
            "valid_cases": summary.get("successful_cases"),
            "invalid_cases": summary.get("failed_cases"),
            "benchmark_valid": (summary.get("benchmark_validity") or {}).get("valid"),
            "recall_at_5": summary.get("recall_at_5"),
        },
        "invalid_cases": invalid,
        "route_short_circuited": short_circuited,
        "recall_failures": recall_failures,
        "slowest_cases": slowest_info,
        "retried_cases": retried,
    }


def _summarize(pipeline: list[dict[str, Any]], reviewer: dict[str, Any]) -> dict[str, Any]:
    """汇总管道评测和审查器评测的各项指标。

    计算：
        - Benchmark 有效性（validity、invalidation reasons）
        - 总样本数、有效/无效数
        - 平均 Recall@5（仅有效且执行了检索的 case）
        - 端到端延迟 P50/P95/P99（仅有效 case）
        - 各阶段 P95 耗时
        - 管道最终决策分布
        - 审查器评测汇总

    Args:
        pipeline: 管道评测结果列表。
        reviewer: 审查器评测结果字典。

    Returns:
        汇总指标字典。
    """
    # Classify each case
    classified = [(row, _classify_case_validity(row)) for row in pipeline]
    valid_rows = [row for row, vc in classified if vc["business_valid"]]
    invalid_rows = [(row, vc) for row, vc in classified if not vc["business_valid"]]
    retrieval_rows = [row for row, vc in classified if vc["retrieval_executed"]]

    # Invalidation reasons
    reason_counts: dict[str, int] = {}
    for _row, vc in invalid_rows:
        cat = vc["failure_category"]
        if cat:
            reason_counts[cat] = reason_counts.get(cat, 0) + 1

    benchmark_valid = len(invalid_rows) == 0

    # Latency — from valid cases only
    latencies = [float(row["latency_seconds"]) for row in valid_rows]
    retrieve_latencies = [
        float(row["timings"]["retrieve"])
        for row in valid_rows
        if isinstance(row.get("timings"), dict)
        and isinstance(row["timings"].get("retrieve"), (int, float))
    ]
    phase_names = ("query_extract", "retrieve", "rerank", "assess_evidence", "generate", "verify")
    phase_p95 = {}
    for name in phase_names:
        values = [
            float(row["timings"].get(name))
            for row in valid_rows
            if isinstance(row.get("timings"), dict)
            and isinstance(row["timings"].get(name), (int, float))
        ]
        phase_p95[name] = percentile_nearest_rank(values, 0.95)

    # Retrieval quality — from retrieval-executed cases only
    retrieval_quality = {
        "recall_at_1": _average_metric(retrieval_rows, "recall_at_1"),
        "recall_at_3": _average_metric(retrieval_rows, "recall_at_3"),
        "recall_at_5": _average_metric(retrieval_rows, "recall_at_5"),
        "hit_at_1": _average_metric(retrieval_rows, "hit_at_1"),
        "hit_at_3": _average_metric(retrieval_rows, "hit_at_3"),
        "hit_at_5": _average_metric(retrieval_rows, "hit_at_5"),
        "mrr": _average_metric(retrieval_rows, "reciprocal_rank"),
    }

    return {
        "schema_version": "2.0",
        "dataset_cases": len(pipeline),
        # successful_cases = business valid (compat alias, denominator = dataset_cases)
        "successful_cases": len(valid_rows),
        # failed_cases = business invalid (compat alias)
        "failed_cases": len(invalid_rows),
        "benchmark_validity": {
            "valid": benchmark_valid,
            "invalid_count": len(invalid_rows),
            "invalidation_reasons": dict(sorted(reason_counts.items(), key=lambda x: -x[1])),
        },
        "recall_at_5": retrieval_quality["recall_at_5"],
        "retrieval_quality": retrieval_quality,
        "segmented_metrics": _segment_metrics(classified),
        "routing_summary": _routing_summary(classified),
        "recall_groups": _recall_groups(retrieval_rows),
        "latency_groups": _latency_groups(valid_rows),
        "latency_seconds": _percentile_summary(latencies),
        "retrieval_latency_seconds": _percentile_summary(retrieve_latencies),
        "phase_p95_seconds": phase_p95,
        "llm_tasks": _summarize_llm_tasks(valid_rows),
        "fastpath_diagnosis": _summarize_fastpath(valid_rows),
        "retry_diagnosis": _summarize_retry(valid_rows),
        "pipeline_decision_counts": dict(Counter(row["decision"] for row in valid_rows)),
        "reviewer": {key: value for key, value in reviewer.items() if key != "cases"},
    }


def _render_markdown(summary: dict[str, Any]) -> str:
    """将汇总指标渲染为 Markdown 格式的可读报告。

    Args:
        summary: 汇总指标字典。

    Returns:
        Markdown 格式的字符串。
    """
    def pct(value: Any) -> str:
        return f"{float(value):.2%}" if isinstance(value, (int, float)) else "N/A"

    def seconds(value: Any) -> str:
        return f"{float(value):.3f}s" if isinstance(value, (int, float)) else "N/A"

    quality = summary.get("retrieval_quality") or {}
    latency = summary.get("latency_seconds") or {}
    retrieval_latency = summary.get("retrieval_latency_seconds") or {}
    reviewer = summary.get("reviewer") or {}
    bv = summary.get("benchmark_validity") or {}

    lines = [
        "# RAG 检索能力离线评测",
        "",
    ]

    # Schema version
    schema_ver = summary.get("schema_version")
    if schema_ver:
        lines.append(f'- 报告版本：{schema_ver}')

    # Benchmark validity — MUST appear before quality/latency metrics
    lines.append(f'- 样本数：{summary["dataset_cases"]}（有效 {summary["successful_cases"]}，无效 {summary["failed_cases"]}）')
    valid_str = "有效" if bv.get("valid") else "无效"
    lines.append(f'- Benchmark 有效性：{valid_str}')
    reasons = bv.get("invalidation_reasons") or {}
    if reasons:
        reason_parts = [f"{cat}={cnt}" for cat, cnt in reasons.items()]
        lines.append(f'- 无效原因：{", ".join(reason_parts)}')

    lines.extend([
        (
            "- Recall@1/3/5："
            f'{pct(quality.get("recall_at_1"))} / {pct(quality.get("recall_at_3"))} / '
            f'{pct(quality.get("recall_at_5"))}'
        ),
        (
            "- Hit@1/3/5："
            f'{pct(quality.get("hit_at_1"))} / {pct(quality.get("hit_at_3"))} / '
            f'{pct(quality.get("hit_at_5"))}'
        ),
        f'- MRR：{pct(quality.get("mrr"))}',
        (
            "- 检索延迟 P50/P95/P99："
            f'{seconds(retrieval_latency.get("p50"))} / {seconds(retrieval_latency.get("p95"))} / '
            f'{seconds(retrieval_latency.get("p99"))}'
        ),
        (
            "- 端到端延迟 P50/P95/P99："
            f'{seconds(latency.get("p50"))} / {seconds(latency.get("p95"))} / '
            f'{seconds(latency.get("p99"))}'
        ),
    ])

    llm_tasks = summary.get("llm_tasks") or {}
    if llm_tasks:
        lines.extend(
            [
                "",
                "## LLM 调用统计",
                "",
                "| Task | 调用数 | 成功率 | Fallback | 429恢复 | 429终败 | Timeout | P50 | P95 | P99 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for task, item in llm_tasks.items():
            task_latency = item.get("latency_seconds") or {}
            lines.append(
                f'| {task} | {item.get("call_count", 0)} | {pct(item.get("success_rate"))} | '
                f'{item.get("fallback_count", 0)} | {item.get("recovered_rate_limit", 0)} | '
                f'{item.get("terminal_rate_limit_failure", 0)} | '
                f'{item.get("timeout_count", 0)} | '
                f'{seconds(task_latency.get("p50"))} | {seconds(task_latency.get("p95"))} | '
                f'{seconds(task_latency.get("p99"))} |'
            )

    # Routing summary
    routing = summary.get("routing_summary") or {}
    if routing:
        lines.extend([
            "",
            "## 路由分布",
            "",
            "| 路由 | 数量 |",
            "|---|---:|",
        ])
        for route, count in routing.items():
            if count > 0:
                lines.append(f"| {route} | {count} |")

    # Segmented metrics
    seg = summary.get("segmented_metrics") or {}
    if seg:
        lines.extend([
            "",
            "## 分层指标",
            "",
            "| 分层 | 数量 | Recall@5 | Hit@5 | MRR | 延迟P50 | 延迟P95 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ])
        for seg_name in ("all_cases", "retrieval_eligible", "retrieval_executed", "route_short_circuited", "invalid_cases"):
            s = seg.get(seg_name) or {}
            lines.append(
                f'| {seg_name} | {s.get("count", 0)} | '
                f'{pct(s.get("recall_at_5"))} | {pct(s.get("hit_at_5"))} | {pct(s.get("mrr"))} | '
                f'{seconds(s.get("latency_p50"))} | {seconds(s.get("latency_p95"))} |'
            )

    # Fast-path diagnosis
    fp = summary.get("fastpath_diagnosis") or {}
    if fp:
        lines.extend([
            "",
            "## Fast-Path 诊断",
            "",
            f'- 跳过 generate_reasoning：{fp.get("skipped_count", 0)} / {fp.get("skipped_count", 0) + fp.get("executed_count", 0)} 条',
            f'- 执行 generate_reasoning：{fp.get("executed_count", 0)} 条',
        ])
        blockers = fp.get("blocker_counts") or {}
        if blockers:
            lines.extend([
                "",
                "| Blocker | 次数 |",
                "|---|---:|",
            ])
            for name, count in blockers.items():
                lines.append(f"| {name} | {count} |")
        relaxations = fp.get("relaxation_counts") or {}
        if relaxations:
            lines.extend([
                "",
                "| 放宽条件命中 | 次数 |",
                "|---|---:|",
            ])
            for name, count in relaxations.items():
                lines.append(f"| {name} | {count} |")

    # Retry convergence diagnosis
    retry = summary.get("retry_diagnosis") or {}
    if retry.get("retried_count"):
        lines.extend([
            "",
            "## Retry 收敛诊断",
            "",
            f'- 触发重试的 case：{retry["retried_count"]} 条',
        ])
        reasons = retry.get("convergence_reasons") or {}
        if reasons:
            lines.extend([
                "",
                "| 收敛原因 | 次数 |",
                "|---|---:|",
            ])
            for reason, count in reasons.items():
                lines.append(f"| {reason} | {count} |")
        never_conv = retry.get("never_converged") or []
        if never_conv:
            lines.append(f'- 未触发收敛（跑满重试次数）：{", ".join(never_conv)}')
        per_case = retry.get("per_case") or []
        if per_case:
            lines.extend(["", "### 逐 case 重试详情", ""])
            for case in per_case:
                lines.append(f'**{case["name"]}** — retry_count={case["retry_count"]}, convergence_reason={case["convergence_reason"]}')
                lines.append("")
                lines.append("| attempt | gate_pass | raw_llm_pass | missing_signals | source_set_changed | quality_score |")
                lines.append("|---:|---:|---:|---|---|---:|")
                for r in case.get("rounds", []):
                    ms = ", ".join(r.get("missing_signals") or []) or "—"
                    ssc = r.get("source_set_changed")
                    ssc_str = "True" if ssc is True else ("False" if ssc is False else "None")
                    qs = r.get("quality_score")
                    qs_str = f"{qs:.2f}" if isinstance(qs, (int, float)) else "—"
                    gp = "✓" if r.get("gate_pass") else "✗"
                    raw_gp = r.get("raw_llm_gate_pass")
                    raw_gp_str = "✓" if raw_gp is True else ("✗" if raw_gp is False else "—")
                    lines.append(f'| {r.get("attempt")} | {gp} | {raw_gp_str} | {ms} | {ssc_str} | {qs_str} |')
                lines.append("")

    if reviewer.get("case_pairs"):
        lines.extend(
            [
                "",
                f'- Reviewer 风险拦截召回率：{pct(reviewer.get("risk_intercept_recall"))}',
                f'- Reviewer 正常回答误拦截率：{pct(reviewer.get("normal_answer_false_intercept_rate"))}',
            ]
        )

    lines.extend(
        [
            "",
            "口径：外部数据集通过稳定 source_url 判定命中；评测问题与标准答案不得导入知识库。",
        ]
    )
    return "\n".join(lines)


async def _main(args: argparse.Namespace) -> int:
    """主流程编排：
    1. 初始化运行时缓存
    2. 从数据库加载评测样例
    3. 运行管道评测（遍历样例调用完整 RAG 管道）
    4. 运行审查器评测（成对测试 ReviewerGate）
    5. 汇总指标
    6. 输出 JSON 和 Markdown 文件

    Args:
        args: 命令行参数。

    Returns:
        0（全部成功）或 2（存在失败的样例）。
    """
    await initialize_runtime()
    override_embedding_base_url(args.embedding_base_url)
    enable_llm_call_capture(getattr(args, "capture_llm_calls", False))

    # Apply eval-only source_url prefix filter if requested.
    source_url_prefix = getattr(args, "source_url_prefix", None)
    filter_token = None
    if source_url_prefix:
        from app.services.retrieval import set_source_url_filter
        filter_token = set_source_url_filter(source_url_prefix)
        print(f"[info] source_url filter active: prefix={source_url_prefix!r}")

    dataset_json = getattr(args, "dataset_json", None)
    try:
        cases = (
            load_eval_cases_json(dataset_json, args.limit)
            if dataset_json
            else await _load_cases(args.limit)
        )
        if not cases:
            raise RuntimeError("No eligible knowledge-base cases found")
        case_delay = getattr(args, "case_delay", 0.0)
        pipeline = await _run_pipeline_cases(cases, args.case_timeout, case_delay=case_delay)
    finally:
        if filter_token is not None:
            from app.services.retrieval import reset_source_url_filter
            reset_source_url_filter(filter_token)
    if dataset_json:
        reviewer = {
            "case_pairs": 0,
            "risk_intercept_recall": None,
            "normal_answer_false_intercept_rate": None,
            "positive_status_counts": {},
            "negative_status_counts": {},
            "cases": [],
        }
    else:
        reviewer = _run_reviewer_cases(cases, args.review_limit)
    summary = _summarize(pipeline, reviewer)
    payload = {
        "dataset": {
            "mode": "external_json" if dataset_json else "knowledge_base_discovery",
            "path": str(Path(dataset_json).resolve()) if dataset_json else None,
        },
        "metadata": {
            "case_delay_seconds": getattr(args, "case_delay", 0.0),
            "case_timeout_seconds": args.case_timeout,
            "source_url_prefix": getattr(args, "source_url_prefix", None),
            "capture_llm_calls": getattr(args, "capture_llm_calls", False),
        },
        "summary": summary,
        "pipeline_cases": pipeline,
        "reviewer_cases": reviewer["cases"],
    }

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(_render_markdown(summary), encoding="utf-8")

    # Write compact diagnosis JSON alongside main report
    diagnosis = _generate_diagnosis_pack(summary, pipeline)
    diag_path = output_json.with_name(output_json.stem + "-diagnosis.json")
    diag_path.write_text(json.dumps(diagnosis, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    bv = summary.get("benchmark_validity") or {}
    # Exit 0 only when benchmark is fully valid; exit 2 when any case is invalid
    # Reports are always written so failures can be diagnosed.
    return 0 if bv.get("valid") else 2


def main() -> int:
    """CLI 入口。

    命令行参数：
        --limit            评测样例的最大数量（默认 36）
        --review-limit     审查器评测的最大样例数（默认 20）
        --case-timeout     单条管道评测超时秒数（默认 180）
        --dataset-json      独立外部评测集 JSON（可选）
        --capture-llm-calls 强制采集逐次 LLM 调用数据
        --embedding-base-url 覆盖 Embedding 服务地址（可选）
        --output-json      JSON 输出路径（必填）
        --output-md        Markdown 输出路径（必填）

    Returns:
        exit code。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=36)
    parser.add_argument("--review-limit", type=int, default=20)
    parser.add_argument("--case-timeout", type=float, default=180.0)
    parser.add_argument(
        "--dataset-json",
        default=None,
        help="Independent evaluation JSON; questions in this file must not be ingested into the knowledge base",
    )
    parser.add_argument(
        "--capture-llm-calls",
        action="store_true",
        help="Force per-attempt LLM capture for this evaluation process",
    )
    parser.add_argument("--embedding-base-url", default=None)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument(
        "--source-url-prefix",
        default=None,
        help=(
            "Eval-only: only keep retrieval results whose source_url starts with this prefix. "
            "Example: eval://retrieval/ to isolate benchmark corpus from old business docs."
        ),
    )
    parser.add_argument(
        "--case-delay",
        type=float,
        default=0.5,
        help="Seconds to wait between cases to avoid rate-limiting (default: 0.5)",
    )
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
