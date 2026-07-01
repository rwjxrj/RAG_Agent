# Issue 02：AsyncOpenAI 客户端生命周期与连接泄漏修复

Status: ready-for-agent

## What to build

为主、备用 `AsyncOpenAI` 客户端建立明确且可验证的生命周期，避免每次创建网关后遗留未关闭的 HTTP session。无论主客户端与备用客户端是两个实例还是同一实例，关闭逻辑都必须幂等，且不能重复关闭同一对象。

实现应结合项目当前网关创建方式选择最小改动方案，并确保正常完成、异常、超时和取消路径最终都能释放由网关拥有的客户端资源。

## Acceptance criteria

- [ ] 明确网关是请求级复用还是应用级复用，并在代码中建立对应的关闭入口。
- [ ] 主、备用客户端为不同实例时都能关闭；指向同一实例时只关闭一次。
- [ ] 正常、provider 异常、pipeline 超时和任务取消路径不会遗留未关闭 session。
- [ ] 增加确定性测试验证 `aclose()` 调用次数和异常路径清理。
- [ ] 运行相关 smoke 时不再出现 `Unclosed client session` 或 `Unclosed connector`。
- [ ] 不通过吞掉资源警告或强制垃圾回收来伪装修复。
- [ ] 相关后端 pytest 通过，不引入新依赖。

## Blocked by

None - can start immediately

## Comments

- 100 条 benchmark 末尾曾出现 `Unclosed client session` / `Unclosed connector`；独立 fallback 客户端会放大该问题。
- 实施前先确认 `get_llm_gateway()` 与 `PipelineRunner` 的真实实例化边界，避免关闭仍被复用的客户端。
