Status: ready-for-agent

# Issue 2：Evidence Selector 触发条件收窄

## Parent

`.scratch/rag-latency-optimization-phase2/PRD.md`

## What to build

进一步收窄 evidence selector LLM 的触发条件：普通检索 case 默认使用 deterministic selection；只有在硬性证据覆盖、高风险、精确答案、政策类或候选证据混杂等高价值场景才调用 selector LLM。

这个 slice 的目标是降低 retrieve 阶段 P95，同时不破坏 required evidence 覆盖、结构化文档优先和 conversation cap。

## Acceptance criteria

- [ ] `required_evidence` 为空时继续跳过 selector LLM。
- [ ] 单个弱 required evidence 场景跳过 selector LLM，使用 deterministic selection。
- [ ] `hard_requirements` 非空时调用 selector LLM。
- [ ] policy、exact、pricing、direct_link、中高风险场景调用 selector LLM。
- [ ] direct lookup 且 top candidates 已来自结构化文档时跳过 selector LLM。
- [ ] deterministic selection 仍保留结构化文档优先、conversation cap、doc type 多样性和 top-k fallback。
- [ ] retrieval debug/stats 记录 selector 是否使用 LLM，以及 `skip_reason` 或 `trigger_reason`。
- [ ] 单测覆盖 selector LLM 调用、跳过、fallback、debug 字段。
- [ ] 10 条冷启动 smoke 中成功率保持 100%、Recall@5 >= 95%、unknown task = 0。
- [ ] smoke 中 evidence_selector call_count 较当前冷启动基线 8/10 下降，目标 3-5/10。

## Blocked by

- `.scratch/rag-latency-optimization-phase2/issues/01-generate-reasoning-fast-path.md`

## Suggested verification

```powershell
python -m pytest tests/test_evidence_selector.py tests/test_retrieval.py tests/test_llm_task_context.py -q
```

容器 smoke：

```powershell
docker-compose exec -T api sh -lc 'python .scratch/resume-eval/run_resume_eval.py --dataset-json artifacts/offline_eval/datasets/eval_cases_v1.json --limit 10 --source-url-prefix eval://retrieval/ --case-timeout 180 --output-json /tmp/smoke-selector-narrowing-10.json --output-md /tmp/smoke-selector-narrowing-10.md --capture-llm-calls'
```

## Notes

- 不要为了降低调用次数直接禁用 selector。
- 如果 Recall@5 或 expected source 覆盖下降，应优先收紧 skip 条件，而不是继续扩大 skip 范围。
