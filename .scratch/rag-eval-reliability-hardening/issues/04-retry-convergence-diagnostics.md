# Issue 04：收敛无收益 Retry 与修正诊断口径

Status: ready-for-agent

## Parent

`.scratch/rag-eval-reliability-hardening/PRD.md`

## What to build

修正 retry diagnostics 的轮次一致性，并阻止基础设施失败、语义等价缺口或没有实际证据增益的 retry 反复执行完整检索链路。每轮 diagnostic 中的 raw LLM gate、代码最终 gate、missing signals、source-set change、quality score 和 evidence state 必须来自同一轮 assessment。

收敛策略必须使用稳定、机器可判断的信号，不能只依赖 LLM 自由文本完全相等。达到最大有效重试次数时必须给出明确 exhaustion reason。确实产生新证据或补齐硬要求的 targeted retry 仍应被允许，避免为了性能直接关闭有价值的重检。

覆盖 User Stories：19–25。

## Acceptance criteria

- [ ] 每轮 retry diagnostic 的 gate、raw gate、missing signals、source state 和 quality score 来自同一 assessment round。
- [ ] 基础设施失败不会触发新的完整 retrieval retry。
- [ ] 连续基础设施失败、连续 gate failure、soft contradiction 和无新证据场景均有稳定的 convergence reason。
- [ ] 语义相同但措辞不同的 missing signals 不会无限绕过收敛；实现不得依赖真实 LLM judge。
- [ ] productive retry 上限可配置，默认不允许出现当前观察到的无解释三次重试长尾。
- [ ] 达到 retry 上限时 `convergence_reason` 或 `exhaustion_reason` 必须非空。
- [ ] evidence set 有实际增益、补齐硬要求或命中新的 authoritative source 时，可在上限内继续 targeted retry。
- [ ] retry count、convergence reason 和逐轮诊断能够被评测脚本稳定读取。
- [ ] 测试覆盖不同措辞同语义、source set 变化但无质量增益、真实证据改善、基础设施失败和达到上限。
- [ ] 现有质量门控、Orchestrator/PipelineRunner 与 generate phase 相关测试无回归。
- [ ] 本 Issue 不修改评测汇总和 Markdown 渲染模块，避免与 Issue 02/03 的 agent 产生文件冲突。
- [ ] 修改 RAG 查询链路后同步检查并更新 RAG flow harness；若无需更新，交付说明必须给出原因。

## Blocked by

- Issue 01：修正评测成功口径与报告契约

