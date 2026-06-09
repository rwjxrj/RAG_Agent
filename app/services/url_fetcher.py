"""Fetch and extract content from URLs for document ingestion."""

import re
import os
from html import unescape
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.core.logging import get_logger

logger = get_logger(__name__)

_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _clean_html(html: str, base_url: str | None = None) -> str:
    """Strip boilerplate and extract text from HTML. Preserves links as text (href in content)."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # Preserve <a href> as text so links appear in content (for evidence quality, citations)
    if base_url:
        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue
            try:
                full_url = urljoin(base_url, href)
                parsed = urlparse(full_url)
                if parsed.scheme in ("http", "https"):
                    link_text = a.get_text(strip=True) or full_url
                    a.replace_with(f"{link_text} ({full_url})")
            except Exception:
                pass

    text = soup.get_text(separator="\n")
    text = unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" +", " ", text)
    return text.strip()


def _extract_title(soup: BeautifulSoup) -> str:
    """Extract page title from HTML."""
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        return title_tag.get_text(strip=True)
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    return "Untitled"


def _normalize_fetch_url(url: str) -> str:
    if not url or not url.strip():
        raise ValueError("URL is required")
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _fetch_static_html(url: str, timeout: float = 15.0) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; SupportAI-Bot/1.0; +https://github.com/support-ai)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.text


def _fetch_rendered_html(url: str, timeout: float = 15.0) -> str:
    """Fetch rendered HTML with Playwright for JavaScript-heavy pages."""
    if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
        for candidate in ("/ms-playwright", "/app/ms-playwright"):
            if os.path.exists(candidate):
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = candidate
                break

    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    timeout_ms = max(1000, int(timeout * 1000))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=_CHROME_UA,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 5000))
            except PlaywrightTimeoutError:
                logger.debug("url_fetch_render_networkidle_timeout", url=url[:120])
            page.wait_for_timeout(500)
            return page.content()
        finally:
            browser.close()


def fetch_content_from_url(url: str, timeout: float = 15.0, render_js: bool = False) -> dict:
    """
    Fetch webpage and extract title + content.
    Returns {"title": str, "content": str, "raw_html": str} or raises.
    """
    url = _normalize_fetch_url(url)
    html = _fetch_rendered_html(url, timeout=timeout) if render_js else _fetch_static_html(url, timeout=timeout)

    soup = BeautifulSoup(html, "lxml")
    title = _extract_title(soup)
    content = _clean_html(html, base_url=url)

    if len(content) < 50:
        logger.warning("url_fetch_minimal_content", url=url, content_length=len(content))

    return {
        "title": title,
        "content": content,
        "raw_html": html,
    }
