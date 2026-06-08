# 08_CODEX_HARNESS_ADAPTER.md

## 结论
Harness Starter 在本项目中适配为 Codex 可执行的文档化 harness：保留“安全、上下文、审查、记忆、同步”的思想，不复制 Claude Code 专用 hooks、skills、LSP 安装和 npm 分发脚本。

## 适配边界
- 当前项目主要使用 Codex，不以 Claude Code 为运行前提。
- 不创建 `.claude/`。
- 不创建 `.lsp.json`。
- 不安装 `typescript-language-server`、`pyright` 或其他全局语言服务。
- 不新增 npm package 分发配置。
- 不改业务代码、Docker、迁移、认证。

## 模板映射

| Harness Starter 原件 | 原用途 | 本项目 Codex 等价物 |
|---|---|---|
| `CLAUDE.md` | Claude 行为规则入口 | `AGENTS.md` |
| `.claude/hooks/pre-tool-check.mjs` | 工具调用前安全检查 | `AGENTS.md` 变更前检查 + `.agent-harness/04_CHANGE_GUIDE.md` |
| `.claude/hooks/post-tool-check.mjs` | 编辑后检查/格式化 | 窄验证命令 + 禁止批量格式化 |
| `.claude/hooks/session-review.mjs` | 响应前审查 | `.agent-harness/09_REVIEW_CHECKLIST.md` |
| `.claude/hooks/session-context.mjs` | 会话开始注入状态 | 每次任务先读 `AGENTS.md` 和相关 `.agent-harness/` |
| `.claude/hooks/pre-compact.mjs` | 压缩前保存状态 | 长任务结束前写入 `07_FAILURE_MEMORY.md` 或最终回复 |
| `.claude/.harness-state` | 模式/阶段状态 | `AGENTS.md` 中的 Harness 模式/阶段 |
| `.lsp.json` | LSP 配置 | 不启用；用项目已有测试/构建命令验证 |
| `scripts/check.mjs` | 健康检查 | `.agent-harness/09_REVIEW_CHECKLIST.md` + `03_DEV_COMMANDS.md` |
| `.github/workflows/harness-check.yml` | CI 检查 | 暂不创建；如需 CI，需用户明确确认 |

## Codex 生命周期

```mermaid
flowchart LR
  A["任务开始"] --> B["读取 AGENTS.md"]
  B --> C["读取相关 .agent-harness 文档"]
  C --> D["git status --short"]
  D --> E["说明将改/不改文件"]
  E --> F["小步编辑"]
  F --> G["窄验证"]
  G --> H["Review Checklist"]
  H --> I["必要时同步 Harness 文档"]
  I --> J["中文最终回复"]
```

## 模式与阶段
- 模式见 `AGENTS.md`：`full`、`tweak`、`hotfix`。
- 阶段见 `AGENTS.md`：`design`、`build`、`fix`、`docs`。
- 默认组合：`full + build`。
- 文档任务默认：`full + docs`。

## 当前项目默认配置
- 语言：中文。
- 技术栈：FastAPI、React/Vite、PostgreSQL、Redis/Celery、OpenSearch、Qdrant、MinIO。
- 高风险区域：Docker、迁移、认证、数据清理、WHMCS 抓取、RAG 检索/生成主流程。
- 低风险区域：`AGENTS.md`、`.agent-harness/*.md`、README 类文档。

## 执行原则
- Harness 文档是导航，不是事实来源；代码仍是事实来源。
- 代码变动后应按 `.agent-harness/10_SYNC_POLICY.md` 判断是否同步文档。
- 如果文档与代码冲突，先说明冲突，再以代码为准更新文档。
- 没有用户确认，不把文档化 harness 升级为自动 hook 或 CI。
