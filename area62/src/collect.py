"""
Area 62 collector: scrapes the Nikkei evening edition (夕刊) listing page.
Returns raw (url, title_ja, section_ja) tuples — no article body scraping.
"""

import logging
from datetime import datetime, timezone, timedelta
from playwright.sync_api import Page
from nikkei_auth import make_page

log = logging.getLogger(__name__)

BASE_URL  = "https://www.nikkei.com"
PAPER_URL = "https://www.nikkei.com/paper/"

# Nikkei evening edition (夕刊) section names, in natural paper order.
# Numbered variants included as insurance in case the listing splits a page.
ALL_SECTIONS = [
    '１面',
    'ビジネス', 'ビジネス１', 'ビジネス２',
    '総合', '総合１', '総合２',
    'マーケット・投資', 'マーケット', '投資',
    'ニュースぷらす',
    '社会', '社会１', '社会２',
    '文化',
]

_EXTRACT_JS = """
([allSections]) => {
    const all = new Set(allSections);
    const results = [];
    const seen = new Set();
    let currentSection = null;

    const iter = document.createNodeIterator(document.body, NodeFilter.SHOW_ELEMENT);
    let el;
    while ((el = iter.nextNode())) {
        const directText = Array.from(el.childNodes)
            .filter(n => n.nodeType === 3)
            .map(n => n.textContent.trim())
            .filter(t => t.length > 0)
            .join('');

        if (all.has(directText)) {
            currentSection = directText;
        }

        if (el.tagName === 'A') {
            const href = el.getAttribute('href') || '';
            if (href.includes('/paper/article/') && !seen.has(href)) {
                seen.add(href);
                const title = (el.textContent || '').trim();
                if (title.length > 8) {
                    results.push([
                        href.startsWith('/') ? 'https://www.nikkei.com' + href : href,
                        title.substring(0, 120),
                        currentSection || 'other'
                    ]);
                }
            }
        }
    }
    return results;
}
"""


def _get_evening_url(page: Page) -> str:
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).strftime('%Y%m%d')
    fallback = f"{BASE_URL}/paper/evening/?b={today}&d=0"

    try:
        page.goto(PAPER_URL, wait_until="domcontentloaded", timeout=30000)
        for a in page.query_selector_all('a[href*="/paper/evening/"]'):
            href = a.get_attribute('href') or ''
            if today in href:
                url = f"{BASE_URL}{href}" if href.startswith('/') else href
                log.info("Area 62: evening edition link found: %s", url)
                return url
    except Exception as e:
        log.warning("Area 62: /paper/ navigation failed: %s — using fallback URL", e)

    log.info("Area 62: using constructed evening URL: %s", fallback)
    return fallback


def fetch() -> list[tuple[str, str, str]]:
    """Return list of (url, title_ja, section_ja) from today's evening edition listing."""
    result = make_page("nikkei_jp")
    if not result:
        return []
    pw, browser, page = result

    try:
        evening_url = _get_evening_url(page)
        page.goto(evening_url, wait_until="domcontentloaded", timeout=30000)
        links = page.evaluate(_EXTRACT_JS, [ALL_SECTIONS])
        log.info("Area 62: %d article links collected from listing page", len(links))
        # Log distinct sections seen — confirms the evening section labels on first runs
        seen_sections = sorted({section for _, _, section in links})
        log.info("Area 62: sections detected: %s", seen_sections)
        return [(url, title, section) for url, title, section in links]
    finally:
        browser.close()
        pw.stop()
