# Issue 06：修复冷启动 Smoke 的 Normalizer Fast-Path 与轻量 LLM 遥测

Status: ready-for-agent

## Parent

`.scratch/rag-eval-reliability-hardening/PRD.md`

## What to build

修复 10 条冷启动 smoke 暴露的两个阻塞问题，使评测能够在不启用完整 prompt/response capture 的情况下稳定完成，并输出可信的轻量 LLM task 统计。

当前真实冷启动运行中，EVAL-001 在 normalizer 规则 fast-path 构造 `QuerySpec` 时传入数据契约不支持的 `fastpath_rule` 参数，导致管道异常并被包装为 `ESCALATE`，最终 benchmark 判定为 invalid。修复后，规则 fast-path 必须只使用 `QuerySpec` 的正式字段；如果仍需暴露命中的规则名称，应放入已有兼容元数据或独立 debug 信息，不能通过未声明构造参数注入。

同一次 smoke 中实际发生了 44 次 LLM 成功调用，但报告的 `llm_tasks` 为空。轻量调用日志必须在正常评测中默认初始化、记录并随输出传给评测脚本；完整 prompt、response、token 与成本等重字段仍只允许在显式开启完整 capture 时写入。默认轻量模式至少应保留 task、model、attempt、fallback、duration、status、error type、429 退避信息和 cache 状态。

本任务完成后，应重新构建 API 容器、清理 LLM 缓存并复跑 10 条 cold smoke。不得通过关闭 normalizer fast-path、开启全量 LLM capture 或忽略异常 case 来绕过问题。

本次失败证据：

- `artifacts/offline_eval/smoke-cold-10.json`
- `artifacts/offline_eval/smoke-cold-10-diagnosis.json`
- `artifacts/offline_eval/smoke-cold-10-console.log`
- 异常：`QuerySpec.__init__() got an unexpected keyword argument 'fastpath_rule'`
- 当前结果：9/10 有效、benchmark invalid、`llm_tasks={}`、日志中 44 次 LLM success、0 次 429、0 次 cache hit。

## Acceptance criteria

- [ ] EVAL-001 命中 normalizer 规则 fast-path 时不再抛出 `QuerySpec` 未知参数异常，且 fast-path 仍保持启用。
- [ ] 为该真实失败路径增加回归测试；测试应调用 fast-path 构造入口并验证返回合法 `QuerySpec`，而不是只测试规则匹配函数。
- [ ] 默认 `debug_llm_calls=false` 时仍初始化并采集轻量 LLM 调用日志，最终评测 JSON 的 `summary.llm_tasks` 非空。
- [ ] 默认轻量日志不包含 messages、prompt、response content、完整证据文本、token 或成本字段。
- [ ] 显式开启完整 capture 时，原有详细追踪能力保持兼容，不得因默认轻量采集而重复记录同一次模型调用。
- [ ] 轻量日志能够进入每个 case 的 `llm_calls`，并正确汇总 success、timeout、fallback、rate-limited、recovered rate limit 和 terminal rate-limit failure。
- [ ] 增加端到端或接近端到端的评测回归测试：不启用完整 capture 时执行至少一个真实 PipelineRunner case，报告仍包含非空轻量 task 统计。
- [ ] 运行本次触达模块的窄测试，至少覆盖 normalizer fast-path、LLM gateway、PipelineRunner/AnswerService 和 resume eval。
- [ ] 重建 API 容器并确认容器内代码包含本次修复，然后清空 LLM 缓存运行 10 条 cold smoke。
- [ ] smoke 报告满足：10/10 业务有效、benchmark valid、无 generation_failure、`llm_tasks` 非空、cache hit 为 0；若出现 429，报告必须正确区分恢复与终败。
- [ ] 保存并交付 JSON、Markdown、diagnosis JSON 和控制台日志；只有 smoke 通过后才能继续 100 条冷启动评测。
- [ ] 不新增第三方依赖，不修改 Docker 拓扑、数据库迁移、认证逻辑或生产检索默认行为。
- [ ] 如修改查询链路或评测命令，按项目规范同步检查 `.agent-harness/02_RAG_FLOW.md`、`.agent-harness/03_DEV_COMMANDS.md` 和失败记忆文档。

## Blocked by

None - can start immediately.

## Comments

- 2026-06-27：由最新 10 条真实冷启动 smoke 自动验收失败创建。当前检索有效样本 Recall@5 为 100%，本任务只处理评测可靠性与运行时契约错误，不进行检索算法调参。
