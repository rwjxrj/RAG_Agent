# 04 - 删除 `web_crawler.py` 并清理所有残留引用

Status: done

## Parent

.scratch/remove-site-crawl/PRD.md

## What to build

删除 `app/services/web_crawler.py` 整个文件。删除 `tests/test_web_crawler.py` 整个文件。清理 `app/services/normalization.py` 模块文档字符串中对 `web_crawler.py` 的引用。

此任务依赖 01（`_doc_type_from_url` 已迁移）和 02（`documents.py` 中的 import 已删除），确保删除后无 import 断裂。

## Acceptance criteria

- [ ] `app/services/web_crawler.py` 文件不存在
- [ ] `tests/test_web_crawler.py` 文件不存在
- [ ] `normalization.py` 文档字符串中无 `web_crawler.py` 引用
- [ ] 全局搜索 `web_crawler` 无残留 import（仅 `normalization.py` 注释中允许出现）
- [ ] `pytest` 全部通过

## Blocked by

- .scratch/remove-site-crawl/issues/01-migrate-doc-type-from-url.md
- .scratch/remove-site-crawl/issues/02-delete-backend-crawl-route.md
