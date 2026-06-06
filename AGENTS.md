# AGENTS.md

## 项目定位
这是一个企业客服 RAG 系统，包含 FastAPI 后端、React 前端、PostgreSQL、Redis、Celery、OpenSearch、Qdrant、Playwright 爬虫和知识库导入流程。

## 工作原则
- 优先帮助我理解项目，不要一上来大规模重构。
- 每次修改前，先说明将改哪些文件、为什么改。
- 不允许批量格式化无关文件。
- 不允许删除已有功能。
- 不允许引入新的第三方依赖，除非我明确同意。
- 不允许改动 Docker、数据库迁移、认证逻辑，除非任务明确要求。
- 优先小步修改，每次只解决一个清晰问题。

## 阅读顺序
理解项目时按以下顺序阅读：
1. README.md
2. docker-compose.yml
3. .env.example
4. app/main.py
5. app/api/routes/
6. app/services/
7. app/search/
8. worker/
9. frontend/src/

## 重点模块
- RAG 问答流程：reply / conversations / retrieval / llm / search
- 知识库导入：documents / source_loaders / ingestion scripts
- 工单学习流程：tickets / WHMCS crawler / approval / ingest tickets
- 前端页面：Login、Conversations、Documents、Crawl、Dashboard、Settings

## 输出要求
- 回答我时使用中文。
- 先给结论，再解释。
- 对陌生模块先画流程，不要直接改代码。
- 修改代码后必须说明测试方式。