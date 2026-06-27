Status: ready-for-agent

# Issue 2：Evidence Selector 逐 case 诊断输出

## Parent

`.scratch/rag-latency-optimization-phase3/PRD.md`

## What to build

在 retrieval stats 的 `evidence_selector` dict 中补充 5 个诊断字段，让评测 JSON 能输出每条 case 的 selector 触发/跳过原因和查询元数据。

这个 slice 的目标是**不改策略逻辑**，只增加可观测性。拿到诊断数据后再决定是否继续收窄 selector 触发条件。

## Acceptance criteria

- [ ] `stats["evidence_selector"]` 中新增 `required_evidence` 字段（list[str]）。
- [ ] `stats["evidence_selector"]` 中新增 `hard_requirements` 字段（list[str]）。
- [ ] `stats["evidence_selector"]` 中新增 `answer_type` 字段（str | None）。
- [ ] `stats["evidence_selector"]` 中新增 `answer_shape` 字段（str | None）。
- [ ] `stats["evidence_selector"]` 中新增 `risk_level` 字段（str | None）。
- [ ] 新增字段不影响 selector 调用行为（used_llm、skip_reason、trigger_reason 不变）。
- [ ] 单测验证 stats dict 包含所有新增字段。
- [ ] 10 条冷启动 smoke 中 selector call_count 不变（纯诊断，不改策略）。

## Blocked by

None - can start immediately (可与 Issue 1 并行)

## Suggested verification

```powershell
python -m pytest tests/test_evidence_selector.py tests/test_retrieval.py -q
```

## Implementation notes

修改文件：

- `app/services/retrieval.py`: 在 `stats["evidence_selector"]` 构建处（约 line 1325-1334）补充 5 个字段
- `tests/test_evidence_selector.py` 或 `tests/test_retrieval.py`: 新增断言

不改文件：

- `app/services/evidence_selector.py`（不改 selector 逻辑）
- `app/services/phases/retrieve.py`
- `app/services/orchestrator.py`

## Notes

- 这个 issue 是纯诊断，零风险。
- 不要修改 selector 触发/跳过逻辑。
- 不要修改 `_first_selector_trigger_reason` 或 `_selector_skip_reason`。
- 如果诊断数据表明 8 次触发大部分是 `hard_requirements_present` 或 `multiple_required_evidence`，说明不应继续收窄。
- 如果大部分是 `answer_type_policy` 或 `answer_expectation_exact`，才在后续 Phase 中考虑收窄。
