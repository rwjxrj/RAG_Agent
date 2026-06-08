# 06_DEBUG_CHECKLIST.md

## 结论
调试时先判断问题属于服务启动、认证、入库、检索、生成、前端还是外部爬虫。不要直接重建索引、清库或改配置；先收集最小证据。

## 通用检查
- 当前分支和改动：`git status --short`
- 服务状态：`docker-compose ps`
- API 日志：`docker-compose logs api`
- Worker 日志：`docker-compose logs worker`
- 环境变量：只检查 key 是否存在，不输出密钥值。
- 最近改动：只看与问题相关的 diff。

## API 启动失败
检查：
- `app/main.py` lifespan 中缓存刷新是否失败。
- `.env` 是否设置 `JWT_SECRET`。
- `DATABASE_URL`、`REDIS_URL`、`OPENSEARCH_HOST`、`QDRANT_HOST` 是否与运行环境一致。
- Alembic 是否已升级到 head。

避免：
- 不要直接改迁移。
- 不要跳过认证逻辑。

## 前端访问失败
检查：
- Docker 前端：`http://localhost:5174`
- 本地 Vite：通常 `http://localhost:5173`
- `frontend/src/api/client.ts` 中 API base 和 headers。
- 浏览器请求是否返回 401、404、500。

常见原因：
- 未登录或 token 失效。
- `API_KEY` / `ADMIN_API_KEY` 与后端不一致。
- API 服务未启动。

## 登录或认证失败
检查：
- 是否已运行迁移 011 之后的管理员创建命令。
- `JWT_SECRET` 是否变更导致旧 token 失效。
- 请求是否使用 Bearer JWT、`X-API-Key` 或 `X-Admin-API-Key`。
- `app/core/auth.py` 和 `app/api/routes/auth.py`，具体逻辑待代码确认。

禁止：
- 未经确认不要放宽认证。
- 不要把密钥写入文档、日志或前端代码。

## 入库无数据
检查：
- `source/` 是否存在目标 JSON 或 SQL。
- JSON 格式是否符合 `source_loaders.py` 支持的 pages、articles、plans、sales_kb、sample_conversations。
- `make ingest-dry` 是否能读取数据。
- Document/Chunk 是否写入 PostgreSQL。
- worker 是否在线，Redis broker 是否可用。

下一步：
- 先用 dry run 或 loader 测试。
- 再检查 OpenSearch/Qdrant 是否有对应 chunk。

## OpenSearch 搜不到
检查：
- OpenSearch 服务健康。
- `OPENSEARCH_HOST` 是否正确。
- index 名称是否为 `support_docs` 或配置覆盖值。
- 入库时是否写入 OpenSearch。
- doc_type 过滤是否过窄。

相关文件：
- `app/search/opensearch_client.py`
- `app/services/retrieval.py`

## Qdrant 搜不到
检查：
- Qdrant 服务是否可访问 `127.0.0.1:6333`。
- collection 是否为 `support_chunks` 或配置覆盖值。
- embedding provider 是否正常返回向量。
- embedding 维度与 collection 是否一致。
- 入库时是否写入 Qdrant。

相关文件：
- `app/search/qdrant_client.py`
- `app/search/embeddings.py`
- `app/services/embedding_config.py`

## 回答没有引用或引用错误
检查：
- retrieval 是否返回 EvidencePack。
- EvidenceSet 是否为空。
- reranker 是否只返回低质量 chunk。
- citations 是否在 `AnswerOutput` 中构建。
- conversations API 是否保存 Citation。

相关文件：
- `app/services/retrieval.py`
- `app/services/evidence_set_builder.py`
- `app/services/output_builder.py`
- `app/api/routes/conversations.py`

## 回答被拦截、ASK_USER 或 ESCALATE
检查：
- decision router 输出。
- evidence quality gate。
- reviewer high risk patterns。
- policy/tos doc_type 是否缺失。
- debug_metadata 中的 decision、confidence、followup_questions。

相关文件：
- `app/services/decision_router.py`
- `app/services/reviewer.py`
- `app/services/phases/decide.py`
- `app/services/phases/verify.py`

## WHMCS 抓取失败
检查：
- `WHMCS_BASE_URL`、list path、login path。
- cookies 是否过期。
- 是否需要 TOTP。
- Playwright 浏览器是否可用。
- 是否被远端风控或网络阻断。

避免：
- 不要反复高频抓取生产站。
- 不要把 cookies 输出到日志或文档。

## MinIO 或上传失败
检查：
- `minio` 和 `minio-init` 是否启动。
- bucket `support-ai-docs` 是否存在。
- `OBJECT_STORAGE_URL`、access key、secret key 是否匹配。
- 上传接口是否实际写 MinIO，具体路径待代码确认。

## 何时停止并询问
- 需要删除或重建索引。
- 需要清空数据库或数据卷。
- 需要修改迁移、认证、Docker。
- 需要安装依赖。
- 需要访问外部 WHMCS 或消耗大量 LLM token。
