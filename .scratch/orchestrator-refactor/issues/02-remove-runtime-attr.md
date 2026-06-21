Status: ready-for-agent

# 消除运行时属性注入

## What to build

将 `ctx._last_reviewer_result`（orchestrator.py line 509）移入 OrchestrContext 的正式字段。

当前代码在 `_apply_result()` 中通过 `ctx._last_reviewer_result = result.reviewer_result` 注入运行时属性，在 `next_action()` 和 `output_builder.py` 中通过 `getattr(ctx, "_last_reviewer_result", None)` 读取。

改为：
1. OrchestrContext 添加 `last_reviewer_result: Any = None` 字段
2. `_apply_result()` 写入 `ctx.last_reviewer_result`
3. `next_action()` 读取 `ctx.last_reviewer_result`
4. `output_builder.py` 读取 `ctx.last_reviewer_result`
5. 删除所有 `getattr(ctx, "_last_reviewer_result", None)` 调用

## Acceptance criteria

- [ ] OrchestrContext 有 `last_reviewer_result` 正式字段
- [ ] 不再有 `ctx._last_reviewer_result` 运行时注入
- [ ] 不再有 `getattr(ctx, "_last_reviewer_result")` 调用
- [ ] reviewer 相关测试通过

## Blocked by

None - 可以立即开始
