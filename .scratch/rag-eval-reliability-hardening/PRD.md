# RAG 评测可信度与长尾收敛优化 PRD

Status: ready-for-agent

## Problem Statement

当前 100 条冷启动评测能够完整执行并生成 JSON、Markdown 和控制台日志，但“脚本执行成功”与“RAG 业务成功”没有被正确区分。本轮结果显示 `successful_cases=100`，控制台却出现 144 次 LLM 调用错误、327 条 `Too many requests`、39 次答案生成失败和 29 条通用错误回答；这些失败最终大多被包装为 `ESCALATE`，仍计入成功用例。由此产生三个直接问题：

1. 用户无法判断一轮评测是否受到模型限流、基础设施故障或 fallback 污染，可能把失真的延迟和决策分布当作真实性能。
2. 全量指标把正常 RAG 检索、Agentic Router 直接转人工、模型异常和无检索输出混在一起。当前 Recall@5 为 89.33%，但其中 3 条 case 在 0.3ms 内直接 `human_handoff`，根本没有执行检索。
3. retry 是当前长尾延迟的主要来源。75 条无重试 case 的端到端 P95 为 20.29 秒，而 22 条重试 case 的 P95 为 53.26 秒；6 条达到 3 次重试的 case 平均耗时 44.63 秒，且没有记录收敛原因。

本轮评测同时证明检索能力相对旧基线已有明显提升：Recall@5 从 68.17% 提升到 89.33%，Hit@5 从 72% 提升到 92%，MRR 从 0.483 提升到 0.774。但在消除 429 污染、修正成功口径和拆分检索适用样本之前，这些结果不能作为稳定的发布门槛或生产 SLA。

## Solution

建立一套“默认轻量、失败可见、指标分层、长尾可收敛”的离线评测机制：

- 将 case 的脚本完成状态、业务终态、模型调用状态和检索适用状态分开记录。
- 即使未启用完整 LLM 调用追踪，也始终采集不包含 prompt/response 的轻量任务统计，包括调用数、成功、429、timeout、fallback 和最终失败。
- 为批量评测增加可配置的 case 间隔和限流退避，避免连续调用压垮 OpenAI-compatible 模型网关。
- 将总体指标拆分为 all cases、retrieval-eligible cases、retrieval-executed cases 和 route-short-circuited cases，避免直接转人工样本拉低检索指标。
- 对无收益 retry 设置清晰上限和收敛原因，确保基础设施失败、语义等价缺口以及连续 gate failure 不会反复执行完整检索链路。
- 自动生成一个体积可控的诊断包，只包含总体摘要、失败 case、最慢 case、重试 case、路由短路和召回缺口，供后续 AI 审查使用。
- 完成修复后重新运行 100 条冷启动评测，并用无 429 污染的结果建立新的可信基线。

## User Stories

1. As an RAG engineer, I want `successful_cases` to represent completed and valid business outputs, so that infrastructure failures are not reported as success.
2. As an RAG engineer, I want script execution failures and business answer failures to be separate counters, so that I can distinguish harness stability from RAG quality.
3. As an evaluator, I want a generic error answer to be classified as failed, so that an exception wrapped as `ESCALATE` cannot hide inside successful results.
4. As an evaluator, I want a missing normal termination reason to be visible in the summary, so that incomplete state-machine executions are easy to locate.
5. As an evaluator, I want lightweight LLM task metrics without storing prompts, so that a 100-case report remains small while still exposing model failures.
6. As an evaluator, I want 429, timeout, fallback and parsing failures counted separately, so that different failure modes do not collapse into a generic model error.
7. As a privacy-conscious operator, I want prompt and response bodies excluded by default, so that routine benchmark artifacts do not contain unnecessary user or knowledge-base content.
8. As a debugging engineer, I want an opt-in full LLM trace for selected cases, so that I can investigate a failure without tracing all 100 cases.
9. As an operator, I want a configurable delay between cases, so that sequential benchmark traffic respects provider request limits.
10. As an operator, I want rate-limit backoff to honor bounded retry and provider hints when available, so that transient throttling can recover without creating an unbounded run.
11. As an operator, I want a benchmark marked invalid when the configured infrastructure-error threshold is exceeded, so that polluted results cannot become a release baseline.
12. As an operator, I want the CLI to return a non-zero exit code for an invalid benchmark, so that CI and automation can stop reliably.
13. As a retrieval engineer, I want retrieval metrics calculated only over retrieval-eligible cases, so that direct response and human-handoff routes do not distort Recall and Hit rates.
14. As a retrieval engineer, I want metrics for all cases retained separately, so that routing behavior remains observable rather than silently excluded.
15. As a routing engineer, I want direct response, clarification, human handoff and RAG search counts reported independently, so that route-distribution regressions are visible.
16. As a routing engineer, I want human-handoff cases to record their route reason and matched boundary, so that false-positive escalation can be audited.
17. As a retrieval engineer, I want zero-result, full-recall and partial-recall counts in the summary, so that Recall@5 is explainable without reading every case.
18. As a retrieval engineer, I want missed expected sources grouped by lexical-gap, multi-hop, negative-condition and numeric-condition tags, so that recall work can be prioritized by failure pattern.
19. As an RAG engineer, I want retries grouped by retry count and convergence reason, so that long-tail latency can be attributed to specific policies.
20. As an RAG engineer, I want infrastructure failures to stop retrieval retries early, so that repeating the same failed LLM call does not increase latency.
21. As an RAG engineer, I want consecutive gate failures with no meaningful evidence improvement to converge, so that semantic wording changes do not bypass convergence indefinitely.
22. As an RAG engineer, I want retry count capped by a configurable policy, so that no individual case unexpectedly performs repeated full retrieval cycles.
23. As an RAG engineer, I want every exhausted retry path to emit a convergence or exhaustion reason, so that `convergence_reason=null` is not the normal result for max-retry cases.
24. As a performance engineer, I want latency reported separately for no-retry, retried and max-retry groups, so that global percentiles do not hide the dominant long-tail source.
25. As a performance engineer, I want retrieved-only latency reported separately from route-short-circuit latency, so that a faster router does not look like a faster retrieval engine.
26. As an AI reviewer, I want an automatically generated compact diagnosis JSON, so that I can analyze core failures without loading full console logs.
27. As an AI reviewer, I want the diagnosis package to include the slowest cases and their phase timings, so that I can identify the responsible stage directly.
28. As an AI reviewer, I want the diagnosis package to include failed and partial-recall cases with expected and actual sources, so that ranking gaps are immediately visible.
29. As a developer, I want JSON and Markdown reports to use the same metric definitions, so that human and machine-readable outputs cannot disagree.
30. As a maintainer, I want the report schema versioned, so that downstream scripts can detect incompatible changes.
31. As a maintainer, I want old result files to remain readable when practical, so that historical baseline comparisons are preserved.
32. As a project owner, I want a clean 100-case cold-start validation gate, so that future performance claims are based on reproducible evidence.
33. As a project owner, I want the clean baseline to preserve or improve Recall@5, Hit@5 and MRR, so that latency optimization does not reduce retrieval quality.
34. As a project owner, I want benchmark validity displayed before performance metrics, so that a fast but invalid run is never presented as an optimization success.

## Implementation Decisions

- The benchmark result model will distinguish at least four concepts: harness completion, business output validity, retrieval eligibility and retrieval execution. A case may finish without a Python exception but still be invalid because generation failed or no valid terminal output was produced.
- A valid business output must have a recognized terminal decision, a non-error answer appropriate to that decision, and a normal termination reason. A known generic system-error response is not a valid answer.
- Human handoff triggered intentionally by the Agentic Router remains a valid business output, but it is route-short-circuited and excluded from retrieval-executed Recall/Hit denominators. It remains visible in all-case and routing metrics.
- Model or infrastructure failure wrapped as `ESCALATE` is invalid, not an intentional human handoff. The output must carry a machine-readable failure category rather than relying on answer-text matching alone.
- Lightweight LLM telemetry is enabled for evaluations by default. It records task, model, attempt, latency, status, error type, fallback and cache status, but excludes messages, response content, tokens and cost unless full capture is explicitly requested.
- Full LLM capture remains opt-in and should support selection by case name or a small case subset. The 100-case default path must not require full capture to determine benchmark validity.
- The CLI will support a non-negative case delay. The default should be conservative enough for local evaluation without making existing short smoke runs unnecessarily slow; the chosen value must be explicit in the report metadata.
- Rate-limit handling will be bounded. It may use provider retry hints or exponential backoff, but it must not create unbounded per-call or per-case retries. Rate-limit attempts and sleep duration are reported.
- The summary will expose benchmark validity and invalidation reasons before quality and latency metrics. Suggested invalidation reasons include rate-limit threshold exceeded, generation failures, timeout threshold exceeded and malformed output threshold exceeded.
- The process exit code will distinguish a successfully generated valid report from a completed but invalid benchmark. Reports must still be written when the run is invalid so the failure can be diagnosed.
- Metrics will be grouped into `all_cases`, `retrieval_eligible`, `retrieval_executed`, `route_short_circuited` and `invalid_cases`. Existing top-level metric names may remain temporarily as compatibility aliases, but their denominator must be documented.
- Routing summary will count RAG search, direct response, clarification and human handoff, including a reason distribution. This will expose cases such as verification-code, invoice/refund and payment-state queries that bypass retrieval.
- Recall summaries will include counts for full, partial and zero recall, plus expected-source misses grouped by dataset tags and difficulty.
- Retry diagnostics will always record the current attempt consistently. Raw LLM judgment, code-overridden gate result, missing signals, source-set change and quality score must come from the same assessment round.
- Retry convergence will use stable, machine-readable signals. Free-form missing-signal wording alone is insufficient because semantically identical gaps can be phrased differently.
- Infrastructure failures will never justify a fresh full retrieval attempt when the evidence set is not the cause of failure.
- The maximum productive retrieval retry count will be configurable and lower than the current observed three-retry long tail unless a case demonstrates meaningful evidence improvement. Reaching the limit must produce an explicit exhaustion reason.
- The compact diagnosis artifact will be written automatically beside the JSON and Markdown reports. It will include summary, invalid cases, route-short-circuited cases, recall failures, slowest cases and retried cases, without full prompts or full evidence text.
- Report metadata will include dataset identity, case count, timestamp, cold/warm cache declaration, source filter, case delay, timeout, full-capture state, relevant retry settings and report schema version.
- Retrieval algorithm tuning for the 14 incomplete-recall cases begins only after a valid, rate-limit-free benchmark exists. Otherwise model fallbacks and routing failures would confound the diagnosis.
- After benchmark reliability is fixed, the first retrieval cases to inspect are the lexical-gap single-hop misses and route-boundary misses, followed by multi-hop partial recall. Any retrieval change must preserve source isolation and production defaults.

## Testing Decisions

- The primary test seam is the offline evaluation CLI because it exercises the same workflow used by the user: run cases, invoke the pipeline, classify outputs, aggregate metrics and write all artifacts. A deterministic fixture will include successful RAG, intentional human handoff, generation 429, quality 429, timeout, generic error output, zero recall, partial recall and max-retry cases.
- CLI-level tests will assert process exit code, report creation, benchmark validity, invalidation reasons, case classifications and consistency between JSON and Markdown. Tests will inspect externally visible reports rather than private helper implementation.
- The existing evaluation test module is the prior art for dataset loading, source metrics, pipeline-case capture, summary rendering and LLM capture behavior. New behavior should extend this seam rather than create a second benchmark runner.
- The existing retry convergence test module is the prior art for state-machine retry decisions. New convergence tests will use complete round records and assert observable stop/continue decisions plus convergence reasons.
- A regression test will reproduce the exact observed false-success pattern: the pipeline returns an `ESCALATE` output containing a system error after generation fails. The expected case classification is invalid/failed, not successful.
- A regression test will reproduce an intentional Agentic Router human handoff. The output remains valid, appears in route metrics and is excluded from retrieval-executed Recall denominators.
- A regression test will run without full LLM capture and still assert non-empty lightweight task metrics and 429 counters. It will also assert that prompt and response bodies are absent.
- A regression test will enable full capture for a selected case and verify that detailed data appears only for the selected case.
- A rate-limit test will use a fake clock or injected sleeper so delay and backoff behavior is deterministic and fast. It will assert bounded retries and recorded sleep duration without real waiting.
- A retry test will model three semantically equivalent missing-signal messages with different wording and no meaningful evidence gain. The pipeline must stop within the configured productive retry limit and emit a non-null reason.
- A retry test will confirm that a genuinely improved evidence set may continue within the configured limit, preserving useful targeted retry behavior.
- A reporting test will verify full/partial/zero recall counts, grouped miss tags, routing counts and latency groups using a small deterministic fixture with known denominators.
- A compact-diagnosis test will verify that only selected diagnostic fields are emitted and that prompt, response and full evidence bodies are not included.
- The final manual acceptance test is a 10-case cold smoke followed by a 100-case cold run. The 100-case run is acceptable only when it reports zero generation failures, zero unhandled model-rate-limit failures, no generic error answers and no missing termination reasons.
- The clean 100-case run must preserve at least the current observed retrieval quality thresholds: Recall@5 >= 0.89, Hit@5 >= 0.92 and MRR >= 0.77, measured on the documented retrieval denominator. Threshold changes require an explicit explanation of denominator differences.
- Performance acceptance focuses on clean outputs: no-retry retrieval P95 should not regress materially from 6.84 seconds, and no case should perform more than the configured productive retry limit without an explicit override and reason.

## Out of Scope

- Replacing the current LLM or embedding provider.
- Increasing provider quota, purchasing a higher rate-limit tier or changing external provider infrastructure.
- Large-scale redesign of PipelineRunner, RetrievalService, QuerySpec or the phase architecture.
- Replacing OpenSearch, Qdrant, the reranker or the RRF fusion strategy.
- Broad prompt rewriting across normalizer, selector, quality evaluator and generation.
- Production SLA guarantees based solely on local offline evaluation.
- Treating intentional high-risk human handoff as a retrieval failure.
- Full answer correctness grading by a separate judge model; this PRD focuses on benchmark validity, retrieval metrics and observable pipeline outcomes.
- Immediate tuning of every failed query. Retrieval tuning is conditional on first obtaining a clean benchmark.
- Database migration, Docker topology, authentication or frontend changes.

## Further Notes

- Source evidence for this PRD is the 2026-06-27 100-case cold run. It reported Recall@5 0.8933, Hit@5 0.92, MRR 0.7741, total P50/P95/P99 13.22/30.71/53.26 seconds and retrieval P50/P95/P99 0.16/15.14/27.42 seconds.
- The previous 100-case baseline reported Recall@5 0.6817, Hit@5 0.72, MRR 0.4834 and total P50/P95/P99 58.22/80.85/103.43 seconds. The quality improvement is meaningful, but the new latency comparison is contaminated by rapid 429 failures and must be repeated.
- Of 100 cases, 86 had full Recall@5, 6 partial recall and 8 zero recall. Three zero-recall cases never executed retrieval because the Agentic Router selected human handoff.
- Retry distribution was 75 no-retry retrieved cases, 22 retried cases and 6 cases with three retries. The three-retry group averaged 44.63 seconds and reached 55.40 seconds P95 under the observed sample.
- The latest run omitted full LLM capture as intended, which kept the JSON manageable, but this also exposed that lightweight task metrics currently disappear. The solution must preserve small artifacts without sacrificing failure visibility.
- After implementation, README and the development-command harness should be synchronized with the final CLI flags, validity semantics and report fields.
