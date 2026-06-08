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

## 待补充记忆
- RAG 检索无结果的真实案例。
- embedding 维度不匹配的处理记录。
- WHMCS cookies 过期或 TOTP 失败案例。
- OpenSearch/Qdrant 索引重建流程。
- MinIO 上传或对象读取失败案例。
