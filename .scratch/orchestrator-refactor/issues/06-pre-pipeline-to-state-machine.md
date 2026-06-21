Status: ready-for-agent

# 任务 6：将预处理逻辑纳入状态机

## Parent

PRD: `.scratch/orchestrator-refactor/PRD-phase2.md`

## What to build

将 AnswerService.generate() 中的预处理逻辑（intent cache、agentic router、normalizer、skip_retrieval）移入 Orchestrator 的状态机循环。

### 新增状态

| 状态 | 转换条件 | 逻辑来源 |
|---|---|---|
| INTENT_CACHE | INIT → INTENT_CACHE | answer_service.py:127-150 |
| AGENTIC_ROUTE | INTENT_CACHE → AGENTIC_ROUTE | answer_service.py:154-225 |
| NORMALIZE | AGENTIC_ROUTE → NORMALIZE | answer_service.py:227-268 |
| SKIP_RETRIEVAL | NORMALIZE → SKIP_RETRIEVAL → DONE | answer_service.py:253-268 |

### 状态转换图

```
INIT → INTENT_CACHE → AGENTIC_ROUTE → NORMALIZE → RETRIEVING → ASSESSING → DECIDING → GENERATING → VERIFYING → DONE
                     ↘ early_return   ↘ early_return ↘ SKIP_RETRIEVAL → DONE
```

### 变更点

1. **OrchestratorState 枚举**：新增 INTENT_CACHE、AGENTIC_ROUTE、NORMALIZE、SKIP_RETRIEVAL
2. **Orchestrator.run()**：在主循环前执行预处理状态
3. **Orchestrator._phase_intent_cache()**：新方法，从 answer_service.py 迁移
4. **Orchestrator._phase_agentic_route()**：新方法，从 answer_service.py 迁移
5. **Orchestrator._phase_normalize()**：新方法，从 answer_service.py 迁移
6. **AnswerService.generate()**：删除预处理逻辑，只保留 orchestrator.run() 调用

### 迁移的逻辑

从 AnswerService.generate() 迁移到 Orchestrator：
- 意图缓存检查（~25 行）
- Agentic router 路由（~70 行）
- 语言检测 + normalizer（~40 行）
- skip_retrieval 早返回（~15 行）

总迁移量：~150 行

### 风险

高 — 改变 pipeline 入口点。需要仔细验证：
- 意图缓存命中时的行为不变
- Agentic router 的 direct_response/clarify/human_handoff 路由不变
- Normalizer 的 skip_retrieval 早返回不变
- trace_id 传递正确

## Acceptance criteria

- [ ] OrchestratorState 有 INTENT_CACHE、AGENTIC_ROUTE、NORMALIZE、SKIP_RETRIEVAL 状态
- [ ] Orchestrator.run() 在主循环前执行预处理状态
- [ ] 意图缓存命中时的行为与当前一致
- [ ] Agentic router 路由决策与当前一致
- [ ] Normalizer 的 skip_retrieval 早返回与当前一致
- [ ] AnswerService.generate() 不再包含预处理逻辑
- [ ] 所有现有测试通过
- [ ] 新测试覆盖每个预处理状态

## Blocked by

- 任务 5
