Status: ready-for-agent

# 任务 7：删除 OrchestratorHandlers 协议，合并为 PipelineRunner

## Parent

PRD: `.scratch/orchestrator-refactor/PRD-phase2.md`

## What to build

将 AnswerService 和 Orchestrator 合并为 PipelineRunner。删除 OrchestratorHandlers 协议。AnswerService 变为 PipelineRunner 的薄包装。

### 变更点

1. **PipelineRunner 类**：继承 Orchestrator 的状态机逻辑，拥有 AnswerService 的依赖
2. **删除 OrchestratorHandlers 协议**：不再需要依赖反转
3. **删除 AnswerService.execute()**：已在任务 5 中删除
4. **删除 AnswerService.build_output()**：逻辑移入 PipelineRunner._build_output()
5. **AnswerService 变为薄包装**：
   ```python
   class AnswerService:
       def __init__(self):
           self._runner = PipelineRunner()
       async def generate(self, query, conversation_history, source_lang="en", trace_id=None):
           return await self._runner.run(query, conversation_history, trace_id, source_lang)
   ```
6. **PhaseResult 简化**：每种 phase 返回自己的类型化结果（RetrieveResult、AssessResult、GenerateResult、VerifyResult）
7. **_apply_result() 简化**：从 100 行 if/elif 链改为 match/case

### PipelineRunner.run() 完整流程

```python
async def run(self, query, conversation_history, trace_id, source_lang="en") -> AnswerOutput:
    ctx = OrchestratorContext(query=query, trace_id=trace_id, conversation_history=conversation_history)
    
    # 预处理状态
    ctx = await self._phase_intent_cache(ctx)
    if ctx.early_return: return self._build_output(ctx)
    
    ctx = await self._phase_agentic_route(ctx)
    if ctx.early_return: return self._build_output(ctx)
    
    ctx = await self._phase_normalize(ctx, source_lang)
    if ctx.skip_retrieval: return self._build_output(ctx)
    
    # 主循环
    while ctx.can_continue():
        action = self.next_action(ctx)
        if action.is_terminal():
            return self._build_output(ctx, action)
        result = await self._execute_phase(ctx, action)
        self._apply_result(ctx, action, result)
    
    return self._build_output(ctx)
```

### 删除的代码

| 删除项 | 行数 | 原因 |
|---|---|---|
| OrchestratorHandlers 协议 | ~10 行 | 不再需要 |
| AnswerService.execute() | ~30 行 | 逻辑移入 PipelineRunner._execute_phase() |
| AnswerService.build_output() | ~10 行 | 逻辑移入 PipelineRunner._build_output() |
| AnswerService 构造函数中的依赖 | ~20 行 | 移入 PipelineRunner |
| PhaseResult 的 18 字段 | ~20 行 | 改为 4 个类型化结果 |
| _apply_result() 的 if/elif 链 | ~100 行 | 改为 match/case |

### 保留的代码

| 保留项 | 原因 |
|---|---|
| AnswerService 类 | 外部调用者不需要修改 |
| AnswerService.generate() | 变为薄包装 |
| OrchestratorContext | 阶段 1 已完成类型化 |
| 所有 phase 函数内部逻辑 | 只改变依赖注入方式 |

### 风险

高 — 架构性变更。需要仔细验证：
- 所有现有测试通过
- 外部 API 接口不变
- Phase 函数行为不变
- 状态机转换正确

## Acceptance criteria

- [ ] PipelineRunner 类存在，拥有所有依赖和状态机
- [ ] OrchestratorHandlers 协议被删除
- [ ] AnswerService 是 PipelineRunner 的薄包装
- [ ] AnswerService.generate() 调用 PipelineRunner.run()
- [ ] PhaseResult 被 4 个类型化结果替代
- [ ] _apply_result() 使用 match/case
- [ ] 所有现有测试通过
- [ ] 新测试覆盖 PipelineRunner.run() 的完整流程
- [ ] 外部 API 接口不变

## Blocked by

- 任务 5
- 任务 6
