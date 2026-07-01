# Issue 03：跨供应商 LLM 缓存隔离与配置变更失效

Status: ready-for-agent

## What to build

让 LLM 响应缓存能够区分主模型与备用供应商执行结果，避免切换 fallback model、Base URL 或供应商后继续命中旧供应商生成的响应。缓存标识不得包含明文 API key，但应包含足以区分模型路由配置的稳定、非敏感信息。

管理员更新影响请求语义或供应商路由的 LLM 配置后，应采用有界、可观测的缓存失效策略，避免有效配置已经更新但旧响应持续生效。

## Acceptance criteria

- [ ] 缓存键能区分 primary model、fallback model、响应格式、token 参数和供应商端点身份。
- [ ] 缓存键及日志不包含明文 API key、Authorization header 或其他凭证。
- [ ] fallback 成功结果不会与不同供应商或不同 fallback model 的请求共享缓存。
- [ ] 管理员修改模型或 Base URL 后，旧路由缓存不会继续命中；失效范围有界且有日志/返回结果可观察。
- [ ] 保留相同配置下的正常缓存命中能力，不把缓存整体永久禁用。
- [ ] 增加配置切换前后、主失败 fallback 成功、同配置重复请求的确定性测试。
- [ ] 相关后端 pytest 通过，并说明是否需要清理现有 Redis LLM cache。

## Blocked by

- `.scratch/llm-fallback-provider-hardening/issues/01-fallback-config-contract-and-switching-tests.md`

## Comments

- 当前请求缓存键以主请求模型为核心，fallback provider 和 fallback model 未完整进入命名空间。
- 如果选择配置更新时清理缓存，必须只操作 `llm_cache:*` 范围，不得执行 Redis 全库清理。
