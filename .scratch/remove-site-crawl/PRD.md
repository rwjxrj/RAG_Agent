# 移除整站爬取功能

Status: ready-for-agent

## Problem Statement

文档管理页面的"抓取网站"功能依赖 BFS 递归抓取同域名页面，但当前大多数网站存在反爬措施（Cloudflare、验证码、速率限制等），导致整站爬取基本无法正常工作。该功能入口对用户形成误导，且对应后端模块 `web_crawler.py` 增加了不必要的维护负担。

## Solution

移除文档管理页面的"抓取网站"按钮及其弹窗，删除后端 `POST /documents/crawl-website` 路由和 `web_crawler.py` 模块。保留"添加文档"中的 URL 单页获取功能（`POST /documents/fetch-from-url`）以及单文档/全量重新抓取功能（`POST /documents/{id}/re-crawl`、`POST /documents/re-crawl-all`）。

`web_crawler.py` 中被其他模块依赖的 `_doc_type_from_url` 函数迁移到 `app/services/doc_type_classifier.py`。

## User Stories

1. As 管理员, I want 文档管理页面不再显示"抓取网站"按钮, so that 我不会误用已失效的功能
2. As 管理员, I want "添加文档"弹窗中的 URL 获取功能保持不变, so that 我仍能通过输入 URL 自动获取单页内容
3. As 管理员, I want 文档列表中每行的重新抓取按钮保持不变, so that 我仍能刷新已有 URL 文档的内容
4. As 管理员, I want "重新抓取全部"按钮保持不变, so that 我仍能批量更新所有 URL 文档
5. As 管理员, I want 整站爬取相关的后端路由完全移除, so that API 文档中不会出现已废弃的端点
6. As 开发者, I want `web_crawler.py` 被完全删除, so that 代码库中不存在未使用的爬取模块
7. As 开发者, I want `_doc_type_from_url` 函数迁移到 `doc_type_classifier.py`, so that 依赖该函数的模块不会中断
8. As 开发者, I want 前端 `client.ts` 中的 `crawlWebsite` 方法和相关类型被移除, so that 前端 API 层保持整洁
9. As 开发者, I want `test_web_crawler.py` 测试文件被删除, so that 测试套件不会引用已删除的模块
10. As 开发者, I want `test_query_spec_refactor.py` 中引用 `web_crawler` 的测试用例被清理, so that 测试通过

## Implementation Decisions

### 1. 函数迁移策略

`web_crawler.py` 中的 `_doc_type_from_url` 函数被 `doc_type_classifier.py` 导入使用。将该函数迁移到 `doc_type_classifier.py` 作为模块级私有函数，原 `from app.services.web_crawler import _doc_type_from_url` 改为本地定义。

迁移范围：

| 函数 | 来源 | 目标 | 说明 |
|------|------|------|------|
| `_doc_type_from_url` | `web_crawler.py` | `doc_type_classifier.py` | 仅此函数有外部依赖 |
| `_infer_page_kind` | `web_crawler.py` | 不迁移 | `normalization.py` 已有同名函数，`web_crawler.py` 仅 re-export |
| `_normalize_product_family` | `web_crawler.py` | 不迁移 | 同上 |
| 其余函数 | `web_crawler.py` | 删除 | 无外部依赖，随模块一并删除 |

### 2. 前端删除清单

`DocumentList.tsx` 中需删除：

- `CrawlWebsiteModal` 组件（整站爬取弹窗）
- "抓取网站" 按钮及其 `onClick` 事件
- `showCrawlModal` 状态声明
- `showCrawlModal` 的条件渲染块
- `Globe` 图标 import（需确认是否仅爬取相关使用；若统计卡片中仍有使用则保留）

`client.ts` 中需删除：

- `CrawlWebsiteResponse` 接口定义
- `crawlWebsite` 方法

### 3. 后端删除清单

`documents.py` 中需删除：

- `POST /documents/crawl-website` 路由函数
- import 中的 `CrawlWebsiteRequest`、`CrawlWebsiteResponse`、`CrawledPage`

`schemas.py` 中需删除：

- `CrawlWebsiteRequest` schema
- `CrawledPage` schema
- `CrawlWebsiteResponse` schema

### 4. 测试清理

- 删除 `tests/test_web_crawler.py`
- 删除 `tests/test_query_spec_refactor.py` 中 `test_web_crawler_imports` 测试用例

### 5. 注释清理

- `app/services/normalization.py` 模块文档字符串中移除 `web_crawler.py` 引用

## Testing Decisions

- 迁移后的 `_doc_type_from_url` 函数在 `doc_type_classifier.py` 中的行为应与原函数完全一致，通过现有 `doc_type_classifier` 测试覆盖
- 前端执行 `npm run build` 通过，无 TypeScript 编译错误
- 后端执行 `pytest` 通过，无 import 错误
- 手动验证：文档管理页面不再显示"抓取网站"按钮
- 手动验证："添加文档"弹窗的 URL 获取功能正常
- 手动验证：单文档重新抓取和全量重新抓取功能正常

## Out of Scope

- 单文档重新抓取（`POST /documents/{id}/re-crawl`）的修改或删除
- 全量重新抓取（`POST /documents/re-crawl-all`）的修改或删除
- URL 单页获取功能（`POST /documents/fetch-from-url`）的修改
- 数据库 schema 变更
- Docker 或部署配置变更

## Further Notes

- 删除 `web_crawler.py` 后，`BeautifulSoup` 和 `lxml` 的依赖可保留（`url_fetcher.py` 可能仍使用），需后续确认是否可从 `requirements.txt` 移除
- `app/crawlers/` 目录下的 WHMCS 爬虫是独立功能，不受本次改动影响
