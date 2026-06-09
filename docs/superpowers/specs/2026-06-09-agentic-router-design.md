---
comet_change: agentic-router
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-09-agentic-router
status: final
---

# Agentic Router 技术设计

## 结论

Agentic Router 采用“独立轻量 Router 模块 + `AnswerService.generate()` 内部接入”的方案。Router 位于 guardrails 之后、intent cache 未命中之后、固定 RAG 流程之前；`rag_search` 是默认和异常回退路径。该设计不替换现有 RAG，不复用或改造检索后的 `app/services/decision_router.py`，也不改变外部 API 顶层返回格式。

## 上游事实源

- OpenSpec change: `openspec/changes/agentic-router`
- Canonical capability spec: `openspec/changes/agentic-router/specs/agentic-router/spec.md`
- Handoff context: `openspec/changes/agentic-router/.comet/handoff/design-context.md`
- Handoff hash: `52813575b287435ac9e69a0749031d1b1ccac6434339aa48b18124ffcd5e405a`

本设计文档只细化实现方案、技术风险和测试策略，不重新定义需求。能力要求以 OpenSpec delta spec 为准。

## 现状观察

当前三个用户入口最终都收敛到 `AnswerService.generate()`：

- `/reply/generate` 在 `app/api/routes/reply.py` 中调用 `AnswerService.generate()`。
- 同步会话在 `app/api/routes/conversations.py` 中调用 `AnswerService.generate()`。
- 流式会话在 `app/api/routes/conversations.py` 中异步调用 `AnswerService.generate()`。

`AnswerService.generate()` 内部已有 intent cache 命中逻辑。命中时返回 `PASS`、空 citations、`confidence=1.0` 和 `debug.intent_cache`；未命中后继续进入 query extract、retrieve、assess evidence、retry、generate、verify 等 RAG 阶段。

因此最小且一致的接入点是 `AnswerService.generate()` 内部 intent cache miss 之后、query extract 之前。

## 推荐方案

新增一个独立 Router 服务模块，未来实现时可命名为 `app/services/agentic_router.py`。该模块只负责输入归一、路由选择和结构化决策输出，不直接执行 RAG 检索、LLM 生成、数据库写入或外部系统操作。

建议数据流：

```text
API route
  -> guardrails validate + sanitize
  -> AnswerService.generate(query, history, trace_id)
      -> intent cache
          -> hit: return intent answer, debug.agentic_router.skipped=true
          -> miss: Agentic Router
              -> rag_search: continue existing RAG
              -> direct_response: return AnswerOutput(PASS)
              -> clarify: return AnswerOutput(ASK_USER)
              -> human_handoff: return AnswerOutput(ESCALATE)
              -> low confidence/error: continue existing RAG, fallback_to_rag=true
```

## 组件边界

### Agentic Router

职责：
- 接收原始 query、截断后的 conversation history、入口 source 和 trace_id。
- 输出标准化 route、tool、reason、confidence、可选 query rewrite、clarifying questions、risk flags、fallback_to_rag。
- 对低置信和异常路径给出可审计回退结果。

不负责：
- 不执行向量检索。
- 不生成最终 RAG 答案。
- 不写数据库或触发后台执行动作。
- 不替换 post-retrieval `decision_router.py`。

### AnswerService

职责：
- 保留现有 intent cache 命中行为。
- 在 intent cache miss 后调用 Agentic Router。
- 根据 Router route 决定是否继续现有 RAG，或直接构造 `AnswerOutput`。
- 将 Router 信息合并到 `debug.agentic_router`。

### decision_router.py

职责保持不变：仍是检索后的证据决策器，用于基于证据质量输出 `PASS`、`ASK_USER`、`ESCALATE` 等结果。它不承担 RAG 前工具选择。

## 路由策略

### rag_search

默认路径。适用于产品、政策、价格、排障、配置、知识库问答，以及 Router 不确定或异常的所有情况。

处理方式：
- 继续执行现有完整 RAG 流程。
- 保留 citations、confidence 和现有 debug metadata。
- 如由低置信或异常触发，写入 `debug.agentic_router.fallback_to_rag=true`。

### direct_response

适用于问候、能力说明、简单交互类问题。

处理方式：
- 不检索。
- 不调用 RAG 生成。
- 返回 `decision=PASS`。
- citations 为空。

### clarify

适用于缺少关键条件且无法安全回答的问题。

处理方式：
- 不检索。
- 返回 `decision=ASK_USER`。
- `followup_questions` 包含 1 到 3 个追问。

### human_handoff

适用于账号、账单、安全、删除、退款执行、订单修改等必须人工处理或确认的请求。

处理方式：
- 不检索。
- 返回 `decision=ESCALATE`。
- 回复内容提示客服或人工流程跟进，不承诺已执行任何后台操作。

## 接口草案

内部输入：

```json
{
  "query": "用户原始问题",
  "conversation_history": [],
  "source": "reply|conversation|stream",
  "trace_id": "可选"
}
```

内部输出：

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

外部 API 顶层字段保持：

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

Router 只增加可选 debug：

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

## 关键取舍

### 接入点选在 AnswerService

推荐接入 `AnswerService.generate()`，因为现有三个入口已经收敛到这里。这避免在 `reply.py`、同步会话和流式会话中复制 Router 调用，也保证三入口行为一致。

### 不在 API route 层接入

API route 层能看到 source，但会造成三处重复分支。后续新增入口时也容易漏接 Router。

### 不复用 decision_router.py

`decision_router.py` 的语义是检索后证据决策。Agentic Router 是检索前工具选择。复用会混淆两个不同决策点，也会增加 RAG 主流程回归风险。

### 首版不引入复杂编排框架

本方案不需要 LangGraph。四个工具路由是简单枚举，低置信和异常都回退 RAG，用普通服务模块即可表达。

## 错误处理

- Router 输出无法解析：记录 `reason=router_parse_error`，选择 `rag_search`。
- Router 抛异常：捕获异常，记录 `reason=router_exception`，选择 `rag_search`。
- Router 置信度低：记录 `reason=router_low_confidence`，选择 `rag_search`。
- Router 输出未知 route：按无效输出处理，回退 `rag_search`。

这些路径都不得影响现有问答可用性。

## 测试策略

单元测试：
- Router 输出模型校验。
- 四类 route 分类。
- 未知 route、低置信、异常回退。
- `clarify` 的追问数量为 1 到 3。
- `human_handoff` 不承诺执行后台操作。

AnswerService 集成测试：
- intent cache 命中时 Router 跳过。
- intent cache 未命中且 Router 选择 `rag_search` 时进入现有 RAG。
- `direct_response` 不触发检索且 citations 为空。
- `clarify` 返回 `ASK_USER` 和追问。
- `human_handoff` 返回 `ESCALATE`。
- Router 低置信或异常时继续现有 RAG。

入口一致性测试：
- 同一个问题分别走 `/reply/generate`、同步会话、流式会话，route category 保持一致。

安全测试：
- prompt injection 或越权输入仍由现有 guardrails 在 Router 前拦截。

## 实施顺序建议

1. 新增 Router 数据模型和服务模块。
2. 写 Router 单元测试，先覆盖四类 route 和回退策略。
3. 在 `AnswerService.generate()` 的 intent cache miss 后接入 Router。
4. 为直接返回类 route 构造 `AnswerOutput`。
5. 为 RAG 路径合并 `debug.agentic_router`。
6. 补三入口一致性测试。
7. 真正改动 RAG 查询链路后，同步 `.agent-harness/02_RAG_FLOW.md`。

## 风险与缓解

- Router 误判知识库问题：默认和低置信都走 `rag_search`。
- Router 异常影响主链路：调用处必须捕获异常并回退 RAG。
- debug 信息过度暴露：`reason` 使用短枚举，不写 prompt 或内部上下文。
- 与 `decision_router.py` 混淆：命名、文档和 debug 字段都明确区分 pre-RAG Router 与 post-retrieval evidence decision。

## Spec Patch

当前不需要回写 OpenSpec delta spec。现有 `openspec/changes/agentic-router/specs/agentic-router/spec.md` 已覆盖触发位置、四类工具、结构化输出、API 兼容、与 `decision_router.py` 分离、三入口一致性、低置信和异常回退等验收场景。
