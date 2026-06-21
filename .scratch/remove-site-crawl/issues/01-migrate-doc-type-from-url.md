# 01 - 迁移 `_doc_type_from_url` 到 `doc_type_classifier.py`

Status: done

## Parent

.scratch/remove-site-crawl/PRD.md

## What to build

将 `web_crawler.py` 中的 `_doc_type_from_url` 函数迁移到 `doc_type_classifier.py`，使其成为该模块的本地私有函数。原 `from app.services.web_crawler import _doc_type_from_url` 改为直接使用本地定义。同时删除 `tests/test_query_spec_refactor.py` 中 `test_web_crawler_imports` 测试用例（该用例验证的是 `web_crawler` 的 re-export，迁移后不再适用）。

迁移后 `_doc_type_from_url` 的行为必须与原函数完全一致：根据 URL 路径中的关键词匹配 `doc_type_url_keywords` 配置，返回对应的 doc_type 字符串。

## Acceptance criteria

- [ ] `_doc_type_from_url` 函数在 `doc_type_classifier.py` 中可用，行为与原函数一致
- [ ] `doc_type_classifier.py` 中不再有 `from app.services.web_crawler import _doc_type_from_url` 的 import
- [ ] `tests/test_query_spec_refactor.py` 中 `test_web_crawler_imports` 测试用例已删除
- [ ] `pytest` 全部通过

## Blocked by

None - can start immediately
