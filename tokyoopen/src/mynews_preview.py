"""
Tokyo Open source: the Nikkei /mynews "（先読み株式相場）" article — a daily
human-written pre-open market preview (published ~07:30 JST). Reuses the same
Nikkei auth as the other collectors and returns the full article body.

Fully defensive: returns [] (never raises) if the article isn't there, auth
fails, or anything goes wrong — so Tokyo Open just carries on with its existing
sources. This source is purely additive.
"""

import logging
from collectors.nikkei_auth import make_page
from collectors.base import Article

log = logging.getLogger(__name__)

MYNEWS_URL = "https://www.nikkei.com/mynews"
MARKER = "先読み株式相場"  # appears in the title, e.g. "…（先読み株式相場）"

_FIND_JS = r"""
([marker]) => {
  const out = [];
  document.querySelectorAll('a[href*="/article/"]').forEach(a => {
    const title = (a.textContent || '').replace(/\s+/g, ' ').trim();
    if (title.includes(marker)) {
      out.push({ href: a.getAttribute('href') || '', title: title.slice(0, 160) });
    }
  });
  return out;
}
"""

# Body lives in <article>/<main>; class-based selectors don't exist on these pages.
_BODY_JS = ("() => (document.querySelector('article') || document.querySelector('main'))"
            "?.innerText || ''")

_BOILERPLATE = (
    "朝夕刊や電子版ではお伝えしきれない",
    "企業での記事共有や会議資料への転載",
)


def _clean_body(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(ln for ln in lines if not any(b in ln for b in _BOILERPLATE))


def fetch() -> list[Article]:
    """The （先読み株式相場）preview article with full body, or [] if absent/failed."""
    try:
        result = make_page("nikkei_jp")
    except Exception as e:
        log.warning("先読み: auth failed (%s) — continuing without it", e)
        return []
    if not result:
        log.info("先読み: no authenticated page — continuing without it")
        return []

    pw, browser, page = result
    try:
        page.goto(MYNEWS_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        hits = page.evaluate(_FIND_JS, [MARKER])
        if not hits:
            log.info("先読み: no （%s）article on /mynews today — continuing without it", MARKER)
            return []

        hit = hits[0]
        url = hit["href"] if hit["href"].startswith("http") else "https://www.nikkei.com" + hit["href"]
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(1500)

        h1 = page.evaluate("() => (document.querySelector('h1')?.textContent || '').trim()") or hit["title"]
        body = _clean_body(page.evaluate(_BODY_JS))
        if len(body) < 80:
            log.info("先読み: article body too thin (%d chars) — continuing without it", len(body))
            return []

        log.info("先読み: collected preview article (%d chars): %s", len(body), h1[:70])
        return [Article(
            title=h1.strip(),
            body=body[:4000],
            source="Nikkei 先読み株式相場 (daily preview)",
            url=url,
            language="ja",
        )]
    except Exception as e:
        log.warning("先読み: fetch failed (%s) — continuing without it", e)
        return []
    finally:
        try:
            browser.close()
            pw.stop()
        except Exception:
            pass
