# 03 - 删除前端抓取网站 UI 和 API 客户端

Status: done

## Parent

.scratch/remove-site-crawl/PRD.md

## What to build

删除 `frontend/src/pages/DocumentList.tsx` 中的 `CrawlWebsiteModal` 组件、"抓取网站"按钮、`showCrawlModal` 状态及其条件渲染块。删除 `frontend/src/api/client.ts` 中的 `crawlWebsite` 方法和 `CrawlWebsiteResponse` 类型。

删除后，文档管理页面不再显示"抓取网站"入口，"添加文档"、"上传文件"、"从 source 导入"、"重新抓取全部"按钮和功能保持不变。

注意：`Globe` 图标若在统计卡片（"HTTP 来源"）中仍使用，则保留 import；仅移除爬取相关的使用。

## Acceptance criteria

- [ ] 文档管理页面不显示"抓取网站"按钮
- [ ] `CrawlWebsiteModal` 组件不存在
- [ ] `client.ts` 中无 `crawlWebsite` 方法和 `CrawlWebsiteResponse` 类型
- [ ] "添加文档"弹窗的 URL 获取功能正常
- [ ] 单文档重新抓取和全量重新抓取功能正常
- [ ] `npm run build` 通过

## Blocked by

None - can start immediately
