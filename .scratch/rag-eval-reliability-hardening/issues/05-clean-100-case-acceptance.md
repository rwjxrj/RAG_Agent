# Issue 05：执行可信 100 条验收并同步文档

Status: ready-for-agent

## Parent

`.scratch/rag-eval-reliability-hardening/PRD.md`

## What to build

整合前四个 Issues 的结果，执行 10 条冷启动 smoke 和完整 100 条冷启动评测，确认评测自身有效、LLM 未受未处理限流污染、检索质量不回退、retry 长尾按新策略收敛。验收完成后，将最终 CLI 参数、指标语义、退出码、诊断包和手动运行方法同步到项目入口文档与开发命令文档。

本 Issue 不承担新的检索算法大改。如果 clean run 仍存在召回缺口，应输出按优先级排序的后续清单，而不是在验收过程中临时调参。

覆盖 User Stories：32–34，并验证其他 Stories 的整体交付。

## Acceptance criteria

- [ ] 先执行相关自动化测试，所有本次触达模块的测试通过。
- [ ] 清空 LLM 缓存后运行 10 条 cold smoke，报告被判定为 valid。
- [ ] 运行完整 100 条 cold benchmark，报告和 compact diagnosis 均成功生成。
- [ ] 100 条报告中 terminal generation failures 为 0、未处理 terminal 429 为 0、generic error answers 为 0、missing termination reasons 为 0。
- [ ] intentional human handoff、route short-circuit 和 invalid infrastructure cases 的计数语义正确且可追溯。
- [ ] retrieval-executed 指标达到 Recall@5 >= 0.89、Hit@5 >= 0.92、MRR >= 0.77；如 denominator 变化，报告必须同时给出旧口径对照。
- [ ] no-retry retrieval P95 不相对 6.84 秒基线发生明显回退。
- [ ] 不存在超过配置 productive retry limit 且无明确 override/reason 的 case。
- [ ] no-retry、retried 和 max-retry 延迟分组能够解释全局 P95/P99。
- [ ] compact diagnosis 可由 AI 单独读取并定位失败、慢查询、重试与召回缺口，无需完整控制台日志。
- [ ] README 更新最终 100 条命令、有效性语义、简洁指标输出和诊断包说明。
- [ ] 开发命令 harness 更新新增 CLI 参数和推荐运行流程；RAG flow harness 与最终 retry 行为保持一致。
- [ ] 最终交付包含执行命令、测试结果、100 条摘要、剩余风险和未实施的后续召回优化清单。
- [ ] 不将本地离线结果表述为生产 SLA，不修改 Docker、数据库、认证或生产数据。

## Blocked by

- Issue 02：增加轻量 LLM 统计与限流保护
- Issue 03：拆分路由与检索指标并生成诊断包
- Issue 04：收敛无收益 Retry 与修正诊断口径
