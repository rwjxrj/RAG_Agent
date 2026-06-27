# RAG 检索评测基线修复 — LLM 空响应、语料隔离、ESCALATE 短路

Status: ready-for-agent

## Problem Statement

100 条离线 benchmark 评测显示 Recall@5=0.68、Hit@5=0.72、MRR=0.48，远低于目标（Recall@5≥0.80、Hit@5≥0.85、MRR≥0.60）。诊断发现三条独立的问题链：

1. **LLM 空响应污染缓存**：LLM API 偶发返回空 content，被当作成功响应写入 Redis 缓存。后续所有相同 prompt 的调用命中缓存 → JSON 解析失败 → normalizer/evidence_selector/evidence_quality 全部 fallback。缓存不是根因而是放大器。
2. **旧业务语料污染召回池**：Top5 中 44%（220/500）是 `file://` 旧业务文档，正确 benchmark 文档被挤出 fetch window。
3. **agentic 路由误 ESCALATE**：`"退款"` 同时出现在 `sensitive_terms` 和 `execution_terms` 中，导致所有含"退款"的知识查询被路由到 HUMAN_HANDOFF → ESCALATE，完全跳过检索。8 条 ESCALATE 中 4 条因此产生。

## Solution

三组独立修复，按优先级实施：

1. 修 LLM 空响应处理：空 content 触发 retry/fallback 而非缓存；已有空缓存自动清理。
2. 评测语料隔离：给 benchmark 评测脚本加可选 `--source-url-prefix` 参数，仅在评测时过滤召回结果。
3. ESCALATE 路由修复：移除 `execution_terms` 中的 `"退款"`，补回归测试。

## User Stories

1. As 运维, I want LLM 返回空 content 时不写入 Redis 缓存, so that 后续调用不会命中脏缓存持续失败
2. As 运维, I want 读取到空 content 缓存时自动删除该 key, so that 脏缓存能自愈而非永久污染
3. As 运维, I want 空 content 响应触发 fallback model 重试, so that 偶发空响应不导致整条链路降级
4. As 运维, I want 一个选择性清理空缓存的函数, so that 可以一次性修复历史脏数据而不丢失有效缓存
5. As 运维, I want Redis 连接在异常时也能正确释放, so that 不会因 pickle 反序列化失败导致连接泄漏
6. As 开发者, I want 3 条 llm_gateway 回归测试覆盖空响应场景, so that 未来改动不会回退
7. As QA, I want benchmark 评测脚本支持 `--source-url-prefix` 参数, so that 可以隔离评测语料排除旧业务文档干扰
8. As QA, I want source filter 接到实际使用的 `.scratch/resume-eval/run_resume_eval.py`, so that 100 条 benchmark 能直接使用
9. As QA, I want source filter 放在 merge 后、rerank 前, so that 污染 chunk 被排除但不改变检索层逻辑
10. As QA, I want 如果 merge 后过滤仍漏召，能把 filter 下推到 OpenSearch/Qdrant 查询层, so that benchmark 文档不被旧语料挤出 fetch window
11. As 用户, I want "退款多久到账"等知识查询进入 RAG 检索, so that 能得到基于知识库的回答而非直接转人工
12. As 用户, I want "帮我退款"等代执行请求仍走 HUMAN_HANDOFF, so that 敏感操作不被自动化处理
13. As 开发者, I want agentic_router 回归测试覆盖退款知识 vs 代执行的区分, so that 路由逻辑不会被未来改动破坏
14. As 开发者, I want "退款怎么处理"等含"处理"的知识问法被标记为观察边界, so that 先通过 benchmark 数据判断是否需要进一步调整 execution_terms
15. As QA, I want 先跑 10 条 smoke 验证每项修复, so that 不浪费完整 100 条跑的时间
16. As QA, I want 复跑 100 条 benchmark 对比修复前后指标, so that 效果可量化
17. As 管理者, I want 修复后 ESCALATE 从 8 条降到约 4 条, so that 更多问题得到自动回答
18. As 管理者, I want 修复后 Hit@5/Recall@5 有可测量的提升, so that 检索质量改善可被验证

## Implementation Decisions

### 1. LLM 空响应处理

**改动模块：** `app/services/llm_gateway.py`

**chat() 空 content 检测：** 在构建 `LLMResponse` 之前检查 `choice.message.content`，空 content 抛 `ValueError("LLM returned empty content")`，触发 model fallback 重试。不改变已有的 fallback 机制。

**_set_cached() 拒绝空 content：** 在 pickle.dumps 之前检查 `response.content`，空则 skip 并 log。

**_get_cached() 自愈：** 反序列化后检查 `cached.content`，空则删除 key 返回 None。pickle.loads 异常时也删除 key。使用 try/finally 确保 Redis 连接 close。

**purge_empty_llm_cache()：** 遍历所有 `llm_cache:*` key，反序列化检查 content，删除空/损坏条目。同样用 try/finally 释放连接。

### 2. 评测语料隔离

**改动模块：** `app/services/retrieval.py`、`.scratch/resume-eval/run_resume_eval.py`

**context variable 方案：** 在 `retrieval.py` 中用 `contextvars.ContextVar` 存储可选的 `source_url_include_prefix`。`set_source_url_filter(prefix)` 设置，`reset_source_url_filter(token)` 恢复。

**过滤位置：** 在 `retrieve()` 方法中，merge 后、rerank 前过滤。只保留 `source_url.startswith(prefix)` 的 chunk。

**可观测字段：** source filter 生效时，`retrieval_stats` 必须记录：

```json
{
  "source_url_filter": "eval://retrieval/",
  "source_url_filter_before": 20,
  "source_url_filter_after": 7
}
```

这样 10 条 smoke 和 100 条复跑都能确认 filter 是否真正生效，以及旧语料被过滤的规模。

**接入评测脚本：** 在 `.scratch/resume-eval/run_resume_eval.py` 的 argparse 中加 `--source-url-prefix` 参数，运行时 set filter，结束后 reset。

**下推查询层（条件触发）：** 如果 merge 后过滤仍导致漏召（benchmark 文档被旧语料挤出 fetch window），需把 filter 下推到 `_search_opensearch_safe()` 和 `_search_qdrant_safe()`，在查询时加 prefix 条件。这一步在首次 100 条复跑后根据数据决定是否实施。

触发条件：

- filtered 100 条 benchmark 中 `Hit@5 < 0.85`；并且
- 失败 case 的 pre-filter 候选中没有 `expected_source_urls`，说明目标文档在 merge 前已被旧语料挤出 fetch window。

**生产不受影响：** 默认 `None` 不过滤，只有显式传参时生效。

### 3. ESCALATE 路由修复

**改动模块：** `app/services/agentic_router.py`

**根因：** `execution_terms` 包含 `"退款"`，而 `sensitive_terms` 也包含 `"退款"`。`_is_human_handoff()` 要求两个列表的 term 同时出现在 query 中，但 `"退款"` 同属两个列表，等价于只检查 sensitive_terms。

**修复：** 从 `execution_terms` 中移除 `"退款"`。保留 `"帮我"`、`"给我"`、`"替我"`、`"执行"`、`"处理"`、`"删除"`、`"修改"`、`"取消"` 作为真正的执行动词。

**已知边界：** `"处理"` 仍在 execution_terms 中，"退款怎么处理"会匹配 sensitive="退款" + execution="处理" → HUMAN_HANDOFF。本次不直接调整 `"处理"`，先把它作为观察边界：统计 100 条 benchmark 中是否出现此类知识问法及其影响。如果该边界造成误判，再进入下一轮路由规则优化。

### 4. 不改动的部分

- normalizer fallback keyword expansion（优先级 3，等前两项修复后评估收益）
- OpenSearch/Qdrant 查询层 filter（条件触发，等首次复跑数据决定）
- Docker、认证、数据库迁移
- 新增第三方依赖

## Testing Decisions

### 测试 1：LLM 空响应处理（`tests/test_llm_gateway.py`）

已有测试文件，使用 mock gateway 模式（`_build_gateway(fake_create)`）。新增 4 条测试：

- **cached 空响应 → 删除 + cache miss**：mock `redis.asyncio.from_url`，调用真实 `gateway._get_cached(key)`；fake Redis 返回 `pickle.dumps(LLMResponse(content="", ...))`，验证删除 `llm_cache:{key}`、返回 None，且 Redis 连接被 close
- **损坏缓存 → 删除 + cache miss**：fake Redis 返回不可反序列化 bytes，验证删除 `llm_cache:{key}`、返回 None，且 Redis 连接被 close
- **空响应 primary → fallback success**：mock primary model 返回空 content，验证 fallback model 被调用且返回有效结果
- **purge 只删空缓存**：mock Redis 含 2 条缓存（一条空 content、一条正常），验证 purge 后只剩正常条目

### 测试 2：ESCALATE 路由修复（`tests/test_agentic_router.py`）

已有测试文件。新增 2 条强验收测试 + 1 个观察记录：

- **退款知识查询 → RAG_SEARCH**：验证 "退款多久到账"、"退款怎么退" 等 query 路由到 RAG_SEARCH
- **代执行退款 → HUMAN_HANDOFF**：验证 "帮我退款"、"帮我取消订单" 等 query 路由到 HUMAN_HANDOFF
- **边界观察，不作为本次强验收**：记录 "退款怎么处理" 当前路由结果；如果仍为 HUMAN_HANDOFF，不阻塞本 PRD，但需要在 100 条复跑后决定是否单独优化

### 测试 3：评测脚本 source filter（`.scratch/resume-eval/`）

- 验证 `--source-url-prefix` 参数被正确解析
- 验证 context variable 在 eval 期间被设置、结束后被重置
- 验证 source filter 生效时，`retrieval_stats` 输出 `source_url_filter`、`source_url_filter_before`、`source_url_filter_after`
- 单测落点优先放在 `tests/test_resume_eval.py`，因为该测试文件已经通过 importlib 加载 `.scratch/resume-eval/run_resume_eval.py`
- 10 条 smoke 验证过滤生效

### 验证流程

```powershell
# 1. 跑单元测试
python -m pytest tests/test_llm_gateway.py tests/test_agentic_router.py -v

# 2. 10 条 smoke（含 source filter）
python .scratch/resume-eval/run_resume_eval.py --dataset-json artifacts/offline_eval/datasets/eval_cases_v1.json --limit 10 --source-url-prefix eval://retrieval/ --capture-llm-calls --case-timeout 180 --output-json artifacts/offline_eval/smoke-filtered.json --output-md artifacts/offline_eval/smoke-filtered.md

# 3. 100 条完整 benchmark
python .scratch/resume-eval/run_resume_eval.py --dataset-json artifacts/offline_eval/datasets/eval_cases_v1.json --limit 100 --source-url-prefix eval://retrieval/ --capture-llm-calls --case-timeout 180 --output-json artifacts/offline_eval/benchmark-filtered.json --output-md artifacts/offline_eval/benchmark-filtered.md
```

## Out of Scope

- normalizer fallback keyword expansion（优先级 3，等修复 1+2 后评估）
- OpenSearch/Qdrant 查询层 source filter 下推（条件触发，等首次复跑数据）
- LLM Gateway CLI/API 入口 for `purge_empty_llm_cache()`（当前仅函数级，后续可加）
- Docker、认证、数据库迁移
- 新增第三方依赖
- 模型切换或降级策略调整
- 知识库数据内容优化

## Further Notes

- 本次诊断基于 `artifacts/offline_eval/retrieval-baseline-100.json` 的 100 条评测结果
- ESCALATE 修复的 4 条 case（EVAL-020, 047, 055, 098）将进入正常 RAG 流程，但 LLM 缓存污染和旧语料污染仍可能影响其检索质量，需复跑验证
- "退款怎么处理"类边界 case 需要在 100 条 benchmark 中统计出现频率，再决定是否调整 `execution_terms` 中的 `"处理"`
- 如果 merge 后 source filter 仍导致 benchmark 文档漏召，说明旧语料已占满 fetch window，需下推到查询层
