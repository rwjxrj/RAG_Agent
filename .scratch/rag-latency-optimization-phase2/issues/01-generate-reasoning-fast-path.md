Status: ready-for-agent

# Issue 1：生成阶段 fast-path：简单 case 跳过 generate_reasoning

## Parent

`.scratch/rag-latency-optimization-phase2/PRD.md`

## What to build

为简单客服问答增加生成阶段 fast-path：当问题是简单直答、证据质量已通过、证据数量较少且不属于高风险或复杂策略场景时，跳过 `generate_reasoning` 预推理，直接进入最终答案生成。

这个 slice 的目标是减少每条简单 case 一次 4-5 秒级 LLM 调用，同时保留最终生成、证据引用和 reviewer 校验，不绕过安全边界。

## Acceptance criteria

- [ ] 简单 `direct_lookup` / `short_answer` 场景在 evidence quality pass 且 evidence chunk 数量不超过阈值时，不调用 `generate_reasoning`。
- [ ] 高风险、政策执行、退款执行、账号安全、多方案比较、多轮上下文依赖场景仍调用 `generate_reasoning`。
- [ ] 跳过 `generate_reasoning` 后仍执行最终 `generate`，并保留证据约束、引用和 reviewer。
- [ ] debug/timing 输出能区分 `generate_reasoning` 是执行还是跳过，并记录跳过原因。
- [ ] fast-path 有配置开关；关闭后恢复原有生成路径。
- [ ] 单测覆盖“跳过”和“不跳过”两类路径。
- [ ] 10 条冷启动 smoke 中成功率保持 100%、Recall@5 >= 95%、unknown task = 0。
- [ ] smoke 中 `generate_reasoning` call_count 下降，`generate P95` 较当前冷启动基线 9.1s 有下降。

## Blocked by

None - can start immediately

## Suggested verification

```powershell
python -m pytest tests/test_orchestrator.py tests/test_answer_service.py tests/test_llm_task_context.py -q
```

容器 smoke：

```powershell
docker-compose build api worker
docker-compose up -d api worker
docker-compose exec -T api sh -lc 'python .scratch/resume-eval/run_resume_eval.py --dataset-json artifacts/offline_eval/datasets/eval_cases_v1.json --limit 10 --source-url-prefix eval://retrieval/ --case-timeout 180 --output-json /tmp/smoke-generate-fastpath-10.json --output-md /tmp/smoke-generate-fastpath-10.md --capture-llm-calls'
```

## Notes

- 不要删除 reviewer。
- 不要删除 evidence quality gate。
- 不要用热缓存结果判断是否达标；本 issue 需要看冷启动 LLM call_count 和 phase timings。
