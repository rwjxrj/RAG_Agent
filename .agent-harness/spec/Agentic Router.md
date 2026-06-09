# Agentic Router 计划文档

## 结论
本计划只定义一个轻量 Agentic Router 的目标、边界和验收方式，不实施业务代码。该 Router 规划放在现有 intent cache 未命中之后、固定 RAG 流程之前，用于先判断问题类型并选择工具；现有 `app/services/decision_router.py` 继续作为检索后的证据决策器，不与本 Router 混用。

## 目标
- 为当前企业客服 RAG 系统增加一层“Agent 感”的轻量决策规划。
- 在用户问题未命中已配置意图时，先由 Agentic Router 判断问题类型，再决定是否进入 RAG、直接回复、追问或人工接管。
- 保持现有 RAG 主流程不变：`query extract → retrieve → assess evidence → retry → generate → verify`。
- 保持外部 API 返回结构稳定，不要求调用方迁移。

## 边界
- 不引入 LangGraph。
- 不新增第三方依赖。
- 不修改数据库、Docker、认证、迁移或现有 API 路由。
- 不替换当前 RAG 编排。
- intent cache 命中时继续直接返回，Agentic Router 不执行。
- Agentic Router 低置信、解析失败或运行异常时，默认回退到现有 RAG，保证行为可回退。
- 本计划文档不要求实现任何会写数据库、访问外部系统或触发生产数据变更的工具。

## 位置与流程
规划后的查询入口顺序如下：

```text
reply / conversations / stream
  → guardrails 注入检查与输入清洗
  → AnswerService.generate()
  → intent cache
      → 命中：直接返回预设答案，Agentic Router 跳过
      → 未命中：Agentic Router 选择工具
          → rag_search：进入现有完整 RAG 流程
          → direct_response：直接返回轻量答案
          → clarify：返回追问
          → human_handoff：返回人工接管
```

与现有组件的边界：
- Agentic Router 是“RAG 前工具选择器”。
- `app/services/decision_router.py` 是“检索后证据决策器”，继续负责基于证据质量输出 `PASS`、`ASK_USER`、`ESCALATE` 等结果。
- 两者命名、输入、输出和 debug 字段应保持可区分，避免后续维护时误把检索后决策逻辑前移。

## 内部接口
Agentic Router 的概念输入：

```json
{
  "query": "用户原始问题",
  "conversation_history": [],
  "source": "reply|conversation|stream",
  "trace_id": "可选"
}
```

字段说明：
- `query`：经过 guardrails 检查和清洗后的用户问题。
- `conversation_history`：已截断到 RAG 管线可接受范围的历史上下文。
- `source`：调用来源，用于 debug 和一致性测试，不用于改变核心策略。
- `trace_id`：沿用现有追踪标识。

## Router 输出
Agentic Router 的概念输出：

```json
{
  "route": "rag_search|direct_response|clarify|human_handoff",
  "tool": "工具名",
  "reason": "选择原因",
  "confidence": 0.0,
  "query_for_tool": "可选改写问题",
  "clarifying_questions": [],
  "risk_flags": [],
  "fallback_to_rag": false
}
```

字段说明：
- `route`：标准化路由结果。
- `tool`：实际选择的工具名，默认与 `route` 相同。
- `reason`：简短、可审计的选择原因。
- `confidence`：0 到 1 的置信度；低于实现阈值时应回退 `rag_search`。
- `query_for_tool`：可选的工具输入改写；为空时使用原始 query。
- `clarifying_questions`：`clarify` 路径下返回给用户的追问。
- `risk_flags`：记录账号、账单、安全、删除、退款执行等风险信号。
- `fallback_to_rag`：当 Router 不确定或异常时置为 `true`，并选择 `rag_search`。

## 工具定义
### `rag_search`
- 默认工具。
- 进入现有完整 RAG 流程。
- 适用于产品、价格、政策、排障、配置、知识库问答等需要检索证据的问题。
- 输出应保留现有 citations、confidence、debug metadata 行为。

### `direct_response`
- 不进入检索，不调用 RAG 生成。
- 适用于问候、能力说明、简单交互类问题。
- 返回 `PASS`，无 citations。
- 不应用于需要事实依据、政策依据、价格依据或账号状态的问题。

### `clarify`
- 不进入检索。
- 适用于缺少关键条件且无法安全给出有用答案的问题。
- 返回 `ASK_USER`，包含 1 到 3 个追问。
- 典型场景：用户只说“帮我选一个套餐”，但没有预算、地区、用途等必要条件。

### `human_handoff`
- 不进入检索。
- 适用于必须由人工处理或确认的请求。
- 返回 `ESCALATE`，提示客服跟进。
- 典型场景：账号权限、账单争议、退款执行、删除数据、安全事件、要求修改订单或执行后台操作。

## 返回格式
外部 API 顶层返回保持不变：

```json
{
  "answer": "回复内容",
  "decision": "PASS|ASK_USER|ESCALATE",
  "followup_questions": [],
  "citations": [],
  "confidence": 0.0,
  "debug": {}
}
```

仅规划在 `debug` 中增加可选字段：

```json
{
  "debug": {
    "agentic_router": {
      "route": "rag_search",
      "tool": "rag_search",
      "reason": "support_knowledge_question",
      "confidence": 0.86,
      "skipped": false
    }
  }
}
```

intent cache 命中时：

```json
{
  "debug": {
    "intent_cache": "matched_intent_key",
    "agentic_router": {
      "skipped": true,
      "reason": "intent_cache_hit"
    }
  }
}
```

Router 低置信或异常回退时：

```json
{
  "debug": {
    "agentic_router": {
      "route": "rag_search",
      "tool": "rag_search",
      "reason": "router_low_confidence_or_error",
      "confidence": 0.0,
      "fallback_to_rag": true,
      "skipped": false
    }
  }
}
```

## 验收标准
- 文档只写入 `.agent-harness/spec/Agentic Router.md`。
- 文档明确说明 Agentic Router 位于 intent cache 之后、RAG 之前。
- 文档明确区分新 Router 与现有检索后 `decision_router.py`。
- 文档覆盖目标、边界、接口、工具、返回格式、验收标准、测试用例。
- 文档不要求引入 LangGraph、数据库变更、Docker 变更、新依赖或业务代码改动。
- 未来实现时，低置信和异常必须默认回退现有 RAG。
- 未来实现时，`/reply/generate`、同步会话、流式会话三类入口应保持一致的 Router 策略。

## 测试用例
| 用例 | 输入特征 | 期望路由 | 期望结果 |
|---|---|---|---|
| 已配置意图命中 | 命中 intent cache 的固定问题 | 跳过 Router | 直接返回 intent answer，debug 标记 `agentic_router.skipped=true` |
| 普通知识库问题 | 询问产品、价格、政策、排障或配置 | `rag_search` | 进入现有 RAG，并保留 citations |
| 问候 | “你好”“hello” | `direct_response` | 返回 `PASS`，不检索，无 citations |
| 能力询问 | “你能帮我做什么？” | `direct_response` | 返回能力说明，不检索，无 citations |
| 缺少关键条件 | “帮我选个套餐”但无预算、用途、地区 | `clarify` | 返回 `ASK_USER` 和追问 |
| 账号或账单执行 | “帮我退款”“删除我的账号数据” | `human_handoff` | 返回 `ESCALATE`，提示人工处理 |
| 注入攻击 | 包含 prompt injection 或越权指令 | 不进入 Router | 由现有 guardrails 拦截 |
| Router 低置信 | 分类置信度低于阈值 | `rag_search` | 回退现有 RAG，debug 标记 `fallback_to_rag=true` |
| Router 异常 | Router 解析失败或抛错 | `rag_search` | 回退现有 RAG，不影响回答可用性 |
| 三入口一致性 | 同一问题分别走 reply、sync conversation、stream | 相同路由 | 顶层返回结构保持一致 |

## 非目标
- 不在本计划中实现 Router 代码。
- 不新增管理后台配置项。
- 不新增数据库表或迁移。
- 不改变 OpenSearch、Qdrant、PostgreSQL 的读写策略。
- 不改变 WHMCS 工单抓取、审批或入库流程。
- 不改变现有 prompt、normalizer、retrieval planner、reviewer 的职责。

## 后续实现建议
- 优先以小模块方式实现，例如独立的 `agentic_router` 服务，避免改写现有 Orchestrator。
- 先用确定性规则或轻量 LLM-compatible 调用形成最小可回退版本。
- 实现前应补充单元测试，覆盖四个工具、intent 跳过、低置信回退和异常回退。
- 真正修改 RAG 查询链路时，必须同步检查 `.agent-harness/02_RAG_FLOW.md`。

## Harness 同步说明
当前只是新增规格文档，没有修改业务代码、服务拓扑、RAG 查询链路、脚本命令或工作规范。因此本次不需要同步 `.agent-harness/02_RAG_FLOW.md`、`.agent-harness/01_SERVICE_MAP.md`、`.agent-harness/03_DEV_COMMANDS.md` 或 `AGENTS.md`。
