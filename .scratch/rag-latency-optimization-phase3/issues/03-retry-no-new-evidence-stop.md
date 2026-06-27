Status: ready-for-agent

# Issue 3：Retry "无新增证据停止" — source set 完全相同即终止

## Parent

`.scratch/rag-latency-optimization-phase3/PRD.md`

## What to build

在现有 retry 收敛逻辑基础上增加一个停止条件：如果 retry 前后候选 source set 完全相同（不要求 missing_signals 一致），说明检索已饱和，停止继续 retry。

这个 slice 的目标是降低 P95 尾部延迟，避免在 retrieval 饱和时反复消耗 LLM 调用。

## Acceptance criteria

- [ ] retry 前后 source set 完全相同时停止 retry，记录 `convergence_reason = "source_set_unchanged_retry_saturated"`。
- [ ] source set 有变化时不影响现有收敛判断。
- [ ] 使用现有 `quality_gate_retry_convergence_enabled` 开关，不新增配置项。
- [ ] 单测覆盖：source set 相同 + missing_signals 不同 → 停止；source set 有变化 → 不停止；convergence disabled → 不停止。
- [ ] 10 条冷启动 smoke 中成功率保持 100%、Recall@5 >= 95%、unknown task = 0。
- [ ] smoke 中 retry case 数不高于当前基线。

## Blocked by

None - can start immediately

## Suggested verification

```powershell
python -m pytest tests/test_quality_gate_retry_convergence.py tests/test_orchestrator.py -q
```

## Implementation notes

修改文件：

- `app/services/orchestrator.py`: `_should_stop_retry()` 方法中新增第 4 个条件
- `tests/test_quality_gate_retry_convergence.py`: 新增 ~3 个测试

不改文件：

- `app/services/phases/assess.py`（诊断记录已完善）
- `app/services/evidence_quality.py`
- `app/core/config.py`（复用现有开关）

## Notes

- 不要直接把 `max_retrieval_attempts` 改成 1。
- 不要删除现有的两个收敛条件（`same_missing_signals_no_new_sources`、`top_sources_cover_expected`）。
- 这个条件比 `same_missing_signals_no_new_sources` 更宽松：只要 source 没变就停，不管 missing_signals 是否变化。
- 理由是：retrieval 饱和意味着换 query 策略也无法拿到新证据，继续 retry 只浪费 LLM 调用。
