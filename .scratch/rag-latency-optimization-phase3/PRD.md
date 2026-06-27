# RAG 冷启动延迟优化 Phase 3 — 放宽 fast-path 条件与补诊断可观测性

Status: ready-for-agent

## Problem Statement

Phase 2 已完成代码实现并通过全量测试（179 passed，0 failed），四个 issue 的核心逻辑已就绪：generate reasoning fast-path、evidence selector 触发收窄、normalizer fast-path、quality gate retry 收敛。

但最新评测显示 **generate_reasoning fast-path 从未触发**：10/10 全部执行了 reasoning prepass，P95 7.4s。当前跳过条件过严，导致简单 case 也无法命中 fast-path。

具体卡住的 5 个条件（按可能性排序）：

1. `missing_signals` 非空即否决 — 即使 `quality_gate` 已通过，仍要求 missing_signals 完全为空。
2. `answer_type` 在 `{pricing, direct_link, account}` 中被排除 — `pricing` 和 `direct_link` 的低风险直答也被排除。
3. `hard_requirements` 非空即否决 — 即使 evidence quality 已覆盖这些要求。
4. evidence chunk 阈值 5 太严 — 多数 case 有 6-10 个 evidence chunk。
5. `answer_shape` 不在 `{direct_lookup, short_answer, yes_no}` — `bounded_summary`、`procedural` 被排除。

同时，evidence_selector 的 8 次触发缺少逐 case 诊断输出，无法判断是否应继续收窄。retry 收敛逻辑已实现但缺少"无新增证据停止"的补充条件。

当前延迟基线（Phase 2 实现后，10 条冷启动）：

| 指标 | 当前 | 线上目标 | 判断 |
|---|---:|---:|---|
| P50 | ~12s | < 8s | 偏慢 |
| P95 | ~22s | < 15s | 偏慢 |
| retrieve P95 | ~8s | < 5s | 偏慢 |
| generate P95 | ~11.3s | < 6s | 偏慢 |
| generate_reasoning 调用 | 10/10 | 3-6/10 | 过高 |

## Solution

Phase 3 只做 3 个小改动，不动大架构：

1. **放宽 generate_reasoning fast-path 条件** — 让已通过 quality gate 的低风险简单 case 跳过 reasoning。
2. **补充 evidence_selector 逐 case 诊断输出** — 不改策略，先看清楚 8 次触发的原因。
3. **补充 retry "无新增证据停止"条件** — 已有收敛逻辑基础上增加一个停止条件。

目标指标：

| 指标 | 当前 | Phase 3 目标 |
|---|---:|---:|
| Recall@5 | 100% | >= 95%，理想保持 100% |
| generate_reasoning 调用/10 cases | 10 | 3-6 |
| generate P95 | ~11.3s | <= 7s |
| 冷启动 P50 | ~12s | <= 9s |
| 冷启动 P95 | ~22s | <= 16s |
| unknown task | 0 | 0 |
| 10 条 smoke 成功率 | 100% | 100% |

## Implementation Decisions

### 1. Issue 1：放宽 generate_reasoning fast-path

**目标：** 让 `generate_reasoning` 从 10/10 降到 3-6/10，generate P95 从 ~11.3s 降到 6-8s。

**当前跳过条件（`_reasoning_prepass_skip_reason`）及修改：**

| 条件 | 当前 | Phase 3 修改 |
|---|---|---|
| `missing_signals` | 非空即否决 | quality gate 已通过时允许存在，记录为 blocker 但不否决 |
| `answer_type` | `{pricing, direct_link, account}` 排除 | 仅排除 `account`；低风险 `pricing`、`direct_link` 允许跳过 |
| `hard_requirements` | 非空即否决 | 如果 `quality_report.hard_requirement_coverage` 全部为 True，允许跳过 |
| evidence chunks | `<= 5` | 默认提到 `8` |
| `answer_shape` | `{direct_lookup, short_answer, yes_no}` | 保持不变 |
| `risk_level` | `{medium, high}` 排除 | 保持不变 |
| `conversation_history` | 非空即否决 | 保持不变 |

**新增诊断输出 — reasoning_prepass.blockers：**

当 fast-path 未跳过时，debug 输出应记录**所有**阻止跳过的条件（不只是第一个），便于分析：

```json
{
  "reasoning_prepass": {
    "skipped": false,
    "reason": "executed",
    "blockers": ["missing_signals_not_empty", "answer_type_pricing_excluded"]
  }
}
```

当跳过时：

```json
{
  "reasoning_prepass": {
    "skipped": true,
    "reason": "quality_passed_simple_case",
    "evidence_count": 6,
    "answer_type": "pricing",
    "answer_shape": "direct_lookup",
    "risk_level": "low",
    "hard_requirements_covered": true
  }
}
```

**配置项：**

- `generate_reasoning_fastpath_max_evidence_chunks`: 默认 5 → 8
- `generate_reasoning_skip_simple_lookup`: 保持 true
- `generate_reasoning_enabled`: 保持 true
- 新增 `generate_reasoning_fastpath_allow_missing_signals`: 默认 true
- 新增 `generate_reasoning_fastpath_covered_hard_requirements`: 默认 true

**风险：**

- 放宽后某些 pricing/direct_link case 的答案组织质量可能下降。
- 但 final generate + reviewer 仍保留，风险可控。
- 如果 Recall@5 或 reviewer 风险指标下降，可通过配置逐项关闭。

### 2. Issue 2：Evidence Selector 逐 case 诊断输出

**目标：** 不改策略逻辑，只在评测输出中增加每条 case 的 selector 诊断字段。

**不做的事：**

- 不继续收窄 selector 触发条件。
- 不修改 `_first_selector_trigger_reason` 的判断逻辑。
- 不删除任何已有的 selector 调用。

**做的事：**

确保评测 JSON 中每条 case 的 debug 包含：

```json
{
  "evidence_selector": {
    "used_llm": true,
    "trigger_reason": "hard_requirements_present",
    "required_evidence": ["policy_language", "numbers_units"],
    "hard_requirements": ["policy_language"],
    "answer_type": "policy",
    "answer_shape": "direct_lookup",
    "risk_level": "low"
  }
}
```

或跳过时：

```json
{
  "evidence_selector": {
    "used_llm": false,
    "skip_reason": "single_weak_required_evidence",
    "required_evidence": ["policy_language"],
    "hard_requirements": [],
    "answer_type": "policy",
    "answer_shape": "direct_lookup",
    "risk_level": "low"
  }
}
```

**实现方式：**

在 `retrieval.py` 的 `stats["evidence_selector"]` 中补充 `required_evidence`、`hard_requirements`、`answer_type`、`answer_shape`、`risk_level` 五个字段。这些值在调用 `select_evidence_for_query` 时已作为参数传入，只需在 stats dict 中额外记录。

**验收标准：**

- 评测 JSON 中每条 case 都有完整的 selector 诊断。
- 10 条 smoke 的 selector 触发分布可被统计和分类。
- 不改 selector 策略，不改 call_count。

### 3. Issue 3：Retry "无新增证据停止"

**目标：** 补充一个 retry 停止条件 — 如果 retry 前后 Top5 source set 完全相同，停止继续 retry。

**当前已有收敛条件（Phase 2 实现）：**

1. 连续相同 `missing_signals` + 无新 source → 停止（`same_missing_signals_no_new_sources`）
2. Top5 已命中 expected source → 停止（`top_sources_cover_expected`）
3. `quality_llm_failed` → 不触发 retry

**Phase 3 新增条件：**

4. retry 前后候选 source set 完全相同（不要求 missing_signals 一致）→ 停止

理由：即使 missing_signals 变化了，如果检索返回的证据完全没有新增，说明 retrieval 已经饱和，继续 retry 只会消耗 LLM 调用而不带来新信息。

**实现方式：**

在 `_should_stop_retry` 中增加：

```python
# Condition 4: source set unchanged (regardless of missing_signals)
if (
    ctx.retrieval_attempt > 0
    and ctx.retry_diagnostics
    and ctx.retry_diagnostics[-1].get("source_set_changed") is False
):
    self._set_convergence_reason(ctx, "source_set_unchanged_retry_saturated")
    return True
```

**配置：**

使用现有 `quality_gate_retry_convergence_enabled` 开关，不新增配置项。

**风险：**

- 某些 case 可能 missing_signals 变化后需要不同检索策略，但 source 没变确实说明 retrieval 饱和。
- 可通过关闭 `quality_gate_retry_convergence_enabled` 回退。

## Testing Decisions

### Issue 1 测试

新增/修改测试：

1. `missing_signals` 非空 + quality gate pass + 其他条件满足 → 跳过 reasoning
2. `answer_type=pricing` + 低风险 + quality gate pass → 跳过 reasoning
3. `answer_type=direct_link` + 低风险 + quality gate pass → 跳过 reasoning
4. `answer_type=account` + quality gate pass → 不跳过（account 仍排除）
5. `hard_requirements` 非空但全部覆盖 → 跳过 reasoning
6. `hard_requirements` 非空且部分未覆盖 → 不跳过
7. evidence chunks = 7 + 其他条件满足 → 跳过 reasoning（阈值提到 8）
8. evidence chunks = 9 + 其他条件满足 → 不跳过
9. debug blockers 列表正确记录所有阻止原因
10. 配置项可逐项关闭放宽条件

### Issue 2 测试

1. `stats["evidence_selector"]` 包含 `required_evidence`、`hard_requirements`、`answer_type`、`answer_shape`、`risk_level`
2. 不改变 selector 调用行为

### Issue 3 测试

1. source set 完全相同 + missing_signals 不同 → 停止 retry
2. source set 有变化 + missing_signals 相同 → 不停止（依赖现有条件 1）
3. convergence disabled → 不停止

### 离线评测验收

每个 issue 完成后跑：

```powershell
python -m pytest tests/test_generate_phase.py tests/test_evidence_selector.py tests/test_quality_gate_retry_convergence.py tests/test_retrieval.py tests/test_orchestrator.py tests/test_config.py -q
```

10 条冷启动 smoke：

```powershell
docker-compose build api worker
docker-compose up -d api worker
docker-compose exec -T api sh -lc 'python .scratch/resume-eval/run_resume_eval.py --dataset-json artifacts/offline_eval/datasets/eval_cases_v1.json --limit 10 --source-url-prefix eval://retrieval/ --case-timeout 180 --output-json /tmp/smoke-phase3-10.json --output-md /tmp/smoke-phase3-10.md --capture-llm-calls'
```

关键验收指标：

- success_rate = 100%
- Recall@5 >= 95%
- unknown task = 0
- generate_reasoning call_count 从 10 降到 3-6
- generate P95 下降

## Out of Scope

- 不改 orchestrator 架构
- 不替换模型
- 不删除 evidence_quality
- 不删除 reviewer
- 不直接禁用 evidence_selector
- 不改 `max_retrieval_attempts=1`
- 不继续扩 normalizer 规则
- 不做 Docker Compose 改造
- 不做数据库迁移
- 不新增第三方依赖

## 推荐执行顺序

1. **Issue 1** — 放宽 generate_reasoning fast-path（收益最大，风险最低）
2. **Issue 2** — evidence_selector 诊断输出（纯观测，零风险）
3. **Issue 3** — retry 无新增证据停止（补收敛条件，低风险）

Issue 1 和 Issue 2 可并行执行。Issue 3 独立。
