# RAG 管道延迟优化 — generate 阶段并行化与超时收紧

Status: ready-for-agent

## Problem Statement

离线评测（20 条）显示端到端延迟 P50=1.1s 但 P95=47.4s，差距 43 倍。慢请求（9/20 条，39-55s）的瓶颈集中在 generate 阶段（P95=30.5s，占总耗时 57%）。根因是 generate 内部 3-4 次 LLM 调用完全串行执行，叠加 LLM API 响应时间波动（单次 2-10s），导致总耗时线性累积。

## Solution

两项改动：
1. 将 generate 阶段中独立的 `relevance_check` 和 `reasoning_prepass` 两个 LLM 调用从串行改为并行（`asyncio.gather`），减少一个 LLM 往返延迟。
2. 将 LLM 单次调用超时从 60s 收紧到 20s，避免极端慢请求阻塞管道过久。

预期效果：P95 从 47s 降至 ~25-30s，极端 case 从 55s 降至 ~30s。

## User Stories

1. As 用户, I want 问题能在 30 秒内得到回答, so that 体验不会因偶发慢请求而中断
2. As 用户, I want 典型请求（P50）保持 1-2 秒响应, so that 快速场景不受影响
3. As 运维, I want 单次 LLM 调用超时从 60s 降至 20s, so that 慢请求快速失败而非长时间挂起
4. As 运维, I want 慢请求的超时错误信息清晰可辨, so that 能快速定位是 LLM 超时还是其他原因
5. As 开发者, I want generate 阶段的并行化不改变输出语义, so that 回答质量不受影响
6. As 开发者, I want relevance_check 和 reasoning_prepass 的并行执行不影响 main_generation 的输入正确性, so that 并行化是安全的
7. As 开发者, I want 超时配置可通过环境变量调整, so that 不同部署环境可独立调优
8. As QA, I want 离线评测脚本能复现优化前后的延迟对比, so that 效果可量化验证
9. As QA, I want 优化后 Recall@5 和 Reviewer 指标不退化, so that 性能优化不损害质量
10. As 管理者, I want 优化后 P95 延迟降至 30s 以下, so that 95% 的用户请求在合理时间内完成

## Implementation Decisions

### 1. generate 阶段并行化

当前 `execute_generate` 中的 LLM 调用序列：

```
relevance_check (串行) → reasoning_prepass (串行) → main_generation → self_critic → [regeneration]
```

改为：

```
relevance_check ─┐
                  ├─ asyncio.gather → main_generation → self_critic → [regeneration]
reasoning_prepass ┘
```

**安全性分析：**
- `relevance_check` 仅读写 `ctx.conversation_history`（可能清空历史）
- `reasoning_prepass` 仅读 `ctx.evidence` 和 `ctx.effective_query`，写 `reasoning_prewrite` 返回值
- 两者操作的数据域完全不相交，无竞争条件
- `main_generation` 依赖两者的输出：使用清空后的 `conversation_history` 和注入的 `reasoning_prewrite`

**实现方式：** 在 `execute_generate` 函数中，将两个 await 调用合并为 `asyncio.gather(_apply_relevance_check(...), _run_reasoning_prepass(...))`，然后从结果中取值传入 main_generation。

**改动模块：** `app/services/phases/generate.py`

### 2. LLM 超时收紧

当前 `llm_timeout_seconds` 默认 60s。改为 20s。

**依据：**
- 正常 LLM 响应 2-5s
- 慢请求 8-10s
- 20s 足以覆盖 99% 的正常请求，同时避免 60s 的极端挂起
- 超时后 LLM gateway 的 model fallback 机制仍会尝试备用模型

**改动模块：** `app/core/config.py` 中 `llm_timeout_seconds` 默认值

### 3. 超时错误处理

LLM 超时后，当前 `llm_gateway.py` 会尝试 fallback 模型。如果 fallback 也超时，会抛出异常被 orchestrator 捕获并返回 ESCALATE 决策。

需确认：
- 超时异常消息中包含 "timeout" 关键字，便于日志检索
- 超时后的 ESCALATE 决策不会导致无限重试

**改动模块：** `app/services/llm_gateway.py`（如需增强错误信息）

### 4. 不改动的部分

以下不在本次优化范围内：
- normalize → retrieve 的串行依赖（有硬数据依赖，无法并行）
- retrieve 内部的 embedding + search 并行化（已由 retrieval 模块内部处理）
- self_critic + regeneration 的串行依赖（critic 输出决定是否需要 regeneration）
- 评估器（evidence_evaluator）默认关闭，不涉及

## Testing Decisions

### 验证方式

使用现有离线评测脚本对比优化前后：

```powershell
# 优化前基线
python .scratch/resume-eval/run_resume_eval.py --limit 20 --output-json artifacts/offline_eval/before-opt.json --output-md artifacts/offline_eval/before-opt.md

# 优化后
python .scratch/resume-eval/run_resume_eval.py --limit 20 --output-json artifacts/offline_eval/after-opt.json --output-md artifacts/offline_eval/after-opt.md
```

### 验收标准

| 指标 | 优化前 | 目标 |
|------|--------|------|
| P95 延迟 | 47.4s | ≤ 30s |
| P99 延迟 | 55.4s | ≤ 40s |
| P50 延迟 | 1.1s | ≤ 1.5s（不退化） |
| Recall@5 | 0.85 | ≥ 0.85（不退化） |
| 风险拦截召回率 | 1.0 | = 1.0（不退化） |
| 正常回答误拦截率 | 0.0 | = 0.0（不退化） |

### 回归测试

- 现有 `tests/` 目录下的单元测试全部通过
- generate 阶段的输出格式不变（decision、answer、citations、confidence）

## Out of Scope

- normalize → retrieve 的并行化（有硬数据依赖）
- retrieve 内部的 embedding/search 并行优化
- self_critic 的移除或并行化
- evidence_evaluator 的启用
- Reranker 超时调整（当前 rerank P95 ≈ 0s，不是瓶颈）
- 模型切换或降级策略调整
- 知识库数据优化（Recall@5 相关）

## Further Notes

- 快速集群（11/20 条，0.9-1.2s）中 generate=0.01s，说明这些 case 走了 intent cache 或短路路径，不在本次优化范围内
- 慢集群（9/20 条）中所有 LLM 阶段同时变慢（query_extract 9s、assess 6s、generate 30s），说明根因是 LLM API 响应时间波动，并行化可以减少等待的 LLM 调用数，但无法消除 API 本身的慢响应
- 如果 P95 优化后仍高于目标，下一步可考虑：(1) 降低 `self_critic_regenerate_max` 为 0 省掉 1-2 次 LLM 调用，(2) 将 assess_evidence 的 LLM 调用改为规则引擎
