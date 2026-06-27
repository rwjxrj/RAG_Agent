# 无泄漏检索能力基准数据集设计

## 目标

为 RAG 查询链路建立 100 条可重复、无答案泄漏的检索能力基准，同时采集检索阶段与逐 LLM 任务的延迟数据。

## 数据集拆分

AI 一次生成两个 JSON 文件：

1. `knowledge_base.json`：仅包含知识事实、流程、规则和必要元数据，导入知识库。
2. `eval_cases.json`：包含 100 条评测问题和期望来源，只保存在评测目录，不导入知识库。

知识文档使用固定且唯一的 `source_url`，格式为 `eval://retrieval/doc-NNN`。评测集通过 `expected_source_urls` 与实际检索证据的 `source_url` 匹配，避免依赖入库时生成的 chunk UUID。

## 知识库文件结构

```json
{
  "source": "synthetic_retrieval_benchmark_v1",
  "doc_type": "faq",
  "pages": [
    {
      "url": "eval://retrieval/doc-001",
      "title": "示例知识文档",
      "text": "只包含事实内容，不包含评测问题、标准答案、检索关键词或期望来源。"
    }
  ]
}
```

## 外部评测文件结构

```json
{
  "version": "1.0",
  "name": "synthetic_retrieval_benchmark_v1",
  "cases": [
    {
      "id": "EVAL-001",
      "question": "用户自然语言问题",
      "expected_source_urls": ["eval://retrieval/doc-001"],
      "standard_answer": "仅用于人工核验，不进入知识库",
      "tags": ["paraphrase", "single-hop"],
      "difficulty": "medium"
    }
  ]
}
```

## 评测脚本接口

保留现有数据库自发现模式，并新增：

```text
--dataset-json <path>  从独立 JSON 加载评测问题
--capture-llm-calls   在当前评测进程强制采集逐次 LLM 调用数据
```

外部数据集启用时：

- 验证 case id、question、expected_source_urls、difficulty 和 tags。
- 按输入顺序截取 `--limit`。
- 使用证据的 `source_url` 计算检索指标。
- 不运行依赖标准 chunk 内容的旧 Reviewer 合成评测。

## 指标

### 检索质量

- Recall@1、Recall@3、Recall@5：Top-K 中命中的期望来源比例。
- Hit@1、Hit@3、Hit@5：Top-K 是否至少命中一个期望来源。
- MRR：首个期望来源排名的倒数。
- 每条 case 保存实际 Top5 source URL 和命中排名。

### 性能

- 端到端延迟 P50/P95/P99。
- retrieve 延迟 P50/P95/P99。
- 现有阶段耗时 P95。
- 按 LLM task 汇总调用次数、fallback 次数、timeout 次数、成功率和 P50/P95/P99。

## 错误与兼容性

- 外部数据集格式错误时在运行前失败，并指出具体 case。
- `debug_metadata.llm_call_log` 缺失时检索指标仍可生成，LLM 汇总为空。
- 保留原有数据库评测模式和现有 JSON 字段，新增字段不删除旧字段。
- 评测失败样本不计入质量和延迟分位数，但单独统计失败数及错误类型。

## 验证

- 单元测试覆盖数据集加载、source URL 匹配、Recall/Hit/MRR、LLM task 汇总和 Markdown 输出。
- 使用最小 3-case fixture 做脚本级静态测试。
- 实际 100 条测试在用户完成数据生成与入库后运行。

## 不在本次范围

- 自动调用 AI 生成数据。
- 自动导入知识库或写入生产数据。
- 修改 embedding、reranker、检索融合、prompt、模型和超时配置。
