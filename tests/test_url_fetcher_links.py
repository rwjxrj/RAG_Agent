"""Test that crawl preserves links in content."""

from app.services.url_fetcher import _clean_html


def test_clean_html_preserves_links():
    html = '<p>Check our <a href="/dedicated-servers.php">Dedicated Servers</a>.</p>'
    base = "https://greencloudvps.com/"
    out = _clean_html(html, base_url=base)
    assert "dedicated-servers.php" in out
    assert "greencloudvps.com" in out
    assert "Dedicated Servers" in out


def test_clean_html_without_base_url_keeps_link_text_only():
    """When no base_url, links are stripped to text only (no href)."""
    html = '<p>Check <a href="/page">link</a>.</p>'
    out = _clean_html(html, base_url=None)
    assert "link" in out


def test_fetch_content_from_url_can_use_rendered_html(monkeypatch):
    from app.services import url_fetcher

    html = """
    <html>
      <head><title>Rendered page</title></head>
      <body><main><h1>Rendered content</h1><p>Loaded by JavaScript.</p></main></body>
    </html>
    """

    def fake_rendered_html(url: str, timeout: float = 15.0) -> str:
        assert url == "https://example.com/app"
        assert timeout == 3.0
        return html

    monkeypatch.setattr(url_fetcher, "_fetch_rendered_html", fake_rendered_html, raising=False)

    result = url_fetcher.fetch_content_from_url("https://example.com/app", timeout=3.0, render_js=True)

    assert result["title"] == "Rendered page"
    assert "Rendered content" in result["content"]
    assert "Loaded by JavaScript" in result["content"]
    assert result["raw_html"] == html
