Status: ready-for-agent

# 任务 5：将依赖注入移入 Orchestrator

## Parent

PRD: `.scratch/orchestrator-refactor/PRD-phase2.md`

## What to build

Orchestrator 构造时接收 retrieval、llm、reviewer 依赖。run() 循环中直接传递依赖给 phase 函数，AnswerService.execute() 不再是依赖传递层。

### 变更点

1. **Orchestrator 构造函数**：新增 `retrieval`、`llm`、`reviewer` 参数
2. **Orchestrator._execute_phase()**：新方法，根据 action 直接调用 phase 函数并传递 self 的依赖
3. **Phase 函数签名**：从 `execute_retrieve(ctx, retrieval=..., settings=...)` 改为接收 orchestrator 或直接接收依赖
4. **删除 AnswerService.execute()**：不再需要手动 if/elif 分发
5. **保留 AnswerService.generate()**：仍然构造 OrchestratorContext 并调用 orchestrator.run()

### Phase 依赖映射

| Phase | 需要的依赖 |
|---|---|
| retrieve | retrieval, settings |
| assess | 无 |
| decide | 无 |
| generate | llm, settings |
| verify | reviewer |

### 向后兼容

AnswerService 仍然存在，仍然拥有 Orchestrator。只是 Orchestrator 现在也拥有依赖。AnswerService.execute() 被删除，但 AnswerService.generate() 保持不变。

## Acceptance criteria

- [ ] Orchestrator 构造函数接收 retrieval、llm、reviewer
- [ ] Orchestrator 有 _execute_phase() 方法，根据 action 调用对应 phase
- [ ] Phase 函数通过 orchestrator 参数获取依赖（而非 kwargs）
- [ ] AnswerService.execute() 被删除
- [ ] AnswerService.generate() 仍然正常工作
- [ ] 所有现有测试通过
- [ ] 新测试覆盖 Orchestrator 直接调用 phase 的场景

## Blocked by

- 任务 1-4（已完成）
