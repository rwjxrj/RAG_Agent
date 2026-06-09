# 张鉴豪

**求职意向：AI 应用开发实习生 / Agent开发实习生**  
**具备 AI Agent、RAG 检索增强生成、全栈项目落地经验**
- 电话：158-8180-1741
- 邮箱：rwjxri@163.com
## 技术栈与框架

- **后端开发**：Python、FastAPI、Pydantic v2、SQLAlchemy、Alembic、RESTful API
- **AI / RAG**：RAG、BM25 + 向量混合检索、OpenAI-compatible Chat Completions、Prompt Engineering、Reviewer 校验
- **检索与数据**：OpenSearch、Qdrant、PostgreSQL、Redis、文档分块、Embedding、Rerank
- **异步与工程化**：Celery、Docker Compose、Uvicorn、环境变量配置、日志与健康检查
- **前端开发**：React、Vite、Tailwind CSS、TypeScript、管理后台页面与 API 对接
- **自动化与爬虫**：Playwright、网页抓取、WHMCS 工单数据导入、文件解析与知识库入库
- **AI 辅助开发**：Claude code / Vibe Coding、Codex、结构化需求拆解、代码理解与小步可回退修改

## 核心项目实战

### 企业客服 RAG 智能助手系统

**项目定位**：面向企业客服场景的 Support AI Assistant，支持将网页文档、人工整理 FAQ、历史工单和高评分会话沉淀为知识库，通过 RAG 流程为客服工单、在线会话和外部 helpdesk 系统生成带引用的建议回复。  
**技术栈**：FastAPI、React、PostgreSQL、Redis、Celery、OpenSearch、Qdrant、Playwright、Docker Compose、OpenAI-compatible LLM

- **负责全链路项目理解与落地**：梳理 FastAPI 后端、React 前端、PostgreSQL、Redis、Celery、OpenSearch、Qdrant 等服务关系，建立项目地图、服务地图、RAG 查询链路和入库流程文档，保证后续迭代可理解、可验证、可回退。
- **参与 RAG 查询链路建设**：围绕 `reply` / `conversations` 入口，理解并整理从用户问题到 `AnswerService`、`Orchestrator`、`RetrievalService`、LLM Gateway、Reviewer 校验的完整流程，使系统能够输出答案、引用、置信度和调试元数据。
- **落地混合检索能力**：结合 OpenSearch BM25 与 Qdrant 向量检索，通过 RRF / simple merge、rerank、EvidenceSet 构建等方式提升客服问答的召回质量和答案可追溯性。
- **完善知识库入库流程**：支持从 `source/*.json`、URL 抓取、整站爬取、上传文件、WHMCS 工单等来源导入知识；入库过程中完成文本清洗、语义分块、Embedding、PostgreSQL 落库、OpenSearch/Qdrant 索引写入。
- **支持工单持续学习闭环**：梳理并使用“抓取工单 -> 人工审批 -> 导出已批准会话 -> 重新入库”的流程，使高质量真实客服会话可以转化为可检索知识，持续优化客服回复质量。
- **实现 OpenAI-compatible 模型接入思路**：基于统一 Chat Completions 形式，支持 DeepSeek、Qwen、GLM、Kimi、硅基流动等国内模型配置，降低项目对单一模型供应商的依赖。
- **维护管理后台能力**：前端包含登录、会话、文档、抓取、仪表盘、设置、意图、文档类型、API Token、API Reference 等页面，支撑客服和管理员完成知识维护、会话调试和模型配置。
- **注重工程可维护性**：在改动前检查 git 状态、阅读项目文档和 harness 约束，遵循小步修改、窄范围验证、不批量格式化无关文件、不破坏既有功能的协作方式。

## 荣誉奖励

- 2025 年 蓝桥杯 AIGC 图像方向 全国三等奖
- 2024 年 蓝桥杯 AIGC 图像方向 全国三等奖
- 2024 年 传智杯 AIGC 图片方向 省级二等奖
- 2024 年 大学生计算机设计大赛 UI 设计 省二等奖
- 2024 年 大学生计算机设计大赛 UI 设计 省三等奖

## 教育背景

**闽南理工学院**  
物联网工程 / 本科  
2023.09 - 2027.06

**自学课程**：数据结构、前端开发、人工智能基础、人机交互设计等

## 个人优势

1. **具备 AI 应用端到端落地能力**：能够从需求理解、服务拆解、RAG 流程梳理、后端 API、前端管理页面到 Docker 化部署进行完整思考，适合参与 AI 应用工程化项目。
2. **熟悉 RAG 与大模型接入链路**：理解知识库入库、文档分块、Embedding、BM25/向量混合检索、rerank、证据选择、LLM 生成和 Reviewer 校验等关键环节。
3. **具备后端与数据工程基础**：掌握 FastAPI、PostgreSQL、Redis、Celery、OpenSearch、Qdrant 等组件的协作方式，能够围绕业务流程定位问题并进行小步迭代。
4. **有 AI 辅助开发与文档化协作习惯**：熟练使用 Cursor、Codex 等工具进行代码理解、流程梳理和辅助开发，重视变更前阅读上下文、变更后验证和失败经验沉淀。
5. **兼具产品视角与视觉表达能力**：有 UI 设计和 AIGC 图像竞赛经历，能够从用户体验、管理后台可用性和 AI 输出质量多个角度思考项目落地。
