# 04_CHANGE_GUIDE.md

## 结论
Codex 在本项目中应按“先读、再画流程、再小步改、最后窄验证”的方式工作。没有明确要求时，不改 Docker、迁移、认证和业务核心编排。Harness Starter 的 Hook 自动化在这里改为显式流程，由 Codex 在每次任务中主动执行。

## Harness Starter 等价生命周期

| Harness Starter 概念 | Claude Code 形态 | 当前 Codex 适配 |
|---|---|---|
| PreToolUse | 工具调用前安全拦截 | 修改前读取 `AGENTS.md`，执行 `git status --short`，说明将改/不改文件 |
| PostToolUse | 编辑后自动格式化/检查 | 不自动格式化；只运行与改动相关的窄验证 |
| Stop | 响应前审查变更 | 按 `.agent-harness/09_REVIEW_CHECKLIST.md` 做收尾审查 |
| SessionStart | 注入状态/历史 | 新任务先读 `AGENTS.md`、相关 harness 文档和当前 git 状态 |
| PreCompact | 压缩前保存状态 | 长任务结束前把关键发现写入文档或最终回复 |
| .harness-state | 模式/阶段状态 | 由 `AGENTS.md` 中的 Harness 模式/阶段约定人工选择 |

## 标准工作流

1. 读取 `AGENTS.md` 和相关 `.agent-harness/` 文档。
2. 执行 `git status --short`，识别已有未提交改动。
3. 只读相关文件，优先使用项目已有文档和代码证据。
4. 对陌生模块先画短流程。
5. 修改前说明将改哪些文件和为什么。
6. 使用小补丁，只改任务范围内文件。
7. 运行最窄验证，或说明为什么不能运行。
8. 检查是否需要同步 `.agent-harness/`。
9. 最终回复列出改动文件、验证方式、风险和下一步。

## 修改前必须说明

```text
将改动：
- path/to/file: 原因

暂不改动：
- path/to/file: 原因
```

## 默认禁止
- 批量格式化无关文件。
- 删除已有功能。
- 新增第三方依赖。
- 修改 Docker、数据库迁移、认证逻辑。
- 清理数据卷、删除数据库、重置 git。
- 把 Claude Code `.claude/hooks` 原样复制进项目。
- 为了“适配模板”而新增 Claude 专用目录、npm 包发布配置或全局 LSP 安装。

## 可以优先做的安全改动
- 增补中文文档和项目地图。
- 为已有逻辑添加窄测试。
- 修复明确 bug 的最小代码路径。
- 调整前端单页文案或小范围交互。
- 增加 debug 输出时必须可控，避免泄露密钥或用户隐私。

## RAG 流程改动规则
- 先明确入口：`/reply/generate`、`/conversations/{id}/messages`、Documents API、Admin ingest、脚本。
- 先画当前流程，再说明改动点。
- 检索相关改动要说明对 BM25、向量、rerank、EvidenceSet 的影响。
- 生成相关改动要说明对 prompt、LLM gateway、reviewer、debug_metadata 的影响。
- 入库相关改动要说明对 PostgreSQL、OpenSearch、Qdrant 的写入影响。
- 涉及重建索引、重新入库或清理数据时必须先确认。

## 前端改动规则
- 入口优先看 `frontend/src/App.tsx` 和 `frontend/src/api/client.ts`。
- 页面改动只触达对应 `frontend/src/pages/*.tsx`。
- 不做全局设计重写。
- 不引入新 UI 依赖。
- 文案保持中文一致性。

## 后端改动规则
- 路由只负责协议、认证、请求校验和调用服务。
- 业务逻辑优先放在 `app/services/`。
- 检索和索引逻辑优先放在 `app/search/` 或 `app/services/retrieval.py`。
- 配置读取优先通过 `app/core/config.py` 或已有 DB config/cache 服务。
- 不把密钥写入日志、debug metadata 或前端。

## 测试选择

| 改动范围 | 优先验证 |
|---|---|
| 文档 | `git diff -- AGENTS.md .agent-harness` |
| 单个后端服务 | 对应 `tests/test_*.py -v` |
| RAG 编排 | `tests/test_answer_service.py`, `tests/test_orchestrator.py`, 相关 phase 测试 |
| 检索 | `tests/test_retrieval.py`, `tests/test_retrieval_planner.py`, `tests/test_opensearch_client_phase2.py` |
| 入库 | `tests/test_ingestion_chunking_phase2.py`, `tests/test_source_loaders.py` |
| 前端 | `cd frontend && npm run build` |

## 最终回复模板

```text
结论：已完成/未完成什么。

改动文件：
- ...

验证：
- ...

风险/待确认：
- ...

下一步建议：
- ...
```

## Harness 同步判断

| 代码变动 | 需要同步 |
|---|---|
| `app/services/answer_service.py`, `orchestrator.py`, `phases/`, `retrieval.py` | `.agent-harness/02_RAG_FLOW.md` |
| `app/api/routes/*.py` 新增/改接口 | `.agent-harness/02_RAG_FLOW.md` 或 `.agent-harness/05_COMMON_TASKS.md` |
| `docker-compose.yml`, `Dockerfile`, `nginx/` | `.agent-harness/01_SERVICE_MAP.md`, `.agent-harness/03_DEV_COMMANDS.md` |
| `scripts/`, `Makefile`, `frontend/package.json`, `pyproject.toml` | `.agent-harness/03_DEV_COMMANDS.md` |
| 新增故障排查经验 | `.agent-harness/06_DEBUG_CHECKLIST.md`, `.agent-harness/07_FAILURE_MEMORY.md` |
