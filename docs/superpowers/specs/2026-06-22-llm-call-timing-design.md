# LLM 调用级耗时埋点设计

## 目标

在不改变 LLM 调用、缓存、主备模型回退和答案输出语义的前提下，为 `OpenAIGateway.chat()` 内每次真实模型尝试记录可检索的性能数据，用于定位 RAG 各阶段的 LLM 延迟瓶颈。

## 范围

- 修改 `app/services/llm_gateway.py`，在每次模型尝试结束时记录结构化事件。
- 修改 `tests/test_llm_gateway.py`，覆盖成功、主模型失败后回退、最终超时。
- 实现完成后同步检查 `.agent-harness/02_RAG_FLOW.md`。
- 不调整并行策略、超时默认值、SDK 重试、模型路由、缓存行为或 API 顶层字段。

## 事件字段

每次真实模型尝试记录以下字段：

| 字段 | 说明 |
|---|---|
| `task` | `current_llm_task_var` 中的任务名，缺失时为 `unknown` |
| `model` | 本次尝试使用的模型 |
| `attempt` | 当前 `chat()` 内从 1 开始的模型尝试序号 |
| `is_fallback` | 是否为备用模型尝试 |
| `duration_seconds` | 本次模型尝试的耗时，使用单调时钟计算 |
| `status` | `success`、`error` 或 `timeout` |
| `error_type` | 失败时的异常类型；成功时为空 |

结构化日志不包含 API 密钥、完整 prompt 或完整响应正文。

## 数据流

```text
phase 设置 current_llm_task_var
  -> OpenAIGateway.chat()
  -> 读取缓存
  -> 对主模型/备用模型逐次尝试
  -> 每次尝试单独计时
  -> 写入结构化日志
  -> debug_llm_calls 开启时追加到现有 llm_call_log
  -> 保持原有成功返回或异常传播
```

缓存命中不会发起模型请求，记录为现有缓存日志，不纳入模型尝试耗时。

## 错误处理

- 用异常类型和异常名称识别超时，事件状态记为 `timeout`；其他异常记为 `error`。
- 埋点代码失败不得影响业务调用、回退或异常传播。
- 主模型失败后仍按现有顺序尝试备用模型。
- 最终异常保持原类型向上抛出。

## 测试

采用测试先行：

1. 单模型成功时产生一条 `success` 事件，字段完整且耗时非负。
2. 主模型失败、备用模型成功时产生两条事件，attempt 和 fallback 标记正确。
3. 最终超时时产生 `timeout` 事件，且原异常继续抛出。
4. 运行 `tests/test_llm_gateway.py`，再运行与 LLM Gateway 直接相关的窄测试集合。

## 验收标准

- 能按 `task`、`model`、`status` 检索每次模型尝试及其耗时。
- 可区分主模型与备用模型。
- 成功、普通异常和超时均有记录。
- 原有缓存、回退、token 统计和返回结构不变。
- 不新增第三方依赖。
