## Context

当前系统已有固定 RAG 查询链路：`query extract → retrieve → assess evidence → retry → generate → verify`。在现有链路中，intent cache 命中时可以直接返回预设答案；未命中后则默认进入完整 RAG。这个策略稳定但缺少 RAG 前的问题类型判断，导致问候、能力询问、信息不足和人工处理类请求也容易被送入检索生成流程。

Agentic Router 的设计目标是在不替换现有 RAG 的前提下，补一个轻量、可回退、可审计的前置工具选择层。它只在 guardrails 放行且 intent cache 未命中后执行。

规划位置：

```text
reply / conversations / stream
  -> guardrails
  -> AnswerService.generate()
  -> intent cache
      -> hit: return intent answer, skip Agentic Router
      -> miss: Agentic Router
          -> rag_search: existing RAG flow
          -> direct_response: PASS without citations
          -> clarify: ASK_USER with follow-up questions
          -> human_handoff: ESCALATE
```

## Goals / Non-Goals

**Goals:**

- 增加 RAG 前的轻量 Agent 决策感。
- 在 intent cache 未命中后选择合适工具，而不是所有问题固定进入 RAG。
- 保留现有 RAG 主流程和外部 API 顶层返回格式。
- 明确低置信、解析失败、异常时默认回退 `rag_search`。
- 明确 Agentic Router 与现有 `app/services/decision_router.py` 的职责边界。
- 保证未来 `/reply/generate`、同步会话、流式会话三类入口策略一致。

**Non-Goals:**

- 不实施本变更的业务代码。
- 不引入 LangGraph 或新的第三方依赖。
- 不新增数据库表、迁移、Docker 配置或认证逻辑。
- 不替换当前 RAG 编排。
- 不改变 OpenSearch、Qdrant、PostgreSQL 的读写策略。
- 不改变 WHMCS 工单抓取、审批或入库流程。

## Decisions

### Decision: Place Router after intent cache miss and before RAG

Agentic Router 只在 intent cache 未命中后执行。这样可保留已配置意图的确定性行为，也避免 Router 对高优先级预设回答造成干扰。

Alternatives considered:
- 放在 intent cache 前：会让 Router 截获本应直接命中的固定意图，增加不确定性。
- 放在 RAG 检索后：会与现有 `decision_router.py` 职责重叠，无法解决“是否需要检索”的问题。

### Decision: Keep `rag_search` as default and fallback route

`rag_search` 是默认工具。Router 低置信、结构化输出解析失败或运行异常时，必须回退到现有 RAG。

Alternatives considered:
- 低置信时追问：可能增加用户摩擦，并改变当前知识库问答的可用性。
- 低置信时拒答：会降低系统可用性，不符合可回退目标。

### Decision: Keep route set small

首版只规划四个工具：`rag_search`、`direct_response`、`clarify`、`human_handoff`。这四类覆盖当前客服问答中最有价值的分流场景，同时避免把 Router 变成复杂编排器。

Alternatives considered:
- 增加更多工具：会扩大实现范围，并引入更多测试和安全边界。
- 只做 RAG/direct 两类：无法覆盖信息不足和人工处理类请求。

### Decision: Preserve API top-level response shape

外部 API 顶层仍保持 `answer`、`decision`、`followup_questions`、`citations`、`confidence`、`debug`。Router 信息只作为可选字段写入 `debug.agentic_router`。

Alternatives considered:
- 新增顶层字段：调用方需要适配，超出轻量变更范围。
- 不暴露 debug：排查 Router 选择原因会困难，也不利于验收。

### Decision: Separate Router from `decision_router.py`

Agentic Router 是 RAG 前工具选择器；`app/services/decision_router.py` 仍是检索后证据决策器，继续基于证据质量输出 `PASS`、`ASK_USER`、`ESCALATE` 等结果。两者命名、输入输出和 debug 字段必须保持可区分。

Alternatives considered:
- 复用 `decision_router.py`：会混淆“是否检索”和“证据是否足够”两个决策点。
- 替换 `decision_router.py`：会扩大回归风险，不符合本变更边界。

## Interface

概念输入：

```json
{
  "query": "用户原始问题",
  "conversation_history": [],
  "source": "reply|conversation|stream",
  "trace_id": "可选"
}
```

概念输出：

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

## Tool Semantics

- `rag_search`: 默认工具，进入现有完整 RAG 流程，保留 citations、confidence 和现有 debug metadata。
- `direct_response`: 用于问候、能力说明、简单交互类问题；不检索，返回 `PASS`，无 citations。
- `clarify`: 用于缺少关键条件且无法安全回答的问题；返回 `ASK_USER` 和 1 到 3 个追问。
- `human_handoff`: 用于账号、账单、安全、删除、退款执行、订单修改等需人工处理的问题；返回 `ESCALATE`。

## Risks / Trade-offs

- [Risk] Router 误判导致知识库问题没有进入 RAG → Mitigation: 将 `rag_search` 作为默认路径，并在低置信时回退。
- [Risk] Router 异常影响主问答链路 → Mitigation: Router 调用必须被异常保护包裹，失败时设置 `fallback_to_rag=true`。
- [Risk] debug 字段泄露过多内部信息 → Mitigation: `reason` 使用短枚举或简短审计原因，不包含敏感 prompt 或内部上下文。
- [Risk] 与现有 `decision_router.py` 概念混淆 → Mitigation: 文档、命名和 debug 字段均明确区分 pre-RAG Router 与 post-retrieval evidence decision。

## Migration Plan

当前 change 只沉淀规划产物，不实施代码，因此没有运行时迁移。

未来实现时建议按以下顺序推进：

1. 新增独立 Router 模块和单元测试。
2. 在 intent cache miss 后接入 Router，但保持 `rag_search` 默认回退。
3. 对 `/reply/generate`、同步会话、流式会话做一致性测试。
4. 验证 debug 字段兼容现有 API 返回。
5. 真正修改 RAG 查询链路后，同步更新 `.agent-harness/02_RAG_FLOW.md`。

Rollback strategy:
- 通过配置或代码路径禁用 Router。
- 所有低置信和异常路径回退现有 RAG，因此禁用后应恢复当前固定 RAG 行为。

## Open Questions

- 未来实现时 Router 是先用确定性规则，还是使用已有 OpenAI-compatible LLM 调用进行分类。
- `confidence` 的默认阈值需要结合真实流量样本确定。
- `direct_response` 的固定回复文案是否需要配置化。
