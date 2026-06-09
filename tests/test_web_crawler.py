from app.services import web_crawler


def test_crawl_website_passes_render_js_to_url_fetcher(monkeypatch):
    calls: list[dict] = []

    def fake_fetch(url: str, timeout: float = 15.0, render_js: bool = False) -> dict:
        calls.append({"url": url, "timeout": timeout, "render_js": render_js})
        return {
            "title": "Rendered docs",
            "content": "This rendered documentation page has enough content for ingestion.",
            "raw_html": "<html><body>Rendered docs</body></html>",
        }

    monkeypatch.setattr(web_crawler, "fetch_content_from_url", fake_fetch)
    monkeypatch.setattr(web_crawler, "_extract_links", lambda html, base_url: set())

    docs = web_crawler.crawl_website(
        "https://example.com/docs",
        max_pages=1,
        max_depth=0,
        render_js=True,
    )

    assert len(docs) == 1
    assert calls == [{"url": "https://example.com/docs", "timeout": 15.0, "render_js": True}]
