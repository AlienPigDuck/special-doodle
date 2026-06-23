"""
Nikkei Japan morning newspaper (朝刊) collector.
Authenticates with Playwright, navigates to today's morning edition at /paper/,
and scrapes full articles from market-relevant sections.
Articles are in Japanese — the digest step handles translation.
"""

import logging
from datetime import datetime, timezone, timedelta
from playwright.sync_api import Page
from .base import Article
from .nikkei_auth import make_page

log = logging.getLogger(__name__)

BASE_URL  = "https://www.nikkei.com"
PAPER_URL = "https://www.nikkei.com/paper/"

# Morning edition sections to collect — markets, business, international
KEEP_SECTIONS = frozenset({
    '１面',
    '総合１', '総合２', '総合３', '総合４', '総合５',
    'グローバル市場',
    '国際',
    'アジアBiz',
    'ビジネス１', 'ビジネス２',
    '投資１', '投資２',
    '商品',
})

# All section names — used so the DOM walker knows when a new section starts
_ALL_SECTIONS = KEEP_SECTIONS | frozenset({
    '社説', 'オピニオン',
    'マネーのまなび１', 'マネーのまなび２',
    '医療・介護・健康', '詩歌・教養',
    '読書１', '読書２',
    '東京・首都圏経済',
    'スポーツ１', 'スポーツ２',
    '社会１', '社会２',
    '文化',
})

# JS that walks the DOM in document order, tracking section headers,
# and collects /paper/article/ links in market-relevant sections.
# Section headers are detected by finding elements whose direct text nodes
# equal a known section name (e.g. <span>１面</span> or <h2>グローバル市場</h2>).
_EXTRACT_JS = """
([keepSections, allSections]) => {
    const keep = new Set(keepSections);
    const all  = new Set(allSections);
    const results = [];
    const seen = new Set();
    let currentSection = null;

    const iter = document.createNodeIterator(
        document.body,
        NodeFilter.SHOW_ELEMENT
    );

    let el;
    while ((el = iter.nextNode())) {
        // Direct text: only immediate TEXT_NODE children (not grandchildren)
        const directText = Array.from(el.childNodes)
            .filter(n => n.nodeType === 3)
            .map(n => n.textContent.trim())
            .filter(t => t.length > 0)
            .join('');

        if (all.has(directText)) {
            currentSection = directText;
        }

        if (el.tagName === 'A' && keep.has(currentSection)) {
            const href = el.getAttribute('href') || '';
            if (href.includes('/paper/article/') && !seen.has(href)) {
                seen.add(href);
                const title = (el.textContent || '').trim();
                if (title.length > 8) {
                    results.push([
                        href.startsWith('/') ? 'https://www.nikkei.com' + href : href,
                        title.substring(0, 120),
                        currentSection
                    ]);
                }
            }
        }
    }
    return results;
}
"""

# Fallback JS: collect all /paper/article/ links regardless of section
_FALLBACK_JS = """
() => {
    const results = [];
    const seen = new Set();
    for (const el of document.querySelectorAll('a[href*="/paper/article/"]')) {
        const href = el.getAttribute('href') || '';
        if (!seen.has(href)) {
            seen.add(href);
            const title = (el.textContent || '').trim();
            if (title.length > 8) {
                results.push([
                    href.startsWith('/') ? 'https://www.nikkei.com' + href : href,
                    title.substring(0, 120),
                    'unknown'
                ]);
            }
        }
    }
    return results;
}
"""


def _get_morning_url(page: Page) -> str:
    """Navigate to /paper/ and return today's morning edition URL."""
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).strftime('%Y%m%d')
    fallback = f"{BASE_URL}/paper/morning/?b={today}&d=0"

    try:
        page.goto(PAPER_URL, wait_until="domcontentloaded", timeout=30000)
        for a in page.query_selector_all('a[href*="/paper/morning/"]'):
            href = a.get_attribute('href') or ''
            if today in href:
                url = f"{BASE_URL}{href}" if href.startswith('/') else href
                log.info("Nikkei JP: morning edition link found: %s", url)
                return url
    except Exception as e:
        log.warning("Nikkei JP: /paper/ navigation failed: %s — using fallback URL", e)

    log.info("Nikkei JP: using constructed morning URL: %s", fallback)
    return fallback


def _extract_links(page: Page) -> list[tuple[str, str, str]]:
    """
    Extract article links from the morning edition page.
    Returns list of (url, title, section).
    Falls back to all paper articles if section detection yields nothing.
    """
    links = page.evaluate(_EXTRACT_JS, [list(KEEP_SECTIONS), list(_ALL_SECTIONS)])

    if not links:
        log.warning("Nikkei JP: section detection found 0 articles — falling back to all paper articles")
        links = page.evaluate(_FALLBACK_JS)

    log.info("Nikkei JP: %d article links found", len(links))
    return links


def _scrape_article(page: Page, url: str) -> tuple[str, str]:
    """Returns (title, body) for a newspaper article page — both in Japanese."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)

        title = ""
        try:
            title = page.locator("h1").first.inner_text(timeout=3000).strip()
        except Exception:
            pass

        body = page.inner_text("body").strip()
        return title, body[:4000]
    except Exception as e:
        log.warning("Nikkei JP: article scrape failed [%s]: %s", url, e)
        return "", ""


def fetch(max_age_hours: int = 14) -> list[Article]:
    result = make_page("nikkei_jp")
    if not result:
        return []
    pw, browser, page = result

    articles: list[Article] = []

    try:
        morning_url = _get_morning_url(page)
        page.goto(morning_url, wait_until="domcontentloaded", timeout=30000)

        links = _extract_links(page)
        seen_urls: set[str] = set()

        for url, link_title, section in links:
            if url in seen_urls:
                continue
            seen_urls.add(url)

            title, body = _scrape_article(page, url)
            if not title:
                title = link_title
            if not title and not body:
                continue

            articles.append(Article(
                title=title,
                body=body,
                source="Nikkei JP",
                url=url,
                section=section,
                published_at=datetime.now(timezone.utc),
                language="ja",
            ))
    finally:
        browser.close()
        pw.stop()

    with_body = sum(1 for a in articles if len(a.body) > 100)
    avg_chars = int(sum(len(a.body) for a in articles) / max(len(articles), 1))
    log.info("Nikkei JP: %d articles collected — %d/%d have body content (avg %d chars)",
             len(articles), with_body, len(articles), avg_chars)
    if with_body == 0 and articles:
        raise RuntimeError("Nikkei JP: all article bodies are empty — _scrape_article selectors are broken")
    return articles
