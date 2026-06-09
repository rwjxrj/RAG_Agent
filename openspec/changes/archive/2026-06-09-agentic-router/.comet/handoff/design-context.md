# Comet Design Handoff

- Change: agentic-router
- Phase: design
- Mode: compact
- Context hash: 52813575b287435ac9e69a0749031d1b1ccac6434339aa48b18124ffcd5e405a

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/agentic-router/proposal.md

- Source: openspec/changes/agentic-router/proposal.md
- Lines: 1-33
- SHA256: 9203a1d00decf8432cd920da51b17392b8c2a4774e6bf8004a749a038444e3e7

```md
## Why

当前客服问答链路在 intent cache 未命中后默认进入固定 RAG 流程，所有问题都会被当作知识库问题处理。这样对问候、能力询问、信息不足、账号账单安全等需要人工处理的问题缺少“先判断再选择工具”的 Agent 决策感。

本变更规划一个轻量 Agentic Router：放在 intent cache 未命中之后、现有 RAG 流程之前，先判断用户问题类型，再选择 `rag_search`、`direct_response`、`clarify` 或 `human_handoff`。低置信或异常时必须默认回退现有 RAG，保证行为可回退。

## What Changes

- 新增 Agentic Router 的规格与设计规划，用于描述 RAG 前工具选择能力。
- 明确 Router 触发位置：guardrails 之后、intent cache 未命中之后、固定 RAG 流程之前。
- 明确 intent cache 命中时 Router 跳过，仍直接返回预设 intent answer。
- 明确 Router 可选择四类工具：`rag_search`、`direct_response`、`clarify`、`human_handoff`。
- 明确外部 API 顶层返回结构保持不变，仅允许在 `debug.agentic_router` 增加可选调试字段。
- 明确新 Router 与现有 `app/services/decision_router.py` 的职责边界：前者是 RAG 前工具选择器，后者仍是检索后证据决策器。
- 本 change 当前只创建 OpenSpec/Comet 规划产物，不实施业务代码。

## Capabilities

### New Capabilities

- `agentic-router`: 定义 intent cache 未命中后、RAG 前的轻量工具选择能力，包括路由输入输出、工具语义、回退策略、debug 返回和验收测试。

### Modified Capabilities

- 无。本次不修改现有 OpenSpec capability；当前仓库 `openspec/specs/` 下没有可复用的既有规格。

## Impact

- 规划影响的未来实现入口：`/reply/generate`、同步会话、流式会话三类问答入口。
- 规划影响的未来服务边界：未来可新增独立 Router 服务模块，但不替换现有 RAG 编排。
- 规划影响的未来返回字段：仅在 `debug` 中增加可选 `agentic_router` 字段，外部顶层返回保持 `answer`、`decision`、`followup_questions`、`citations`、`confidence`、`debug` 不变。
- 不引入新第三方依赖，不修改数据库、Docker、认证、迁移或现有 API 路由。
- 不改变现有 RAG 主流程：`query extract → retrieve → assess evidence → retry → generate → verify`。
```

## openspec/changes/agentic-router/design.md

- Source: openspec/changes/agentic-router/design.md
- Lines: 1-146
- SHA256: 99043aa76eddfa7e7a5716e99070056ca489be1dae84633b4b15b48e5397a385

[TRUNCATED]

```md
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
```

Full source: openspec/changes/agentic-router/design.md

## openspec/changes/agentic-router/tasks.md

- Source: openspec/changes/agentic-router/tasks.md
- Lines: 1-49
- SHA256: afecf401eb2ff88bb989f7c45c0ff6b5dfc6fcae0e54f46b7e4c1924ba7183cd

```md
## 1. Router Contract

- [ ] 1.1 Define Agentic Router input model with `query`, `conversation_history`, `source`, and optional `trace_id`.
- [ ] 1.2 Define Agentic Router output model with `route`, `tool`, `reason`, `confidence`, optional `query_for_tool`, `clarifying_questions`, `risk_flags`, and `fallback_to_rag`.
- [ ] 1.3 Define the four supported route values: `rag_search`, `direct_response`, `clarify`, and `human_handoff`.
- [ ] 1.4 Add unit tests for Router output validation and invalid route handling.

## 2. Router Decision Logic

- [ ] 2.1 Implement `rag_search` as the default route for support knowledge questions.
- [ ] 2.2 Implement `direct_response` classification for greetings, capability questions, and simple interactions that do not require knowledge-base evidence.
- [ ] 2.3 Implement `clarify` classification for questions missing critical conditions, including one to three follow-up questions.
- [ ] 2.4 Implement `human_handoff` classification for account, billing, security, deletion, refund execution, order modification, and other human-only actions.
- [ ] 2.5 Add low-confidence handling that sets `fallback_to_rag=true` and routes to `rag_search`.
- [ ] 2.6 Add exception handling that routes to `rag_search` without breaking the current answer flow.

## 3. RAG Entrypoint Integration

- [ ] 3.1 Locate the shared point after guardrails and intent cache miss for `/reply/generate`, synchronous conversation, and streaming conversation entrypoints.
- [ ] 3.2 Ensure intent cache hits skip Agentic Router and return existing intent answers unchanged.
- [ ] 3.3 Call Agentic Router only on intent cache miss and before the fixed RAG flow.
- [ ] 3.4 Preserve the existing RAG flow for `rag_search`: `query extract -> retrieve -> assess evidence -> retry -> generate -> verify`.
- [ ] 3.5 Keep Agentic Router separate from `app/services/decision_router.py`, which remains the post-retrieval evidence decision component.

## 4. Response Mapping

- [ ] 4.1 Map `rag_search` results to the existing RAG response shape with citations preserved.
- [ ] 4.2 Map `direct_response` to `decision=PASS` with no citations.
- [ ] 4.3 Map `clarify` to `decision=ASK_USER` with follow-up questions.
- [ ] 4.4 Map `human_handoff` to `decision=ESCALATE`.
- [ ] 4.5 Add optional `debug.agentic_router` metadata without changing top-level API fields.
- [ ] 4.6 Add debug metadata for intent cache hit skip and Router fallback-to-RAG cases.

## 5. Verification

- [ ] 5.1 Add tests proving configured intent hits skip Router.
- [ ] 5.2 Add tests proving ordinary knowledge-base questions choose `rag_search` and preserve citations.
- [ ] 5.3 Add tests proving greetings and capability questions choose `direct_response` without retrieval or citations.
- [ ] 5.4 Add tests proving missing key conditions choose `clarify` and return `ASK_USER`.
- [ ] 5.5 Add tests proving account, billing, security, deletion, refund execution, and order modification requests choose `human_handoff` and return `ESCALATE`.
- [ ] 5.6 Add tests proving prompt injection inputs are still intercepted by existing guardrails before Router.
- [ ] 5.7 Add tests proving low-confidence and Router exception paths fall back to `rag_search`.
- [ ] 5.8 Add tests proving `/reply/generate`, synchronous conversation, and streaming conversation entrypoints use consistent Router policy.

## 6. Documentation Sync

- [ ] 6.1 Update `.agent-harness/02_RAG_FLOW.md` only when the Router is actually wired into the RAG query chain.
- [ ] 6.2 Keep `.agent-harness/spec/Agentic Router.md` aligned with final implementation decisions if behavior changes during build.
- [ ] 6.3 Record any reproducible implementation failure or rollback lesson in `.agent-harness/07_FAILURE_MEMORY.md`.
```

## openspec/changes/agentic-router/specs/agentic-router/spec.md

- Source: openspec/changes/agentic-router/specs/agentic-router/spec.md
- Lines: 1-78
- SHA256: a1934bee8711ad1bccc6b5548062688e98297740bd5631eb0d4bee0c897d12c9

```md
## ADDED Requirements

### Requirement: Router executes only after intent cache miss
The system SHALL execute Agentic Router only after guardrails have accepted the request and intent cache does not match a configured intent.

#### Scenario: Intent cache hit skips Router
- **WHEN** a user query matches an existing intent cache entry
- **THEN** the system MUST return the intent answer without executing Agentic Router

#### Scenario: Intent cache miss invokes Router
- **WHEN** a user query passes guardrails and does not match intent cache
- **THEN** the system MUST evaluate the query with Agentic Router before entering the fixed RAG flow

### Requirement: Router preserves existing RAG as default path
The system SHALL preserve the existing RAG flow as the default route for support knowledge questions and uncertain Router results.

#### Scenario: Knowledge question routes to RAG
- **WHEN** the user asks a product, policy, price, troubleshooting, configuration, or knowledge-base question
- **THEN** Agentic Router MUST choose `rag_search` and enter the existing RAG flow

#### Scenario: Low confidence falls back to RAG
- **WHEN** Agentic Router confidence is below the implementation threshold
- **THEN** the system MUST choose `rag_search` with `fallback_to_rag=true`

#### Scenario: Router error falls back to RAG
- **WHEN** Agentic Router parsing fails or raises an exception
- **THEN** the system MUST choose `rag_search` and continue serving the answer through the existing RAG flow

### Requirement: Router provides four tool routes
The system SHALL expose exactly four planned Router routes for the lightweight Agentic Router: `rag_search`, `direct_response`, `clarify`, and `human_handoff`.

#### Scenario: Greeting uses direct response
- **WHEN** the user sends a greeting or simple capability question that does not require knowledge-base evidence
- **THEN** Agentic Router MUST choose `direct_response`, return `PASS`, and return no citations

#### Scenario: Missing critical information uses clarify
- **WHEN** the user asks a question that lacks required conditions and cannot be safely answered
- **THEN** Agentic Router MUST choose `clarify`, return `ASK_USER`, and include one to three follow-up questions

#### Scenario: Execution or sensitive account request uses handoff
- **WHEN** the user asks for account, billing, security, deletion, refund execution, order modification, or other human-only actions
- **THEN** Agentic Router MUST choose `human_handoff` and return `ESCALATE`

### Requirement: Router output is structured and auditable
The system SHALL represent Router decisions with a structured internal output containing route, tool, reason, confidence, optional query rewrite, clarifying questions, risk flags, and fallback status.

#### Scenario: Router returns complete decision object
- **WHEN** Agentic Router evaluates a request
- **THEN** the Router output MUST include `route`, `tool`, `reason`, `confidence`, `clarifying_questions`, `risk_flags`, and `fallback_to_rag`

#### Scenario: Clarify includes questions
- **WHEN** Agentic Router chooses `clarify`
- **THEN** the Router output MUST include user-facing `clarifying_questions`

### Requirement: External API shape remains stable
The system SHALL keep the existing top-level API response fields unchanged and only add optional Agentic Router metadata under `debug`.

#### Scenario: RAG route preserves citations
- **WHEN** Agentic Router chooses `rag_search`
- **THEN** the final API response MUST preserve existing `answer`, `decision`, `followup_questions`, `citations`, `confidence`, and `debug` behavior

#### Scenario: Router debug is optional
- **WHEN** Router metadata is available
- **THEN** the system MAY include `debug.agentic_router` without requiring clients to change their top-level response parsing

### Requirement: Router remains separate from evidence decision router
The system SHALL keep Agentic Router separate from the existing post-retrieval `app/services/decision_router.py` evidence decision behavior.

#### Scenario: Pre-RAG and post-retrieval decisions are not mixed
- **WHEN** a request enters the RAG path
- **THEN** Agentic Router MUST be treated as a pre-RAG tool selector and `decision_router.py` MUST remain the post-retrieval evidence decision component

### Requirement: Entrypoints use consistent Router policy
The system SHALL apply the same planned Router policy across `/reply/generate`, synchronous conversation, and streaming conversation entrypoints.

#### Scenario: Same question across entrypoints
- **WHEN** the same user query is sent through reply, synchronous conversation, and streaming conversation entrypoints
- **THEN** Agentic Router MUST choose the same route category for each entrypoint
```

