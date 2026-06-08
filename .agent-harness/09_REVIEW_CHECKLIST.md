# 09_REVIEW_CHECKLIST.md

## 结论
这是 Codex 版 Stop Hook 的替代清单。每次完成修改前，用它做最后一轮自查：范围是否正确、是否触碰禁区、验证是否足够、harness 是否需要同步。

## 1. 范围检查
- 本次改动是否只解决一个清晰问题。
- 是否改了用户没有要求的业务逻辑。
- 是否批量格式化了无关文件。
- 是否覆盖或回退了用户已有未提交改动。
- 是否新增了未说明的文件。

## 2. 禁区检查
除非用户明确要求，否则不得改动：
- Docker / Compose / Nginx。
- Alembic 迁移。
- JWT、登录、API token、鉴权中间件。
- 数据删除、索引重建、数据卷清理。
- 新第三方依赖。
- `.claude/` hooks、Claude 专用 settings、全局 LSP 安装。

## 3. 安全检查
- 是否泄露 API key、JWT secret、cookie、WHMCS 凭据。
- 日志、debug metadata、前端文案是否可能暴露敏感信息。
- 是否运行了会访问外部 WHMCS 或消耗大量 LLM token 的命令。
- 是否运行了会写生产数据的命令。

## 4. RAG 质量检查
如果触碰 RAG 相关代码，必须说明：
- 查询入口：`reply`、`conversations`、stream 还是后台任务。
- 影响阶段：normalizer、retrieval、evidence、decision、generate、verify、output。
- 对 OpenSearch / Qdrant / PostgreSQL 的读写影响。
- 是否需要重新入库或重建索引。
- 是否需要同步 `.agent-harness/02_RAG_FLOW.md`。

## 5. 验证检查
按改动范围选择最窄验证：

| 改动 | 验证 |
|---|---|
| 文档 | 检查文件存在、目标 diff、关键字 |
| 后端服务 | 相关 `pytest tests/test_*.py -v` |
| RAG 编排 | `tests/test_answer_service.py`, `tests/test_orchestrator.py`, phase 测试 |
| 检索 | `tests/test_retrieval.py`, `tests/test_retrieval_planner.py` |
| 前端 | `cd frontend && npm run build` |
| 脚本 | 先 dry run 或只读参数检查 |

无法运行验证时，最终回复必须说明原因和后续建议命令。

## 6. Harness 同步检查
完成代码或配置改动后，检查：
- 服务拓扑是否变了：更新 `01_SERVICE_MAP.md`。
- RAG 链路是否变了：更新 `02_RAG_FLOW.md`。
- 命令是否变了：更新 `03_DEV_COMMANDS.md`。
- 工作规则是否变了：更新 `AGENTS.md` 或 `04_CHANGE_GUIDE.md`。
- 新坑是否可复现：更新 `07_FAILURE_MEMORY.md`。

## 7. 最终回复检查
最终回复必须包含：
- 结论。
- 改动文件。
- 验证方式和结果。
- 未完成或仍待确认项。
- 如果 harness 无需同步，说明原因。
