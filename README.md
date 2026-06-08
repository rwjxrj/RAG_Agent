# 自动回复聊天机器人 | Support AI Assistant

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**RAG (Retrieval-Augmented Generation) 聊天机器人** - 面向企业内部的 Support AI Assistant。它基于知识库上的**混合检索**（BM25 + 向量搜索），通过 REST API 回答支持问题。知识库可结合网页抓取数据、人工整理的示例会话，以及来自高评分会话的持续学习。

> 关键词：RAG 聊天机器人、LLM 支持助手、WHMCS 工单爬虫、向量搜索、知识库 AI、客服自动化

## 目录

- [数据来源与持续学习](#数据来源与持续学习)
- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [使用指南](#使用指南)
- [认证](#认证)
- [API 端点](#api-端点)
- [配置](#配置)
- [项目结构](#项目结构)

## 数据来源与持续学习

知识库由**三类来源**构建，并通过反馈闭环**持续改进**：

### 1. 网页抓取数据

- **WHMCS 工单**：从 WHMCS 抓取支持工单（通过 Playwright，使用 cookie 或账号密码登录）
- **URL 文档**：通过 `/documents/fetch-from-url` API 抓取网页内容（政策、FAQ、文档）
- **整站抓取**：通过 `/documents/crawl-website` 抓取整个站点
- **Source JSON**：支持多种格式摄取，如 `pages`（url、title、text）、`articles`、`plans`、`sales_kb` 等
- **WHMCS SQL 转储**：通过 `make import-whmcs` 从 `source/*.sql` 导入工单

### 2. 人工整理的示例会话

- **sample_conversations.json**：直接添加高质量示例会话（真实问答）
- **sample_docs.json**：预先准备的静态文档（网页、文章）
- **custom_docs.json**：从管理后台创建并同步回文件的文档

### 3. 从高评分会话学习

- 抓取到的工单需要**人工审核**（批准/拒绝）。只有**已批准**的工单会加入知识库
- 通过 `POST /v1/admin/ingest-tickets-to-file` 将**已批准工单导出**到 `sample_conversations.json`
- 重新运行摄取流程，将新的示例会话嵌入并索引到 OpenSearch/Qdrant
- 闭环：*抓取 → 审核（批准）→ 导出 → 摄取*，让系统从真实高质量会话中**持续学习**

---

## 功能特性

- **RAG**：BM25（OpenSearch）+ 向量（Qdrant）+ reranking
- **会话**：CRUD、同步/流式聊天，可关联 ticket/livechat
- **工单**：从 DB 列表查看，支持审批流程（pending/approved/rejected）
- **文档**：CRUD、从 URL 抓取、整站抓取、重新抓取、上传
- **WHMCS 爬虫**：通过 Playwright 抓取工单，保存 cookie，检查会话状态
- **管理后台**：摄取文档/工单，配置 prompts、intents、doc-types、LLM、archi，以及 branding
- **认证**：JWT 登录、API tokens（sk_*）、用户管理
- **前端**：React + Vite，包含登录、会话、示例会话、文档、抓取、仪表盘、意图、文档类型、设置、API Tokens、API 参考

## 技术栈

- **API**：FastAPI + Pydantic v2 + Uvicorn
- **DB**：PostgreSQL 15+
- **缓存/队列**：Redis + Celery
- **搜索**：OpenSearch（BM25）、Qdrant（向量）
- **Embeddings/LLM**：OpenAI（可插拔）
- **爬虫**：Playwright（Chromium）
- **前端**：React 19、Vite 7、Tailwind CSS

## 快速开始

### 前置条件

- Docker 和 docker-compose
- OpenAI API key

### 环境变量

```bash
cp .env.example .env
# 编辑 .env：OPENAI_API_KEY、JWT_SECRET（生产环境）、ADMIN_API_KEY、API_KEY
```

### 使用 Docker Compose 运行

```bash
docker-compose up -d
```

- **API**：http://localhost:8000
- **前端**：http://localhost:5174
- **MinIO**：http://localhost:9000（控制台：9001）

**使用 Nginx 网关**（API 监听 80 端口）：

```bash
docker-compose --profile full up -d
```

### 迁移与初始化设置

```bash
# 容器内执行
docker-compose exec api alembic upgrade head
docker-compose exec api python -m scripts.create_admin_user   # 创建管理员（迁移 011 之后）
docker-compose exec api python scripts/ingest_from_source.py
docker-compose exec api python scripts/ingest_tickets_from_source.py

# 或本地执行（服务已运行）
make init-db
make create-admin
make ingest
```

`source/` 中的**源文件**：

- `sample_docs.json` - 文档（pages: url、title、text）
- `sample_conversations.json` - 工单/会话（来自 WHMCS 抓取或手动整理）
- `custom_docs.json` - 管理后台创建的文档
- `*.sql` - 用于 `make import-whmcs` 的 WHMCS SQL 转储

支持的格式见 `app/services/source_loaders.py`。

### 本地开发

1. 启动 PostgreSQL、Redis、OpenSearch、Qdrant（或只用 docker-compose 启动基础设施）
2. `pip install -r requirements.txt`
3. `uvicorn app.main:app --reload`
4. Worker：`celery -A worker.celery_app worker --loglevel=info`
5. `alembic upgrade head`
6. `make create-admin`（创建第一个管理员用户）

## 使用指南

### 首次设置（完整流程）

1. **启动服务**：`docker-compose up -d`
2. **运行迁移**：`docker-compose exec api alembic upgrade head`
3. **创建管理员**：`docker-compose exec api python -m scripts.create_admin_user`（按提示输入用户名/密码）
4. **登录前端**：打开 http://localhost:5174，用刚创建的账号登录
5. **添加知识库数据**（从下面选择一种或多种方法）

### 方法 1：从 `source/` 中的 JSON 文件摄取

准备 `source/sample_docs.json` 或 `source/sample_conversations.json`：

```json
// sample_docs.json - 文档（网页、政策、FAQ）
{
  "pages": [
    {"url": "https://example.com/refund-policy", "title": "Refund Policy", "text": "Full content..."}
  ]
}

// sample_conversations.json - 来自工单的问答（需要 external_id、subject、description）
{
  "source": "whmcs",
  "conversations": [
    {
      "external_id": "12345",
      "subject": "Refund question",
      "description": "User: How do I request a refund?\nStaff: You can request a refund within 30 days...",
      "status": "Closed",
      "priority": "Medium"
    }
  ]
}
```

运行摄取：

```bash
make ingest                                    # 摄取文档
python scripts/ingest_tickets_from_source.py   # 摄取示例会话
```

### 方法 2：从 URL 抓取或整站抓取

- **单个 URL**：使用 API `POST /v1/documents/fetch-from-url`，请求体为 `{"url": "https://..."}`；也可在前端 **Documents** → Add → Fetch from URL 操作
- **整个网站**：使用 API `POST /v1/documents/crawl-website`，请求体为 `{"base_url": "https://example.com", "max_pages": 50}`；也可在前端 **Documents** → Crawl website 操作

### 方法 3：抓取 WHMCS 工单（通过前端）

1. 进入 **Crawl**（侧边栏）
2. 输入 **Base URL**（例如 `https://billing.example.com`）
3. **登录 WHMCS**：
   - **选项 A（Cookies）**：在浏览器中登录 WHMCS → DevTools → Application → Cookies → 复制 JSON → 粘贴到 “Session cookies” 字段 → 保存 cookies
   - **选项 B（Credentials）**：输入用户名、密码（如适用，也输入 TOTP）→ 点击 “Login & Crawl”
4. **检查连接** → 如果正常，点击 **Crawl tickets**
5. 进入 **Sample conversations**（Tickets）→ 审核每个工单 → **批准**高质量工单
6. **导出已批准内容** → 调用 `POST /v1/admin/ingest-tickets-to-file`（或对应按钮）写入 `sample_conversations.json`
7. 运行 `python scripts/ingest_tickets_from_source.py` 进行 embedding 和索引

### 方法 4：从 WHMCS SQL 转储导入

如果你有 WHMCS 转储文件（例如 `source/greenvps_whmcs.sql`）：

```bash
make import-whmcs-dry   # 先验证解析
make import-whmcs       # 执行实际导入
```

本项目通过结构化评估、prompt 优化和持续反馈闭环提升聊天机器人性能。

由 [OptyxStack AI Optimization](https://optyxstack.com/ai-optimization) 提供支持，用于增强准确性、相关性和大规模可靠性。

然后在 **Sample conversations** 中批准工单，并按方法 3 的步骤 6-7 摄取。

### 聊天流程（API）

1. **创建会话**：
   ```bash
   curl -X POST http://localhost:8000/v1/conversations \
     -H "Authorization: Bearer YOUR_JWT" \
     -H "Content-Type: application/json" \
     -d '{"source_type": "ticket", "source_id": "TKT-123"}'
   ```
2. **发送消息**（同步或流式）：
   ```bash
   curl -X POST http://localhost:8000/v1/conversations/{CONV_ID}/messages \
     -H "Authorization: Bearer YOUR_JWT" \
     -H "Content-Type: application/json" \
     -d '{"content": "What is your refund policy?"}'
   ```
3. 响应包含 `answer`（RAG 生成结果）和 `debug_metadata`（检索、证据）。

### 前端主要页面

| 页面 | 用途 |
|------|------|
| **Conversations** | 查看会话列表、创建新会话、试用聊天 |
| **Sample conversations** | 查看抓取/导入的工单、批准/拒绝、导出已批准内容 |
| **Documents** | 文档 CRUD、抓取 URL、整站抓取、重新抓取 |
| **Crawl** | 配置 WHMCS、保存 cookies、抓取工单 |
| **Dashboard** | Token 统计、检索、升级转人工指标 |
| **Intents** | 意图 CRUD（查询分类） |
| **Doc Types** | 文档类型 CRUD（policy、faq、pricing 等） |
| **Settings** | System prompt、LLM 配置、branding、领域术语 |
| **API Tokens** | 创建/撤销 API token（sk_*） |
| **API Reference** | API 文档 |

### 外部系统集成

- **建议回复（平台无关）**：调用 `POST /v1/reply/generate`，将 `query` 设置为 ticket/chat 内容。无需创建会话。适用于 WHMCS、Zendesk、livechat 或任何 helpdesk。
- **Livechat / 工单系统（聊天流程）**：调用 `POST /v1/conversations`，传入 `source_type: "livechat"` 或 `"ticket"`，`source_id` 为外部系统中的 ID。用户发送消息时，调用 `POST /v1/conversations/{id}/messages`，并使用 `answer` 展示给用户。
- **Webhook**：可以用自己的 webhook endpoint 包装 API，以接收来自 livechat/ticket 平台的请求。

### 故障排查

| 问题 | 建议 |
|------|------|
| 前端登录返回 401 | 检查 `.env` 中的 `JWT_SECRET`，确认已运行 `make create-admin` |
| WHMCS 抓取失败 | Cookies 已过期，重新登录 WHMCS 并复制新的 cookies |
| 摄取没有数据 | 检查 `source/` 中的文件格式是否正确（pages、conversations），运行 `make ingest-dry` 查看日志 |
| API 返回 401 | 使用 Bearer JWT（来自 `/auth/login`）或有效的 `X-API-Key` |
| OpenSearch/Qdrant 错误 | 确认所有服务健康：`docker-compose ps` |

## 认证

API 接受**三种认证方式**：

1. **Bearer JWT** - 来自 `POST /v1/auth/login`（用户名/密码）
2. **X-API-Key** - 环境变量 `API_KEY` 或 DB API token（sk_*）
3. **X-Admin-API-Key** - 用于管理端点（环境变量 `ADMIN_API_KEY`，或 role=admin 的 JWT）

**创建管理员用户**（迁移 011 之后）：

```bash
make create-admin
# 或：python -m scripts.create_admin_user
```

**API tokens**（sk_*）：通过 `POST /v1/auth/tokens` 创建（需要 Bearer JWT）。Token 存储在 DB 中，可撤销。

## API 端点

### Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/auth/login` | 登录（用户名、密码）→ JWT |
| GET | `/v1/auth/me` | 当前用户（Bearer JWT） |
| GET | `/v1/auth/tokens` | 列出 API tokens |
| POST | `/v1/auth/tokens` | 创建 API token |
| DELETE | `/v1/auth/tokens/{token_id}` | 撤销 token |

### Conversations

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/conversations` | 列表（分页，筛选：source_type、source_id） |
| POST | `/v1/conversations` | 创建（source_type: ticket/livechat, source_id） |
| GET | `/v1/conversations/{id}` | 详情 + messages |
| PATCH | `/v1/conversations/{id}` | 更新 metadata |
| DELETE | `/v1/conversations/{id}` | 删除 |
| POST | `/v1/conversations/{id}/messages` | 发送消息（同步） |
| POST | `/v1/conversations/{id}/messages:stream` | 发送消息（SSE） |

### Suggest Reply（平台无关）

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/reply/generate` | 生成建议回复（ticket、livechat、helpdesk）。无状态，无需会话。 |

### Tickets

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/tickets` | 列表（分页，筛选：status、approval_status、q） |
| GET | `/v1/tickets/{id}` | 工单详情 |

### Documents

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/documents` | 列表（分页，筛选：doc_type、q） |
| GET | `/v1/documents/{id}` | 详情 |
| POST | `/v1/documents` | 创建文档（ingest） |
| POST | `/v1/documents/fetch-from-url` | 从 URL 抓取内容 |
| POST | `/v1/documents/crawl-website` | 抓取网站 |
| POST | `/v1/documents/re-crawl-all` | 重新抓取所有文档 |
| POST | `/v1/documents/upload` | 上传文档 |
| POST | `/v1/documents/{id}/re-crawl` | 重新抓取单个文档 |
| PATCH | `/v1/documents/{id}` | 更新 metadata |
| DELETE | `/v1/documents/{id}` | 删除 |

### Admin（Bearer JWT admin / X-Admin-API-Key）

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/admin/ingest` | 摄取文档（进入 Celery 队列） |
| POST | `/v1/admin/ingest-from-source` | 从 source/ 摄取（同步） |
| POST | `/v1/admin/save-whmcs-cookies` | 保存 WHMCS cookies |
| POST | `/v1/admin/check-whmcs-cookies` | 检查 cookies |
| GET | `/v1/admin/whmcs-cookies` | 获取已保存 cookies |
| GET | `/v1/admin/config/whmcs` | WHMCS 默认配置 |
| POST | `/v1/admin/crawl-tickets` | 抓取 WHMCS 工单 |
| PATCH | `/v1/admin/tickets/{id}/approval` | 更新审批状态（pending/approved/rejected） |
| POST | `/v1/admin/ingest-tickets-to-file` | 导出已批准工单 → sample_conversations.json |
| GET/PUT | `/v1/admin/config/llm` | LLM 配置 |
| GET/PUT | `/v1/admin/config/archi` | 架构配置（normalizer、evidence 等） |
| GET/PUT | `/v1/admin/config/system-prompt` | System prompt |
| GET/PUT | `/v1/admin/config/{key}` | App 配置（通用） |
| POST | `/v1/admin/config/refresh-cache` | 刷新配置缓存 |
| POST | `/v1/admin/config/auto-generate-from-domain` | 从 domain 自动生成 branding |
| GET/POST/PUT/DELETE | `/v1/admin/intents` | 意图 CRUD |
| GET/POST/PUT/DELETE | `/v1/admin/doc-types` | 文档类型 CRUD |

### Health & Dashboard

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/health` | 健康检查 |
| GET | `/v1/metrics` | Prometheus 指标 |
| GET | `/v1/dashboard/stats` | Token 成本、检索命中率、升级转人工率 |

## cURL 请求示例

### 登录

```bash
curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your-password"}'
```

### 创建会话（使用 Bearer JWT 或 X-API-Key）

```bash
curl -X POST http://localhost:8000/v1/conversations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT" \
  -d '{"source_type": "ticket", "source_id": "TKT-12345", "metadata": {}}'
```

### 发送消息

```bash
curl -X POST http://localhost:8000/v1/conversations/{CONV_ID}/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT" \
  -H "X-External-User-Id: user-123" \
  -d '{"content": "What is your refund policy?"}'
```

### 生成建议回复（平台无关）

```bash
curl -X POST http://localhost:8000/v1/reply/generate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT" \
  -d '{
    "query": "What is your refund policy? I want to cancel my order.",
    "source_type": "ticket",
    "source_id": "TKT-12345"
  }'
```

响应：`{ "answer": "...", "decision": "PASS"|"ASK_USER"|"ESCALATE", "followup_questions": [], "citations": [...], "confidence": 0.9 }`

### 摄取文档

```bash
curl -X POST http://localhost:8000/v1/admin/ingest \
  -H "Content-Type: application/json" \
  -H "X-Admin-API-Key: admin-key" \
  -d '{
    "documents": [
      {
        "url": "https://example.com/refund-policy",
        "title": "Refund Policy",
        "raw_text": "Full refund within 30 days...",
        "doc_type": "policy"
      }
    ]
  }'
```

## 配置

### 选择中国模型

本项目的 LLM 网关使用 OpenAI-compatible Chat Completions 接口。进入前端 **Settings → LLM 配置** 后，可以在“模型供应商预设”中选择 DeepSeek、阿里云百炼/Qwen、智谱 GLM、月之暗面/Kimi 或硅基流动。选择预设会自动填入主模型、备用模型、经济模型和 Base URL；你仍然可以手动修改模型名，以适配厂商最新模型或私有中转服务。

运行时优先使用数据库中的 Settings 配置；当数据库配置为空时，才回退到 `.env` / `.env.example` 中的 `LLM_MODEL`、`LLM_FALLBACK_MODEL`、`LLM_MODEL_ECONOMY`、`OPENAI_API_KEY`、`OPENAI_BASE_URL`。

常用 OpenAI-compatible Base URL：

| 供应商 | Base URL | 示例模型 |
|--------|----------|----------|
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| 阿里云百炼/Qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus`、`qwen-turbo` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-plus`、`glm-4-flash` |
| 月之暗面/Kimi | `https://api.moonshot.cn/v1` | `kimi-k2.5`、`moonshot-v1-32k` |
| 硅基流动 | `https://api.siliconflow.cn/v1` | 使用模型广场中的完整模型名 |

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL（异步） |
| `DATABASE_URL_SYNC` | `postgresql://...` | PostgreSQL（同步，Celery） |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `OPENSEARCH_HOST` | `http://localhost:9200` | OpenSearch |
| `QDRANT_HOST` | `localhost` | Qdrant |
| `OPENAI_API_KEY` | - | embeddings/LLM 必需 |
| `API_KEY` | - | API 认证（空值 = 开发模式） |
| `ADMIN_API_KEY` | - | 管理员认证 |
| `JWT_SECRET` | `change-me-in-production` | JWT 签名密钥（生产环境必需） |
| `JWT_EXPIRE_MINUTES` | `10080`（7 天） | JWT 过期时间 |
| `OBJECT_STORAGE_URL` | - | MinIO/S3（例如 http://minio:9000） |
| `LLM_MODEL` | `gpt-5.2` | LLM 模型 |
| `LLM_MAX_TOKENS` | `2048` | 最大 tokens |
| `APP_NAME` | - | 用于 branding 的公司/应用名称（问候语、标题） |
| `NORMALIZER_DOMAIN_TERMS` | - | 逗号分隔的实体术语（例如 vps,windows,linux,pricing） |
| `NORMALIZER_SLOTS_ENABLED` | `false` | 启用 slot 提取（product_type、os、billing_cycle、region） |
| `NORMALIZER_SLOT_PRODUCT_TYPES` | - | slot 的产品类型（例如 vps,dedicated,vds）。空值 = 禁用 |
| `NORMALIZER_SLOT_OS_TYPES` | - | os slot 的系统类型（例如 windows,linux,macos）。空值 = 禁用 |
| `CORS_ORIGINS` | `*` | 允许的 CORS origins，逗号分隔（例如 `https://app.example.com`）。`*` = 全部允许（开发环境） |
| `DOCS_ENABLED` | `true` | 启用 `/docs` 和 `/redoc`。生产环境可设为 `false` 隐藏 API 文档 |

## 脚本

| Script | Description |
|--------|-------------|
| `scripts/init_db.py` | 创建 DB 并运行迁移 |
| `scripts/create_admin_user.py` | 创建初始管理员用户（迁移 011 后运行） |
| `scripts/ingest_from_source.py` | 从 source/ 摄取文档 |
| `scripts/ingest_tickets_from_source.py` | 从 sample_conversations.json 摄取工单 |
| `scripts/import_whmcs_sql_dump_to_tickets.py` | 从 source/*.sql 导入工单 |
| `scripts/crawl_whmcs_tickets.py` | 抓取 WHMCS 工单（CLI） |
| `scripts/whmcs_login_browser.py` | 打开浏览器登录 WHMCS 并获取 cookies |

### Makefile 命令

```bash
make init-db       # 运行迁移
make create-admin  # 创建管理员用户
make ingest        # 从 source/ 摄取文档
make ingest-dry    # Dry run：加载文档但不摄取
make import-whmcs  # 从 source/*.sql 导入 WHMCS 工单
make import-whmcs-dry  # Dry run：验证 SQL 解析
```

## 前端

```bash
cd frontend && npm install && npm run dev
# http://localhost:5173
```

或使用 Docker：`docker-compose up -d frontend` → http://localhost:5174

**主要页面**：Login、Conversations、Sample conversations（tickets）、Documents、Crawl（WHMCS）、Dashboard、Intents、Doc Types、Settings、API Tokens、API Reference。

## 项目结构

```
app/
  main.py              # FastAPI app
  api/routes/          # auth、conversations、reply、tickets、documents、admin、health、dashboard
  services/            # retrieval、LLM、ingestion、ticket_db、ticket_loaders、source_loaders
  search/              # OpenSearch、Qdrant、reranker、embeddings
  crawlers/            # WHMCS 爬虫（Playwright）
  db/                  # Models、session
  core/                # Config、auth、logging、rate limit、tracing、gateway
worker/
  celery_app.py
  tasks.py             # 摄取任务
frontend/              # React + Vite（CRUD、chat、crawl UI）
alembic/              # 迁移
scripts/               # init_db、create_admin_user、ingest_from_source、ingest_tickets_from_source、import_whmcs_sql_dump_to_tickets、crawl_whmcs_tickets、whmcs_login_browser
source/                # sample_docs.json、sample_conversations.json、custom_docs.json、*.sql
```

## 测试

```bash
pip install -e ".[dev]"
pytest tests/ -v
```
