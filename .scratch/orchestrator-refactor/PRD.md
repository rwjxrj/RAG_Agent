# Orchestrator Refactor: 消除 AnswerService/Orchestrator 分裂脑

## 背景

当前架构中，AnswerService 拥有所有依赖（RetrievalService、LLMGateway、ReviewerGate），Orchestrator 拥有状态机循环。两者通过 OrchestratorHandlers 协议耦合，形成三跳依赖链：

```
Orchestrator.run() → AnswerService.execute() → phase 函数（kwargs 传递依赖）
```

## 目标

渐进式重构，分两阶段：
- **阶段 1（低/中风险）**：类型化 ctx.extra、消除运行时注入、统一计时、统一模型路由
- **阶段 2（高风险）**：依赖注入移入 Orchestrator、预处理纳入状态机、合并为 PipelineRunner

## 阶段 1 任务

1. 给 ctx.extra 添加类型化替代字段
2. 消除运行时属性注入（_last_reviewer_result）
3. 统一计时系统
4. 统一模型路由

## 验证标准

- 所有现有测试通过
- 新测试覆盖类型化字段
- 行为无变化（纯重构）
