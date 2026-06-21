# 健康检查功能

## Problem Statement

管理员无法直观地了解 RAG 系统的核心服务（LLM、Embedding、Reranker、数据库、搜索引擎）是否正常运行。当检索质量下降或回答异常时，需要逐个手动检查各服务状态，排查效率低。

## Solution

在前端侧边栏新增"健康检查"页面，管理员点击"开始检查"按钮后，系统自动检测 9 项核心服务的连通性，并以卡片形式展示每项的状态、详情和延迟。

## User Stories

1. As 管理员, I want 点击侧边栏"健康检查"进入检查页面, so that 我能快速访问系统状态
2. As 管理员, I want 点击"开始检查"按钮触发检测, so that 我能按需检查而非自动消耗资源
3. As 管理员, I want 看到 LLM 主模型的连通状态, so that 我知道 gpt-5.2 是否可用
4. As 管理员, I want 看到 LLM 备用模型的连通状态, so that 我知道 fallback 是否可用
5. As 管理员, I want 看到 LLM 经济模型的连通状态, so that 我知道 normalizer/router 用的模型是否可用
6. As 管理员, I want 看到 Embedding 模型的连通状态, so that 我知道向量化是否正常
7. As 管理员, I want 看到 Reranker 模型的连通状态, so that 我知道重排序是否正常
8. As 管理员, I want 看到 PostgreSQL 的连通状态, so that 我知道数据库是否正常
9. As 管理员, I want 看到 Redis 的连通状态, so that 我知道缓存是否正常
10. As 管理员, I want 看到 Qdrant 的连通状态, so that 我知道向量检索是否正常
11. As 管理员, I want 看到 OpenSearch 的连通状态, so that 我知道全文检索是否正常
12. As 管理员, I want 看到每项检查的响应延迟, so that 我能判断服务是否过慢
13. As 管理员, I want 看到顶部的状态总览徽章, so that 我一眼知道整体健康状况
14. As 管理员, I want 检查失败时看到友好的错误提示, so that 我知道问题在哪但不会泄露 API Key
15. As 管理员, I want 看到每项检查显示的模型名称来自我的配置, so that 我确认检查的是正确的模型
16. As 管理员, I want 检查完成后点击"刷新"重新检查, so that 我能确认修复后状态恢复
17. As 管理员, I want 检查进行中看到加载状态, so that 我知道系统正在工作
18. As 管理员, I want 某项检查超时时看到超时提示, so that 我知道是慢而不是挂了

## Implementation Decisions

### 1. 后端新增健康检查服务

新建 `app/services/health_check.py`，包含 9 个检查函数，每个函数独立执行、独立超时、独立捕获异常。

检查项与配置来源：

| 检查项 | 配置来源 | 检查方式 |
|---|---|---|
| LLM 主模型 | `llm_config.get_llm_model()` + API key + base URL | `chat(max_tokens=1)` |
| LLM 备用模型 | `llm_config` 的 fallback 配置 | 同上 |
| LLM 经济模型 | `archi_config.get_llm_model_economy()` | 同上 |
| Embedding | `embedding_config` 的 model + API key | 单文本 embed |
| Reranker | `reranker_provider` + `reranker_url` / `cohere_api_key` | 测试 rerank 请求 |
| PostgreSQL | `database_url` | `SELECT 1` |
| Redis | `redis_url` | `PING` |
| Qdrant | `qdrant_host:qdrant_port` | HTTP GET `/` |
| OpenSearch | `opensearch_url` | `GET /_cluster/health` |

### 2. API 端点

新增 `POST /v1/health/check`，返回：

```python
class HealthCheckItem(BaseModel):
    name: str           # "LLM 主模型"
    status: str         # "ok" | "error" | "timeout"
    detail: str         # "gpt-5.2 via openai" 或 脱敏错误信息
    latency_ms: int     # 响应毫秒数

class HealthCheckResponse(BaseModel):
    status: str         # "healthy" | "degraded" | "unhealthy"
    checks: list[HealthCheckItem]
    summary: dict       # {"total": 9, "ok": 8, "failed": 1}
```

### 3. 错误脱敏规则

| 错误类型关键词 | 脱敏后显示 |
|---|---|
| `401` / `invalid` / `api_key` / `authentication` | `认证失败，请检查 API Key 配置` |
| `404` / `model_not_found` / `does not exist` | `模型未找到，请检查模型名称配置` |
| `timeout` / `connect` / `timed out` | `连接超时，请检查网络和服务地址` |
| `connection refused` / `ECONNREFUSED` | `连接被拒绝，请检查服务是否启动` |
| `429` / `rate_limit` | `请求过于频繁，请稍后重试` |
| 其他 | `检查失败: {error_type}` |

### 4. 前端页面

- 侧边栏新增入口：`{ to: '/health', icon: Activity, label: '健康检查' }`
- 页面组件：`frontend/src/pages/HealthCheck.tsx`
- 使用 `lucide-react` 的 `Activity` 图标
- 页面布局：
  - 顶部：状态总览（绿色/黄色/红色徽章 + "8/9 正常"）
  - 中间：9 个检查卡片网格
  - 底部："开始检查"按钮（点击后变为"检查中..."）

### 5. 前端 API 调用

在 `frontend/src/api/client.ts` 新增：
```typescript
export async function runHealthCheck(): Promise<HealthCheckResponse>
```

### 6. 实现顺序

1. 后端 schema（`app/api/schemas.py`）
2. 后端服务（`app/services/health_check.py`）
3. 后端路由（`app/api/routes/health.py`）
4. 前端 API（`frontend/src/api/client.ts`）
5. 前端页面（`frontend/src/pages/HealthCheck.tsx`）
6. 前端路由（`frontend/src/App.tsx`）

## Testing Decisions

- 后端：测试每个检查函数在正常/异常/超时场景下的返回
- 后端：测试错误脱敏逻辑
- 后端：测试 API 端点的响应格式
- 前端：手动验证页面渲染和交互

## Out of Scope

- 自动定时检查（仅手动触发）
- 检查结果持久化（不存储历史）
- 告警通知（不发送邮件/webhook）
- 模型性能基准测试（只检查连通性）

## Further Notes

- 检查 LLM 时会消耗极少量 token（max_tokens=1），成本可忽略
- 检查 Embedding 时会调用一次 embed API，成本可忽略
- 检查 Reranker 时发送 1 个文档的 rerank 请求，成本可忽略
- 所有检查并行执行，总耗时取决于最慢的一项（通常 2-5 秒）
