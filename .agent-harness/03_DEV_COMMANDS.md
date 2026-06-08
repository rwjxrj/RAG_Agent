# 03_DEV_COMMANDS.md

## 结论
本文件只记录项目已存在的开发命令，不要求安装新依赖。运行会写数据库、抓取外部站点或修改 source 文件的命令前，需要先确认目标和环境。

## Docker Compose

```powershell
docker-compose up -d
docker-compose ps
docker-compose logs api
docker-compose logs worker
docker-compose --profile full up -d
```

说明：
- `docker-compose up -d` 会启动 frontend、api、worker、postgres、redis、opensearch、qdrant、minio 等服务。
- `--profile full` 会额外启用 nginx。
- 不要随意运行删除 volume 或清库命令。

## 数据库和初始化

```powershell
docker-compose exec api alembic upgrade head
docker-compose exec api python -m scripts.create_admin_user
make init-db
make create-admin
```

注意：
- 迁移会修改数据库结构，执行前确认数据库环境。
- 创建管理员用户需要交互或环境支持，具体行为待代码确认。

## 知识库入库

```powershell
make ingest
make ingest-dry
python scripts/ingest_from_source.py
python scripts/ingest_from_source.py --dry-run
python scripts/ingest_tickets_from_source.py
```

注意：
- `make ingest` 会从 `source/` 入库，可能写 PostgreSQL、OpenSearch、Qdrant。
- 优先用 dry run 或只读检查确认源文件格式。
- `ingest_tickets_from_source.py` 读取 sample conversations，具体写入路径待代码确认。

## WHMCS 工单导入和抓取

```powershell
make import-whmcs-dry
make import-whmcs
python scripts/crawl_whmcs_tickets.py
python scripts/whmcs_login_browser.py
```

注意：
- WHMCS 抓取可能访问外部系统，不要在未确认账号、cookie、base URL 时运行。
- `make import-whmcs` 会写入工单数据，优先运行 dry run。

## 后端开发

```powershell
uvicorn app.main:app --reload
celery -A worker.celery_app worker --loglevel=info
pytest tests/ -v
pytest tests/test_retrieval.py -v
pytest tests/test_answer_service.py -v
```

说明：
- `uvicorn` 本地启动 FastAPI。
- `celery` 本地启动 worker。
- 修改某个服务时优先跑对应的窄测试，再考虑全量测试。

## 前端开发

```powershell
cd frontend
npm run dev
npm run build
npm run preview
```

说明：
- `npm run dev` 默认 Vite 开发服务，README_zh 记录端口为 `5173`。
- Docker 前端访问端口为 `5174`。
- 不要在本任务中运行 `npm install`，除非用户明确同意。

## 调试脚本

```powershell
python scripts/debug_retrieval_ip.py
python scripts/debug_retrieval_zero_chunks.py
python scripts/debug_qdrant.py
python scripts/debug_chunks_by_url.py
python scripts/debug_normalizer.py
python scripts/run_offline_eval.py
```

注意：
- 调试脚本可能依赖服务和数据状态，运行前先读脚本开头和参数。
- offline eval 可能消耗 LLM token，执行前确认。

## 文档-only 变更验证

```powershell
git status --short
git diff -- AGENTS.md .agent-harness
```

说明：
- 文档-only 修改无需启动服务。
- 本仓库当前已有多处未提交改动；查看 diff 时只关注本次文档文件。
