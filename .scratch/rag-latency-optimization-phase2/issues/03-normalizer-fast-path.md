Status: ready-for-agent

# Issue 3：Normalizer fast-path：简单短问法减少 normalizer LLM

## Parent

`.scratch/rag-latency-optimization-phase2/PRD.md`

## What to build

为高置信中文客服短问法增加 normalizer 规则 fast-path：明显 FAQ 型问题直接构造完整 QuerySpec，未命中或存在歧义时继续走现有 normalizer LLM。

这个 slice 的目标是降低简单 case 的 query_extract 成本，同时保证下游 retrieval planner 收到的仍是完整、标准化的 QuerySpec。

## Acceptance criteria

- [ ] 服务时间类短问法命中 fast-path。
- [ ] 退款到账时间类短问法命中 fast-path。
- [ ] 订单保留/未付款释放类短问法命中 fast-path。
- [ ] 退换货期限类短问法命中 fast-path。
- [ ] 洗护、尺码、客服协助选择等简单 FAQ 型问题可按高置信规则逐步覆盖。
- [ ] 指代不明、多轮上下文依赖、多条件组合、多方案比较问题不命中 fast-path。
- [ ] “帮我退款”“替我取消订单”等执行型高风险请求不命中 fast-path。
- [ ] fast-path 输出完整 QuerySpec 子结构，不能要求下游兼容特殊简化对象。
- [ ] debug 中记录 extraction mode 和 fastpath rule。
- [ ] fast-path 有配置开关；关闭后恢复现有 normalizer LLM 路径。
- [ ] 单测覆盖命中、不命中、高风险拒绝、QuerySpec 关键字段。
- [ ] 10 条冷启动 smoke 中成功率保持 100%、Recall@5 >= 95%、unknown task = 0。
- [ ] smoke 中 normalizer call_count 下降，并记录 fastpath hit count。

## Blocked by

- `.scratch/rag-latency-optimization-phase2/issues/01-generate-reasoning-fast-path.md`
- `.scratch/rag-latency-optimization-phase2/issues/02-evidence-selector-trigger-narrowing.md`

## Suggested verification

```powershell
python -m pytest tests/test_llm_gateway.py tests/test_retrieval.py tests/test_orchestrator.py -q
```

容器 smoke：

```powershell
docker-compose exec -T api sh -lc 'python .scratch/resume-eval/run_resume_eval.py --dataset-json artifacts/offline_eval/datasets/eval_cases_v1.json --limit 10 --source-url-prefix eval://retrieval/ --case-timeout 180 --output-json /tmp/smoke-normalizer-fastpath-10.json --output-md /tmp/smoke-normalizer-fastpath-10.md --capture-llm-calls'
```

## Notes

- 初版规则必须保守，宁可少命中，不要误判复杂问题。
- 不要把 normalizer LLM 删除；fast-path 只处理高置信短问法。
- 如果 fast-path case 的 Recall@5 下降，应优先缩小规则覆盖面。
