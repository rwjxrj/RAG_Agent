Status: ready-for-agent

# 统一模型路由

## What to build

将分散在 3 处的模型路由集中到 Orchestrator。

当前：
- `Orchestrator.get_model_for_query()` → `get_model_for_task("generate")`
- `generate.py` 通过 `orchestrator.get_model_for_query()` 获取模型
- `relevance_check.py` 直接调用 `get_model_for_task()`，绕过 Orchestrator
- `output_builder.py` 通过回调参数获取模型

改为：
1. Orchestrator 暴露统一的 `get_model_for_task(task: str)` 方法
2. `generate.py` 通过 `orchestrator.get_model_for_task("generate")` 获取模型
3. `relevance_check.py` 接收 orchestrator 参数，通过 `orchestrator.get_model_for_task()` 获取模型
4. `output_builder.py` 通过 orchestrator 参数获取模型，不接收回调
5. 删除 `AnswerService.build_output()` 中传递回调的代码

## Acceptance criteria

- [ ] 所有模型路由通过 Orchestrator
- [ ] relevance_check.py 不再直接调用 get_model_for_task
- [ ] output_builder.py 不再接收 get_model_for_query 回调
- [ ] 模型选择行为不变
- [ ] 所有现有测试通过

## Blocked by

None - 可以立即开始（与任务 1-3 并行）
