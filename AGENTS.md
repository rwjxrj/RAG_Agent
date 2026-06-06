# Repository Guidelines

## 项目结构与模块组织

本仓库是 FastAPI + React/Vite 的 RAG 支持助手。后端源码在 `app/`：`api/routes/` 放接口路由，`services/` 放检索、LLM、摄取和业务编排，`search/` 放 OpenSearch、Qdrant、reranker 和 embeddings，`db/` 放模型与会话。后台任务在 `worker/`，数据库迁移在 `alembic/versions/`，脚本在 `scripts/`，测试在 `tests/`，测试数据在 `tests/fixtures/`。前端源码在 `frontend/src/`，静态资源在 `frontend/public/`，知识库输入样例在 `source/`。

## 构建、测试与开发命令

- `pip install -r requirements.txt`：安装后端运行依赖。
- `pip install -e ".[dev]"`：安装后端开发与测试依赖。
- `uvicorn app.main:app --reload`：本地启动 API。
- `celery -A worker.celery_app worker --loglevel=info`：启动异步任务 worker。
- `pytest tests/ -v`：运行后端测试。
- `make init-db` / `make create-admin` / `make ingest`：初始化数据库、创建管理员、摄取 `source/` 数据。
- `cd frontend && npm install && npm run dev`：启动前端开发服务器。
- `cd frontend && npm run build`：执行 TypeScript 检查并构建前端。

## 编码风格与命名约定

Python 代码使用 4 空格缩进，优先类型标注和 Pydantic v2 schema；模块与函数使用 `snake_case`，类名使用 `PascalCase`。React 组件使用 TypeScript，组件文件和组件名使用 `PascalCase`，hooks 使用 `useXxx`。保持 API 字段名、路由路径和配置键稳定，不为展示文案改动后端契约。

## 测试指南

后端测试框架是 `pytest`，异步测试由 `pytest-asyncio` 自动处理；测试文件命名为 `tests/test_*.py`，共享 fixture 放在 `tests/conftest.py` 或 `tests/fixtures/`。修改检索、路由、认证、摄取、LLM 网关或评分逻辑时，应补充或更新相邻测试。前端当前没有单独测试脚本，至少运行 `npm run build` 验证类型与构建。

## 提交与 Pull Request

当前本地分支没有可归纳的提交历史；建议使用简洁的 Conventional Commits，例如 `feat: add document crawler filter`、`fix: handle empty retrieval results`。PR 应说明变更目的、关键实现、验证命令和风险点；前端界面变更附截图，接口变更列出受影响 endpoint，并关联 issue 或需求来源。

## 安全与配置

从 `.env.example` 复制 `.env`，不要提交真实密钥、JWT secret、数据库密码、WHMCS cookie 或 API Token。生产环境应显式设置 `JWT_SECRET`、`OPENAI_API_KEY`、`ADMIN_API_KEY`、`DATABASE_URL`、`REDIS_URL`、`OPENSEARCH_HOST` 和 `QDRANT_HOST`。

## Agent 专用说明

回答与仓库文档默认使用中文。执行前端中文化时，只修改 `frontend/src` 下用户可见文案；不要修改 API 字段名、变量名、函数名、组件名、路由、CSS/Tailwind class、图标组件、后端代码或 Docker 配置。不要扫描 `node_modules`、`dist`、`build`，每次最多修改 3 个页面或组件文件。保留专业术语：API、Token、RAG、BM25、Qdrant、OpenSearch、JSON、URL、Webhook。
