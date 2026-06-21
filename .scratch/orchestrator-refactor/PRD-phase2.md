# Orchestrator Refactor 阶段 2：合并 AnswerService/Orchestrator 为 PipelineRunner

## Problem Statement

当前架构中，AnswerService 拥有所有依赖（RetrievalService、LLMGateway、ReviewerGate、AgenticRouter），Orchestrator 拥有状态机循环。两者通过 OrchestratorHandlers 协议耦合，形成三跳依赖链：

```
Orchestrator.run() → AnswerService.execute() → phase 函数（kwargs 传递依赖）
```

这导致：
1. 新增依赖需要改三个文件（phase 签名、AnswerService.execute()、AnswerService 构造函数）
2. 预处理逻辑（intent cache、agentic router、normalizer）在状态机之外执行，无法享受重试、追踪、错误处理
3. OrchestratorHandlers 协议存在是因为 Orchestrator 无法直接调用 phase 函数（它不拥有依赖）

阶段 1（已完成）已解决：类型化 ctx.extra、消除运行时注入、统一计时、统一模型路由。

## Solution

将 AnswerService 和 Orchestrator 合并为 PipelineRunner，它同时拥有状态机和依赖。预处理逻辑纳入状态机控制。删除 OrchestratorHandlers 协议。

## User Stories

1. As a developer, I want to add a new dependency to a phase function by changing only one file, so that I don't need to update three files (phase signature, execute dispatcher, constructor)
2. As a developer, I want the intent cache logic to be governed by the state machine, so that I can add retry and tracing to it
3. As a developer, I want the agentic router logic to be governed by the state machine, so that I can add error handling and metrics to it
4. As a developer, I want the normalizer logic to be governed by the state machine, so that I can add retry on LLM failure
5. As a developer, I want the skip-retrieval canned response to be a state in the pipeline, so that it's traceable and testable
6. As a developer, I want the OrchestratorHandlers protocol deleted, so that there's no indirection between the loop and phase execution
7. As a developer, I want PipelineRunner to own RetrievalService, LLMGateway, ReviewerGate, and AgenticRouter, so that dependency injection is centralized
8. As a developer, I want each phase function to receive dependencies from PipelineRunner directly, so that there's no kwargs threading
9. As a developer, I want the `ctx.extra` dict to be fully replaced by typed phase output fields, so that there's compile-time safety
10. As a developer, I want the existing tests to pass after the refactor, so that behavior is preserved
11. As a developer, I want new tests for the PipelineRunner entry point, so that the full pipeline is covered
12. As a developer, I want the AnswerService class to become a thin wrapper around PipelineRunner, so that external callers don't break
13. As a developer, I want the state machine to include INTENT_CACHE, AGENTIC_ROUTE, NORMALIZE, and SKIP_RETRIEVAL states, so that the full pipeline is governed
14. As a developer, I want the `_apply_result()` method to be simplified, so that phase result mapping is clear
15. As a developer, I want the `ctx.extra` dict to be removed entirely, so that all inter-phase communication is through typed fields

## Implementation Decisions

### 1. PipelineRunner 类设计

PipelineRunner 继承或组合当前 Orchestrator 的状态机逻辑，同时拥有 AnswerService 的依赖。

```python
class PipelineRunner:
    def __init__(self, settings=None):
        self._settings = settings or get_settings()
        self._retrieval = RetrievalService()
        self._llm = get_llm_gateway()
        self._reviewer = ReviewerGate()
        self._agentic_router = AgenticRouter()
        self._reranker = get_reranker_provider()
        # 模型路由统一入口
        self._primary_model = get_llm_model()
        self._fallback_model = get_llm_fallback_model()
```

### 2. 状态机扩展

当前状态：INIT → RETRIEVING → ASSESSING → DECIDING → GENERATING → VERIFYING → RETRYING → DONE

新增状态：
- `INTENT_CACHE` — 检查意图缓存
- `AGENTIC_ROUTE` — 运行 agentic router
- `NORMALIZE` — 运行 normalizer
- `SKIP_RETRIEVAL` — skip_retrieval 早返回

状态转换：
```
INIT → INTENT_CACHE → AGENTIC_ROUTE → NORMALIZE → RETRIEVING → ASSESSING → DECIDING → GENERATING → VERIFYING → DONE
                                    ↘ SKIP_RETRIEVAL → DONE
```

### 3. run() 方法重写

```python
async def run(self, query, conversation_history, trace_id, source_lang="en") -> AnswerOutput:
    ctx = OrchestratorContext(query=query, trace_id=trace_id, conversation_history=conversation_history)
    
    # Phase 1: Intent cache
    ctx = await self._phase_intent_cache(ctx)
    if ctx.early_return:
        return self._build_output(ctx)
    
    # Phase 2: Agentic router
    ctx = await self._phase_agentic_route(ctx)
    if ctx.early_return:
        return self._build_output(ctx)
    
    # Phase 3: Normalize
    ctx = await self._phase_normalize(ctx, source_lang)
    if ctx.skip_retrieval:
        return self._build_output(ctx)
    
    # Phase 4-8: Main pipeline loop
    while ctx.can_continue():
        action = self.next_action(ctx)
        if action.is_terminal():
            return self._build_output(ctx, action)
        await self._execute_phase(ctx, action)
        self._apply_result(ctx, action)
    
    return self._build_output(ctx)
```

### 4. Phase 函数签名变更

当前签名（通过 kwargs 传递依赖）：
```python
async def execute_retrieve(ctx, *, retrieval, orchestrator, settings) -> PhaseResult
async def execute_generate(ctx, *, llm, orchestrator, settings) -> PhaseResult
async def execute_verify(ctx, *, reviewer) -> PhaseResult
```

新签名（通过 self 传递依赖）：
```python
async def _phase_retrieve(self, ctx: OrchestratorContext) -> PhaseResult
async def _phase_generate(self, ctx: OrchestratorContext) -> PhaseResult
async def _phase_verify(self, ctx: OrchestratorContext) -> PhaseResult
```

每个 `_phase_*` 方法直接访问 `self._retrieval`、`self._llm`、`self._reviewer`。

### 5. 预处理逻辑迁移

从 AnswerService.generate() 迁移到 PipelineRunner 的状态方法：

| 当前位置 | 新状态 | 逻辑 |
|---|---|---|
| answer_service.py:127-150 | `_phase_intent_cache()` | 意图缓存检查 |
| answer_service.py:154-225 | `_phase_agentic_route()` | Agentic router 路由 |
| answer_service.py:227-268 | `_phase_normalize()` | 语言检测 + normalizer |
| answer_service.py:253-268 | `_phase_skip_retrieval()` | skip_retrieval 早返回 |

### 6. ctx.extra 完全删除

阶段 1 已添加类型化字段（RetrievePhaseOutput、GeneratePhaseOutput、VerifyPhaseOutput、OrchestratorDebug）。阶段 2 需要：
- 将所有 `ctx.extra` 读写迁移到类型化字段
- 删除 `ctx.extra: dict[str, Any]` 字段
- 更新所有消费者

### 7. AnswerService 保留为薄包装

```python
class AnswerService:
    def __init__(self):
        self._runner = PipelineRunner()
    
    async def generate(self, query, conversation_history, source_lang="en", trace_id=None):
        return await self._runner.run(query, conversation_history, trace_id, source_lang)
```

外部调用者（API routes）不需要修改。

### 8. OrchestratorHandlers 协议删除

删除 `OrchestratorHandlers` 协议定义。删除 `AnswerService.execute()` 和 `AnswerService.build_output()` 方法。

### 9. PhaseResult 简化

当前 PhaseResult 有 18 个字段，大多数为 None。改为每种 phase 返回自己的类型化结果：

```python
@dataclass
class RetrieveResult:
    evidence_pack: Any
    evidence: list[Any]

@dataclass
class AssessResult:
    quality_report: Any
    passes_quality_gate: bool

@dataclass
class GenerateResult:
    answer: str
    citations: list[Any]
    followup: list[str]
    confidence: float
    answer_plan: Any
    generated_decision: str

@dataclass
class VerifyResult:
    reviewer_result: Any
    hypothesis_judge: dict | None
```

### 10. _apply_result() 简化

当前是 100 行的 if/elif 链。改为类型匹配：

```python
def _apply_result(self, ctx, action, result):
    match action:
        case Action.RETRIEVE:
            ctx.evidence_pack = result.evidence_pack
            ctx.evidence = result.evidence
            ctx.state = State.ASSESSING
        case Action.ASSESS:
            ctx.quality_report = result.quality_report
            ctx.passes_quality_gate = result.passes_quality_gate
            ctx.state = State.DECIDING
        # ...
```

## Testing Decisions

### 好的测试标准
- 通过公共接口（PipelineRunner.run()）测试行为
- 不测试内部实现细节（哪个 phase 被调用、什么顺序）
- 测试 observable behavior：给定输入，输出是什么

### 需要测试的模块
1. **PipelineRunner.run()** — 完整 pipeline 集成测试
2. **_phase_intent_cache()** — 意图缓存命中/未命中
3. **_phase_agentic_route()** — 路由决策（direct_response、clarify、human_handoff、rag）
4. **_phase_normalize()** — normalizer 输出、skip_retrieval 早返回
5. **_phase_retrieve()** — 检索结果、evidence 评估
6. **_phase_generate()** — LLM 生成、self-critic
7. **_phase_verify()** — reviewer gate、targeted retry

### 现有测试参考
- `tests/test_answer_service.py` — 38 个测试，覆盖 intent cache、agentic router、RAG route
- `tests/test_orchestrator.py` — 状态机测试
- `tests/test_rag_integration.py` — 7 个端到端测试
- `tests/test_phase_generate.py` — generate phase 测试
- `tests/test_phase_verify.py` — verify phase 测试

### 测试策略
- 保留所有现有测试（通过 AnswerService 薄包装调用）
- 新增 PipelineRunner 直接调用的测试
- 新增预处理状态的单元测试

## Out of Scope

1. **不改变外部 API 接口** — API routes 继续调用 AnswerService.generate()
2. **不改变 phase 函数的内部逻辑** — 只改变依赖注入方式
3. **不改变 OrchestratorContext 的字段** — 阶段 1 已完成类型化
4. **不改变检索/生成/验证的业务逻辑** — 纯架构重构
5. **不引入新的第三方依赖**

## Further Notes

### 执行顺序

任务 5 → 6 → 7 必须按顺序执行：

**任务 5：将依赖注入移入 Orchestrator**
- Orchestrator 构造时接收 retrieval、llm、reviewer
- run() 循环中直接传递依赖给 phase 函数
- AnswerService.execute() 不再是依赖传递层
- 风险：中 — 改变 Orchestrator 构造函数

**任务 6：将预处理逻辑纳入状态机**
- 新增 INTENT_CACHE、AGENTIC_ROUTE、NORMALIZE、SKIP_RETRIEVAL 状态
- 将 AnswerService.generate() 的前 140 行移入 Orchestrator 循环
- 风险：高 — 改变 pipeline 入口点

**任务 7：删除 OrchestratorHandlers 协议**
- 合并 AnswerService 和 Orchestrator 为 PipelineRunner
- 删除 OrchestratorHandlers 协议
- AnswerService 变为 PipelineRunner 的薄包装
- 风险：高 — 架构性变更

### 阶段 1 已完成的前提

以下已在阶段 1 完成，阶段 2 依赖这些改动：
- RetrievePhaseOutput、GeneratePhaseOutput、VerifyPhaseOutput、OrchestratorDebug 数据类
- OrchContext 上的类型化输出字段
- last_reviewer_result 正式字段
- orchestrator_debug.phase_timings 统一计时
- 模型路由统一通过 Orchestrator

### 关键文件

| 文件 | 当前职责 | 阶段 2 变更 |
|---|---|---|
| orchestrator.py | 状态机循环 | 扩展状态、持有依赖、合并 AnswerService |
| answer_service.py | 依赖持有、预处理 | 变为薄包装 |
| phases/retrieve.py | 检索 phase | 接收依赖从 self 而非 kwargs |
| phases/generate.py | 生成 phase | 接收依赖从 self 而非 kwargs |
| phases/verify.py | 验证 phase | 接收依赖从 self 而非 kwargs |
| phases/assess.py | 评估 phase | 无变更（已无外部依赖） |
| phases/decide.py | 决策 phase | 无变更（已无外部依赖） |
| output_builder.py | 输出构建 | 通过 orchestrator 参数获取模型 |
| schemas.py | 数据类定义 | 新增 PhaseResult 子类 |
