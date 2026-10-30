"""
Area 61 collector: scrapes the Nikkei morning edition (朝刊) listing page.
Returns raw (url, title_ja, section_ja) tuples — no article body scraping.
"""

import logging
from datetime import datetime, timezone, timedelta
from playwright.sync_api import Page
from nikkei_auth import make_page

log = logging.getLogger(__name__)

BASE_URL  = "https://www.nikkei.com"
PAPER_URL = "https://www.nikkei.com/paper/"
_JST = timezone(timedelta(hours=9))

# Nikkei redesigned its 朝刊・夕刊 pages in October 2026. Each edition now has its own
# URL — /paper/YYYYMMDDM101 (morning) and /paper/YYYYMMDDE101 (evening) — and article
# links look like /paper/<edition>/<pageID>/article/<articleID>. Section names are the
# <h2> headings above each group of links, e.g. 1面, 総合1, 政治・外交, ビジネス2 (page
# numbers are half-width digits now; the old pages used full-width ones).

# Walks the DOM in document order. An <h2> starts a new section; every anchor whose
# href is a paper article is collected with the headline (the <h3> inside the anchor —
# the anchor's own text also carries the lead paragraph) and the current section.
_EXTRACT_JS = """
() => {
    const re = /\\/paper\\/(?:\\d{8}[A-Z]\\d+\\/[A-Z0-9]+\\/)?article\\//;
    const results = [];
    const seen = new Set();
    let section = null;
    const iter = document.createNodeIterator(document.body, NodeFilter.SHOW_ELEMENT);
    let el;
    while ((el = iter.nextNode())) {
        if (el.tagName === 'H2') {
            const t = (el.textContent || '').trim();
            if (t && t.length <= 24) section = t;
        }
        if (el.tagName !== 'A') continue;
        const href = el.getAttribute('href') || '';
        if (!re.test(href) || seen.has(href)) continue;
        seen.add(href);
        const h = el.querySelector('h3, h2, h4');
        const title = ((h ? h.textContent : el.textContent) || '').trim();
        if (title.length > 8) {
            results.push([
                href.startsWith('/') ? 'https://www.nikkei.com' + href : href,
                title.substring(0, 120),
                section || 'unknown',
            ]);
        }
    }
    return results;
}
"""

def _goto_settle(page: Page, url: str) -> None:
    """Navigate and let the SPA settle (it self-redirects, which interrupts a plain goto)."""
    try:
        page.goto(url, wait_until="commit", timeout=30000)
    except Exception as e:
        log.warning("Area 61: goto hiccup at %s: %s", url, e)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(3000)
    try:
        page.wait_for_selector('a[href*="/article/"]', timeout=20000)
    except Exception:
        pass


def _eval_retry(page: Page, js, *args, tries: int = 5):
    """Run page.evaluate, retrying while the SPA's self-redirect keeps destroying
    the execution context, until the page holds still."""
    for i in range(tries):
        try:
            return page.evaluate(js, *args)
        except Exception as e:
            if i < tries - 1:
                log.warning("Area 61: extract attempt %d failed (%s) — retrying", i + 1, str(e)[:90])
                page.wait_for_timeout(2500)
            else:
                raise


def _load_links(page: Page) -> list[tuple[str, str, str]]:
    """Load today's 朝刊 edition and return (url, title, section) for every
    article in it. Tries the explicit edition URL first, then /paper/ (whatever edition
    the site defaults to) — a page is accepted only if its title says 朝刊."""
    today = datetime.now(_JST).strftime("%Y%m%d")
    for url in (f"{BASE_URL}/paper/{today}M101", PAPER_URL):
        _goto_settle(page, url)
        title = page.title()
        links = _eval_retry(page, _EXTRACT_JS)
        if links and '朝刊' in title:
            log.info("Area 61: %s — %d article links (%s)", title, len(links), page.url)
            return links
        log.warning("Area 61: %s gave %d links, page title %r — %s", url, len(links), title,
                    "trying /paper/" if url != PAPER_URL else "giving up")
    return []


def fetch() -> list[tuple[str, str, str]]:
    """Return list of (url, title_ja, section_ja) from today's 朝刊 listing.
    Empty when there is no 朝刊 today (weekends/holidays for the 夕刊)."""
    result = make_page("nikkei_jp")
    if not result:
        return []
    pw, browser, page = result

    try:
        links = _load_links(page)
        log.info("Area 61: %d article links collected; sections: %s",
                 len(links), sorted({sec for _, _, sec in links}))
        return links
    finally:
        browser.close()
        pw.stop()
