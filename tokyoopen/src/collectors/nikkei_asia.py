"""
Nikkei Asia collector.
Authenticates with a Playwright browser (email/password via id.nikkei.com SSO),
fetches RSS article links, then renders each article to extract full body text.
"""

import logging
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from playwright.sync_api import Page
from .base import Article
from .nikkei_auth import make_page

log = logging.getLogger(__name__)

RSS_URL      = "https://asia.nikkei.com/rss/feed/nar"
MAX_ARTICLES = 20

SKIP_URLS = ("/life-arts/", "/watch-listen/", "/sports/")


def _scrape_body(page: Page, url: str) -> str:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        container = (
            soup.find("article") or
            soup.find("div", {"class": lambda c: c and "article-body" in c}) or
            soup.find("div", {"class": lambda c: c and "content" in c})
        )
        if not container:
            return ""
        for tag in container(["script", "style", "aside", "nav", "figure", "figcaption", "button"]):
            tag.decompose()
        return container.get_text(separator=" ", strip=True)[:4000]
    except Exception as e:
        log.warning("Nikkei Asia: scrape failed [%s]: %s", url, e)
        return ""


def fetch(max_age_hours: int = 14) -> list[Article]:
    result = make_page("nikkei_asia")
    if not result:
        return []
    pw, browser, page = result

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    try:
        feed = feedparser.parse(RSS_URL)
    except Exception as e:
        log.warning("Nikkei Asia: RSS fetch failed: %s", e)
        browser.close()
        pw.stop()
        return []

    articles = []
    for entry in feed.entries[:MAX_ARTICLES]:
        pub = entry.get("published_parsed") or entry.get("updated_parsed")
        pub_dt = datetime(*pub[:6], tzinfo=timezone.utc) if pub else None
        if pub_dt and pub_dt < cutoff:
            continue

        url   = entry.get("link", "")
        title = entry.get("title", "").strip()

        if any(skip in url for skip in SKIP_URLS):
            continue

        body = _scrape_body(page, url) if url else ""
        if not body:
            body = (entry.get("summary") or "")[:600].strip()

        articles.append(Article(
            title=title,
            body=body,
            source="Nikkei Asia",
            url=url,
            published_at=pub_dt,
        ))

    browser.close()
    pw.stop()
    log.info("Nikkei Asia: %d articles", len(articles))
    return articles
