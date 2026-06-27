Status: ready-for-agent

# Issue 1：放宽 generate_reasoning fast-path 条件 + blockers 诊断

## Parent

`.scratch/rag-latency-optimization-phase3/PRD.md`

## What to build

放宽 `_reasoning_prepass_skip_reason` 中的 5 个过严条件，让已通过 quality gate 的低风险简单 case 能够跳过 generate_reasoning；同时新增 `blockers` 诊断字段，记录所有阻止 fast-path 的条件。

这个 slice 的目标是将 `generate_reasoning` 调用从 10/10 降到 3-6/10，generate P95 从 ~11.3s 降到 6-8s。

## Acceptance criteria

- [ ] `missing_signals` 非空但 quality gate 已通过时，允许跳过 reasoning（新增配置开关 `generate_reasoning_fastpath_allow_missing_signals`，默认 true）。
- [ ] `answer_type` 排除列表从 `{pricing, direct_link, account}` 缩减为仅 `{account}`；低风险 `pricing`、`direct_link` 允许跳过。
- [ ] `hard_requirements` 非空但 `quality_report.hard_requirement_coverage` 全部为 True 时，允许跳过（新增配置开关 `generate_reasoning_fastpath_covered_hard_requirements`，默认 true）。
- [ ] evidence chunk fast-path 阈值从 5 提升到 8（修改 `generate_reasoning_fastpath_max_evidence_chunks` 默认值）。
- [ ] debug 输出新增 `blockers` 列表：当 fast-path 未跳过时，记录所有阻止跳过的具体原因。
- [ ] debug 输出跳过时记录 `evidence_count`、`answer_type`、`answer_shape`、`risk_level`、`hard_requirements_covered`。
- [ ] 所有放宽条件均有独立配置开关，关闭后恢复 Phase 2 行为。
- [ ] 单测覆盖：missing_signals 放宽、pricing/direct_link 放宽、hard_requirements 覆盖放宽、阈值提升、blockers 诊断、account 仍排除。
- [ ] 10 条冷启动 smoke 中成功率保持 100%、Recall@5 >= 95%、unknown task = 0。
- [ ] smoke 中 `generate_reasoning` call_count 从 10 降到 3-6。

## Blocked by

None - can start immediately

## Suggested verification

```powershell
python -m pytest tests/test_generate_phase.py tests/test_config.py tests/test_orchestrator.py -q
```

容器 smoke：

```powershell
docker-compose build api worker
docker-compose up -d api worker
docker-compose exec -T api sh -lc 'python .scratch/resume-eval/run_resume_eval.py --dataset-json artifacts/offline_eval/datasets/eval_cases_v1.json --limit 10 --source-url-prefix eval://retrieval/ --case-timeout 180 --output-json /tmp/smoke-phase3-issue1-10.json --output-md /tmp/smoke-phase3-issue1-10.md --capture-llm-calls'
```

## Implementation notes

修改文件：

- `app/services/phases/generate.py`: `_reasoning_prepass_skip_reason()` 放宽条件 + blockers 收集
- `app/core/config.py`: 新增 2 个配置项，修改 1 个默认值
- `tests/test_generate_phase.py`: 新增 ~10 个测试

不改文件：

- `app/services/orchestrator.py`
- `app/services/schemas.py`（GeneratePhaseOutput.reasoning_prepass 已是 dict，无需改 schema）
- `app/services/flow_debug.py`（已传递 reasoning_prepass dict，无需改）

## Notes

- 不要删除 reviewer。
- 不要删除 evidence quality gate。
- 不要改 `answer_shape` 的允许列表（保持 `{direct_lookup, short_answer, yes_no}`）。
- 不要改 `risk_level` 排除逻辑（`medium`/`high` 仍排除）。
- 不要改 `conversation_history` 排除逻辑（有历史仍排除）。
- blockers 列表应包含所有阻止原因，不只是第一个命中的。
