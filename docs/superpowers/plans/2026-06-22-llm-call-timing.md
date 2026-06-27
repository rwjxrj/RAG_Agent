# LLM 调用级耗时埋点实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `OpenAIGateway.chat()` 的每次真实模型尝试记录任务、模型、尝试序号、回退标记、耗时和结果。

**Architecture:** 在 LLM Gateway 内部以单调时钟包围每次 provider 请求，构建统一尝试事件。事件始终写结构化日志；开启 `debug_llm_calls` 时追加到请求级 `llm_call_log`，成功事件同时保留现有 prompt、response、token 和成本字段。

**Tech Stack:** Python、asyncio、structlog 风格项目日志、ContextVar、pytest、pytest-asyncio。

---

### Task 1: 定义调用级埋点行为

**Files:**
- Modify: `tests/test_llm_gateway.py`
- Modify: `app/services/llm_gateway.py`

- [x] **Step 1: 写成功路径失败测试**

测试设置 `current_llm_task_var="generate_reasoning"` 和空的 `llm_call_log_var`，开启 debug，调用成功后断言记录包含：

```python
{
    "task": "generate_reasoning",
    "model": "gpt-5.2",
    "attempt": 1,
    "is_fallback": False,
    "status": "success",
    "error_type": None,
}
```

并断言 `duration_seconds >= 0`。

- [x] **Step 2: 运行成功路径测试并确认 RED**

Run: `python -m pytest tests/test_llm_gateway.py::test_chat_records_successful_model_attempt -q`

Expected: FAIL，因为现有 debug 记录缺少调用级字段。

- [x] **Step 3: 写回退与超时失败测试**

主模型抛 `RuntimeError`、备用模型成功时断言两条事件的 attempt 为 1/2，第二条 `is_fallback=True`；两个模型均抛 `TimeoutError` 时断言两条 `timeout` 事件并继续抛出原异常。

- [x] **Step 4: 运行新增测试并确认 RED**

Run: `python -m pytest tests/test_llm_gateway.py -q`

Expected: 新增测试 FAIL，原有测试 PASS。

- [x] **Step 5: 实现最小埋点**

在 `app/services/llm_gateway.py`：

```python
started = time.perf_counter()
```

每次模型尝试结束后构建：

```python
event = {
    "task": current_llm_task_var.get() or "unknown",
    "model": model,
    "attempt": attempt,
    "is_fallback": attempt > 1,
    "duration_seconds": round(time.perf_counter() - started, 6),
    "status": status,
    "error_type": error_type,
}
```

通过一个 best-effort 私有 helper 写结构化日志；开启 debug 时把事件追加到 `llm_call_log_var`。成功事件合并现有 prompt/response/token/cost 字段，避免同一次尝试产生重复 debug 条目。

- [x] **Step 6: 运行 Gateway 测试并确认 GREEN**

Run: `python -m pytest tests/test_llm_gateway.py -q`

Expected: 全部 PASS。

### Task 2: 同步 harness 并完成窄验证

**Files:**
- Modify: `.agent-harness/02_RAG_FLOW.md`

- [x] **Step 1: 更新调试字段说明**

在查询 debug 说明中补充：开启 `debug_llm_calls` 后，每次真实模型尝试记录 task、model、attempt、is_fallback、duration_seconds、status、error_type；缓存命中不计作模型尝试。

- [x] **Step 2: 运行相关测试**

Run: `python -m pytest tests/test_llm_gateway.py tests/test_relevance_check.py tests/test_model_router.py -q`

Expected: 全部 PASS。

- [x] **Step 3: 检查差异**

Run: `git diff --check`

Expected: 无空白错误。然后核对 diff 仅包含计划内文件，且没有改变模型调用、回退和异常传播逻辑。
