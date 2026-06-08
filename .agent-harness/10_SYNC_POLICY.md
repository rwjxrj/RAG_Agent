# 10_SYNC_POLICY.md

## 结论
当前 harness 不会随着代码变动实时自动更新。它采用“代码变更触发人工/Codex 同步”的策略：每次改到关键模块时，必须判断对应 harness 文档是否需要更新。

## 同步原则
- 代码是事实来源，harness 是导航文档。
- 文档与代码冲突时，以代码为准，更新文档。
- 不为了文档同步扩大业务改动。
- 没有改到相关链路时，不强行更新 harness。
- 同步与否都应在最终回复中说明。

## 同步触发表

| 变动范围 | 必看文档 | 同步条件 |
|---|---|---|
| `app/main.py`, 路由注册 | `00_PROJECT_MAP.md`, `01_SERVICE_MAP.md` | 新增/移除路由或中间件 |
| `docker-compose.yml`, Dockerfile, nginx | `01_SERVICE_MAP.md`, `03_DEV_COMMANDS.md` | 服务、端口、依赖、命令变化 |
| `app/api/routes/reply.py`, `conversations.py` | `02_RAG_FLOW.md`, `05_COMMON_TASKS.md` | 查询入口、持久化、返回结构变化 |
| `app/services/answer_service.py` | `02_RAG_FLOW.md` | RAG 编排顺序、intent、normalizer、输出变化 |
| `app/services/orchestrator.py` | `02_RAG_FLOW.md` | 状态机、retry、ASK_USER/ESCALATE/DONE 行为变化 |
| `app/services/phases/` | `02_RAG_FLOW.md` | retrieve/assess/decide/generate/verify 任一阶段语义变化 |
| `app/services/retrieval.py` | `02_RAG_FLOW.md`, `06_DEBUG_CHECKLIST.md` | BM25/vector/rerank/EvidenceSet 变化 |
| `app/services/ingestion.py` | `02_RAG_FLOW.md`, `06_DEBUG_CHECKLIST.md` | 清洗、分块、embedding、索引、事务边界变化 |
| `app/search/` | `02_RAG_FLOW.md`, `06_DEBUG_CHECKLIST.md` | OpenSearch/Qdrant/embedding/reranker 行为变化 |
| `worker/`, `scripts/` | `03_DEV_COMMANDS.md`, `05_COMMON_TASKS.md` | 新增命令、参数、任务、dry run 方式变化 |
| `frontend/src/App.tsx`, `frontend/src/api/client.ts` | `00_PROJECT_MAP.md`, `05_COMMON_TASKS.md` | 页面路由、API client、认证 header 变化 |
| `frontend/src/pages/` | `05_COMMON_TASKS.md` | 页面职责、主要工作流变化 |
| 新故障或排查经验 | `06_DEBUG_CHECKLIST.md`, `07_FAILURE_MEMORY.md` | 可复现、可迁移到后续任务 |

## 同步流程
1. 完成代码改动后，看触发表。
2. 如果命中，打开对应 harness 文档。
3. 用真实代码函数名更新，不写猜测。
4. 不确定的地方标注“待代码确认”。
5. 文档-only 验证：检查目标 diff 和关键字。

## 最终回复格式

```text
Harness 同步：
- 已同步：path，原因
- 无需同步：原因
- 待确认：如有
```

## 当前状态
- Harness 是手动/Codex 维护，不是实时自动系统。
- 未配置 hook、CI 或守护进程。
- 如未来需要自动提醒，应先设计轻量只读检查脚本，并经用户确认后再添加。
