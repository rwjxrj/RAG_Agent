# 05_COMMON_TASKS.md

## 结论
常见任务应先定位入口，再做最小范围修改。RAG、入库、工单学习和前端页面是本项目最常见的四类工作。

## 解释 RAG 回答为什么不准
先读：
- `.agent-harness/02_RAG_FLOW.md`
- `app/api/routes/reply.py`
- `app/api/routes/conversations.py`
- `app/services/answer_service.py`
- `app/services/phases/retrieve.py`
- `app/services/retrieval.py`
- `app/services/phases/generate.py`
- `app/services/phases/verify.py`

排查顺序：
1. 请求是否命中 intent cache 或 skip retrieval。
2. normalizer 是否产生错误 QuerySpec。
3. OpenSearch/Qdrant 是否有候选 chunk。
4. rerank/EvidenceSet 是否筛掉关键证据。
5. LLM prompt 是否包含足够证据。
6. reviewer 是否拦截或降级。

## 解释为什么搜不到知识库
先读：
- `app/services/ingestion.py`
- `app/services/source_loaders.py`
- `app/search/opensearch_client.py`
- `app/search/qdrant_client.py`
- `app/search/embeddings.py`
- `scripts/debug_retrieval_zero_chunks.py`
- `scripts/debug_qdrant.py`

检查点：
- source 文件是否被加载。
- Document/Chunk 是否写入 PostgreSQL。
- OpenSearch index 是否存在并有文档。
- Qdrant collection 是否存在并有向量。
- embedding 维度是否匹配。
- doc_type 过滤是否过窄。

## 添加或调整文档入库来源
先读：
- `README_zh.md` 的数据来源与持续学习章节。
- `app/api/routes/documents.py`
- `app/api/routes/admin.py`
- `app/services/source_loaders.py`
- `app/services/source_sync.py`

安全做法：
- 先支持一个明确格式。
- 保持 source JSON 向后兼容。
- 新增测试优先覆盖 loader。
- 不直接清理旧索引。

## [已归档] 调整工单学习流程（原 WHMCS）

以下是原 WHMCS 集成流程，仍可用但不再主动维护。新用户请优先使用文档入库。

先读：
- `app/api/routes/admin.py`
- `app/api/routes/tickets.py`
- `app/crawlers/whmcs.py`（遗留归档）
- `app/services/ticket_db.py`
- `app/services/ticket_sync.py`
- `scripts/import_whmcs_sql_dump_to_tickets.py`（遗留归档）
- `scripts/ingest_tickets_from_source.py`

流程：
1. 抓取或导入工单。
2. 写入 Ticket 表。
3. 前端审批 approved/rejected。
4. 导出 approved 到 `source/sample_conversations.json`。
5. 重新入库到 RAG 索引。

注意：
- 抓取外部系统前必须确认 base URL、cookie 或账号。
- SQL 导入先 dry run。
- 不绕过人工审批。

## 修改前端页面
先读：
- `frontend/src/App.tsx`
- `frontend/src/api/client.ts`
- 对应 `frontend/src/pages/*.tsx`

页面入口：
- Conversations：`ConversationList.tsx`, `ConversationDetail.tsx`
- Documents：`DocumentList.tsx`, `DocumentDetail.tsx`
- Crawl：`Crawler.tsx` 保留为 WHMCS 直达页面；主导航默认隐藏，常规网页内容抓取从 Documents 的“抓取网站/添加文档”进入，并可选择 JavaScript 渲染抓取。JS 渲染抓取默认用于指定单页，不做动态整站爬取。
- Dashboard：`Dashboard.tsx`
- Settings：`Settings.tsx`，模型、向量、提示词和回答流程配置；回答流程默认显示“回答模式”，内部 RAG/LLM 细开关折叠在高级设置中。
- Tickets：`TicketList.tsx`, `TicketDetail.tsx`
- Intents：`IntentList.tsx`
- Doc Types：`DocTypeList.tsx`
- Login：`Login.tsx`

验证：
- 优先 `cd frontend && npm run build`。
- 如启动 UI，再用浏览器烟测对应页面。

## 调整模型或 embedding 配置
先读：
- `.env.example`
- `app/core/config.py`
- `app/services/llm_config.py`
- `app/services/embedding_config.py`
- `app/services/llm_gateway.py`
- `app/search/embeddings.py`
- `frontend/src/pages/Settings.tsx`

注意：
- LLM 使用 OpenAI-compatible 接口。
- embedding 维度变化可能要求重建 Qdrant collection 或重新入库，必须先确认。
- 优先通过 Settings UI 或 DB config，环境变量是 fallback。

## 做只读项目理解
输出建议：
- 先给结论。
- 给服务图或流程图。
- 标注证据文件。
- 不改代码。
- 不运行会写数据的命令。

## 做文档-only 修改
可改：
- `AGENTS.md`
- `.agent-harness/*.md`
- README 类文档

验证：
- `git diff -- AGENTS.md .agent-harness`
- 确认中文、路径、待确认标注、未误写业务代码。
