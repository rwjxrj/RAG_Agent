# Issue 02：增加轻量 LLM 统计与限流保护

Status: ready-for-agent

## Parent

`.scratch/rag-eval-reliability-hardening/PRD.md`

## What to build

让 100 条批量评测在不保存完整 prompt/response 的前提下，仍能可靠统计每个 LLM task 的调用数、成功、429、timeout、fallback、解析失败和最终失败。同时增加可配置的 case 间隔与有界限流退避，防止 OpenAI-compatible 模型网关因连续调用产生大面积 429。

默认评测应使用轻量追踪；完整 LLM 追踪继续保持显式 opt-in，并支持只追踪指定 case 或小范围 case。限流恢复必须有上限，不能形成无限模型重试或无限等待。所有等待、重试和最终限流失败都应进入结构化报告。

覆盖 User Stories：5–10。

## Acceptance criteria

- [ ] 未启用完整 LLM capture 时，summary 的 LLM task 统计仍非空且可用。
- [ ] 轻量记录至少包含 task、model、attempt、duration、status、error type、fallback、timeout、rate-limit 和 cache status。
- [ ] 默认轻量记录不包含 messages、prompt、response content 或完整证据文本。
- [ ] 完整 capture 保持 opt-in，并支持限制到指定 case 或 case 子集。
- [ ] CLI 支持非负 case delay，并把实际值写入报告 metadata。
- [ ] 429 退避有明确最大次数和最大等待边界；优先使用 provider retry hint，缺失时使用有界退避。
- [ ] summary 能区分 rate-limit attempts、recovered rate limits 和 terminal rate-limit failures。
- [ ] 超过配置的基础设施错误阈值时，benchmark 被标记为 invalid，并沿用 Issue 01 的退出码语义。
- [ ] 使用 fake clock 或 injected sleeper 的测试验证 delay 与 backoff，不产生真实等待。
- [ ] 测试覆盖首次 429 后恢复、连续 429 最终失败、timeout、fallback、解析失败和正常调用。
- [ ] 100-case 默认输出体积不会因轻量追踪接近完整 prompt capture 的规模。
- [ ] 不更换模型供应商、不新增第三方依赖、不修改 Docker 拓扑。

## Blocked by

- Issue 01：修正评测成功口径与报告契约

