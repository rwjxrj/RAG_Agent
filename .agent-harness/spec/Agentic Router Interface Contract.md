# Agentic Router 触发流程接口契约

## 结论
本文档定义当前项目 Agentic Router 的触发流程、输入输出契约、路由决策语义、debug 字段和未来迁移到 LangGraph 时必须保持的边界。本文档只描述接口契约，不要求修改业务代码、不引入 LangGraph、不改变数据库、Docker、认证或现有 API 路由。

## 适用范围
- 适用于当前 FastAPI RAG 客服项目中的 Agentic Router。
- 适用于三个问答入口：
  - `POST /v1/reply/generate`
  - `POST /v1/conversations/{conversation_id}/messages`
  - `POST /v1/conversations/{conversation_id}/messages:stream`
- 适用于未来把现有流程迁移为 LangGraph 节点图时的接口对齐。

## 非目标
- 不设计 LangGraph 图结构的完整实现。
- 不引入 LangGraph 依赖。
- 不改变现有 RAG 主链路：`query extract -> retrieve -> assess evidence -> retry -> generate -> verify`。
- 不改 `app/services/decision_router.py` 的职责；它仍是检索后的证据决策器。
- 不改变外部 API 顶层返回字段。

## 当前触发顺序
Agentic Router 的触发位置固定在 guardrails 和 intent cache 之后、RAG query extract 之前。

```text
用户请求
  -> API 入口
  -> guardrails: injection check + sanitize
  -> AnswerService.generate()
  -> intent cache
      -> 命中：直接返回 intent answer，Agentic Router 跳过
      -> 未命中：执行 Agentic Router
          -> direct_response：直接返回 PASS
          -> clarify：直接返回 ASK_USER
          -> human_handoff：直接返回 ESCALATE
          -> rag_search：继续现有 RAG 主链路
          -> 低置信/异常：回退 rag_search
```

## 触发前置条件
Agentic Router 只允许在以下条件同时成立时执行：

| 条件 | 说明 |
|---|---|
| guardrails 已通过 | 注入攻击、越权提示等输入应在 Router 前被拦截。 |
| 输入已清洗 | Router 接收的是 `sanitize_user_input()` 后的 query。 |
| intent cache 未命中 | 命中 intent cache 时，Router 必须跳过。 |
| 已进入 `AnswerService.generate()` | 三个外部入口都应收敛到同一服务层策略。 |

## 概念输入契约
Router 的概念输入为 `AgenticRouterInput`。

```json
{
  "query": "用户清洗后的原始问题",
  "conversation_history": [
    {
      "role": "user|assistant",
      "content": "历史消息内容"
    }
  ],
  "source": "reply|conversation|stream",
  "trace_id": "可选追踪 ID"
}
```

### 字段说明
| 字段 | 类型 | 必填 | 当前约束 | LangGraph 迁移要求 |
|---|---|---|---|---|
| `query` | string | 是 | 必须是 guardrails 通过且清洗后的用户问题。 | 应作为图状态中的原始用户问题字段保留。 |
| `conversation_history` | array | 否 | 默认空数组；应使用已截断的历史上下文。 | 应作为只读上下文传入 Router 节点。 |
| `source` | string | 否 | 当前实现固定为 `"reply"`。 | 迁移时建议按入口区分为 `reply`、`conversation`、`stream`，但不得改变路由策略。 |
| `trace_id` | string/null | 否 | 沿用现有追踪 ID。 | 应贯穿 LangGraph state，用于日志和 debug。 |

## 概念输出契约
Router 的概念输出为 `AgenticRouterDecision`。

```json
{
  "route": "rag_search|direct_response|clarify|human_handoff",
  "tool": "rag_search|direct_response|clarify|human_handoff",
  "reason": "选择原因",
  "confidence": 0.86,
  "query_for_tool": "可选工具输入问题",
  "clarifying_questions": [],
  "risk_flags": [],
  "fallback_to_rag": false
}
```

### 字段说明
| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `route` | enum | 是 | 标准路由结果，只允许四个值。 |
| `tool` | string | 是 | 当前与 `route` 一致；未来可映射到 LangGraph tool/node 名。 |
| `reason` | string | 是 | 可审计的简短原因，不应包含敏感信息。 |
| `confidence` | number | 是 | 范围为 `0.0` 到 `1.0`。 |
| `query_for_tool` | string/null | 否 | 未来可用于改写后的检索问题；为空时使用 `query`。 |
| `clarifying_questions` | array | 否 | `clarify` 路径下返回给用户的追问，最多 3 个。 |
| `risk_flags` | array | 否 | 记录账号、账单、安全、退款、删除等风险标签。 |
| `fallback_to_rag` | boolean | 是 | Router 低置信或异常回退 RAG 时为 `true`。 |

## 路由语义
### `rag_search`
- 默认路由。
- 适用于产品、价格、政策、排障、配置、知识库问答等需要证据的问题。
- 进入现有完整 RAG 主链路。
- 必须保留 citations、原有 debug、timings、retry_count。

### `direct_response`
- 不检索，不进入 RAG。
- 适用于问候、能力询问、简单交互。
- 外部返回：

```json
{
  "decision": "PASS",
  "citations": []
}
```

### `clarify`
- 不检索，不进入 RAG。
- 适用于缺少关键条件且无法安全回答的问题。
- 外部返回：

```json
{
  "decision": "ASK_USER",
  "followup_questions": ["追问 1"]
}
```

### `human_handoff`
- 不检索，不进入 RAG。
- 适用于账号、账单、安全、删除、退款执行、订单修改等需人工处理的问题。
- 外部返回：

```json
{
  "decision": "ESCALATE",
  "citations": []
}
```

## 跳过与回退契约
### intent cache 命中
当 `match_intent(query)` 命中时：
- 不执行 Agentic Router。
- 直接返回 intent answer。
- debug 中必须体现 Router 被跳过。

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

### Router 低置信
当 Router 置信度低于实现阈值时：
- 路由必须变为 `rag_search`。
- `fallback_to_rag=true`。
- 不应中断当前问答。

### Router 异常
当 Router 抛错、解析失败或返回不可用结果时：
- 必须捕获异常。
- 必须回退 `rag_search`。
- `reason` 建议为 `router_exception` 或 `router_low_confidence`。
- 不得向用户暴露内部异常细节。

## 外部 API 返回契约
外部 API 顶层字段保持不变：

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

Router 只允许增加可选 debug 字段：

```json
{
  "debug": {
    "agentic_router": {
      "route": "rag_search",
      "tool": "rag_search",
      "reason": "support_knowledge_question",
      "confidence": 0.86,
      "skipped": false,
      "fallback_to_rag": false
    }
  }
}
```

## 当前实现与迁移注意事项
| 项目 | 当前实现 | LangGraph 迁移建议 |
|---|---|---|
| Router 位置 | `AnswerService.generate()` 内部，intent cache miss 后。 | 建议建模为 `agentic_router` 节点，放在 `intent_cache` 节点之后、RAG 子图之前。 |
| 三入口一致性 | 三入口均调用 `AnswerService.generate()`。 | 三入口应进入同一图入口或同一 Router 子图。 |
| `source` 字段 | 当前传入固定 `"reply"`。 | 可升级为真实入口来源，但不得改变相同 query 的路由策略。 |
| RAG 回退 | `rag_search` 继续现有 Orchestrator。 | 可映射为 `rag_subgraph` 或 `rag_search` 节点。 |
| 非 RAG 路径 | 在服务层直接构造 `AnswerOutput`。 | 可映射为终止节点：`direct_response_node`、`clarify_node`、`human_handoff_node`。 |
| debug | 写入 `debug.agentic_router`。 | 应作为图状态的一部分贯穿最终输出。 |

## LangGraph 节点映射建议
未来迁移时，可以按以下概念拆分，但必须保持本文档契约：

```text
guardrails_node
  -> intent_cache_node
      -> intent_hit_end
      -> agentic_router_node
          -> direct_response_end
          -> clarify_end
          -> human_handoff_end
          -> rag_subgraph
```

建议的 LangGraph state 字段：

```json
{
  "query": "用户问题",
  "conversation_history": [],
  "source": "reply|conversation|stream",
  "trace_id": "trace-id",
  "intent_cache": "matched_intent_key|null",
  "agentic_router": {
    "route": "rag_search",
    "reason": "support_knowledge_question",
    "confidence": 0.86,
    "fallback_to_rag": false,
    "skipped": false
  },
  "answer_output": {
    "answer": "",
    "decision": "",
    "followup_questions": [],
    "citations": [],
    "confidence": 0.0,
    "debug": {}
  }
}
```

## 不变量
迁移为 LangGraph 后也必须保持以下不变量：
- guardrails 仍在 Router 前执行。
- intent cache 命中时 Router 仍跳过。
- `rag_search` 仍保留现有 RAG 行为和 citations。
- 低置信或异常仍回退 `rag_search`。
- 外部 API 顶层字段仍保持兼容。
- `decision_router.py` 仍表示检索后证据决策，不与 Agentic Router 混用。
- debug 中的 `agentic_router` 字段保持可选，客户端不得依赖其必然存在。

## 测试契约
最低测试覆盖应包括：
- intent cache 命中：Router 不执行，返回 intent answer。
- `rag_search`：进入 RAG，保留 citations。
- `direct_response`：返回 `PASS`，无 citations。
- `clarify`：返回 `ASK_USER`，带追问。
- `human_handoff`：返回 `ESCALATE`。
- guardrails 拦截：注入攻击不进入 Router。
- Router 低置信：回退 `rag_search`。
- Router 异常：回退 `rag_search`。
- 三入口一致性：reply、同步会话、流式会话共享同一 Router 策略。

## 验收标准
- 文档明确说明 Router 位于 guardrails 之后、intent cache miss 之后、RAG 之前。
- 文档明确当前实现和未来 LangGraph 迁移之间的接口边界。
- 文档明确四类路由、跳过规则、回退规则、debug 契约和外部 API 兼容要求。
- 文档不要求新增依赖、不要求改数据库、不要求改 Docker、不要求改业务代码。
- 文档可作为后续 LangGraph 迁移时的节点输入输出契约依据。

## Harness 同步说明
本次只新增接口契约文档，没有修改业务代码、服务拓扑、RAG 查询链路、开发命令或安全边界。因此无需同步 `.agent-harness/02_RAG_FLOW.md`、`.agent-harness/01_SERVICE_MAP.md`、`.agent-harness/03_DEV_COMMANDS.md` 或 `AGENTS.md`。
