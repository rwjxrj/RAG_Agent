---
name: update-readme
description: Update, rewrite, optimize, or audit README.md for D:\ai_project\RAG_Search. Use when the user asks to 更新README.md, 优化README, 重写README, refresh README from current project state, or says the existing README is outdated after project changes. Produces Chinese documentation grounded in current repo files and project harness docs.
---

# Update README

## Goal

Update `README.md` as the project entry document for `D:\ai_project\RAG_Search`, using current repository facts instead of stale assumptions. Keep the result Chinese-first, concise, and useful for onboarding, local startup, RAG flow understanding, integration, and maintenance.

## Workflow

1. Check context and ownership.
   - Run `git status --short` before edits.
   - Treat existing uncommitted changes as user-owned.
   - If only README is requested, do not modify code, Docker, migrations, auth, dependency files, or runtime data.

2. Read only the facts needed for README.
   - Start with `AGENTS.md`.
   - Read current `README.md`.
   - Read `docker-compose.yml`, `.env.example`, `Makefile`, `pyproject.toml`, `frontend/package.json`.
   - Read harness docs when present:
     - `.agent-harness/00_PROJECT_MAP.md`
     - `.agent-harness/01_SERVICE_MAP.md`
     - `.agent-harness/02_RAG_FLOW.md`
     - `.agent-harness/03_DEV_COMMANDS.md`
   - Confirm code-facing facts from:
     - `app/main.py`
     - `app/api/routes/`
     - `app/services/`
     - `app/services/phases/`
     - `app/search/`
     - `frontend/src/App.tsx`

3. State the edit scope before changing files, following project rules:

```text
将改动：
- D:\ai_project\RAG_Search\README.md: 根据当前项目结构、运行方式和 RAG/客服流程更新主文档

暂不改动：
- D:\ai_project\RAG_Search\app\, D:\ai_project\RAG_Search\frontend\, D:\ai_project\RAG_Search\worker\: 本次为 README-only，不改业务代码
- D:\ai_project\RAG_Search\docker-compose.yml, D:\ai_project\RAG_Search\.env.example: 仅参考服务和配置，不修改部署或环境示例
```

4. Update README.
   - Prefer a coherent rewrite when the README is stale or structurally misleading.
   - Prefer local edits when the README is mostly current and the user requests a narrow update.
   - Use `apply_patch` for manual edits.
   - Do not add generated marketing copy, unsupported claims, or endpoint/config items not confirmed from repo files.

5. Verify as docs-only.
   - Check `README.md` exists and is readable.
   - Check major headings with `Select-String -Path README.md -Pattern '^# |^## '`.
   - Check key project facts relevant to the update with `Select-String`.
   - Run `git diff --check -- README.md`.
   - Run `git status --short`.

## Recommended README Shape

For a full refresh, use this structure unless the user asks otherwise:

- Title: `Support AI Assistant 企业客服 RAG 系统`
- 结论: one concise paragraph explaining what the system is.
- 目录
- 系统架构: services, ports, and a Mermaid graph.
- 核心流程: query flow and ingestion flow.
- 功能模块
- 技术栈
- 快速开始
- 数据入库与持续学习
- API 与集成
- 认证方式
- 配置说明
- 常用命令
- 项目结构
- 测试与验证
- 故障排查
- 维护约定

## Current Project Facts To Preserve

- Backend: FastAPI under `app/main.py`, API prefix defaults to `/v1`.
- Frontend: React/Vite under `frontend/`, Docker port `5174`, local Vite port `5173`.
- Runtime services: `frontend`, `api`, `worker`, `postgres`, `redis`, `opensearch`, `qdrant`, `minio`; `nginx` appears under the `full` profile.
- Query flow: `reply` / `conversations` route into `AnswerService`; intent cache and lightweight `AgenticRouter` can return direct response, clarify, human handoff, or RAG search; RAG then uses normalizer, orchestrator phases, retrieval, LLM generation, and reviewer.
- Retrieval: OpenSearch BM25 + Qdrant vector search, fusion/rerank/EvidenceSet.
- Ingestion: `source/`, URL/crawl/upload, WHMCS tickets, `IngestionService`, PostgreSQL Document/Chunk, OpenSearch, Qdrant.
- Config: `.env` is fallback; DB Settings can override LLM, embedding, and architecture config.
- Auth: JWT, `X-API-Key`, `X-Admin-API-Key`, DB API tokens.

## Final Response

In Chinese, report:

- changed file(s)
- why the README was updated this way
- verification commands run and their outcome
- whether harness needs updating; for README-only changes, usually say harness does not need updating because no RAG flow, service topology, command, or code behavior changed
