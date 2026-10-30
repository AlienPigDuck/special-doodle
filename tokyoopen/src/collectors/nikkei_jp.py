"""
Nikkei Japan morning newspaper (朝刊) collector.
Authenticates with Playwright, navigates to today's morning edition at /paper/,
and scrapes full articles from market-relevant sections.
Articles are in Japanese — the digest step handles translation.
"""

import re
import logging
import unicodedata
from datetime import datetime, timezone, timedelta
from playwright.sync_api import Page
from .base import Article
from .nikkei_auth import make_page

log = logging.getLogger(__name__)

BASE_URL  = "https://www.nikkei.com"
PAPER_URL = "https://www.nikkei.com/paper/"
_JST = timezone(timedelta(hours=9))

# Nikkei redesigned its 朝刊・夕刊 pages in October 2026. Each edition now has its own
# URL — /paper/YYYYMMDDM101 (morning) and /paper/YYYYMMDDE101 (evening) — and article
# links look like /paper/<edition>/<pageID>/article/<articleID>. Section names are the
# <h2> headings above each group of links, e.g. 1面, 総合1, 政治・外交, ビジネス2 (page
# numbers are half-width digits now; the old pages used full-width ones).

# Sections to collect — markets, business, politics, economy, international — by base
# name (see section_base). Everything else (society, sport, culture, books…) is skipped.
KEEP_SECTIONS = frozenset({
    '1面', '総合', '政治・外交', '経済・政策', '金融経済',
    'グローバル市場', '国際', 'アジアBiz', 'ビジネス', '投資', '商品',
})


def section_base(name: str) -> str:
    """Section name without its page number: '総合２' → '総合', '１面' → '1面', 'ビジネス3' → 'ビジネス'."""
    return re.sub(r'\d+$', '', unicodedata.normalize('NFKC', name or '').strip())


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
        log.warning("Nikkei JP: goto hiccup at %s: %s", url, e)
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
                log.warning("Nikkei JP: extract attempt %d failed (%s) — retrying", i + 1, str(e)[:90])
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
            log.info("Nikkei JP: %s — %d article links (%s)", title, len(links), page.url)
            return links
        log.warning("Nikkei JP: %s gave %d links, page title %r — %s", url, len(links), title,
                    "trying /paper/" if url != PAPER_URL else "giving up")
    return []


def _extract_links(page: Page) -> list[tuple[str, str, str]]:
    """Article links from today's morning edition, limited to KEEP_SECTIONS."""
    links = _load_links(page)
    kept = [(u, t, sec) for u, t, sec in links if section_base(sec) in KEEP_SECTIONS]
    log.info("Nikkei JP: %d article links found, %d in kept sections %s",
             len(links), len(kept), sorted({sec for _, _, sec in kept}))
    return kept


def _scrape_article(page: Page, url: str) -> tuple[str, str]:
    """Returns ("", body) for a newspaper article page — body in Japanese.
    The page's <h1> is now the 朝刊・夕刊 banner, not the headline, so the title is
    left empty and the caller uses the headline from the listing. The clean story
    text is the <article> element; the whole body is the fallback."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        body = ""
        try:
            page.wait_for_selector("article", timeout=6000)
            body = page.locator("article").first.inner_text(timeout=3000).strip()
        except Exception:
            pass
        if len(body) < 200:
            body = page.inner_text("body").strip()
        return "", body[:4000]
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
