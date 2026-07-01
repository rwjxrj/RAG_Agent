# Issue 01：备用供应商配置契约与切换测试

Status: ready-for-agent

## What to build

完善备用 LLM 供应商的端到端配置契约。管理员配置独立备用供应商时，API key 与 Base URL 必须成对生效；配置不完整时不得静默伪装为备用供应商已启用。主供应商调用失败后，网关必须使用备用客户端和 fallback model，且不得把主供应商凭证发送给备用端点。

实现应覆盖管理 API、前端设置页提示/校验、运行时客户端选择和自动化测试，并保持未配置独立供应商时继续使用原有同供应商 fallback model 的兼容行为。

## Acceptance criteria

- [ ] 明确定义并实现三种状态：未配置独立备用供应商、完整配置独立备用供应商、配置不完整。
- [ ] 配置不完整时，管理 API 返回明确的 4xx 校验错误，前端也阻止提交并显示中文提示。
- [ ] 未配置独立备用供应商时，fallback model 继续通过主客户端调用，兼容现有行为。
- [ ] 完整配置时，主客户端失败后只调用备用客户端，并使用 `llm_fallback_model`。
- [ ] 自动化测试分别记录主、备用客户端收到的请求，证明主 API key 不会传入备用端点。
- [ ] 覆盖主调用成功、不完整配置、主失败后备用成功、主与备用均失败四条路径。
- [ ] 相关后端 pytest 与前端构建通过，不引入新依赖。

## Blocked by

None - can start immediately

## Comments

- 审查基线：当前实现只有测试 helper 的 `_fallback_client` 补值，没有真正验证跨供应商切换。
- 不要把真实 API key、完整 Authorization header 或用户 prompt 写入日志和测试快照。
