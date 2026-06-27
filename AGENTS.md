# AGENTS.md

## 结论
这是一个企业客服 RAG 系统。Codex 在本项目中应优先做项目理解、流程梳理和小步可回退修改；默认不要大规模重构、不要复制 Claude Code hooks、不要安装依赖、不要修改业务代码以外的文件。Harness Starter 在本项目中适配为”Codex 可执行的文档化 harness”，而不是 Claude Hook 自动化。

## 架构状态（2026-06-27）

已完成的架构改进：

| 改进项 | 改动 | 状态 |
|---|---|---|
| 标准化模块 | `app/services/normalization.py` 单一来源，消除 8 个函数的跨模块重复 | ✅ |
| QuerySpec 拆分 | 46 字段拆分为 5 个子数据类（QueryIntent、RetrievalHints、ClarificationNeeds、AnswerContract、QuerySlots） | ✅ |
| Retrieval 拆分 | `retrieve()` 486 行拆分为 7 个辅助方法 + BudgetConfig/DocTypeStrategy 数据类 | ✅ |
| 类型化 Phase 输出 | 新增 RetrievePhaseOutput、GeneratePhaseOutput、VerifyPhaseOutput、OrchestratorDebug | ✅ |
| 运行时注入消除 | `_last_reviewer_result` 移入 OrchestratorContext 正式字段 | ✅ |
| 计时统一 | PipelineRunner 成为唯一计时来源 | ✅ |
| 模型路由统一 | 所有模型路由通过 PipelineRunner | ✅ |
| 依赖注入收口 | Retrieval、LLM、Reviewer、Agentic Router、Intent Matcher、Normalizer 和 Language Detector 由 PipelineRunner 统一持有 | ✅ |
| 预处理纳入状态机 | Intent Cache、Agentic Router、语言识别和查询标准化纳入 PipelineRunner 状态推进 | ✅ |
| PipelineRunner 合并 | `PipelineRunner` 成为唯一编排实现；`Orchestrator` 仅保留为兼容别名 | ✅ |

阶段 2 PRD（`.scratch/orchestrator-refactor/PRD-phase2.md`）中的任务 5、6、7 已完成。后续修改查询链路时，应以 `PipelineRunner`、`OrchestratorContext` 和 `app/services/phases/` 为当前架构边界，不再把 `Orchestrator` 视为独立实现。

## Codex 适配原则
- 本项目主要使用 Codex，不以 Claude Code 为运行前提。
- 参考 Harness Starter 的思想：把项目约束、服务地图、RAG 流程、常用命令、变更指南、调试清单和失败记忆沉淀为仓库内文档。
- 不原样复制 `.claude/hooks`，不依赖 hook 自动拦截；Codex 每次操作前应主动读取并遵守本文件和 `.agent-harness/` 文档。
- Harness Starter 的 Hook 生命周期在本项目中映射为 Codex 手动流程：变更前检查、编辑后自查、最终验证、失败记忆沉淀。
- 不安装 LSP、不新增 npm 分发配置、不新增 Claude 专用技能，除非用户明确要求。
- 所有回答、文档和说明优先使用中文。
- 先给结论，再解释。
- 对陌生模块先画流程，不要直接改代码。

## 项目定位
这是一个企业客服 RAG 系统，包含 FastAPI 后端、React 前端、PostgreSQL、Redis、Celery、OpenSearch、Qdrant、Playwright 爬虫和知识库导入流程。

## 本地约定
- 项目目录：`D:\ai_project\RAG_Search`
- 本地 git 目录：`D:\develop\Git`
- 主要项目文档：`README.md`。如历史说明中提到 `README_zh.md`，以当前 `README.md` 为准。
- 轻量 harness 文档目录：`.agent-harness/`

## Harness 模式
默认模式为 `full`，适用于常规开发和文档维护。

| 模式 | 使用场景 | 要求 |
|---|---|---|
| `full` | 默认模式，常规任务 | 完整读取相关 harness 文档，修改前说明范围，修改后做窄验证 |
| `tweak` | 文案、小范围 UI、文档微调 | 仍需检查 git 状态和目标文件 diff |
| `hotfix` | 明确紧急修复 | 保持最小改动，优先修复症状并记录后续补充验证 |

## Harness 阶段
每次任务按当前阶段选择检查强度：

| 阶段 | 说明 |
|---|---|
| `design` | 只理解、画流程、写方案，不改业务代码 |
| `build` | 实施小步变更并运行最窄验证 |
| `fix` | 修复 bug，先复现或定位，再改动 |
| `docs` | 更新 `.agent-harness/`、README 或 AGENTS，不运行业务服务 |

## 阅读顺序
理解项目时按以下顺序阅读：
1. `AGENTS.md`
2. `README.md`；如果不存在，读取 `README_zh.md`
3. `docker-compose.yml`
4. `.env.example`
5. `.agent-harness/00_PROJECT_MAP.md`
6. `.agent-harness/01_SERVICE_MAP.md`
7. `.agent-harness/02_RAG_FLOW.md`
8. `.agent-harness/08_CODEX_HARNESS_ADAPTER.md`
9. `.agent-harness/09_REVIEW_CHECKLIST.md`
10. `.agent-harness/10_SYNC_POLICY.md`
11. `app/main.py`
12. `app/api/routes/`
13. `app/services/`
14. `app/search/`
15. `worker/`
16. `frontend/src/`

## 重点模块
- RAG 问答流程：`reply` / `conversations` / `answer_service` / `orchestrator` / `phases` / `retrieval` / `llm_gateway` / `search`
- 标准化：`app/services/normalization.py`（answer_mode、support_level、answer_type、product_family、page_kind、doc_type、to_str_list）
- QuerySpec 子数据类：`app/services/schemas.py`（QueryIntent、RetrievalHints、ClarificationNeeds、AnswerContract、QuerySlots）
- Phase 输出：`app/services/schemas.py`（RetrievePhaseOutput、GeneratePhaseOutput、VerifyPhaseOutput、OrchestratorDebug）
- 检索：`app/services/retrieval.py`（BudgetConfig、DocTypeStrategy、7 个辅助方法）
- 知识库入库：`documents` / `admin` / `ingestion` / `source_loaders` / `source_sync` / `scripts/ingest_from_source.py`
- 工单学习流程：`tickets` / WHMCS crawler / approval / `ingest_tickets_to_file` / `scripts/ingest_tickets_from_source.py`
- 前端页面：Login、Conversations、Documents、Crawl、Dashboard、Settings、Tickets、Intents、Doc Types、API Tokens、API Reference

## 工作原则
- 优先帮助我理解项目，不要一上来大规模重构。
- 每次修改前，先说明将改哪些文件、为什么改。
- 不允许批量格式化无关文件。
- 不允许删除已有功能。
- 不允许引入新的第三方依赖，除非我明确同意。
- 不允许改动 Docker、数据库迁移、认证逻辑，除非任务明确要求。
- 不允许运行破坏性命令，例如 `git reset --hard`、批量删除、清空数据卷、删除数据库。
- 修改前先看 `git status`，已有未提交改动视为用户资产，不得回退。
- 优先小步修改，每次只解决一个清晰问题。

## 变更前检查
每次准备改文件前，先输出：

```text
将改动：
- path/to/file: 原因

暂不改动：
- path/to/other-file: 原因
```

如果任务涉及 Docker、数据库迁移、认证、删除功能、新依赖、生产数据写入，必须先获得明确确认。

## Harness 同步要求
- 修改 RAG 查询链路时，同步检查 `.agent-harness/02_RAG_FLOW.md`。
- 修改服务拓扑、端口、依赖服务时，同步检查 `.agent-harness/01_SERVICE_MAP.md`。
- 修改脚本、测试、运行命令时，同步检查 `.agent-harness/03_DEV_COMMANDS.md`。
- 修改工作规范、安全边界时，同步检查 `AGENTS.md` 和 `.agent-harness/04_CHANGE_GUIDE.md`。
- 遇到可复现故障或踩坑时，同步记录 `.agent-harness/07_FAILURE_MEMORY.md`。
- 无需同步时，在最终回复中说明”harness 无需更新”的原因。

## Agent skills

### Issue tracker

Local markdown under `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical roles: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context. One `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## 验证要求
- 文档-only 修改：检查 Markdown 文件是否存在、内容是否符合中文和路径要求即可。
- 后端修改：优先运行与触达模块相关的 pytest。
- 前端修改：优先运行 `cd frontend && npm run build` 或更窄的 TypeScript 检查。
- RAG 流程修改：说明至少一个入库或查询烟测路径。
- 如果无法运行验证，必须说明原因和建议后续命令。

## Harness 文档索引
- `.agent-harness/00_PROJECT_MAP.md`：项目地图、目录和风险边界。
- `.agent-harness/01_SERVICE_MAP.md`：frontend、api、worker、postgres、redis、opensearch、qdrant、minio 服务说明。
- `.agent-harness/02_RAG_FLOW.md`：RAG 入库流程和查询流程。
- `.agent-harness/03_DEV_COMMANDS.md`：现有开发、测试、入库命令。
- `.agent-harness/04_CHANGE_GUIDE.md`：小步变更指南。
- `.agent-harness/05_COMMON_TASKS.md`：常见任务入口。
- `.agent-harness/06_DEBUG_CHECKLIST.md`：调试排查清单。
- `.agent-harness/07_FAILURE_MEMORY.md`：失败记忆和待确认事项。
- `.agent-harness/08_CODEX_HARNESS_ADAPTER.md`：Harness Starter 到 Codex 环境的适配映射。
- `.agent-harness/09_REVIEW_CHECKLIST.md`：等价 Stop Hook 的变更审查清单。
- `.agent-harness/10_SYNC_POLICY.md`：代码变动时 harness 文档同步规则。
