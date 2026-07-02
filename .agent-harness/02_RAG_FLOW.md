# 02_RAG_FLOW.md

## 结论
RAG 分两条主线：入库线把 source、URL、上传文件、工单样本转为 Document/Chunk，并写入 PostgreSQL、OpenSearch、Qdrant；查询线从 conversations 或 reply 进入 `AnswerService.generate()` 薄包装，再由 `PipelineRunner.run()` 统一执行 intent cache、Agentic Router、normalizer、检索、生成和校验状态。进入 RAG 时仍经 `RetrievalService.retrieve()`、EvidenceSet、LLM、`ReviewerGate.review()` 输出答案和引用。

## 入库流程

```mermaid
flowchart TD
  A["source/*.json"] --> B["scripts 或 /admin/ingest-from-source"]
  C["单 URL / 整站抓取"] --> D["/documents/fetch-from-url 或 /documents/crawl-website"]
  E["上传文件"] --> F["/documents/upload"]
  G["工单样本抓取（WHMCS 遗留）"] --> H["/admin/crawl-tickets"]
  H --> I["Ticket 表"]
  I --> J["人工审批 approved"]
  J --> K["/admin/ingest-tickets-to-file"]
  K --> A

  B --> L["source_loaders.load_all_docs"]
  D --> M["url_fetcher / web_crawler"]
  F --> N["file_parser"]
  L --> O["IngestionService.ingest_document"]
  M --> O
  N --> O

  O --> P["清洗与分块 prepare_document"]
  P --> Q["PostgreSQL Document/Chunk"]
  P --> R["Embedding Provider"]
  R --> S["Qdrant 向量索引"]
  P --> T["OpenSearch BM25 索引"]
```

## 入库入口

| 入口 | 说明 | 关键文件 |
|---|---|---|
| `POST /v1/admin/ingest` | 将请求中的 documents 交给 Celery 入库任务。 | `app/api/routes/admin.py`, `worker/tasks.py` |
| `POST /v1/admin/ingest-from-source` | 从 `source/` 同步加载 JSON 并逐条入库。 | `app/api/routes/admin.py`, `app/services/source_loaders.py` |
| `POST /v1/documents` | 前端/接口创建单个文档并立即入库。 | `app/api/routes/documents.py` |
| `POST /v1/documents/upload` | 上传 `.txt`、`.md`、`.pdf` 后解析并入库。 | `app/api/routes/documents.py`, `app/services/file_parser.py` |
| `POST /v1/documents/crawl-website` | 抓取网站页面，可选择直接入库；`render_js=true` 时用 Playwright 渲染 JavaScript 后抽取内容，前端默认限制为单页抓取。 | `app/api/routes/documents.py`, `app/services/web_crawler.py`, `app/services/url_fetcher.py` |
| `POST /v1/admin/ingest-tickets-to-file` | 将已批准工单导出到 `source/sample_conversations.json`。 | `app/api/routes/admin.py`, `app/services/ticket_sync.py` |
| `scripts/ingest_from_source.py` | CLI 方式从 source 入库。 | `scripts/ingest_from_source.py` |
| `scripts/ingest_tickets_from_source.py` | CLI 方式从 sample conversations 入库。 | `scripts/ingest_tickets_from_source.py` |

## 入库阶段说明
- 读取：`source_loaders.py` 支持 pages、articles、plans、sales_kb、sample_conversations 等格式；URL/整站抓取默认使用静态 HTML，显式开启 `render_js` 时使用 Playwright 获取渲染后的页面内容。前端 JS 渲染模式默认提交 `max_pages=1`、`max_depth=0`，避免浏览器整站抓取超时。
- 分类：部分入口会调用 `doc_type_classifier.resolve_doc_type`，是否启用受配置影响。
- 清洗/分块：`prepare_document()` 读取 `raw_text` / `raw_html` / `content`，HTML 通过 `_clean_html()` 去除 script/style/nav/footer/header/aside 并保留 heading 和链接；随后 `_chunk_by_semantic_boundaries()` 先按 heading/段落形成 parent chunks，再由 `_expand_to_semantic_units()` 形成 `PreparedChunk`。`chunk_parent_refs_enabled` 开启时会写入 `parent_ref` 和 `parent_heading`。
- 落库：Document、Chunk 写入 PostgreSQL。
- 关键词索引：OpenSearch 写入 chunk，用于 BM25。
- 向量索引：embedding provider 生成向量，Qdrant 写入 chunk 向量。
- 同步源文件：部分 Documents API 会调用 `source_sync` 同步到 source JSON。

## 函数级入库链路

```mermaid
flowchart TD
  A["admin.trigger_ingest()"] --> B["worker.tasks.ingest_documents_task.delay()"]
  B --> C["worker.tasks._ingest_one()"]
  D["admin.ingest_from_source()"] --> E["source_loaders.load_all_docs()"]
  E --> F["IngestionService.ingest_document()"]
  G["documents.create_document()"] --> F
  H["documents.upload_document()"] --> I["file_parser.extract_text_from_file()"]
  I --> F
  J["documents.crawl_website()"] --> K["web_crawler.crawl_website()"]
  K --> L["doc_type_classifier.resolve_doc_type()"]
  L --> F
  C --> F

  F --> M["prepare_document()"]
  M --> N["_clean_html() 可选"]
  M --> O["_chunk_by_semantic_boundaries()"]
  O --> P["_expand_to_semantic_units()"]
  F --> Q["_with_taxonomy_metadata()"]
  F --> R["可选 get_storage().put(raw/{checksum(url)}.txt)"]
  F --> S["按 source_url 查 existing Document"]
  S --> T{"checksum 未变且非 force_reindex?"}
  T -->|是| U["更新 title/doc_type/effective_date/metadata/source_file 并 flush"]
  T -->|否| V["新建或更新 Document"]
  V --> W["更新旧文档时删除旧 chunk 的 OpenSearch/Qdrant 索引和 DB Chunk"]
  W --> X["OpenSearchClient.ensure_index()"]
  V --> X
  X --> Y["QdrantSearchClient.ensure_collection(embedder.dimensions())"]
  Y --> Z["逐 PreparedChunk 创建 Chunk 并 flush"]
  Z --> AA["embedder.embed([chunk_text])"]
  AA --> AB["QdrantSearchClient.upsert_chunk()"]
  AB --> AC["OpenSearchClient.index_chunk()"]
  AC --> AD["db_session.commit()"]
```

### 入库已确认细节
- `IngestionService.ingest_document()` 的幂等键是 `Document.source_url` + cleaned content checksum。
- 内容未变化且未 `force_reindex` 时，不重新分块、embedding 或索引；只更新标题、文档类型、日期、metadata、source_file 并 `flush()`。
- 更新已有文档时，会先读取旧 chunk id，调用 `OpenSearchClient.delete_chunk()` 和 `QdrantSearchClient.delete_chunk()`，再删除 DB 中旧 Chunk。
- 新建或更新后，会先 `ensure_index()` 和 `ensure_collection(dimensions)`，再逐 chunk 写 DB、embedding、Qdrant、OpenSearch。
- 原文对象存储已确认：如果 raw 存在且 `get_storage()._get_client()` 可用，会写入 `raw/{_checksum(url)}.txt`，content type 为 `text/plain`。
- 事务边界已确认：`db_session.commit()` 在所有 chunk 的 embedding、Qdrant upsert、OpenSearch index 完成之后执行；函数内没有显式跨 PostgreSQL/OpenSearch/Qdrant 的补偿事务。
- 索引失败路径已确认：`OpenSearchClient.index_chunk()` 和 `QdrantSearchClient.upsert_chunk()` 的异常会向上抛出；删除旧索引时 `delete_chunk()` 内部是 best-effort 记录 warning。

### 向量模型切换与索引重建

```mermaid
flowchart LR
  A["Settings 保存 embedding 配置"] --> B{"向量空间指纹变化?"}
  B -->|否| C["索引保持 ready"]
  B -->|是| D["状态置为 required，暂停检索型问答和向量化入库"]
  D --> E["管理员确认重建"]
  E --> F["Celery 探测模型和实际维度"]
  F --> G["删除并重建 Qdrant collection"]
  G --> H["读取 PostgreSQL chunks，分批 embedding + upsert"]
  H --> I{"全部成功?"}
  I -->|是| J["状态置为 ready，恢复检索"]
  I -->|否| K["状态置为 failed，保持暂停并允许重试"]
```

- 向量空间指纹由 provider、model、dimensions、规范化 Base URL 组成；只修改 API key 不要求重建。
- 重建只读取 PostgreSQL `chunks` 并重写 Qdrant，不重新分块、不修改 PostgreSQL chunk，也不重建 OpenSearch。
- 固定意图或无需 retrieval 的直接回答不受维护状态影响；进入 `RetrievalService.retrieve()` 时会检查状态。
- worker 在删除 collection 前先调用 embedding 探测并校验维度，失败时保留原 collection；删除后发生失败则保持 `failed`，管理员需从头重试。

## 查询流程

```mermaid
flowchart TD
  A["前端 Conversations"] --> B["/v1/conversations/{id}/messages"]
  C["外部系统建议回复"] --> D["/v1/reply/generate"]
  B --> E["guardrails: injection check + sanitize"]
  D --> E
  E --> F["AnswerService.generate"]
  F --> G{"intent cache 命中?"}
  G -->|是| H["直接返回预设答案，debug 标记 Router skipped"]
  G -->|否| AR["AgenticRouter pre-RAG 工具选择"]
  AR -->|direct_response| AR1["PASS，无 citations"]
  AR -->|clarify| AR2["ASK_USER，返回追问"]
  AR -->|human_handoff| AR3["ESCALATE，转人工"]
  AR -->|rag_search/低置信/异常| I["语言识别 + normalizer -> QuerySpec"]
  I --> J{"skip_retrieval?"}
  J -->|是| K["返回 canned response"]
  J -->|否| L["PipelineRunner"]
  L --> M["RETRIEVE: RetrievalService"]
  M --> N["OpenSearch BM25"]
  M --> O["Embedding + Qdrant"]
  N --> P["RRF/simple merge + rerank"]
  O --> P
  P --> Q["EvidenceSet"]
  Q --> R["ASSESS / DECIDE"]
  R --> S["GENERATE: LLM Gateway"]
  S --> T["VERIFY: ReviewerGate"]
  T --> U["AnswerOutput"]
  U --> V["保存 assistant message、citations、debug_metadata"]
```

## 查询入口

| 入口 | 适用场景 | 持久化 |
|---|---|---|
| `POST /v1/reply/generate` | 任意工单/客服系统的一次性建议回复。 | 不创建会话，不保存消息。 |
| `POST /v1/conversations/{id}/messages` | 已创建会话中的同步问答。 | 保存 user message、assistant message、citations、debug_metadata。 |
| `POST /v1/conversations/{id}/messages:stream` | SSE 流式返回。 | 生成完成后保存 assistant message 和 citations。 |

流式入口除既有 `status`、`ping`、`content`、`citations`、`done`、`error` 事件外，可额外输出 `trace` 事件，事件数据来自 `debug_metadata.trace.nodes` 的节点摘要。旧客户端可以忽略未知 `trace` 类型，仍按原有答案事件完成渲染。

### 查询 debug_metadata
- `debug_metadata.timings` 会返回 `query_extract`、`retrieve`、`assess_evidence`、`rerank`、`generate`、`verify`、`total` 的秒级耗时；这些字段也会作为 `debug_metadata` 顶层字段返回，缺失阶段以 `0.0` 返回。
- 开启 `debug_llm_calls` 后，`debug_metadata.llm_call_log` 会按每次真实模型尝试记录 `task`、`model`、`attempt`、`is_fallback`、`duration_seconds`、`status` 和 `error_type`；成功记录继续包含 prompt、response、token 和成本信息。缓存命中不会计作真实模型尝试。
- 每次 LLM 调用必须通过作用域化的 `llm_task_context()` 设置 `task` 标签，调用结束后恢复上一个标签，避免 normalizer、evidence_evaluator、evidence_quality、generate 等任务在评测追踪中串台。
- `LLMGateway` 会根据 `current_llm_task_var` 为结构化任务自动透传 `response_format={"type":"json_object"}`，覆盖 normalizer、evidence_quality、evidence_selector、generate_reasoning、generate 等需要 JSON 解析的调用；该参数也会进入 LLM 缓存 key，避免 JSON/非 JSON 请求共用缓存。如果 OpenAI-compatible 网关明确拒绝 `response_format` 参数，同一模型会去掉该参数重试一次，作为 prompt-only 兼容降级。
- `debug_metadata.retry_count` 返回实际发生的检索重试次数，不改变 RAG 分支逻辑。
- `LLMGateway` 支持为 fallback model 配置独立的 API key 和 Base URL。当 `llm_fallback_api_key` 与 `llm_fallback_base_url` 同时为非空时，fallback attempt 使用独立 `AsyncOpenAI` 客户端；任一字段缺失时，当前实现继续使用主客户端请求 fallback model，不会把主 API key 发送到另一个 Base URL。
- 主、备用 `AsyncOpenAI` 客户端关闭 SDK 内部自动重试（`max_retries=0`），避免单次 provider 调用在内部重复消耗完整超时预算；模型 fallback 和 429 有界退避统一由 `LLMGateway` 显式控制，确保主模型失败后仍有机会切换备用供应商。
- 管理后台的 LLM 配置接口与设置页可以读写上述两个 fallback 字段。当前实现尚未在保存阶段强制校验两个字段必须成对提供，因此不完整配置会静默退回主客户端；修复任务记录在 `.scratch/llm-fallback-provider-hardening/issues/`。
- 当前 LLM 响应缓存 key 仍以主请求模型、消息和生成参数为主，未区分 fallback provider 端点；独立 fallback 客户端的显式关闭和缓存隔离也属于待修复项。
- `debug_metadata.agentic_router` 是可选字段：intent cache 命中时只标记 `skipped=true` 和 `reason=intent_cache_hit`；Router 执行时记录 `route`、`tool`、`reason`、`confidence`、`skipped` 和 `fallback_to_rag`。顶层 API 字段不因该字段改变。
- `debug_metadata.trace` 是可选执行快照：记录 intent、Agentic Router 选择、稳定逻辑节点路径、工具摘要和毫秒级耗时，用于前端流程可视化和调试，不改变 RAG 决策、答案生成或顶层 API 字段。

### Agentic Router 接入点

在 guardrails 通过后，`AnswerService.generate()` 将请求交给 `PipelineRunner.run()`；Runner 的 `INTENT_CACHE` 未命中后进入 `AGENTIC_ROUTE`。

- `rag_search`：继续现有 `query extract -> retrieve -> assess evidence -> retry -> generate -> verify`；如果 `ASSESS_EVIDENCE` 因质量评估 LLM 不可用返回 `quality_llm_failed`，编排器不会重复检索，直接进入 `DECIDE`，避免同一批证据上反复执行无效 retrieve/assess。
- `direct_response`：用于问候和能力说明，直接返回 `PASS`，不检索。
- `clarify`：信息不足时返回 `ASK_USER` 和追问。
- `human_handoff`：账号、账单、安全、删除、退款执行等人工处理请求返回 `ESCALATE`。

低置信或 Router 异常必须回退 `rag_search`，不影响现有 RAG 可用性。`app/services/decision_router.py` 仍是检索后的证据决策器，不与本 Router 混用。

## 函数级查询链路

```mermaid
flowchart TD
  A["reply.generate_suggested_reply()"] --> B["guardrails.check_injection() / sanitize_user_input()"]
  C["conversations.send_message()"] --> B
  D["conversations.send_message_stream()"] --> B
  C --> E["保存 user Message"]
  D --> E
  B --> F["conversation_context.truncate_for_pipeline()"]
  F --> G["AnswerService.generate()"]
  G --> H["match_intent()"]
  H -->|命中| I["直接 AnswerOutput(PASS, intent.answer)"]
  H -->|未命中| AR["AgenticRouter.route()"]
  AR -->|direct_response| AR1["AnswerOutput(PASS, 无 citations)"]
  AR -->|clarify| AR2["AnswerOutput(ASK_USER, followup_questions)"]
  AR -->|human_handoff| AR3["AnswerOutput(ESCALATE)"]
  AR -->|rag_search/低置信/异常回退| J["detect_language() 可选"]
  J --> K["normalizer.normalize() -> QuerySpec 可选"]
  K --> L{"QuerySpec.skip_retrieval?"}
  L -->|是| M["canned response"]
  L -->|否| N["OrchestratorContext（类型化阶段字段）"]
  N --> O["PipelineRunner 主循环"]
  O --> P["PipelineRunner.execute() 直接调用 phase"]
  P --> Q["execute_retrieve()"]
  Q --> R["build_retrieval_plan_for_attempt()"]
  R --> S["RetrievalService.retrieve()"]
  S --> T["execute_assess_evidence()"]
  T --> U["execute_decide()"]
  U --> V{"decision lane"}
  V -->|PASS / CANDIDATE_VERIFY| W["execute_generate()"]
  V -->|ASK_USER| X["output_builder.build_output(ASK_USER)"]
  V -->|ESCALATE| Y["output_builder.build_output(ESCALATE)"]
  W --> Z["ReviewerGate.review() via execute_verify()"]
  Z --> AA{"reviewer status"}
  AA -->|PASS/TRIM_UNSUPPORTED/DOWNGRADE_LANE| AB["output_builder.build_output(DONE)"]
  AA -->|ESCALATE| Y
  AA -->|ASK_USER 可 targeted retry| Q
  AA -->|ASK_USER 不重试| X
  AB --> AC["AnswerOutput"]
  X --> AC
  Y --> AC
  AC --> AD["conversation 入口保存 assistant Message/Citation/debug_metadata"]
```

## 函数级检索链路

```mermaid
flowchart TD
  A["execute_retrieve()"] --> B["plan_retry() 可选"]
  B --> C["build_retrieval_plan_for_attempt()"]
  C --> D["resolve_retrieval_query()"]
  D --> E{"QuerySpec 存在?"}
  E -->|是| F["_resolve_queries_from_query_spec()"]
  E -->|否| G["query_rewriter.rewrite_for_retrieval() 可选"]
  F --> H["_build_plan_from_inputs() -> RetrievalPlan"]
  G --> H
  H --> I["RetrievalService.retrieve()"]
  I --> J["_fetch_parallel_candidates()"]
  J --> K["_fetch_bm25_bundle() -> _search_opensearch_safe()"]
  J --> L["_fetch_vector_bundle() -> _embed_query_safe() -> _search_qdrant_safe()"]
  K --> M["_apply_search_calibration()"]
  L --> M
  M --> N{"settings.retrieval_fusion"}
  N -->|rrf| O["_merge_with_rrf()"]
  N -->|simple| P["_merge_simple()"]
  O --> Q["extra/diversity chunks 合并"]
  P --> Q
  Q --> R["reranker.rerank()"]
  R --> S["_build_candidate_pool()"]
  R --> T["_apply_rerank_calibration()"]
  T --> U["conversation score penalty / exclude_patterns"]
  U --> V["evidence_selector.select_evidence_for_query() 可选"]
  V --> W["_retain_supporting_conversation_chunk()"]
  W --> X["build_evidence_set()"]
  X --> Y["ensure_doc_types 最小数量补齐可选"]
  Y --> Z["EvidencePack(chunks, retrieval_stats, retrieval_plan, candidate_pool, evidence_set)"]
```

### QuerySpec 到 RetrievalPlan 的映射已确认
- `build_retrieval_plan_for_attempt()` 是运行时入口。
- `resolve_retrieval_query()` 决定本轮 selected query：优先 retry suggested query，其次 verify targeted retry 的 explicit override，其次 fallback rewrite candidate，最后 base query。
- 有 QuerySpec 时，`_resolve_queries_from_query_spec()` 优先使用 `keyword_queries[0]` 和 `semantic_queries[0]`；无 QuerySpec 且启用 `query_rewriter_use_llm` 时，调用 `rewrite_for_retrieval()` 生成 keyword/semantic/profile。
- `retrieval_profile`、`answer_type`、`doc_type_prior`、active hypothesis、hard requirements、required evidence、evidence families 会共同推导 preferred doc types、authoritative/supporting doc types、page_kind/product_family hints、fetch_n、rerank_k 和 budget_hint。
- pricing/policy/troubleshooting profile 会提高 fetch/rerank 预算；pricing 会额外倾向包含 `tos`。
- `evidence_selector` 即使启用 `evidence_selector_use_llm`，也只在高价值覆盖场景调用 LLM：hard requirements、多个 required evidence、中高风险或复杂 answer_shape。`policy` / `exact` 只有在不是低风险单弱证据 direct_lookup 时才触发；这是因为 normalizer 会把大量简单 FAQ 标成 `policy + exact + policy_language`。无 required evidence、单个弱 required evidence、低风险 direct_lookup 等普通检索直接使用 rerank/top-k 加结构化文档重平衡。`retrieval_stats.evidence_selector` 会记录 `used_llm`、`skip_reason` 或 `trigger_reason`，用于评测统计 selector 是否被收窄。

## 函数级生成与校验链路

```mermaid
flowchart TD
  A["execute_generate()"] --> B["_apply_relevance_check()"]
  B --> C["prior citation injection 可选"]
  C --> D["build_answer_plan()"]
  D --> E["format_evidence_for_prompt()"]
  E --> F{"简单直答 fast-path?"}
  F -->|是| G["跳过 generate_reasoning，记录 reasoning_prepass.skipped"]
  F -->|否| H["_run_reasoning_prepass() 可选"]
  G --> I["get_system_prompt() + format_answer_plan_instruction()"]
  H --> I
  I --> J["LLMGateway.chat()"]
  J --> K["parse_llm_response()"]
  K --> L["apply_answer_plan()"]
  L --> M["self_critic.critique() 可选"]
  M --> N["必要时 generate_regenerate"]
  N --> O["PhaseResult(answer, citations, followup, confidence, generated_decision)"]
  O --> P["execute_verify()"]
  P --> Q["ReviewerGate.review()"]
  Q --> R["Orchestrator._apply_result(VERIFY)"]
  R --> S["output_builder.build_output()"]
```

### 生成阶段 reasoning prepass fast-path
- `generate_reasoning` 默认仍开启，但简单直答场景可跳过预推理，避免每条低风险 FAQ 多一次 LLM 调用。
- 跳过条件要求：evidence quality 已通过、缺失信号为空、证据 chunk 数不超过 `generate_reasoning_fastpath_max_evidence_chunks`、无会话上下文依赖、风险等级不是 medium/high、answer_shape 为 `direct_lookup` / `short_answer` / `yes_no`，且无 hard requirements。
- pricing、direct_link、account、高风险、多方案/比较、会话上下文相关或 evidence quality 未通过的 case 继续执行 `generate_reasoning`；低风险 policy FAQ 如果满足简单直答条件，可以走 fast-path。
- `debug_metadata.reasoning_prepass` 会记录 `{skipped, reason}`，用于离线评测统计 `generate_reasoning` 是否因 fast-path 被省略。
- 配置开关：`generate_reasoning_skip_simple_lookup=false` 可关闭该 fast-path，恢复原有预推理路径。

### Reviewer 失败后的状态机已确认
- `PASS`：进入 `DONE`。
- `TRIM_UNSUPPORTED`：如有 `trimmed_answer`，替换答案后进入 `DONE`。
- `DOWNGRADE_LANE`：如有 `trimmed_answer`，替换答案并降级 lane 后进入 `DONE`。
- `ESCALATE`：进入 `ESCALATE` 输出。
- `ASK_USER`：如果 `targeted_retry_enabled`、仍可重试、未用过 verify targeted retry、`retry_reason` 属于 `type_mismatch` / `overclaim` / `unsupported_exact` 且有 `suggested_queries`，则设置 `retry_query_override` 并回到 `RETRY_RETRIEVE`；否则进入 `ASK_USER` 输出。
- `ASSESS_EVIDENCE` 失败但 `missing_signals` 包含 `quality_llm_failed` 时，视为质量评估基础设施不可用，而不是证据缺失；该场景不触发 `RETRY_RETRIEVE`。
- 首轮 `ASSESS_EVIDENCE` 对 `policy_language` 的 `direct_lookup` / `yes_no` / `short_answer` 出现质量门假阴性时，会以 `evidence_quality_verify` 任务标签对前三条权威政策证据执行一次聚焦复核。只有模型返回的 `chunk_id` 存在、逐字引用不少于 8 个字符且经空白归一化后确实包含在原 chunk 中，才修正 `policy_language` 覆盖并放行；解析异常、伪造引用、基础设施失败及后续检索轮次均保持原重试行为。
- 聚焦复核结果写入 retry diagnostics 的 `verification_applied`、`verification_chunk_id`、`verification_quote` 和 `verification_reason`；每个请求最多调用一次。`evidence_quality_verify` 与其他结构化轻量任务一样启用 JSON response format 并进入 LLM attempt 遥测。
- 任一 phase 抛异常时，`PipelineRunner` 捕获后通过 `build_output(ESCALATE)` 结束。

### Retry 收敛规则

`should_stop_retry()` 在每次 `ASSESS_EVIDENCE` 后检查以下条件，任一满足即停止重试并设置 `convergence_reason`：

1. **信号稳定**：最近两轮 `missing_signals` 完全相同且 `source_set_changed=False`，重试不会带来新证据。→ `same_missing_signals_no_new_sources`
2. **来源饱和**：`source_set_changed=False`（来源集合未变化），重试已饱和。→ `source_set_unchanged_retry_saturated`
3. **已覆盖预期类型**：top-5 evidence chunks 已覆盖 QuerySpec 的 `doc_type_prior` 中所有 expected doc types。→ `top_sources_cover_expected`
4. **基础设施连续失败**：最近两轮均为 infrastructure failure（selector/quality LLM）。→ `consecutive_infrastructure_failures`
5. **质量门连续失败**：最近 N 轮（默认 3）gate 均未通过。→ `consecutive_gate_failures_exhausted`
6. **软矛盾**：LLM 返回 `gate_pass=True` 但 code override 强制 `gate_pass=False`，连续 2 轮。→ `soft_contradiction_llm_agrees_evidence_sufficient`

**硬上限**：`max_attempts = max(1, configured_max_retrieval_attempts)`，配置值即硬上限。达到上限且 gate 仍未通过时设置 `max_retries_exhausted`。

**early_output 终态回写**：PipelineRunner 返回 early_output 前，将 `termination_reason` 和 `stage_reasons` 回写到 `debug` dict，确保下游（评测、遥测）可见。

## 关键组件
- `AnswerService`：稳定 API 薄包装，仅委托 `PipelineRunner.run()`。
- `match_intent`：意图缓存命中时跳过检索和 LLM。
- `AgenticRouter`：intent cache 未命中后、固定 RAG 流程前的轻量工具选择器；支持 `rag_search`、`direct_response`、`clarify`、`human_handoff`，低置信或异常默认回退 `rag_search`。
- `normalize_query`：生成 QuerySpec，包含 canonical query、required evidence、retrieval profile 等。
- `PipelineRunner`：唯一编排与依赖所有者，按 INTENT_CACHE、AGENTIC_ROUTE、NORMALIZE、SKIP_RETRIEVAL、RETRIEVE、ASSESS_EVIDENCE、DECIDE、GENERATE、VERIFY 阶段推进。
- `RetrievalService`：执行 BM25 + 向量检索、RRF/simple 融合、rerank、EvidenceSet 构建。
- `LLMGateway`：调用 OpenAI-compatible chat completions。
- `ReviewerGate`：生成后校验和风险拦截。
- `output_builder`：构建最终 AnswerOutput。

## 仍待代码确认
- `app/core/storage.py` 的具体后端实现、MinIO bucket 创建和失败日志策略仍需单独确认。
- `documents.delete_document()` 的删除路径已知是 best-effort 清理 OpenSearch/Qdrant 后删除 DB 和同步 source JSON，但是否需要离线修复 orphan index 的运维脚本仍待确认。
- `scripts/ingest_tickets_from_source.py` 与 `scripts/import_whmcs_sql_dump_to_tickets.py` 的 CLI 参数、事务边界和重复导入策略仍待逐文件确认。
- `ReviewerGate.review()` 内部 claim-level 规则、soft contract 和 final lane 计算细节仍待单独展开。
