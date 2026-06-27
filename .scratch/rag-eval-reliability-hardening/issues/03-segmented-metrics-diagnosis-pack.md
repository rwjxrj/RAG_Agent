# Issue 03：拆分路由与检索指标并生成诊断包

Status: ready-for-agent

## Parent

`.scratch/rag-eval-reliability-hardening/PRD.md`

## What to build

将评测指标按实际执行路径分层，避免 direct response、clarification、intentional human handoff、基础设施失败和真实 RAG retrieval 共用同一个 Recall/延迟 denominator。报告需要同时保留全量视角和纯检索视角，并自动生成一个适合 AI 阅读的精简诊断包。

诊断包只保留总体摘要、无效 case、路由短路、零/部分召回、最慢 case、重试 case、预期与实际 source，以及必要的阶段耗时和结构化原因。不得包含完整 prompt、response、Evidence 文本或全量控制台日志。

覆盖 User Stories：13–18、24–29。

## Acceptance criteria

- [ ] 指标至少分为 all cases、retrieval eligible、retrieval executed、route short-circuited 和 invalid cases。
- [ ] intentional human handoff 不进入 retrieval-executed Recall/Hit denominator，但保留在 all-case 与 routing summary。
- [ ] routing summary 分别统计 RAG search、direct response、clarification 和 human handoff，并汇总 route reason。
- [ ] retrieval summary 输出 full recall、partial recall、zero recall 和 zero-result case 数量。
- [ ] 召回缺口能够按 dataset tags、difficulty 和 expected source 聚合。
- [ ] 延迟至少分为 retrieved-only、route-short-circuit、no-retry、retried 和 max-retry 分组。
- [ ] JSON 与 Markdown 明确展示每组 denominator，且同一字段定义一致。
- [ ] 自动在主报告旁生成 compact diagnosis JSON。
- [ ] diagnosis JSON 包含 summary、invalid cases、route-short-circuited cases、recall failures、slowest cases 和 retried cases。
- [ ] diagnosis JSON 不包含 messages、prompt、response content、完整 Evidence 文本或无关正常 case 详情。
- [ ] 报告 metadata 包含 dataset identity、case count、时间、cache 声明、source filter、delay、timeout、capture 状态和 retry 设置。
- [ ] 测试使用已知 denominator 的小型 fixture 验证全量、路由和检索指标，不依赖真实模型或搜索服务。
- [ ] 保留必要的旧指标兼容字段，并明确其 denominator。

## Blocked by

- Issue 02：增加轻量 LLM 统计与限流保护

