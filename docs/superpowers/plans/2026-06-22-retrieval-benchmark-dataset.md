# 无泄漏检索基准数据集实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 扩展离线评测脚本以读取独立评测 JSON，输出检索质量、检索延迟和逐 LLM task 指标，并提供生成 100 条数据集的中文提示词。

**Architecture:** 保留现有数据库自发现模式，在脚本中增加外部 case 加载和基于稳定 `source_url` 的评测路径。指标计算保持为无副作用纯函数，管道执行仅负责采集证据、timings 和 llm_calls，汇总层统一生成 JSON/Markdown。

**Tech Stack:** Python、argparse、asyncio、pytest、JSON、Markdown。

---

### Task 1: 外部数据集与检索指标

**Files:**
- Create: `tests/test_resume_eval.py`
- Modify: `.scratch/resume-eval/run_resume_eval.py`

- [x] **Step 1: 写外部数据加载失败测试**

覆盖合法 3-case JSON、缺少 `expected_source_urls`、非法 difficulty，并断言错误定位到 case id。

- [x] **Step 2: 运行测试确认 RED**

Run: `python -m pytest tests/test_resume_eval.py -q`

Expected: FAIL，因为脚本尚无 `load_eval_cases_json()`。

- [x] **Step 3: 实现最小加载器并确认 GREEN**

实现 `load_eval_cases_json(path, limit)`，验证 version、cases、id、question、expected_source_urls、tags、difficulty，保持输入顺序并应用 limit。

- [x] **Step 4: 写 Recall/Hit/MRR 失败测试**

使用两个期望来源和五个实际来源，验证 Recall@1/3/5、Hit@1/3/5 和首个命中的 reciprocal rank。

- [x] **Step 5: 实现 source URL 指标并确认 GREEN**

新增纯函数并让 `_run_pipeline_cases()` 保存 Top5 source URL、命中排名和逐 case 指标，同时保留旧 chunk-id 字段。

### Task 2: 延迟与 LLM task 汇总

**Files:**
- Modify: `tests/test_resume_eval.py`
- Modify: `.scratch/resume-eval/run_resume_eval.py`

- [x] **Step 1: 写汇总失败测试**

构造两个 pipeline 结果，验证 retrieve P50/P95/P99，以及 task 调用数、fallback/timeout、成功率和调用延迟 P50/P95/P99。

- [x] **Step 2: 实现汇总并确认 GREEN**

扩展 `_summarize()`，兼容缺失 llm_calls 和 legacy reviewer；扩展 Markdown 输出检索与 LLM 指标。

- [x] **Step 3: 接入 CLI**

新增 `--dataset-json` 和进程级 `--capture-llm-calls`；外部模式跳过旧 Reviewer 合成评测，数据库模式保持原行为。

### Task 3: 数据集提示词和文档同步

**Files:**
- Create: `docs/evaluation/retrieval-benchmark-ai-prompt.md`
- Modify: `.agent-harness/03_DEV_COMMANDS.md`

- [x] **Step 1: 编写 AI 提示词**

要求 AI 生成 `knowledge_base.json` 与 `eval_cases.json`，包含固定 URL、100 条难度分层问题、无泄漏规则和输出前自检。

- [x] **Step 2: 同步运行命令**

记录数据入库边界和带 `--dataset-json --limit 100` 的评测命令。

- [x] **Step 3: 最终验证**

Run: `python -m pytest tests/test_resume_eval.py tests/test_llm_gateway.py -q`

Run: `python .scratch/resume-eval/run_resume_eval.py --help`

Run: `git diff --check`

Expected: 测试全部通过、帮助信息包含 `--dataset-json`、无空白错误。
