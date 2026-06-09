from app.api.schemas import CrawlWebsiteRequest


def test_crawl_website_request_allows_zero_depth_for_single_page_rendered_fetch():
    request = CrawlWebsiteRequest(
        url="https://example.com/app",
        max_pages=1,
        max_depth=0,
        render_js=True,
    )

    assert request.max_pages == 1
    assert request.max_depth == 0
    assert request.render_js is True
