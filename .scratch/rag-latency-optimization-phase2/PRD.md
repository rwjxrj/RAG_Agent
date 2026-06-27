# RAG 冷启动延迟优化 Phase 2 — 减少串行 LLM 调用与质量门重试成本

Status: ready-for-agent

## Problem Statement

当前企业客服 RAG 管道在 10 条冷启动评测中质量表现已经正常：成功率 100%、Recall@5 100%、`unknown task` 为 0、cache hit 为 0，说明检索召回、评测追踪和缓存隔离已基本可信。

但冷启动端到端延迟仍偏高：

| 指标 | 当前冷启动 | 线上实时客服目标 | 判断 |
|---|---:|---:|---|
| P50 | 17.0s | < 8s | 偏慢 |
| P95 | 30.2s | < 15s | 偏慢 |
| retrieve P95 | 10.9s | < 5s | 偏慢 |
| generate P95 | 9.1s | < 6s | 偏慢 |

当前瓶颈不再是单纯的 OpenSearch/Qdrant 检索慢，而是强校验 RAG 管道中多个 LLM 阶段串行执行：

1. `normalizer`：10 次，P95 7.0s
2. `evidence_selector`：8 次，P95 5.5s
3. `evidence_quality`：12 次，P95 2.9s
4. `generate_reasoning`：10 次，P95 4.9s
5. `generate`：10 次，P95 4.2s

每条冷启动请求在完整路径上可能执行 4-5 次 LLM 调用；如果 quality gate 触发 retry，还会重复执行 retrieval、selector 和 quality assessment。该设计提高了答案稳健性，但对实时客服体验过重。

用户目标是保留当前 Recall@5 和回答安全性，同时把冷启动延迟降到更接近生产实时问答水平。

## Solution

分阶段优化 RAG 冷启动路径，核心原则是：

- 不牺牲检索召回优先级
- 不直接删除质量门
- 不盲目减少重试次数
- 先跳过低收益 LLM 阶段
- 只在高风险、复杂、低置信场景启用完整强校验

目标指标：

| 指标 | 当前 | Phase 2 目标 |
|---|---:|---:|
| Recall@5 | 100% | >= 95%，理想保持 100% |
| 冷启动 P50 | 17.0s | <= 10s |
| 冷启动 P95 | 30.2s | <= 18s |
| retrieve P95 | 10.9s | <= 7s |
| generate P95 | 9.1s | <= 5.5s |
| unknown task | 0 | 0 |
| 10 条 smoke 成功率 | 100% | 100% |

本 PRD 推荐按 4 个独立 issue 执行：

1. **Issue 1：生成阶段 fast-path**  
   对简单 `direct_lookup` / 单证据 / quality gate 已通过场景跳过 `generate_reasoning`，直接进入 final generate。

2. **Issue 2：Normalizer fast-path 与缓存策略**  
   对明显中文客服短问法增加规则 QuerySpec fast-path，减少不必要 normalizer LLM；同时确认 LLM cache key 和评测 cache 统计仍准确。

3. **Issue 3：Evidence Selector 触发条件收窄**  
   继续减少 selector LLM 触发，只在 exact/policy/high-risk/多 required evidence 场景启用，普通 required evidence 走 deterministic selection。

4. **Issue 4：Quality Gate retry 诊断与重试策略收敛**  
   对仍触发 retry 的 case 提取 `missing_signals`、`required_evidence`、`quality_score` 和候选证据，判断是 quality prompt 过严、selector 丢证据、还是确实需要重试；再决定是否限制 retry。

## User Stories

1. As 最终用户, I want 简单客服问题在几秒内得到回答, so that 我不会因为等待 20-30 秒而放弃咨询
2. As 最终用户, I want 系统在提速后仍引用正确知识库证据, so that 答案可信而不是为了快而乱答
3. As 最终用户, I want 复杂政策问题仍经过更严格校验, so that 退款、赔付、账号等高风险问题不会被错误简化
4. As 客服主管, I want RAG 冷启动 P50 降到 10 秒以内, so that 系统适合真实客服辅助场景
5. As 客服主管, I want P95 降到 18 秒以内, so that 少数慢请求不会严重影响体验
6. As 客服主管, I want Recall@5 保持在 95% 以上, so that 性能优化不会破坏检索质量
7. As QA, I want 每轮优化都能跑同一套 10 条 smoke 和 100 条 benchmark, so that 指标变化可比较
8. As QA, I want 评测 JSON 记录每个 case 的 LLM task、耗时、retry_count 和 phase timings, so that 可以定位具体瓶颈
9. As QA, I want unknown task 始终为 0, so that LLM 调用统计可信
10. As QA, I want cache hit/store 被明确统计, so that 能区分冷启动和热缓存表现
11. As 开发者, I want 简单 direct_lookup case 跳过 reasoning prepass, so that generate 阶段少一次 4-5 秒 LLM 调用
12. As 开发者, I want reasoning prepass 的跳过条件可配置, so that 出现质量回退时可以快速关闭优化
13. As 开发者, I want answer_shape、support_level、evidence_count、quality gate 结果共同决定是否跳过 reasoning, so that fast-path 不会覆盖复杂场景
14. As 开发者, I want fast-path 后仍保留 main generation 和 reviewer, so that 生成答案仍受证据约束和校验保护
15. As 开发者, I want normalizer 对明显简单问法支持规则 fast-path, so that 不必每条短问都花 5-7 秒调用 LLM
16. As 开发者, I want normalizer fast-path 只覆盖高置信模板, so that 不确定问题仍走 LLM QuerySpec
17. As 开发者, I want normalizer fast-path 输出完整 QuerySpec 子结构, so that 下游 retrieval planner 不需要兼容特殊对象
18. As 开发者, I want evidence_selector 只在有明确覆盖需求时调用 LLM, so that 普通检索不承担 selector LLM 成本
19. As 开发者, I want policy/exact/high-risk 场景仍保留 selector LLM, so that 关键证据覆盖不被 top-k 简化破坏
20. As 开发者, I want deterministic selector 能执行结构化文档优先和 conversation cap, so that 不走 LLM 时仍避免旧对话污染证据
21. As 开发者, I want quality gate retry 的触发原因被结构化输出, so that 可以区分证据缺失和质量评估过严
22. As 开发者, I want retry 前后记录 selected query、required_evidence、missing_signals, so that 能判断 retry 是否真正带来新证据
23. As 开发者, I want 对连续 quality gate fail 的 case 设置可解释终止条件, so that 不会在同一类失败上反复消耗 LLM
24. As 运维, I want 可以通过配置开关关闭每个 fast-path, so that 生产异常时能快速回退
25. As 运维, I want 可以分别观察冷启动和热缓存指标, so that 不会用热缓存 0.4s 误判真实性能
26. As 产品负责人, I want 性能优化 PRD 拆成可独立执行的 issue, so that 每一轮都有明确收益和风险边界
27. As 产品负责人, I want 优化不涉及 Docker、数据库迁移和认证逻辑, so that 变更风险可控
28. As 未来接手的 AI Agent, I want PRD 明确哪些模块应改、哪些不应改, so that 可以按小步可回退方式实现
29. As 未来接手的 AI Agent, I want 每个 issue 都有可执行测试入口, so that 不需要重新探索验证方式
30. As 未来接手的 AI Agent, I want 先修 generate fast-path 而不是直接改 retry, so that 不会牺牲当前 100% Recall@5

## Implementation Decisions

### 1. 总体架构原则

当前系统属于强校验企业客服 RAG，而不是轻量 RAG。优化应降低“默认路径”的 LLM 次数，而不是删除安全链路。

默认路径应从：

```text
normalizer LLM
-> hybrid retrieval
-> optional evidence_selector LLM
-> evidence_quality LLM
-> generate_reasoning LLM
-> generate LLM
-> reviewer
```

逐步收敛为：

```text
normalizer fast-path 或 normalizer LLM
-> hybrid retrieval
-> deterministic selector 或 selector LLM
-> evidence_quality LLM
-> generate LLM
-> reviewer
```

复杂场景仍允许回到完整路径：

```text
normalizer LLM
-> hybrid retrieval
-> evidence_selector LLM
-> evidence_quality LLM
-> generate_reasoning LLM
-> generate LLM
-> reviewer
-> targeted retry
```

### 2. Issue 1：生成阶段 fast-path

**目标：** 降低 `generate` 阶段 P95，从当前 9.1s 降到约 5s。

**核心决策：**

- `generate_reasoning` 不再对所有 case 默认执行。
- 对简单问题跳过 reasoning prepass，直接执行 main generation。
- main generation 和 reviewer 保留，不绕过证据约束。

**建议跳过条件：**

同时满足以下条件时跳过 reasoning prepass：

- answer_shape 是 `direct_lookup`、`short_answer` 或等价简单直答形态
- 当前 evidence_quality 已通过
- `missing_signals` 为空或只包含非阻塞项
- evidence chunk 数量不超过配置阈值，建议默认 `<= 5`
- 没有多方案比较需求
- 不是 high-risk / policy execution / refund execution / account security 场景
- 没有 conversation history relevance 需要合并上下文

**建议配置：**

- `reasoning_prepass_enabled`: 默认 true
- `reasoning_prepass_skip_simple_lookup`: 默认 true
- `reasoning_prepass_max_fastpath_evidence_chunks`: 默认 5

**可观测字段：**

在 generate debug 中记录：

```json
{
  "reasoning_prepass": {
    "skipped": true,
    "reason": "simple_direct_lookup_quality_passed"
  }
}
```

如果未跳过：

```json
{
  "reasoning_prepass": {
    "skipped": false,
    "reason": "complex_or_high_risk"
  }
}
```

**风险：**

- 某些看似简单但实际需要比较的 case 可能答案变粗。
- 如果 evidence 很多但 answer_shape 错判为 direct_lookup，跳过 reasoning 可能降低答案组织质量。

**风险控制：**

- reviewer 不跳过。
- 只在 quality gate pass 后跳过。
- 10 条 smoke 和 100 条 benchmark 对比 answer decision、citation 和 Recall@5。

### 3. Issue 2：Normalizer fast-path 与缓存策略

**目标：** 降低 `query_extract` P95，从当前 7.0s 降到简单 case 近 0s。

**核心决策：**

- 不移除 normalizer LLM。
- 增加高置信规则 fast-path，只覆盖简单客服短问法。
- fast-path 输出完整 QuerySpec，不能返回特殊简化结构。

**适合 fast-path 的问题类型：**

- 服务时间查询：如“晚上几点还有真人客服”
- 退款到账时间查询：如“退款多久到账”
- 库存/订单保留时间：如“下单没付款多久释放”
- 退换货期限：如“几天内能退”
- 洗护/尺码/客服能否协助选择等 FAQ 型问题

**不适合 fast-path 的问题类型：**

- 多轮上下文依赖
- 指代不明：“这个还能退吗”
- 需要比较多个方案
- 高风险执行请求：“帮我退款”“替我取消”
- 涉及账号、支付异常、投诉升级
- 查询中带多个实体、时间、条件组合

**建议实现方式：**

- 在 normalizer 入口先做 deterministic classifier。
- 命中高置信模板时构造 QuerySpec。
- 未命中则走现有 LLM normalizer。

**可观测字段：**

QuerySpec 或 debug 中记录：

```json
{
  "extraction_mode": "rule_fastpath",
  "fastpath_rule": "service_hours"
}
```

现有 LLM 路径继续记录：

```json
{
  "extraction_mode": "llm_primary"
}
```

**风险：**

- 规则覆盖过宽会误判复杂问题。
- fast-path QuerySpec 不完整会影响 retrieval planner。

**风险控制：**

- 初版只覆盖 5-8 个高置信规则。
- 每个规则必须有单测覆盖 QuerySpec 关键字段。
- 评测中统计 fastpath hit count 和 fastpath case 的 Recall@5。

### 4. Issue 3：Evidence Selector 触发条件收窄

**当前状态：**

已经完成一轮优化：当 `required_evidence` 为空时，selector 不再调用 LLM。

冷启动结果：

- evidence_selector 从 16 次降到 8 次
- unknown task 从 15 次降到 0
- retrieve P95 从 24.0s 降到 10.9s

**进一步目标：** 把 selector LLM 调用从 8 次继续降到 3-5 次，仅保留高价值场景。

**建议启用 selector LLM 的条件：**

满足任一条件才调用 selector LLM：

- `required_evidence` 数量 >= 2
- `hard_requirements` 非空
- answer_type 是 `policy`、`pricing`、`direct_link`
- answer_expectation 是 `exact`
- risk_level 是 `medium` 或 `high`
- candidate pool 中 doc_type 混杂且包含 conversation
- evidence_set uncovered_requirements 非空

**建议跳过 selector LLM 的条件：**

- required_evidence 为空
- 只有单个弱 required_evidence，如泛化的 `policy_language`
- candidate top3 已来自同一 eval/source 且 doc_type 为结构化文档
- answer_shape 是简单 direct lookup

**deterministic fallback 必须保留：**

- 结构化文档优先
- conversation cap
- doc_type 多样性
- top-k fallback

**可观测字段：**

retrieval_stats 中记录：

```json
{
  "evidence_selector": {
    "used_llm": false,
    "skip_reason": "single_weak_required_evidence",
    "fallback": "deterministic_rebalance"
  }
}
```

或：

```json
{
  "evidence_selector": {
    "used_llm": true,
    "trigger_reason": "hard_requirements_present"
  }
}
```

### 5. Issue 4：Quality Gate retry 诊断与策略收敛

**目标：** 不牺牲 Recall@5 的前提下降低 retry 对 P95 的影响。

当前 10 条冷启动中：

- 2/10 case 触发 retry
- evidence_quality 12 次
- retrieve P95 10.9s

不建议直接把 `max_retrieval_attempts` 降到 1，因为当前 Recall@5 是 100%，直接砍 retry 可能降低召回。

**先诊断的字段：**

每个 retry case 必须提取：

- case id
- retry_count
- selected retrieval query
- active_hypothesis_name
- required_evidence
- hard_requirements
- evidence_selector used_llm / skip_reason
- evidence_quality quality_score
- completeness_score
- actionability_score
- missing_signals
- hard_requirement_coverage
- first relevant rank before retry
- first relevant rank after retry
- retry 是否带来新 expected source

**策略判断：**

如果 retry 后没有带来新 expected source，说明 retry 低价值，应考虑终止条件。

如果 retry 后带来 expected source，说明 retry 有价值，应保留或只收窄触发条件。

**建议收敛规则：**

- 同一 missing_signals 连续出现两次且候选 source 未变化时，不再 retry。
- 如果 Top5 已命中 expected source，但 quality gate fail，应优先进入 generate/ASK_USER，而不是再检索。
- 对 `quality_llm_failed` 已经不 retry，继续保留。
- 对缺失硬需求但 evidence_set 已覆盖主要 source 的 case，应考虑降级为 PASS_PARTIAL 或 ASK_USER。

**可观测字段：**

```json
{
  "retry_decision": {
    "retry": false,
    "reason": "same_missing_signals_and_no_new_sources",
    "previous_missing_signals": ["policy_language"],
    "current_missing_signals": ["policy_language"]
  }
}
```

### 6. 配置和回退策略

所有优化都应支持配置回退：

- reasoning prepass fast-path 可关闭
- normalizer fast-path 可关闭
- selector trigger narrowing 可关闭
- retry收敛规则可关闭

默认建议：

- 本地评测默认开启
- 生产灰度时逐项开启
- 若 Recall@5 或 reviewer 风险指标下降，优先关闭对应 fast-path

### 7. 不做架构大重构

本 PRD 不要求：

- 合并 PipelineRunner
- 重写 RetrievalService
- 改数据库 schema
- 改 Docker Compose
- 改认证
- 替换模型供应商
- 新增第三方依赖

## Testing Decisions

### 测试原则

测试应优先验证外部可观察行为，而不是内部实现细节：

- 对 RAG pipeline：看 debug timings、llm task count、decision、citations、Recall@5
- 对 selector/normalizer 等模块：可用模块级测试验证输出行为
- 对 retry：需要基于构造的 context 或评测 JSON 诊断，避免只测私有函数

### 1. Generate fast-path 测试

优先测试 seam：

- generate phase 的公共执行入口
- 或 PipelineRunner 端到端 mock LLM/retrieval/reviewer

测试场景：

1. 简单 direct_lookup + quality pass + evidence_count <= 5 时，跳过 reasoning prepass
2. policy/high-risk 场景不跳过 reasoning prepass
3. 多 evidence/options 场景不跳过 reasoning prepass
4. 跳过 reasoning 后仍执行 main generate
5. reviewer 仍执行
6. debug 中记录 skipped reason

已有类似测试参考：

- orchestrator phase 测试
- answer_service 测试
- llm_gateway task 追踪测试

### 2. Normalizer fast-path 测试

测试场景：

1. 服务时间短问法命中 fast-path
2. 退款到账短问法命中 fast-path
3. 库存保留短问法命中 fast-path
4. 指代不明问题不命中 fast-path，走 LLM
5. 高风险执行请求不命中 fast-path
6. fast-path 输出 QuerySpec 的 retrieval_hints、answer_contract、query_slots 可被 retrieval planner 使用

验收：

- fast-path case 不产生 normalizer LLM call
- non-fast-path case 保持现有 normalizer LLM 行为
- 10 条 smoke 中 normalizer call_count 下降，Recall@5 不下降

### 3. Evidence Selector 触发条件测试

已有测试文件：

- selector 空输入
- selector disabled top-k
- selector LLM success
- selector LLM fallback
- invalid ids fallback
- structured docs rebalance
- no required evidence skip LLM

新增测试：

1. 单个弱 required evidence 时跳过 LLM
2. hard_requirements 非空时调用 LLM
3. policy/high-risk 时调用 LLM
4. direct_lookup + structured top candidates 时跳过 LLM
5. retrieval_stats 记录 used_llm、skip_reason 或 trigger_reason

### 4. Quality retry 诊断测试

先补诊断能力，再改策略。

测试场景：

1. retry case 输出 missing_signals history
2. retry case 输出 source set 是否变化
3. 连续相同 missing_signals 且 source 未变化时停止 retry
4. Top5 已命中 expected source 时不因弱质量分重复检索
5. quality_llm_failed 不触发 retry 的既有测试继续保留

### 5. 离线评测验收

每个 issue 完成后至少跑：

```powershell
python -m pytest tests/test_llm_gateway.py tests/test_evidence_selector.py tests/test_evidence_quality.py tests/test_orchestrator.py tests/test_answer_service.py tests/test_retrieval.py -q
```

容器内 10 条冷启动 smoke：

```powershell
docker-compose build api worker
docker-compose up -d api worker

docker-compose exec -T api sh -lc 'python .scratch/resume-eval/run_resume_eval.py --dataset-json artifacts/offline_eval/datasets/eval_cases_v1.json --limit 10 --source-url-prefix eval://retrieval/ --case-timeout 180 --output-json /tmp/smoke-latency-phase2-10.json --output-md /tmp/smoke-latency-phase2-10.md --capture-llm-calls'
```

关键验收指标：

- success_rate = 100%
- Recall@5 >= 95%
- unknown task = 0
- cold P50 逐步下降
- cold P95 逐步下降
- LLM call_count 逐步下降
- reviewer 风险拦截不下降；如未跑 reviewer case，必须明确说明未覆盖

100 条 benchmark 在所有 issue 完成后执行：

```powershell
docker-compose exec -T api sh -lc 'python .scratch/resume-eval/run_resume_eval.py --dataset-json artifacts/offline_eval/datasets/eval_cases_v1.json --limit 100 --source-url-prefix eval://retrieval/ --case-timeout 180 --output-json /tmp/benchmark-latency-phase2-100.json --output-md /tmp/benchmark-latency-phase2-100.md --capture-llm-calls'
```

## Out of Scope

- 不做 Docker Compose 改造
- 不做数据库迁移
- 不改认证、权限、API token
- 不替换模型供应商
- 不新增第三方依赖
- 不重写整个 orchestrator
- 不删除 reviewer
- 不删除 evidence quality gate
- 不直接把 `max_retrieval_attempts` 改成 1
- 不用热缓存 0.4s 作为生产真实性能目标
- 不把 10 条 smoke 结果当成最终结论，最终仍需 100 条 benchmark 验证

## Further Notes

### 当前已完成的前置优化

以下问题已经在前序工作中处理，不属于本 PRD 重新实现范围：

1. LLM 空响应不再写缓存
2. 空 LLM 缓存读取时自动清理
3. MiMo 结构化输出支持 `response_format={"type":"json_object"}`
4. 不支持 `response_format` 的模型自动降级 prompt-only JSON
5. `quality_llm_failed` 不再触发无效 retry
6. source_url prefix filter 支持评测语料隔离
7. `current_llm_task_var` 泄漏修复
8. 所有 LLM 调用点都有 task label
9. `evidence_selector` 在无 required evidence 时跳过 LLM

### 当前冷启动基线

最新冷启动 10 条评测：

| 指标 | 值 |
|---|---:|
| 成功率 | 100% |
| Recall@5 | 100% |
| P50 | 17.0s |
| P95 | 30.2s |
| retrieve P95 | 10.9s |
| generate P95 | 9.1s |
| cache hit | 0 |
| cache store | 50 |
| unknown task | 0 |

LLM 调用：

| task | call_count | P95 |
|---|---:|---:|
| normalizer | 10 | 7.0s |
| evidence_selector | 8 | 5.5s |
| evidence_quality | 12 | 2.9s |
| generate_reasoning | 10 | 4.9s |
| generate | 10 | 4.2s |

### 推荐执行顺序

1. 先做 Issue 1：generate reasoning fast-path  
   预期收益最大，且不影响检索召回。

2. 再做 Issue 3：selector 触发条件继续收窄  
   能降低 retrieve P95，但需要小心 required evidence 覆盖。

3. 再做 Issue 2：normalizer fast-path  
   收益大，但规则设计需要谨慎，避免误判 query intent。

4. 最后做 Issue 4：retry 策略收敛  
   需要基于更多诊断数据，不应最先动。

### 预计收益

如果 Issue 1 成功：

- generate P95 约 9.1s -> 4.5-5.5s
- 冷启动 P50 约 17.0s -> 12-13s

如果 Issue 2 + Issue 3 成功：

- normalizer call_count 可下降 30%-60%
- evidence_selector call_count 可下降到 3-5 次 / 10 cases
- cold P50 有机会接近 8-10s

如果 Issue 4 成功：

- P95 主要收益
- retry case 不再反复消耗 retrieve + selector + quality
- cold P95 有机会接近 15-18s
