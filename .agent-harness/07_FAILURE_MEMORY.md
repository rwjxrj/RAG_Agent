# 07_FAILURE_MEMORY.md

## 结论
本文件记录项目中已经踩过或容易重复踩的坑。每次遇到可复现问题，应补充现象、原因、修复和验证，避免下次重新排查。

## 记录格式

```text
## YYYY-MM-DD - 简短标题
- 现象：
- 影响：
- 根因：
- 修复：
- 验证：
- 相关文件：
- 后续注意：
```

## 2026-06-07 - README.md 不存在
- 现象：任务要求先读取 `README.md`，但仓库根目录未发现该文件。
- 影响：按固定阅读顺序会失败。
- 根因：当前项目主说明文件是 `README_zh.md`。
- 修复：在 `AGENTS.md` 中约定：如 `README.md` 不存在，先说明缺失，再读取 `README_zh.md`。
- 验证：`git ls-files` 显示 `README_zh.md`，未显示 `README.md`。
- 相关文件：`AGENTS.md`, `README_zh.md`
- 后续注意：2026-06-08 用户已新增 `README.md` 并移除 `README_zh.md`，当前入口以 `README.md` 为准；历史记忆仅用于解释为什么早期文档有该 fallback。

## 2026-06-07 - 工作区已有多处未提交改动
- 现象：`git status --short` 显示多个 `app/`、`frontend/`、`alembic/` 文件已修改，并有未跟踪文件。
- 影响：Codex 修改时容易误覆盖用户已有工作。
- 根因：当前工作区不是干净状态。
- 修复：本次只改 `AGENTS.md` 和 `.agent-harness/`，不触碰业务代码。
- 验证：修改前记录状态，最终 diff 只检查本次文档文件。
- 相关文件：多个业务文件，具体以 `git status --short` 为准。
- 后续注意：任何业务代码改动前都要重新读取相关 diff。

## 2026-06-07 - 不复制 Claude hooks
- 现象：参考 Harness Starter 时容易把 `.claude/hooks`、settings、LSP 自动化直接复制。
- 影响：当前项目主要使用 Codex，原样复制会引入不适配的工具假设。
- 根因：Harness Starter 是 Claude Code 模板，而本项目要求 Codex 适配版 lightweight harness。
- 修复：只沉淀 `AGENTS.md` 和 `.agent-harness/` 文档，不创建 `.claude/`、hook、脚本或依赖。
- 验证：本次新增文件不包含 `.claude/` 路径和 hook 脚本。
- 相关文件：`AGENTS.md`, `.agent-harness/*.md`
- 后续注意：若未来要做自动化，应先设计 Codex 可用的、显式执行的轻量检查脚本，并经用户确认。

## 2026-06-08 - Harness Starter 适配为 Codex 文档化流程
- 现象：Harness Starter 原模板包含 `.claude/hooks`、`CLAUDE.md`、`.lsp.json`、npm 初始化脚本和 Claude 专用技能。
- 影响：原样复制会让当前 Codex 项目背上不适配的自动化和依赖假设。
- 根因：当前项目主要使用 Codex，且用户要求 lightweight harness。
- 修复：用 `AGENTS.md`、`.agent-harness/08_CODEX_HARNESS_ADAPTER.md`、`.agent-harness/09_REVIEW_CHECKLIST.md`、`.agent-harness/10_SYNC_POLICY.md` 映射 Harness Starter 的规则、生命周期、审查和同步策略。
- 验证：检查未创建 `.claude/`、`.lsp.json`、npm 分发配置或新依赖。
- 相关文件：`AGENTS.md`, `.agent-harness/*.md`
- 后续注意：除非用户明确要求，不要把 Harness Starter 的 Hook 或安装脚本引入本项目。

## 2026-06-08 - 空 LLM 输出被展示为格式化失败
- 现象：对话结果显示 `We had trouble formatting the response...`，并追加 `That's the best we have from our docs.`；调试路径为多次检索失败后 `PASS_PARTIAL` 生成，再由 reviewer 终止为 `ASK_USER`。
- 影响：用户看到内部解析失败文案，而不是正常追问。
- 根因：`parse_llm_response("")` 在解析失败 fallback 中写入非空 answer；`apply_answer_plan()` 在 `PASS_PARTIAL` 计划下把 `ASK_USER + 非空 answer` 校准成部分回答，并追加 bounded suffix。
- 修复：空解析结果的 fallback answer 保持为空，让 `apply_answer_plan()` 走正常 ASK_USER 澄清文案。
- 验证：一次性 stub 复现脚本修复前输出 `decision=PASS` 且包含 `trouble formatting` / `best we have`；修复后输出 `decision=ASK_USER` 和 `We need one more detail...`。`python -m py_compile app\services\answer_utils.py tests\test_answer_service.py` 通过；正式 pytest 因本机缺 `structlog` 未进入测试收集。
- 相关文件：`app/services/answer_utils.py`, `tests/test_answer_service.py`
- 后续注意：解析失败 fallback 不应填入会被答案校准逻辑当作已生成业务答案的内部错误文案。

## 2026-06-29 - SDK 内部重试耗尽管道 fallback 时间
- 现象：10 条冷启动评测中 `EVAL-010` 在生成阶段停留约 94 秒，未记录主模型失败或备用模型调用，最终触发 120 秒管道总超时。
- 影响：主模型请求异常缓慢时，已配置的独立 DeepSeek 备用供应商没有机会接管，请求以 `ESCALATE` 结束并使 benchmark 无效。
- 根因：主、备用 `AsyncOpenAI` 客户端沿用 SDK 默认 `max_retries=2`；一次 `chat.completions.create()` 会在 gateway 不可见的内部重试，外层显式 fallback 要等调用返回后才能执行。
- 修复：客户端统一设置 `max_retries=0`，由 `LLMGateway` 现有模型 fallback 和 429 有界退避逻辑控制重试。
- 验证：`tests/test_llm_gateway.py::test_primary_and_fallback_clients_disable_sdk_internal_retries` 在修复前因缺少 `max_retries` 失败，修复后通过；完整冷启动结果见对应评测产物。
- 相关文件：`app/services/llm_gateway.py`, `tests/test_llm_gateway.py`, `artifacts/offline_eval/`
- 后续注意：provider SDK 的隐式重试必须纳入端到端超时预算；新增客户端时应显式声明 retry 策略。

## 2026-06-29 - EVAL-004 Evidence Quality 假阴性导致无效检索重试
- 现象：问题“放购物车里的衣服会不会被别人买走？”首轮已将 `eval://retrieval/doc-004` 排在第 1，但质量评估错误判定缺少直接政策说明，连续触发检索重试；其中一次 Evidence Selector 还返回了不完整 JSON。
- 影响：Recall@1 已命中却产生 3 次无效重试，EVAL-004 总耗时升至约 44 秒；最终答案正确，但暴露质量门纠错能力不足。
- 根因：Evidence Quality 对“购物车不锁库存，其他顾客仍可购买”的直接语义覆盖发生假阴性，不是检索失败或知识库政策缺口。
- 修复：仅在首轮、政策短答、非基础设施失败场景执行一次聚焦复核；模型必须给出可在权威 chunk 中逐字校验的引用，才允许修正质量门。调用使用独立任务标签 `evidence_quality_verify`。
- 安全边界：错误 chunk、过短引用、引用不存在、超时或 JSON 解析失败均不得放行；不硬编码购物车关键词，不修改排序、知识库或重试上限。
- 相关文件：`app/services/evidence_quality.py`、`app/services/phases/assess.py`、`tests/test_evidence_quality.py`、`tests/test_quality_gate_retry_convergence.py`

## 2026-06-30 - 100 条评测被正常“请联系客服”业务指引误判为通用错误
- 现象：EVAL-073 正确回答物流超过 72 小时可联系客服催查，100 条脚本却返回 `generic_error_answer`，导致 99/100、Benchmark invalid。
- 根因：评测器将单独短语“请联系客服”列为通用系统错误特征，无法区分正常售后操作指引和真正的异常兜底回答。
- 修复：移除该单独短语；仍保留“系统错误”“暂时无法”“遇到问题”以及英文完整错误句式。新增回归测试保证正常客服指引有效。
- 影响边界：只修正离线评测分类，不修改任何 RAG 业务输出、检索排序或原始 100 条 case 结果。

## 待补充记忆
- RAG 检索无结果的真实案例。
- embedding 维度不匹配的处理记录。
- WHMCS cookies 过期或 TOTP 失败案例。
- OpenSearch/Qdrant 索引重建流程。
- MinIO 上传或对象读取失败案例。
