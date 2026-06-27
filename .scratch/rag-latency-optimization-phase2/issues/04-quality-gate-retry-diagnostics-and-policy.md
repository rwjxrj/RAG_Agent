Status: ready-for-agent

# Issue 4：Quality Gate retry 诊断与策略收敛

## Parent

`.scratch/rag-latency-optimization-phase2/PRD.md`

## What to build

为 quality gate retry 增加结构化诊断，并基于诊断结果收敛低价值 retry：当连续 retry 的 missing signals 相同且候选 source 没有变化时停止重复检索；当 Top5 已命中 expected source 但质量门仍失败时，优先进入生成或 ASK_USER，而不是盲目重跑检索。

这个 slice 的目标是降低 P95 尾部延迟，同时保留对真正证据缺失场景的 retry 能力。

## Acceptance criteria

- [ ] 每个 retry case 记录 retry_count、selected query、active hypothesis、required evidence、hard requirements。
- [ ] 每个 retry case 记录 evidence_selector 是否使用 LLM，以及 skip/trigger reason。
- [ ] 每个 retry case 记录 quality_score、completeness_score、actionability_score、missing_signals、hard requirement coverage。
- [ ] 每次 retry 前后记录候选 source set 是否变化。
- [ ] 连续相同 missing_signals 且候选 source 未变化时停止 retry，并记录终止原因。
- [ ] `quality_llm_failed` 继续不触发 retry。
- [ ] Top5 已命中 expected source 但 quality gate fail 的 case 不因弱质量信号无限重试。
- [ ] retry 策略收敛有配置开关；关闭后恢复原有 retry 行为。
- [ ] 单测覆盖 retry 诊断、无新 source 停止、quality LLM failure 不 retry、Top5 命中后不重复检索。
- [ ] 10 条冷启动 smoke 中成功率保持 100%、Recall@5 >= 95%、unknown task = 0。
- [ ] smoke 中 retry case 数和 evidence_quality call_count 不高于当前冷启动基线 2/10、12 次。
- [ ] 完成后跑 100 条 benchmark，并比较 Recall@5、Hit@5、MRR、P50、P95、retry 分布。

## Blocked by

- `.scratch/rag-latency-optimization-phase2/issues/01-generate-reasoning-fast-path.md`
- `.scratch/rag-latency-optimization-phase2/issues/02-evidence-selector-trigger-narrowing.md`
- `.scratch/rag-latency-optimization-phase2/issues/03-normalizer-fast-path.md`

## Suggested verification

```powershell
python -m pytest tests/test_evidence_quality.py tests/test_orchestrator.py tests/test_retrieval.py tests/test_answer_service.py -q
```

容器 10 条 smoke：

```powershell
docker-compose exec -T api sh -lc 'python .scratch/resume-eval/run_resume_eval.py --dataset-json artifacts/offline_eval/datasets/eval_cases_v1.json --limit 10 --source-url-prefix eval://retrieval/ --case-timeout 180 --output-json /tmp/smoke-retry-policy-10.json --output-md /tmp/smoke-retry-policy-10.md --capture-llm-calls'
```

全部 issue 完成后跑 100 条 benchmark：

```powershell
docker-compose exec -T api sh -lc 'python .scratch/resume-eval/run_resume_eval.py --dataset-json artifacts/offline_eval/datasets/eval_cases_v1.json --limit 100 --source-url-prefix eval://retrieval/ --case-timeout 180 --output-json /tmp/benchmark-latency-phase2-100.json --output-md /tmp/benchmark-latency-phase2-100.md --capture-llm-calls'
```

## Notes

- 不要直接把最大检索尝试次数改成 1。
- 先补诊断，再收敛策略；否则很难判断 Recall@5 下降时是哪一层造成的。
- 这个 issue 应放在最后执行，因为它依赖前面几个 issue 后的真实 retry 分布。
