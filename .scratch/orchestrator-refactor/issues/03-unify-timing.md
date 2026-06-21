Status: ready-for-agent

# 统一计时系统

## What to build

消除 AnswerService 和 Orchestrator 双重写入 `ctx.extra["phase_timings"]` 的问题。

当前：
- AnswerService.generate() 维护独立的 `phase_timings` dict（line 97），传入 `ctx.extra["phase_timings"]`
- Orchestrator.run() 通过 `_record_phase_timing()` 也写入 `ctx.extra["phase_timings"]`

改为：
1. Orchestrator 的 `_record_phase_timing()` 成为唯一计时来源
2. AnswerService 不再维护独立的 `phase_timings` dict
3. 删除 AnswerService 中的 `phase_timings` 相关代码
4. 删除传入 `ctx.extra["phase_timings"]` 的赋值

## Acceptance criteria

- [ ] 只有 Orchestrator 写入 phase_timings
- [ ] AnswerService 不再维护 phase_timings
- [ ] timing 相关 debug 输出正确
- [ ] 所有现有测试通过

## Blocked by

None - 可以立即开始
