Status: ready-for-agent

# 给 ctx.extra 添加类型化替代字段

## What to build

在 OrchestrContext 上添加类型化的 phase 输出字段，替代 `ctx.extra: dict[str, Any]` 中的无类型 key。各 phase 写入类型化字段，消费者从类型化字段读取。

新建数据类：
- `RetrieveOutput`：active_required_evidence, active_hard_requirements, active_soft_requirements, active_hypothesis_name, active_answer_shape, active_evidence_families, hypothesis_history, retry_strategy_applied
- `AssessOutput`：evidence_eval_result
- `GenerateOutput`：llm_resp, messages, answer_candidate, self_critic_regenerated, reasoning_prewrite, conversation_relevance, candidate_render_applied, final_polish_applied
- `VerifyOutput`：generated_decision, targeted_retry_pending, targeted_retry_used, targeted_retry_reason, targeted_retry_queries

在 OrchestrContext 上添加：
- `retrieve_output: RetrieveOutput | None`
- `assess_output: AssessOutput | None`
- `generate_output: GenerateOutput | None`
- `verify_output: VerifyOutput | None`

各 phase 函数改为写入类型化字段。消费者（output_builder、flow_debug 等）改为从类型化字段读取。保留 `ctx.extra` 向后兼容，最终删除。

## Acceptance criteria

- [ ] 4 个 phase 输出数据类定义在 schemas.py
- [ ] OrchestrContext 有 4 个新的类型化输出字段
- [ ] 各 phase 写入类型化字段（同时保留写入 ctx.extra 以兼容）
- [ ] output_builder 和 flow_debug 从类型化字段读取
- [ ] 所有现有测试通过
- [ ] 新测试覆盖类型化字段的读写

## Blocked by

None - 可以立即开始
