# 02 - 删除后端 crawl-website 路由和 schema

Status: ready-for-agent

## Parent

.scratch/remove-site-crawl/PRD.md

## What to build

删除 `app/api/routes/documents.py` 中的 `POST /documents/crawl-website` 路由函数及其 import（`CrawlWebsiteRequest`、`CrawlWebsiteResponse`、`CrawledPage`）。删除 `app/api/schemas.py` 中的 `CrawlWebsiteRequest`、`CrawledPage`、`CrawlWebsiteResponse` 三个 schema。

删除后，API 文档中不再出现该端点，其余文档相关端点（fetch-from-url、re-crawl、re-crawl-all）不受影响。

## Acceptance criteria

- [ ] `POST /documents/crawl-website` 路由不存在
- [ ] `CrawlWebsiteRequest`、`CrawledPage`、`CrawlWebsiteResponse` schema 不存在
- [ ] `documents.py` 中无对上述 schema 的 import
- [ ] `pytest` 全部通过

## Blocked by

None - can start immediately
