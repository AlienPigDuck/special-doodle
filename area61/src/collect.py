"""
Area 61 collector: scrapes the Nikkei morning edition listing page.
Returns raw (url, title_ja, section_ja) tuples — no article body scraping.
"""

import logging
from datetime import datetime, timezone, timedelta
from playwright.sync_api import Page
from nikkei_auth import make_page

log = logging.getLogger(__name__)

BASE_URL  = "https://www.nikkei.com"
PAPER_URL = "https://www.nikkei.com/paper/"

# All known Nikkei morning edition section names, in natural paper order
ALL_SECTIONS = [
    '１面',
    '総合１', '総合２', '総合３', '総合４', '総合５',
    'グローバル市場',
    '国際',
    'アジアBiz',
    'ビジネス１', 'ビジネス２',
    '投資１', '投資２',
    '商品',
    '社説',
    'オピニオン',
    'マネーのまなび１', 'マネーのまなび２',
    '医療・介護・健康',
    '詩歌・教養',
    '読書１', '読書２',
    '東京・首都圏経済',
    'スポーツ１', 'スポーツ２',
    '社会１', '社会２',
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


def _load_paper(page: Page) -> None:
    """Load the Nikkei /paper/ morning listing. The page does a client-side
    self-redirect to /paper/, so a plain goto raises 'interrupted by another
    navigation'. wait_until='commit' returns before that fires; then let it settle."""
    try:
        page.goto(PAPER_URL, wait_until="commit", timeout=30000)
    except Exception as e:
        log.warning("Area 61: /paper/ goto hiccup: %s", e)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(3000)   # let the self-redirect settle before extracting


def _extract_retry(page, tries: int = 5):
    """Run the extractor, retrying while the SPA's self-redirect keeps destroying
    the execution context. Returns links once the page holds still."""
    for i in range(tries):
        try:
            return page.evaluate(_EXTRACT_JS, [ALL_SECTIONS])
        except Exception as e:
            if "Execution context was destroyed" in str(e) and i < tries - 1:
                log.warning("Area 61: context destroyed mid-extract — retry %d", i + 1)
                page.wait_for_timeout(2500)
            else:
                raise


def fetch() -> list[tuple[str, str, str]]:
    """Return list of (url, title_ja, section_ja) from today's morning edition listing."""
    result = make_page("nikkei_jp")
    if not result:
        return []
    pw, browser, page = result

    try:
        _load_paper(page)
        links = _extract_retry(page)
        log.info("Area 61: %d article links collected from listing page", len(links))
        return [(url, title, section) for url, title, section in links]
    finally:
        browser.close()
        pw.stop()
