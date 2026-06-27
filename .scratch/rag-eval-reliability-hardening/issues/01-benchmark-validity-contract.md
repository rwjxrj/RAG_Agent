# Issue 01：修正评测成功口径与报告契约

Status: ready-for-agent

## Parent

`.scratch/rag-eval-reliability-hardening/PRD.md`

## What to build

建立可信的评测结果契约，明确区分 harness 是否完成、业务输出是否有效、是否执行检索以及是否因基础设施故障终止。评测脚本即使成功写出报告，也不能再把生成失败后包装出的通用错误回答计为成功用例。

本切片需要贯通单 case 分类、总体汇总、JSON/Markdown 报告和 CLI 退出状态。 intentional human handoff 应继续被视为有效业务结果；模型异常、通用系统错误、缺少正常终态或不可解析输出必须被分类为无效结果。报告需要带 schema version，并尽量保留旧顶层字段作为兼容别名。

覆盖 User Stories：1–4、11–12、29–31、34。

## Acceptance criteria

- [ ] 单 case 结果能够分别表达 harness completion、business validity、retrieval eligibility、retrieval execution 和 failure category。
- [ ] 已知通用系统错误回答不会计入 successful cases。
- [ ] 生成异常被包装为 `ESCALATE` 时，能够与 intentional human handoff 明确区分。
- [ ] 缺少正常 termination reason 的 case 被标记为无效，并出现在无效原因汇总中。
- [ ] intentional human handoff 保持有效业务输出，不被误报为模型故障。
- [ ] summary 在质量和延迟指标之前输出 benchmark validity、invalid case count 和 invalidation reasons。
- [ ] JSON 与 Markdown 使用相同的成功/失败定义和计数。
- [ ] 报告包含 schema version；旧顶层指标如保留，必须注明兼容语义或 denominator。
- [ ] 有效评测返回成功退出码；完成但无效的评测仍写出报告，并返回非零退出码。
- [ ] 回归测试覆盖正常 PASS、正常 ASK_USER、intentional human handoff、生成失败包装 ESCALATE、通用错误回答、缺少终态和不可解析输出。
- [ ] 相关现有评测测试全部通过，不修改 Docker、数据库、认证或生产数据。

## Blocked by

None - can start immediately

